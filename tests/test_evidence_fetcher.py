import base64
import json
import socket
from types import SimpleNamespace

import pytest

from sieve_app.enrichment_worker import EnrichmentWorker
from talent_ranker.evidence_fetcher import (
    EvidenceFetcher,
    FetchError,
    FetchResponse,
    PublicHttpClient,
    public_addresses,
)


class FixtureClient:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get(self, url, **kwargs):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        kind, body = value
        return FetchResponse(url, kind, body.encode() if isinstance(body, str) else body)


def test_html_evidence_is_text_only_redacted_and_unverified():
    client = FixtureClient({'https://alex.dev/': ('text/html',
        ('<title>Projects</title><script>steal secrets</script><style>hidden</style>'
        '<h1>Built data pipelines</h1><p>alex@example.com</p>'
        '<a href="https://elsewhere.dev/">More</a>'))})
    result = EvidenceFetcher(client).fetch('https://alex.dev/', 'web')
    assert result['title'] == 'Projects'
    assert 'Built data pipelines' in result['text']
    assert 'steal secrets' not in result['text']
    assert 'alex@example.com' not in result['text']
    assert result['untrusted'] and not result['ownership_verified']
    assert client.calls == ['https://alex.dev/']


def test_github_repository_metadata_and_readme_use_api_only():
    url = 'https://api.github.com/repos/alex/project'
    client = FixtureClient({url: ('application/json', json.dumps({
        'full_name': 'alex/project', 'language': 'Python', 'fork': True, 'private': False})),
        url + '/readme': ('application/json', json.dumps({'encoding': 'base64',
            'content': base64.b64encode(b'Distributed data processing').decode()}))})
    result = EvidenceFetcher(client).fetch('https://github.com/alex/project', 'github')
    assert 'Python' in result['text'] and 'fork: True' in result['text']
    assert 'Distributed data processing' in result['text']
    assert result['fetched_urls'] == [url, url + '/readme']


def test_private_repository_is_rejected_even_if_token_can_read_it():
    url = 'https://api.github.com/repos/alex/private'
    client = FixtureClient({url: ('application/json', '{"private":true}')})
    with pytest.raises(FetchError, match='non_public_github_repository'):
        EvidenceFetcher(client).fetch('https://github.com/alex/private', 'github')
    assert client.calls == [url]


@pytest.mark.parametrize('addresses', [['127.0.0.1'], ['169.254.169.254'], ['10.0.0.1'],
                                     ['::1'], ['224.0.0.1'], ['93.184.216.34', '10.0.0.1']])
def test_dns_rejects_any_non_public_answer(monkeypatch, addresses):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in addresses])
    with pytest.raises(FetchError, match='non_public_destination'):
        public_addresses('alex.dev', 443)


class Response:
    def __init__(self, status=200, headers=None, body=b'Project evidence'):
        self.status, self.headers = status, headers or {'Content-Type': 'text/plain'}
        self.body, self.closed = body, False

    def read1(self, size, **kwargs):
        part, self.body = self.body[:size], self.body[size:]
        return part

    def close(self):
        self.closed = True


def install_transport(monkeypatch, responses):
    connections, requests, dns = [], [], []

    def resolve(host, port):
        dns.append(host)
        if host == 'internal.example.com':
            raise FetchError('non_public_destination', blocked=True)
        return ['93.184.216.34']

    class Pool:
        def __init__(self, host, port, **kwargs):
            connections.append((host, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def urlopen(self, method, target, **kwargs):
            requests.append((method, target, kwargs))
            return responses.pop(0)

    monkeypatch.setattr('talent_ranker.evidence_fetcher.public_addresses', resolve)
    monkeypatch.setattr('talent_ranker.evidence_fetcher.urllib3.HTTPSConnectionPool', Pool)
    return connections, requests, dns


def test_transport_pins_validated_ip_and_keeps_tls_hostname(monkeypatch):
    response = Response()
    connections, requests, _ = install_transport(monkeypatch, [response])
    result = PublicHttpClient('secret').get('https://alex.dev/work')
    assert result.body == b'Project evidence' and response.closed
    address, options = connections[0]
    assert address == '93.184.216.34'
    assert options['server_hostname'] == options['assert_hostname'] == 'alex.dev'
    assert 'Authorization' not in requests[0][2]['headers']
    assert requests[0][2]['redirect'] is False and requests[0][2]['retries'] is False


def test_redirect_is_revalidated_and_cannot_forward_github_credentials(monkeypatch):
    responses = [Response(302, {'Location': 'https://alex.dev/work'}), Response()]
    _, requests, dns = install_transport(monkeypatch, responses)
    PublicHttpClient('secret').get('https://api.github.com/repos/alex/work', github_auth=True)
    assert dns == ['api.github.com', 'alex.dev']
    assert requests[0][2]['headers']['Authorization'] == 'Bearer secret'
    assert 'Authorization' not in requests[1][2]['headers']


def test_resume_web_links_cannot_opt_into_github_credentials(monkeypatch):
    _, requests, _ = install_transport(monkeypatch, [Response()])
    PublicHttpClient('secret').get('https://api.github.com/users/alex')
    assert 'Authorization' not in requests[0][2]['headers']


def test_redirect_to_private_dns_is_blocked_before_connection(monkeypatch):
    connections, _, _ = install_transport(monkeypatch, [
        Response(302, {'Location': 'https://internal.example.com/'})])
    with pytest.raises(FetchError, match='non_public_destination'):
        PublicHttpClient().get('https://alex.dev/')
    assert len(connections) == 1


@pytest.mark.parametrize('response,code', [
    (Response(body=b'x' * 101), 'response_too_large'),
    (Response(headers={'Content-Type': 'application/pdf'}), 'unsupported_content_type'),
    (Response(headers={'Content-Type': 'text/plain', 'Content-Encoding': 'gzip'}),
     'unsupported_content_encoding'),
    (Response(302, {'Location': 'http://alex.dev/'}), 'insecure_redirect'),
])
def test_resource_and_redirect_limits(monkeypatch, response, code):
    install_transport(monkeypatch, [response])
    with pytest.raises(FetchError, match=code):
        PublicHttpClient(max_bytes=100).get('https://alex.dev/')
    assert response.closed


def test_rate_limit_wait_is_returned_to_queue(monkeypatch):
    install_transport(monkeypatch, [Response(429, {'Retry-After': '120'})])
    with pytest.raises(FetchError) as caught:
        PublicHttpClient().get('https://api.github.com/users/alex/repos')
    assert caught.value.retryable and caught.value.retry_after == 120


def test_worker_records_failure_and_keeps_next_job_processable():
    jobs = iter([{'id': 'first', 'url': 'https://alex.dev/', 'kind': 'web'},
                 {'id': 'second', 'url': 'https://github.com/alex/work', 'kind': 'github'}, None])
    failures, successes = [], []
    store = SimpleNamespace(claim_next=lambda: next(jobs),
        fail=lambda job, code, **kwargs: failures.append((job['id'], code, kwargs)),
        complete=lambda job, result: successes.append((job['id'], result)))

    class Fetcher:
        def fetch(self, url, kind):
            if kind == 'web':
                raise FetchError('http_429', retryable=True, retry_after=60)
            return {'text': 'Repository evidence'}

    worker = EnrichmentWorker(store, Fetcher())
    assert worker.run_once() and worker.run_once() and not worker.run_once()
    assert failures[0][0:2] == ('first', 'http_429')
    assert failures[0][2]['retryable']
    assert successes == [('second', {'text': 'Repository evidence'})]
