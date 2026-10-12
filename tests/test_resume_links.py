import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from talent_ranker.documents import extract_resume_document
from talent_ranker.privacy import redact_pii
from talent_ranker.resume_links import extract_links, normalize_url


def test_discovery_deduplicates_without_searching_for_profiles():
    text = ('GitHub: github.com/Alex/Project.git\n'
            'https://github.com/alex/project?utm_source=cv#readme\n'
            'Portfolio: https://alex.dev/work. Email alex@example.com\n'
            'https://linkedin.com/in/alex')
    links = extract_links(text, ('https://github.com/Alex/Project/',))
    assert [(link.url, link.kind, link.discovered_via) for link in links] == [
        ('https://github.com/alex/project', 'github', 'hyperlink'),
        ('https://alex.dev/work', 'web', 'text'),
        ('https://linkedin.com/in/alex', 'unsupported', 'text'),
    ]
    assert 'github.com' not in redact_pii(text)
    assert 'alex@example.com' not in redact_pii(text)


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', 'mailto:alex@example.com', 'file:///etc/passwd',
    'https://user:password@example.com/', 'http://127.0.0.1/', 'http://[::1]/',
    'https://localhost/', 'https://host.internal/', 'https://example.com:8443/',
    'https://example.com\\@internal/', 'https://example.com/\nheader',
])
def test_invalid_or_local_urls_are_not_persisted(url):
    assert normalize_url(url) is None


def test_discovery_is_bounded_and_queries_are_not_stored():
    links = extract_links(' '.join(f'https://example.com/project/{i}' for i in range(50)))
    assert len(links) == 25
    assert normalize_url('https://example.com/work?token=private#section') == 'https://example.com/work'


def test_bare_portfolio_domain_and_adjacent_separators():
    links = extract_links('alex.dev | https://github.com/alex/work|https://example.org/project')
    assert [link.url for link in links] == [
        'https://alex.dev/', 'https://github.com/alex/work', 'https://example.org/project',
    ]


def test_normalized_length_is_bounded_and_balanced_parentheses_survive():
    assert normalize_url('alex.dev/' + 'a' * 2039) is None
    assert normalize_url('https://alex.dev/' + ')' * 100_000) is None
    assert normalize_url('https://alex.dev/work(example)).') == 'https://alex.dev/work(example)'


def test_docx_hyperlinks_in_header_and_body_are_captured(tmp_path):
    document = Document()
    document.add_paragraph('An experienced engineer developing scalable software and data pipelines. ' * 2)
    for paragraph, url in [(document.add_paragraph(), 'https://github.com/alex/project'),
                           (document.sections[0].header.paragraphs[0], 'https://alex.dev/')]:
        rel_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
        hyperlink = OxmlElement('w:hyperlink')
        hyperlink.set(qn('r:id'), rel_id)
        run, text = OxmlElement('w:r'), OxmlElement('w:t')
        text.text = 'View my work'
        run.append(text)
        hyperlink.append(run)
        paragraph._p.append(hyperlink)
    path = tmp_path / 'resume.docx'
    document.save(path)
    extracted = extract_resume_document(path)
    assert {link.url for link in extracted.links} == {
        'https://github.com/alex/project', 'https://alex.dev/',
    }
    assert all(link.discovered_via == 'hyperlink' for link in extracted.links)


def test_pdf_annotation_and_visible_url_are_captured_in_one_parse(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 700 Td (Experienced software engineer building reliable '
                    b'services and data systems. Portfolio https://alex.dev/work) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_annotation(0, Link(rect=(20, 650, 150, 675), url='https://github.com/alex/project'))
    page[NameObject('/Annots')] = writer._add_object(page['/Annots'])
    path = tmp_path / 'resume.pdf'
    writer.write(path)
    extracted = extract_resume_document(path)
    assert {link.url for link in extracted.links} == {
        'https://github.com/alex/project', 'https://alex.dev/work',
    }
