"""Independently inspect real source annotations and downloaded PPTX links."""
import argparse
import hashlib
import json
import posixpath
from pathlib import Path
from runpy import run_path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pymupdf as fitz
from pypdf import PdfReader

NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}
LINK_TYPE = NS['r'] + '/hyperlink'
SLIDE_TYPE = NS['r'] + '/slide'
EXPECTED = [
    (0, 'Web', 'https://example.com/report?a=1&b=2#part', 'external'),
    (0, 'Mail', 'mailto:reader@example.com?subject=Report', 'external'),
    (0, 'Jump', 'ppt/slides/slide3.xml', 'internal'),
    (0, 'Table link', 'https://example.com/table', 'external'),
    (1, 'HTTP', 'http://example.com/second', 'external'),
    (2, 'Back', 'ppt/slides/slide1.xml', 'internal'),
]


def verify(source, pptx, rendered=None):
    source_bytes = source.read_bytes()
    factory = run_path(str(Path(__file__).with_name('pdf-pptx-text-links-source.py')))['source_pdf']
    assert source_bytes == factory(), 'Source identity differs from deterministic link fixture'
    source_pdf = PdfReader(source)
    assert len(source_pdf.pages) == 3
    source_links = []
    for i, page in enumerate(source_pdf.pages):
        for ref in page.get('/Annots', []):
            item = ref.get_object()
            if item.get('/Subtype') != '/Link':
                continue
            action = item.get('/A', {})
            if action.get('/S') == '/URI':
                source_links.append((i, str(action['/URI'])))
            elif '/Dest' in item:
                source_links.append((i, 'internal'))
    assert len(source_links) == 7, source_links
    assert (0, 'javascript:alert(1)') in source_links
    found = []
    table_link_count = 0
    table_link_texts = set()
    ooxml_colors = {}
    geometry = []
    with ZipFile(pptx) as archive:
        pres = ET.fromstring(archive.read('ppt/presentation.xml'))
        assert len(pres.findall('p:sldIdLst/p:sldId', NS)) == 3
        theme = ET.fromstring(archive.read('ppt/theme/theme1.xml'))
        theme_hlink_color = theme.find('.//a:clrScheme/a:hlink/a:srgbClr', NS).attrib['val']
        for i in range(3):
            part = f'ppt/slides/slide{i + 1}.xml'
            slide = ET.fromstring(archive.read(part))
            rel_root = ET.fromstring(archive.read(f'ppt/slides/_rels/slide{i + 1}.xml.rels'))
            rels = {r.attrib['Id']: r.attrib for r in rel_root}
            assert len(rels) == len(rel_root), 'Duplicate relationship identity'
            linked_ids = set()
            visible_text = ''.join(t.text or '' for t in slide.findall('.//a:t', NS))
            expected_text = [
                ['Source text links', 'Web plain', 'Mail plain', 'Jump third', 'Unsafe plain', 'Table link', 'Table plain', '10', '20'],
                ['Second source page', 'HTTP plain'], ['Destination page', 'Back first'],
            ][i]
            assert all(text in visible_text for text in expected_text), visible_text
            assert not slide.findall('.//p:cNvPr/a:hlinkClick', NS), 'Text links must retain run ranges'
            for shape in slide.findall('.//p:sp', NS):
                body = shape.find('p:txBody/a:bodyPr', NS)
                if body is None:
                    continue
                assert body.attrib['wrap'] == 'none'
                assert all(body.attrib[k] == '0' for k in ('lIns', 'tIns', 'rIns', 'bIns'))
                assert body.find('a:noAutofit', NS) is not None
                transform = shape.find('p:spPr/a:xfrm', NS)
                geometry.append({'page': i, 'off': transform.find('a:off', NS).attrib,
                                 'ext': transform.find('a:ext', NS).attrib})
            for run in slide.findall('.//a:r', NS):
                text = run.findtext('a:t', default='', namespaces=NS)
                link = run.find('a:rPr/a:hlinkClick', NS)
                if link is None:
                    continue
                rid = link.attrib['{' + NS['r'] + '}id']
                assert rid in rels, (text, rid)
                rel = rels[rid]
                linked_ids.add(rid)
                kind = 'external' if rel['Type'] == LINK_TYPE else 'internal'
                if kind == 'external':
                    assert rel['TargetMode'] == 'External'
                    assert 'action' not in link.attrib
                    target = rel['Target']
                else:
                    assert rel['Type'] == SLIDE_TYPE and 'TargetMode' not in rel
                    assert link.attrib['action'] == 'ppaction://hlinksldjump'
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(part), rel['Target']))
                    assert target in archive.namelist()
                # The source fixture uses no underline, and keeps a non-theme RGB.
                rpr = run.find('a:rPr', NS)
                assert rpr.attrib.get('u') == 'none', text
                assert rpr.find('a:solidFill/a:srgbClr', NS).attrib['val'] == '123456'
                assert rpr.attrib.get('sz') == '1200', text
                ooxml_colors[(i, text.strip())] = rpr.find('a:solidFill/a:srgbClr', NS).attrib['val']
                found.append((i, text.strip(), target, kind))
            for run in slide.findall('.//a:tbl//a:r', NS):
                if run.find('a:rPr/a:hlinkClick', NS) is not None:
                    table_link_count += 1
                    table_link_texts.add((i, run.findtext('a:t', default='', namespaces=NS).strip()))
            link_rels = {rid for rid, rel in rels.items() if rel['Type'] in (LINK_TYPE, SLIDE_TYPE)}
            assert linked_ids == link_rels, 'Unreferenced or unexpected link relationship'
    assert sorted(found) == sorted(EXPECTED), found
    assert table_link_count == 1, table_link_count
    result = {'ok': True, 'sourceSha256': hashlib.sha256(source_bytes).hexdigest(),
              'pptxSha256': hashlib.sha256(pptx.read_bytes()).hexdigest(),
              'links': found, 'tableLinks': table_link_count, 'shapeGeometry': geometry,
              'overallFidelityPassed': False, 'hostVerified': False,
              'hostLinkRelationshipsVerified': False, 'hostSourceColorFidelityPassed': None,
              'remaining': ['首行基线与复杂版式整体保真未通过；不把链接结构专项当成全部保真。']}
    if rendered is not None:
        host = fitz.open(rendered)
        assert len(host) == 3
        host_links = []
        for i, page in enumerate(host):
            for link in page.get_links():
                if link['kind'] == fitz.LINK_URI:
                    host_links.append((i, link['uri']))
                elif link['kind'] == fitz.LINK_GOTO:
                    host_links.append((i, link['page']))
        expected_host = [(p, target if kind == 'external' else int(target.rsplit('slide', 1)[1].split('.')[0]) - 1)
                         for p, _, target, kind in EXPECTED]
        assert sorted(host_links, key=str) == sorted(expected_host, key=str), host_links
        for p, label, _, _ in EXPECTED:
            assert label in host[p].get_text(), label
        assert 'Unsafe plain' in host[0].get_text()

        def span_colors(document, page, label):
            return sorted({f"{span['color']:06X}"
                           for block in document[page].get_text('dict')['blocks']
                           for line in block.get('lines', []) for span in line['spans']
                           if label in span['text']})

        source_render = fitz.open(source)
        color_observations = []
        color_issues = []
        for p, label, _, _ in EXPECTED:
            source_colors = span_colors(source_render, p, label)
            host_colors = span_colors(host, p, label)
            ooxml_color = ooxml_colors[(p, label)]
            matches = source_colors == host_colors == [ooxml_color]
            observation = {'pageIndex': p, 'text': label, 'inTable': (p, label) in table_link_texts,
                           'sourceColors': source_colors, 'ooxmlColor': ooxml_color,
                           'hostColors': host_colors, 'sourceColorFidelityPassed': matches}
            if not matches:
                reason = (f"第 {p + 1} 页链接 {label!r} 颜色保真未通过：来源 {source_colors}、"
                          f"OOXML {ooxml_color}、实际宿主 {host_colors}；theme hlink={theme_hlink_color}。"
                          '链接目标通过不代表宿主颜色保真通过。')
                observation['reason'] = reason
                color_issues.append(reason)
            color_observations.append(observation)
        source_render.close()
        host.close()
        result.update(hostVerified=True, hostLinks=host_links,
                      hostVerificationScope='链接目标、页数和已知正文；颜色保真另行返回，不包含整体版式验收。',
                      hostLinkRelationshipsVerified=True,
                      hostSourceColorFidelityPassed=all(item['sourceColorFidelityPassed'] for item in color_observations),
                      hostLinkColorObservations=color_observations,
                      tableLinkColorObservations=[item for item in color_observations if item['inTable']],
                      hostSourceColorFidelityIssues=color_issues, themeHyperlinkColor=theme_hlink_color,
                      renderedSha256=hashlib.sha256(rendered.read_bytes()).hexdigest())
        result['remaining'].extend(color_issues)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('pptx', type=Path)
    parser.add_argument('--rendered', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.source, args.pptx, args.rendered)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text)
    print(text)
