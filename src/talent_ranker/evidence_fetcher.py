"""Read-only, bounded retrieval of resume-linked public evidence.

DNS results are validated and the connection is pinned to the checked address.
TLS still verifies the original hostname. Every redirect is checked afresh.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

import urllib3

from .privacy import redact_pii
from .resume_links import link_kind, normalize_url


class FetchError(Exception):
    def __init__(self, code: str, *, retryable: bool = False, blocked: bool = False,
                 retry_after: int = 0):
        super().__init__(code)
        self.code, self.retryable, self.blocked = code, retryable, blocked
        self.retry_after = retry_after


@dataclass(frozen=True)
class FetchResponse:
    url: str
    content_type: str
    body: bytes


def public_addresses(host: str, port: int) -> list[str]:
    addresses = list(dict.fromkeys(
        entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ))
    if not addresses or any(not ipaddress.ip_address(ip).is_global
                            or ipaddress.ip_address(ip).is_multicast for ip in addresses):
        raise FetchError('non_public_destination', blocked=True)
    return addresses


class PublicHttpClient:
    """No cookies, environment proxies, automatic redirects, or implicit credentials."""

    def __init__(self, github_token: str | None = None, max_bytes: int = 1_000_000):
        self.github_token, self.max_bytes = github_token, max_bytes

    def get(self, url: str, *, accept: str = 'text/html, text/plain, application/json',
            github_auth: bool = False) -> FetchResponse:
        deadline = time.monotonic() + 30
        for _ in range(4):
            if normalize_url(url) is None or link_kind(url) == 'unsupported':
                raise FetchError('unsupported_destination', blocked=True)
            parts = urlsplit(url)
            host = parts.hostname
            port = 443 if parts.scheme == 'https' else 80
            try:
                address = public_addresses(host, port)[0]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError('fetch_timeout', retryable=True)
                pool_args = {'timeout': urllib3.Timeout(connect=min(5, remaining),
                                                       read=min(5, remaining))}
                if parts.scheme == 'https':
                    pool = urllib3.HTTPSConnectionPool(
                        address, port, server_hostname=host, assert_hostname=host,
                        ssl_context=ssl.create_default_context(), **pool_args,
                    )
                else:
                    pool = urllib3.HTTPConnectionPool(address, port, **pool_args)
                headers = {'Host': host, 'User-Agent': 'SieveEvidence/1.0',
                           'Accept': accept, 'Accept-Encoding': 'identity'}
                if (github_auth and host == 'api.github.com' and parts.scheme == 'https'
                        and parts.path.startswith(('/repos/', '/users/')) and self.github_token):
                    headers['Authorization'] = 'Bearer ' + self.github_token
                target = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
                if parts.query:
                    target += '?' + quote(parts.query, safe='=&%:+,;/-._~')
                with pool:
                    response = pool.urlopen('GET', target, headers=headers, redirect=False,
                                            retries=False, preload_content=False,
                                            assert_same_host=False)
                    try:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get('Location', '')
                            if not location:
                                raise FetchError('invalid_redirect')
                            destination = urljoin(url, location)
                            if parts.scheme == 'https' and urlsplit(destination).scheme != 'https':
                                raise FetchError('insecure_redirect', blocked=True)
                            url = destination
                            continue
                        if response.status != 200:
                            retryable = response.status in {408, 429} or response.status >= 500
                            delay = response.headers.get('Retry-After', '')
                            if host == 'api.github.com' and response.status == 403:
                                retryable = response.headers.get('X-RateLimit-Remaining') == '0'
                                reset = response.headers.get('X-RateLimit-Reset', '')
                                if reset.isdigit():
                                    delay = str(max(1, int(reset) - int(time.time())))
                            raise FetchError(f'http_{response.status}', retryable=retryable,
                                             retry_after=int(delay) if delay.isdigit() else 60)
                        content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
                        if content_type not in {'text/html', 'application/xhtml+xml',
                                                'text/plain', 'application/json'}:
                            raise FetchError('unsupported_content_type')
                        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                            raise FetchError('unsupported_content_encoding')
                        body = bytearray()
                        while True:
                            if time.monotonic() >= deadline:
                                raise FetchError('fetch_timeout', retryable=True)
                            chunk = response.read1(8192, decode_content=False)
                            if not chunk:
                                break
                            body.extend(chunk)
                            if len(body) > self.max_bytes:
                                raise FetchError('response_too_large')
                        return FetchResponse(url, content_type, bytes(body))
                    finally:
                        response.close()
            except FetchError:
                raise
            except (OSError, urllib3.exceptions.HTTPError, ValueError) as error:
                raise FetchError('network_error', retryable=True) from error
        raise FetchError('too_many_redirects', blocked=True)


class PageText(HTMLParser):
    """Extract text only; never execute scripts or follow page links."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip: list[str] = []
        self.in_title = False
        self.title: list[str] = []
        self.parts: list[str] = []
        self.size = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript', 'svg', 'template'}:
            self.skip.append(tag)
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if self.skip and tag == self.skip[-1]:
            self.skip.pop()
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.skip or self.size >= 30_000:
            return
        data = ' '.join(data.split())[:30_000 - self.size]
        if data:
            self.parts.append(data)
            self.size += len(data) + 1
            if self.in_title:
                self.title.append(data)


class EvidenceFetcher:
    def __init__(self, client: PublicHttpClient):
        self.client = client

    def fetch(self, url: str, kind: str) -> dict:
        if kind == 'github':
            return self._github(url)
        if kind != 'web':
            raise FetchError('unsupported_destination', blocked=True)
        response = self.client.get(url)
        content = response.body.decode('utf-8', errors='replace')
        if response.content_type in {'text/html', 'application/xhtml+xml'}:
            parser = PageText()
            parser.feed(content)
            title, text = ' '.join(parser.title), '\n'.join(parser.parts)
        elif response.content_type == 'text/plain':
            title, text = '', content
        else:
            raise FetchError('unsupported_content_type')
        if not text.strip():
            raise FetchError('no_extractable_text')
        return self._result(title, text, [response.url])

    def _github(self, url: str) -> dict:
        parts = urlsplit(url)
        segments = parts.path.strip('/').split('/')
        if (parts.hostname != 'github.com' or not re.fullmatch(r'[a-z0-9-]{1,39}', segments[0])
                or segments[0] in {'login', 'signup', 'settings', 'search', 'topics', 'explore'}):
            raise FetchError('unsupported_github_path')
        owner = segments[0]
        if len(segments) == 1:
            api_url = f'https://api.github.com/users/{owner}/repos?type=owner&sort=updated&per_page=10'
            response = self.client.get(api_url, accept='application/vnd.github+json', github_auth=True)
            items = json.loads(response.body)
            if not isinstance(items, list):
                raise FetchError('invalid_github_response')
            text = '\n\n'.join(self._repo_text(item) for item in items[:10])
            return self._result(f'Public repositories linked from {owner}', text, [response.url])
        repo = segments[1]
        if not re.fullmatch(r'[a-z0-9_.-]{1,100}', repo) or repo in {'.', '..'}:
            raise FetchError('unsupported_github_path')
        api_url = f'https://api.github.com/repos/{owner}/{repo}'
        response = self.client.get(api_url, accept='application/vnd.github+json', github_auth=True)
        item = json.loads(response.body)
        if isinstance(item, dict) and item.get('private'):
            raise FetchError('non_public_github_repository', blocked=True)
        text, sources = self._repo_text(item), [response.url]
        try:
            readme = self.client.get(api_url + '/readme', accept='application/vnd.github+json',
                                     github_auth=True)
            document = json.loads(readme.body)
            if not isinstance(document, dict) or document.get('encoding') != 'base64':
                raise FetchError('unsupported_readme_encoding')
            content = base64.b64decode(''.join(document['content'].split()), validate=True)
            text += '\n\nREADME (unverified source content):\n' + content.decode('utf-8', 'replace')
            sources.append(readme.url)
        except FetchError as error:
            if error.code != 'http_404':
                raise
        return self._result(f'{owner}/{repo}', text, sources)

    @staticmethod
    def _repo_text(item: dict) -> str:
        if not isinstance(item, dict) or item.get('private'):
            raise FetchError('invalid_github_response')
        return '\n'.join(f'{key}: {str(item[key])[:2000]}' for key in
                         ('full_name', 'description', 'language', 'topics', 'fork', 'archived',
                          'pushed_at') if item.get(key) is not None)

    @staticmethod
    def _result(title: str, text: str, sources: list[str]) -> dict:
        return {'title': redact_pii(title)[:250], 'text': redact_pii(text)[:30_000],
                'fetched_urls': [normalize_url(url) for url in sources],
                'untrusted': True, 'ownership_verified': False, 'extractor_version': '1'}
