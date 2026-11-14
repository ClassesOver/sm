// 真实浏览器验收（2026-11-08/09 对齐批次，Word 插入页签）：封面、分页符、空白页、插入表格并在
// 新表格内输入。真实 Chromium + vite 前端；context/file/preview 为替身路由，保存经真实
// Python patch_docx（桥接 + 引擎），下载字节由 python-docx/XML 独立回读。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_SMOKE_PORT ?? 4193)
// insert（默认）：封面/分页/空白页/表格；followup：封面替换+改标题+表格，修订 2 上改表格单元格并删除封面。
const smokeCase = process.env.DOCX_INSERT_CASE ?? 'insert'
const builtPreview = process.env.NATIVE_GUI_PREVIEW === '1'
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestPath = join(frontend, '../static/.vite/manifest.json')
const manifestSha256 = builtPreview ? sha256(await readFile(manifestPath)) : null
if (builtPreview && process.env.DOCX_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.DOCX_EXPECTED_MANIFEST_SHA256)
const temporary = await mkdtemp(join(tmpdir(), 'docx-insert-gui-'))
const sourcePath = join(temporary, 'revision-1.docx'), savedPath = join(temporary, 'revision-2.docx')
const runPython = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64, json, sys
from io import BytesIO
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from docx.enum.section import WD_SECTION
from zipfile import ZipFile
from hashlib import sha256
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
payload = json.load(sys.stdin)
if payload['mode'] == 'create':
    if payload.get('case') in ('layout-decorations', 'layout-decorations-fresh'):
        payload['case'] = 'notes-decorations-fresh' if payload['case'].endswith('-fresh') else 'notes-decorations'
    document = Document()
    for index, text in enumerate(['straße', '第二段前半第二段后半', '第三段'] if payload.get('case') == 'case' else ['第一段正文', '第二段前半第二段后半', '第三段']):
        paragraph = document.add_paragraph(text)
        if payload.get('case') == 'notes-empty':
            from docx.shared import Pt
            from docx.oxml import OxmlElement
            from docx.enum.style import WD_STYLE_TYPE
            if index == 0:
                paragraph.clear()
                run = paragraph.add_run(''); run.font.name = 'Arial'; run.font.size = Pt(22); run.italic = True
                run._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
            elif index == 1:
                paragraph.clear()
                style = document.styles.add_style('EmptyBody', WD_STYLE_TYPE.PARAGRAPH)
                style.font.name = 'Cambria'; style.font.size = Pt(16); style.font.bold = True; style.font.italic = True
                paragraph.style = style
        if payload.get('case') in ('selection-format', 'notes-inline', 'notes-layout', 'notes-decorations', 'notes-decorations-fresh') and index == 0:
            paragraph.clear()
            paragraph.add_run('A😀').bold = True
            paragraph.add_run('BC尾').italic = True
            if payload.get('case') in ('notes-layout', 'notes-decorations', 'notes-decorations-fresh'):
                from docx.oxml import OxmlElement
                paragraph.paragraph_format.keep_with_next = True
                paragraph.runs[0]._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
        if payload.get('case') in ('case', 'clear'):
            paragraph.runs[0].bold = True
        if payload.get('case') == 'paragraph-format-combination' and index == 0:
            from docx.oxml import OxmlElement
            paragraph.paragraph_format.keep_with_next = True
            paragraph.runs[0].bold = True
            paragraph.runs[0]._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
        if payload.get('case') in ('body-decorations', 'body-decorations-no-notes') and index == (1 if payload.get('case') == 'body-decorations-no-notes' else 0):
            from docx.oxml import OxmlElement
            paragraph.paragraph_format.keep_with_next = True
            paragraph.runs[0]._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
        if payload.get('case') in ('title-page', 'odd-even', 'page-number', 'hf-link', 'hf-media', 'hf-same-save') and index == 1:
            document.add_section(WD_SECTION.NEW_PAGE)
    if payload.get('case') in ('title-page', 'odd-even', 'page-number', 'hf-link', 'hf-media', 'hf-same-save'):
        for index, section in enumerate(document.sections):
            section.different_first_page_header_footer = index == 1
            for kind in ('header', 'footer', 'first_page_header', 'first_page_footer', 'even_page_header', 'even_page_footer'):
                part = getattr(section, kind); part.is_linked_to_previous = False
                part.paragraphs[0].text = f'{index}:{kind}'
                if payload.get('case') == 'hf-link': part.paragraphs[0].runs[0].bold = True
    if payload.get('case') in ('hf-media', 'hf-same-save'):
        from PIL import Image
        from docx.shared import Inches
        from docx.oxml import OxmlElement
        from docx.opc.constants import RELATIONSHIP_TYPE
        picture = BytesIO(); Image.new('RGB', (12, 8), '#3483ab').save(picture, format='PNG'); picture.seek(0)
        first = document.sections[0].header
        first.paragraphs[0].add_run().add_picture(picture, width=Inches(.5))
        rid = first.part.relate_to('https://example.com/a?b=1&c=2', RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        hyperlink = OxmlElement('w:hyperlink'); hyperlink.set(qn('r:id'), rid)
        run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'example link'; run.append(text); hyperlink.append(run)
        first.paragraphs[0]._p.append(hyperlink)
        document.sections[1].header.is_linked_to_previous = True
    if payload.get('case') == 'paragraph-format-protected':
        from docx.oxml import OxmlElement
        protection = OxmlElement('w:documentProtection'); protection.set(qn('w:edit'), 'readOnly'); protection.set(qn('w:enforcement'), '1'); document.settings.element.append(protection)
    if payload.get('case', '').startswith('hf-insert-edge-'):
        from docx.oxml import OxmlElement
        if payload['case'].endswith('even'):
            document.add_page_break(); document.add_paragraph('Last page text')
        if payload['case'].endswith('multi'):
            last = document.add_section(WD_SECTION.NEW_PAGE); document.add_paragraph('Last section text')
            numbering = OxmlElement('w:pgNumType'); numbering.set(qn('w:start'), '12'); last._sectPr.append(numbering)
        document.settings.odd_and_even_pages_header_footer = True
        for index, section in enumerate(document.sections):
            section.different_first_page_header_footer = payload['case'].endswith('title')
            for name in ('header', 'footer', 'first_page_header', 'first_page_footer', 'even_page_header', 'even_page_footer'):
                part = getattr(section, name); part.is_linked_to_previous = False; part.paragraphs[0].text = f'{index}:{name}'
    if payload.get('case') in ('hf-insert', 'hf-insert-delete'):
        from docx.oxml import OxmlElement
        document.sections[0].header.paragraphs[0].text = 'Header stays'
        footer = document.sections[0].footer.paragraphs[0]
        footer.text = 'Footer '
        for field in ('PAGE', 'NUMPAGES'):
            simple = OxmlElement('w:fldSimple'); simple.set(qn('w:instr'), f' {field} ')
            run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = '1'; run.append(text); simple.append(run); footer._p.append(simple)
            footer.add_run(' tail ')
    if payload.get('case') == 'pagination-snapshot-sections':
        from docx.shared import Inches
        from docx.oxml import OxmlElement
        document.add_page_break()
        document.add_paragraph('Second physical page')
        continuous = document.add_section(WD_SECTION.CONTINUOUS)
        document.add_paragraph('Continuous section')
        last = document.add_section(WD_SECTION.NEW_PAGE)
        last.different_first_page_header_footer = True
        numbering = OxmlElement('w:pgNumType'); numbering.set(qn('w:start'), '12'); last._sectPr.append(numbering)
        document.settings.odd_and_even_pages_header_footer = True
        document.add_paragraph('Restarted page twelve')
    document.save(payload['path'])
    if payload.get('case') == 'style-majority':
        from smart_reporting.reporting.tests.test_docx_style_majority import source
        Path(payload['path']).write_bytes(source())
    if payload.get('case') == 'note-reference-input':
        from smart_reporting.reporting.tests.test_docx_note_reference_input import terminal_source
        Path(payload['path']).write_bytes(terminal_source())
    if payload.get('case') in ('notes-layout', 'notes-decorations', 'plain-no-notes', 'body-decorations-no-notes'):
        original = Path(payload['path']).read_bytes(); block = inspect_docx(original)['blocks'][0]
        Path(payload['path']).write_bytes(patch_docx(original, [{'kind': 'insertNote', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'noteKind': 'footnote', 'offset': 3, 'text': '来源脚注'}]))
        if payload.get('case') in ('plain-no-notes', 'body-decorations-no-notes'):
            from copy import deepcopy
            from lxml import etree
            from zipfile import ZIP_DEFLATED
            original = Path(payload['path']).read_bytes(); out = BytesIO()
            with ZipFile(BytesIO(original)) as before, ZipFile(out, 'w', ZIP_DEFLATED) as after:
                for item in before.infolist():
                    data = before.read(item.filename)
                    if item.filename == 'word/footnotes.xml':
                        root = etree.fromstring(data); root.append(deepcopy(root.find(qn('w:footnote') + '[@' + qn('w:id') + '="1"]'))); data = etree.tostring(root)
                    after.writestr(item, data)
            Path(payload['path']).write_bytes(out.getvalue())
    print(base64.b64encode(Path(payload['path']).read_bytes()).decode())
elif payload['mode'] == 'patch':
    result = patch_docx(Path(payload['sourcePath']).read_bytes(), payload['operations'])
    Path(payload['outputPath']).write_bytes(result)
    print(base64.b64encode(result).decode())
else:
    content = base64.b64decode(payload['bytes'])
    document = Document(BytesIO(content))
    body = []
    for child in document.element.body:
        tag = child.tag.split('}')[1]
        if tag == 'p':
            ppr = child.find(qn('w:pPr'))
            pbb = ppr is not None and ppr.find(qn('w:pageBreakBefore')) is not None
            body.append(['p', ''.join(t.text or '' for t in child.iter(qn('w:t'))), pbb])
        elif tag == 'tbl':
            rows = child.findall(qn('w:tr'))
            body.append(['tbl', len(rows), len(rows[0].findall(qn('w:tc'))), [''.join(t.text or '' for t in tc.iter(qn('w:t'))) for tc in rows[0].findall(qn('w:tc'))]])
    marks = [b.get(qn('w:name')) for b in document.element.body.iter(qn('w:bookmarkStart'))]
    sections = [{'start': str(sec.start_type), 'orientation': str(sec.orientation), 'width': sec.page_width.twips, 'height': sec.page_height.twips, 'left': sec.left_margin.twips, 'right': sec.right_margin.twips, 'top': sec.top_margin.twips, 'bottom': sec.bottom_margin.twips, 'titlePg': sec.different_first_page_header_footer} for sec in document.sections]
    for sec, info in zip(document.sections, sections):
        pg = sec._sectPr.find(qn('w:pgNumType'))
        info['pageNumberFmt'] = pg.get(qn('w:fmt')) if pg is not None else None
        info['pageNumberStart'] = int(pg.get(qn('w:start'))) if pg is not None and pg.get(qn('w:start')) is not None else None
    runs = [[[run.text, bool(run.bold), bool(run.italic)] for run in paragraph.runs] for paragraph in document.paragraphs]
    emptyFormats = [[[run.text, run.font.name, run.font.size.pt if run.font.size else None, run.italic, run._r.rPr is not None and run._r.rPr.find(qn('w:noProof')) is not None] for run in paragraph.runs] for paragraph in document.paragraphs]
    paragraphLayouts = [{'alignment': str(paragraph.alignment), 'left': paragraph.paragraph_format.left_indent.twips if paragraph.paragraph_format.left_indent is not None else None, 'right': paragraph.paragraph_format.right_indent.twips if paragraph.paragraph_format.right_indent is not None else None, 'before': paragraph.paragraph_format.space_before.twips if paragraph.paragraph_format.space_before is not None else None, 'after': paragraph.paragraph_format.space_after.twips if paragraph.paragraph_format.space_after is not None else None, 'line': paragraph.paragraph_format.line_spacing, 'keepNext': paragraph.paragraph_format.keep_with_next} for paragraph in document.paragraphs]
    runFormats = [[[run.text, run._r.rPr.find(qn('w:highlight')).get(qn('w:val')) if run._r.rPr is not None and run._r.rPr.find(qn('w:highlight')) is not None else None, run._r.rPr.find(qn('w:vertAlign')).get(qn('w:val')) if run._r.rPr is not None and run._r.rPr.find(qn('w:vertAlign')) is not None else None] for run in paragraph.runs] for paragraph in document.paragraphs]
    paragraphDecorations = []
    for paragraph in document.paragraphs:
        properties = {}
        for child in paragraph._p.get_or_add_pPr():
            if child.tag == qn('w:shd'):
                properties['shd'] = {key.split('}')[1]: value for key, value in child.attrib.items()}
            elif child.tag == qn('w:pBdr'):
                properties['pBdr'] = {line.tag.split('}')[1]: {key.split('}')[1]: value for key, value in line.attrib.items()} for line in child}
        paragraphDecorations.append(properties)
    pictures = [{'width': shape.width, 'height': shape.height} for shape in document.inline_shapes]
    with ZipFile(BytesIO(content)) as package:
        from lxml import etree
        hfMedia = {name: {'pictures': len(etree.fromstring(package.read(name)).findall('.//' + qn('w:drawing'))), 'links': len(etree.fromstring(package.read(name)).findall('.//' + qn('w:hyperlink')))} for name in package.namelist() if name.startswith(('word/header', 'word/footer')) and name.endswith('.xml')}
        hfRelations = {name: sha256(package.read(name)).hexdigest() for name in package.namelist() if name.startswith(('word/_rels/header', 'word/_rels/footer')) and name.endswith('.rels')}
        mediaParts = {name: sha256(package.read(name)).hexdigest() for name in package.namelist() if name.startswith('word/media/') and not name.endswith('/')}
        notesParts = {name: sha256(package.read(name)).hexdigest() for name in package.namelist() if name in ('word/footnotes.xml', 'word/endnotes.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml')}
        hfParts = {name: sha256(package.read(name)).hexdigest() for name in package.namelist() if name.startswith(('word/header', 'word/footer')) and not name.endswith('/') or name == 'word/_rels/document.xml.rels'}
        hfDetails = {name: {'fields': [node.text.strip() for node in etree.fromstring(package.read(name)).iter(qn('w:instrText'))], 'aligns': [node.get(qn('w:val')) for node in etree.fromstring(package.read(name)).iter(qn('w:jc'))]} for name in package.namelist() if name.startswith(('word/header', 'word/footer')) and name.endswith('.xml')}
        coreProperties = {child.tag.split('}')[-1]: child.text for child in etree.fromstring(package.read('docProps/core.xml'))}
        packageParts = {name: sha256(package.read(name)).hexdigest() for name in package.namelist() if name != 'word/document.xml' and not name.endswith('/')}
    print(json.dumps({'model': inspect_docx(content), 'body': body, 'bookmarks': marks, 'sections': sections, 'runs': runs, 'emptyFormats': emptyFormats, 'paragraphLayouts': paragraphLayouts, 'paragraphDecorations': paragraphDecorations, 'packageParts': packageParts, 'coreProperties': coreProperties, 'runFormats': runFormats, 'pictures': pictures, 'hfParts': hfParts, 'hfDetails': hfDetails, 'hfMedia': hfMedia, 'hfRelations': hfRelations, 'mediaParts': mediaParts, 'notesParts': notesParts, 'evenAndOddHeaders': document.settings.odd_and_even_pages_header_footer}, ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser
try {
  const sourceBytes = Buffer.from(runPython({ mode: 'create', path: sourcePath, case: smokeCase }), 'base64')
  const sourceInspection = JSON.parse(runPython({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
  const revisions = new Map([[1, sourceBytes]])
  const inspections = new Map([[1, sourceInspection]])
  const savePayloads = new Map()
  let savedBytes, savePayload
  server = spawn('./node_modules/.bin/vite', [...(builtPreview ? ['preview'] : []), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  for (let attempt = 0; attempt < 120; attempt++) { try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const pageErrors = []
  const chunkChecks = [], loadedChunks = new Map()
  if (builtPreview) page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (!path.startsWith('/reports/v1/editor/assets/assets/') || !path.endsWith('.js')) return
    chunkChecks.push((async () => {
      assert.equal(response.status(), 200)
      const file = path.split('/').at(-1), actual = await response.body(), expected = await readFile(join(frontend, '../static/assets', file))
      assert.equal(sha256(actual), sha256(expected), `浏览器必须加载当前构建文件${file}`)
      loadedChunks.set(file, sha256(actual))
    })())
  })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && !/WebSocket|\[vite\] failed to connect/.test(message.text())) pageErrors.push(message.text()) })
  const revisionOf = request => Number(new URL(request.url()).pathname.split('/')[5])
  await page.route('**/reports/v1/native/fixture-insert/*/api/context', route => { const revision = revisionOf(route.request()), bytes = revisions.get(revision); return route.fulfill({ json: {
    context: { documentId: 'fixture-insert', format: 'docx', revision, parentRevision: revision === 1 ? null : revision - 1, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
      sourceFile: { path: `revision-${revision}.docx`, size: bytes.length, sha256: sha256(bytes), mediaType }, origin: 'report' },
    csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: smokeCase !== 'select-all-readonly' } }) })
  await page.route('**/reports/v1/native/fixture-insert/*/api/file', route => route.fulfill({ body: revisions.get(revisionOf(route.request())), contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-insert/*/api/preview', route => { const model = inspections.get(revisionOf(route.request())).model; return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  await page.route('**/reports/v1/native/fixture-insert/*/api/save', async route => {
    const revision = revisionOf(route.request()), next = revision + 1
    savePayload = route.request().postDataJSON(); savePayloads.set(revision, savePayload)
    const input = join(temporary, `revision-${revision}.docx`), output = join(temporary, `revision-${next}.docx`)
    await import('node:fs/promises').then(fs => fs.writeFile(input, revisions.get(revision)))
    savedBytes = Buffer.from(runPython({ mode: 'patch', sourcePath: input, outputPath: output, operations: savePayload.operations }), 'base64')
    revisions.set(next, savedBytes); inspections.set(next, JSON.parse(runPython({ mode: 'inspect', bytes: savedBytes.toString('base64') })))
    await route.fulfill({ json: { documentId: 'fixture-insert', revision: next, parentRevision: revision, revisionRegistered: true,
      artifacts: { word: { downloadUrl: `/fixture-insert-download-${next}.docx`, size: savedBytes.length, sha256: sha256(savedBytes) } },
      editor: { openUrl: `/reports/v1/native/fixture-insert/${next}` }, validation: { ok: true, issues: [] } } })
  })
  await page.route(/\/fixture-insert-download-\d+\.docx$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/-(\d+)\.docx$/)[1])), contentType: mediaType }))
  await page.route(/\/reports\/v1\/native\/fixture-insert\/\d+$/, async route => { await route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }) })
  const open = async revision => { await page.goto(`${baseUrl}/reports/v1/native/fixture-insert/${revision}`); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) }
  await open(1)
  const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const insert = async action => {
    const button = page.locator(`.docx-source-insert [data-action="${action}"]`)
    await delay(300)
    assert.equal(await button.isDisabled(), false, `${action} must be enabled: ${await button.getAttribute('title')}`)
    await button.click()
  }
  await page.locator('[data-tab-id="insert"]').click()
  const save = async revision => {
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(expected => (document.querySelector('.save-state-label')?.textContent ?? '').includes(`已保存修订 ${expected}`), revision, { timeout: 60000 })
    const download = await page.evaluate(async url => { const r = await fetch(url); return Array.from(new Uint8Array(await r.arrayBuffer())) }, `/fixture-insert-download-${revision}.docx`)
    return JSON.parse(runPython({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
  }
  if (smokeCase === 'hf-insert-delete') {
    page.on('dialog', dialog => dialog.accept())
    const remove = async kind => { await page.locator('[data-tab-id="insert"]').click(); await page.locator(`[data-action="insert-${kind}"]`).click(); await page.locator('.docx-source-insert .layout-menu').getByRole('button', { name: kind === 'header' ? '删除页眉' : '删除页脚', exact: true }).click() }
    await remove('header'); const revision2 = await save(2)
    assert.equal(revision2.model.sections[0].headersFooters.parts['header.default'].text, '')
    assert.equal(revision2.model.sections[0].headersFooters.parts['footer.default'].text, sourceInspection.model.sections[0].headersFooters.parts['footer.default'].text)
    await open(2); await remove('footer'); const revision3 = await save(3)
    assert.equal(revision3.model.sections[0].headersFooters.parts['footer.default'].text, '')
    assert.deepEqual(revision3.body, sourceInspection.body)
    assert.deepEqual(revision3.hfDetails[revision3.model.sections[0].headersFooters.parts['footer.default'].path].fields, [])
    await open(3); assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, operations: [...savePayloads.values()].map(value => value.operations), pageErrors }))
  } else if (smokeCase.startsWith('hf-insert-edge-')) {
    page.on('dialog', dialog => dialog.accept())
    const multi = smokeCase.endsWith('multi'), title = smokeCase.endsWith('title'), last = sourceInspection.model.sections.length - 1
    const footerVariant = title ? 'first' : 'even', headerVariant = title ? 'first' : 'default'
    const menu = async action => { await page.locator('[data-tab-id="insert"]').click(); await page.locator(`[data-action="${action}"]`).click() }
    const part = (inspection, index, kind, variant) => inspection.model.sections[index].headersFooters.parts[`${kind}.${variant}`]
    if (multi) await editor.locator('p').filter({ hasText: 'Last section text' }).click()
    await menu('insert-page-number'); await page.locator('[data-source-action="insert-page-number-footer-right"]').click()
    const revision2 = await save(2)
    assert.equal(part(revision2, last, 'footer', footerVariant).text, '\uE001')
    assert.deepEqual(revision2.hfDetails[part(revision2, last, 'footer', footerVariant).path], { fields: ['PAGE'], aligns: ['right'] })
    assert.equal(savePayloads.get(1).operations[0].part, 'footer'); assert.equal(savePayloads.get(1).operations[0].variant, footerVariant)
    assert.equal(savePayloads.get(1).operations[0].sectionId, sourceInspection.model.sections[last].sectionId)
    for (let index = 0; index <= last; index++) for (const kind of ['header', 'footer']) for (const variant of ['default', 'first', 'even']) if (!(index === last && kind === 'footer' && variant === footerVariant)) assert.equal(part(revision2, index, kind, variant).text, part(sourceInspection, index, kind, variant).text)
    await open(2)
    if (multi) await editor.locator('p').filter({ hasText: 'Last section text' }).click()
    await menu('insert-page-number'); await page.locator('[data-source-action="insert-page-number-header-left"]').click()
    if (multi) {
      await menu('insert-page-number'); await page.locator('.docx-source-insert .layout-menu').getByRole('button', { name: '设置页码格式…', exact: true }).click()
      await page.getByLabel('页码编号格式').selectOption('upperRoman'); await page.getByLabel('起始页码', { exact: true }).fill('12')
      await page.getByRole('dialog', { name: '页码格式' }).getByRole('button', { name: '确定', exact: true }).click()
    }
    const revision3 = await save(3)
    assert.equal(part(revision3, 0, 'header', headerVariant).text, '\uE001')
    assert.equal(savePayloads.get(2).operations.find(op => op.kind === 'setHeaderFooter').sectionId, revision2.model.sections[0].sectionId)
    assert.deepEqual(revision3.hfDetails[part(revision3, 0, 'header', headerVariant).path], { fields: ['PAGE'], aligns: ['left'] })
    if (multi) {
      assert.equal(revision3.sections[last].pageNumberFmt, 'upperRoman'); assert.equal(revision3.sections[last].pageNumberStart, 12)
      assert.equal(revision3.sections[0].pageNumberFmt, sourceInspection.sections[0].pageNumberFmt)
    }
    assert.equal(part(revision3, last, 'footer', footerVariant).text, '\uE001')
    const changedPaths = [part(revision3, 0, 'header', headerVariant).path, part(revision3, last, 'footer', footerVariant).path]
    for (const [path, hash] of Object.entries(sourceInspection.hfParts)) if (!changedPaths.includes(path)) assert.equal(revision3.hfParts[path], hash, `非目标ZIP部件${path}`)
    assert.deepEqual(revision3.body, sourceInspection.body)
    await open(3); await menu('insert-footer'); await page.locator('.docx-source-insert .layout-menu').getByRole('button', { name: '编辑页脚', exact: true }).click()
    await page.locator('.docx-hf-editor-host [contenteditable="true"]').waitFor()
    assert.equal(await page.locator('.docx-hf-tabs[aria-label="页眉页脚部件"] button[aria-pressed="true"]').textContent(), '页脚')
    assert.equal(await page.locator('.docx-hf-tabs[aria-label="页眉页脚变体"] button[aria-pressed="true"]').textContent(), title ? '首页' : '偶数页')
    if (multi) {
      await page.locator('[data-tab-id="home"]').click(); await editor.locator('p').filter({ hasText: '第一段正文' }).click()
      await page.locator('[data-tab-id="headerFooter"]').click()
      assert.equal(await page.locator('[data-source-action="hf-current-section"]').textContent(), '第 1 节，共 2 节')
      assert.equal(await page.locator('.docx-hf-tabs[aria-label="页眉页脚部件"] button[aria-pressed="true"]').textContent(), '页眉')
    }
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, footerVariant, headerVariant, operations: [...savePayloads.values()].map(value => value.operations), nonTargetPartsPreserved: true, pageErrors }))
  } else if (smokeCase === 'hf-insert') {
    page.on('dialog', dialog => dialog.accept())
    const menu = async action => { await page.locator('[data-tab-id="insert"]').click(); await page.locator(`[data-action="${action}"]`).click() }
    const item = name => page.locator('.docx-source-insert .layout-menu').getByRole('button', { name, exact: true })
    const footer = inspection => inspection.model.sections[0].headersFooters.parts['footer.default']
    await menu('insert-page-number'); await item('移除页码').click()
    const revision2 = await save(2)
    assert.ok(!footer(revision2).text.includes('\uE001')); assert.ok(footer(revision2).text.includes('\uE000'))
    assert.deepEqual(revision2.hfDetails[footer(revision2).path].fields, ['NUMPAGES'])
    assert.ok(footer(revision2).text.includes('Footer')); assert.deepEqual(revision2.body, sourceInspection.body)
    await open(2); await menu('insert-page-number')
    await page.locator('[data-source-action="insert-page-number-footer-center"]').click()
    const revision3 = await save(3)
    assert.equal(footer(revision3).text, '\uE001')
    const center = revision3.hfParts[footer(revision3).path]
    assert.ok(center)
    assert.deepEqual(revision3.hfDetails[footer(revision3).path], { fields: ['PAGE'], aligns: ['center'] })
    await open(3); await menu('insert-footer'); await item('编辑页脚').click()
    const nested = page.locator('.docx-hf-editor-host [contenteditable="true"]')
    await nested.waitFor(); assert.equal(await page.locator('.docx-hf-tabs[aria-label="页眉页脚部件"] button[aria-pressed="true"]').textContent(), '页脚')
    await nested.click(); await page.keyboard.press('Control+a'); await page.keyboard.type('Edited footer')
    await menu('insert-page-number'); await item('设置页码格式…').click()
    await page.getByLabel('页码编号格式').selectOption('upperRoman'); await page.getByLabel('起始页码', { exact: true }).fill('5')
    await page.getByRole('dialog', { name: '页码格式' }).getByRole('button', { name: '确定', exact: true }).click()
    const revision4 = await save(4)
    assert.equal(footer(revision4).text, 'Edited footer')
    assert.equal(revision4.sections[0].pageNumberFmt, 'upperRoman'); assert.equal(revision4.sections[0].pageNumberStart, 5)
    assert.equal(revision4.model.sections[0].headersFooters.parts['header.default'].text, 'Header stays')
    assert.deepEqual(revision4.body, sourceInspection.body)
    await open(4); await menu('insert-footer'); await item('编辑页脚').click(); assert.equal(await nested.textContent(), 'Edited footer')
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, pageErrors, source: footer(sourceInspection), removed: footer(revision2), positioned: footer(revision3), edited: footer(revision4), operations: [...savePayloads.values()].map(value => value.operations) }))
  } else if (smokeCase.startsWith('pagination-snapshot')) {
    await page.locator('[data-tab-id="view"]').click()
    await page.locator('[data-action="pagination-preview"]').click()
    await page.waitForFunction(() => window.__previewDebug?.slices?.length > 0)
    const cuts = await page.evaluate(() => window.__previewDebug.slices.map(({ start, end, capacityPx, section, pageNo, hf }) => ({ start, end, capacityPx, section, pageNo, hf })))
    if (builtPreview) { await Promise.all(chunkChecks); assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file))) }
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))
  } else if (smokeCase === 'select-all' || smokeCase === 'select-all-readonly') {
    await page.locator('[data-tab-id="home"]').click()
    const baseline = await editor.evaluate(element => element.editor.getJSON())
    const saveDisabledBefore = await page.locator('[data-action="save"]').isDisabled()
    const draftStorage = () => page.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:'))))
    const draftBefore = await draftStorage()
    const button = page.locator('.docx-source-home [data-action="select"]')
    assert.equal(await button.isDisabled(), false)
    assert.equal(await button.textContent(), '全选')
    await button.click()
    const selected = await editor.evaluate(element => {
      const editor = element.editor
      return { from: editor.state.selection.from, to: editor.state.selection.to, size: editor.state.doc.content.size, document: editor.getJSON(), editable: editor.isEditable }
    })
    assert.equal(selected.from, 0); assert.equal(selected.to, selected.size)
    assert.equal(selected.editable, smokeCase !== 'select-all-readonly')
    assert.deepEqual(selected.document, baseline)
    assert.equal(savePayloads.size, 0)
    assert.equal(await page.locator('[data-action="save"]').isDisabled(), saveDisabledBefore)
    assert.deepEqual(await draftStorage(), draftBefore)
    if (builtPreview) { await Promise.all(chunkChecks); assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file))) }
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, selected: { from: selected.from, to: selected.to, size: selected.size, editable: selected.editable }, documentUnchanged: true, saveRequests: savePayloads.size, loadedChunks: Object.fromEntries(loadedChunks), pageErrors }))
  } else if (smokeCase === 'style-majority') {
    const first = () => editor.locator('p').first()
    const choose = async style => { await page.locator('[data-tab-id="home"]').click(); await page.locator('[data-action="paragraph-style"]').selectOption(style) }
    await first().click(); await choose('RibbonCustom')
    assert.equal(await first().locator('strong').count(), 0); assert.equal(await first().locator('em').textContent(), 'D')
    await first().click(); await page.keyboard.press('Control+z'); assert.equal(await first().locator('strong').textContent(), 'ABC')
    await page.keyboard.press('Control+y'); assert.equal(await first().locator('strong').count(), 0)
    await page.reload(); await page.locator('.docx-source-home').waitFor(); assert.equal(await first().locator('strong').count(), 0)
    const revision2 = await save(2)
    assert.equal(revision2.body[0][1], 'ABCD'); assert.equal(revision2.runs[0][0][1], false); assert.equal(revision2.runs[0][1][2], true)
    assert.ok(revision2.emptyFormats[0][0][4]); assert.equal(revision2.paragraphLayouts[0].keepNext, true)
    assert.deepEqual(savePayloads.get(1).operations.map(op => [op.kind, op.ribbon]), [['setParagraphStyle', true]])
    await open(2); await first().click(); await choose('RibbonCustom')
    const revision3 = await save(3); assert.equal(revision3.body[0][1], 'ABCD'); assert.equal(revision3.runs[0][1][2], true)
    await open(3); assert.equal(await first().textContent(), 'ABCD'); assert.equal(await first().locator('em').textContent(), 'D')
    for (const revision of [revision2, revision3]) for (const [name, hash] of Object.entries(sourceInspection.packageParts)) assert.equal(revision.packageParts[name], hash, `保留${name}`)
    if (builtPreview) { await Promise.all(chunkChecks); assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file))) }
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, loadedChunks: Object.fromEntries(loadedChunks), operations: [...savePayloads.values()].map(value => value.operations), pageErrors, temporary }))
  } else if (smokeCase === 'note-reference-input') {
    const first = () => editor.locator('p').first()
    await first().click(); await page.keyboard.press('End')
    assert.equal(await editor.evaluate(element => element.editor.state.selection.$from.nodeBefore?.type.name), 'docNoteRef')
    await page.keyboard.insertText('新增'); await page.keyboard.insertText('续写')
    assert.ok((await first().textContent()).includes('新增续写'))
    await page.keyboard.press('Shift+ArrowLeft'); await page.keyboard.press('Shift+ArrowLeft')
    await page.locator('[data-tab-id="home"]').click(); await page.locator('[data-action="bold"]').click()
    await page.keyboard.press('Control+z'); await page.keyboard.press('Control+y')
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    assert.ok((await first().textContent()).includes('新增续写')); assert.equal(await editor.locator('[data-note-kind]').count(), 1)
    const revision2 = await save(2)
    assert.equal(revision2.body[0][1], 'A😀BC新增续写'); assert.equal(revision2.model.notes.footnotes.length, 1)
    for (const text of ['新增', '续写']) {
      assert.equal(revision2.runFormats[0].find(run => run[0] === text)[2], 'superscript')
      assert.ok(revision2.emptyFormats[0].find(run => run[0] === text)[4])
    }
    assert.equal(revision2.runs[0].find(run => run[0] === '续写')[1], true)
    await open(2); await first().click(); await page.keyboard.press('End'); await page.keyboard.insertText('再改')
    await page.locator('[data-tab-id="references"]').click()
    await page.getByLabel('已有脚注和尾注').selectOption(JSON.stringify(['footnote', '1']))
    await page.locator('[data-note-action="delete"]').click()
    const revision3 = await save(3)
    assert.equal(revision3.body[0][1], 'A😀BC新增续写再改'); assert.deepEqual(revision3.model.notes.footnotes, [])
    await open(3); assert.equal(await editor.locator('[data-note-kind]').count(), 0)
    assert.equal(await first().textContent(), 'A😀BC新增续写再改')
    assert.deepEqual(pageErrors, [])
    if (builtPreview) { await Promise.all(chunkChecks); assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file))) }
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, loadedChunks: Object.fromEntries(loadedChunks), operations: [...savePayloads.values()].map(value => value.operations), pageErrors, temporary }))
  } else if (['notes-decorations', 'notes-decorations-fresh', 'layout-decorations', 'layout-decorations-fresh'].includes(smokeCase)) {
    const fresh = smokeCase.endsWith('-fresh'), combinedLayout = smokeCase.startsWith('layout-decorations'), first = () => editor.locator('p').first()
    assert.equal(sourceInspection.model.blocks[0].editable, fresh)
    assert.equal(sourceInspection.model.blocks[0].paragraphShadingEditable, true); assert.equal(sourceInspection.model.blocks[0].paragraphBordersEditable, true)
    const home = () => page.locator('[data-tab-id="home"]').click(), references = () => page.locator('[data-tab-id="references"]').click()
    const commit = async text => { const dialog = page.locator('.workbook-ribbon-note-dialog'); await dialog.getByLabel('注释内容').fill(text); await dialog.getByRole('button', { name: '确定', exact: true }).click(); await dialog.waitFor({ state: 'hidden' }) }
    const choose = async (kind, id) => { await references(); await page.getByLabel('已有脚注和尾注').selectOption(JSON.stringify([kind, id])) }
    const shade = async action => { await page.locator('[data-action="shading-palette"]').click(); await page.locator(`[data-action="shading-${action}"]`).click(); await page.keyboard.press('Escape') }
    const border = async action => { await page.locator('[data-action="para-borders-menu"]').click(); await page.locator(`[data-action="para-border-${action}"]`).click(); await page.keyboard.press('Escape') }
    const layout = async stage => {
      if (!combinedLayout) return
      await first().click(); await home()
      await page.locator(`[data-action="align-${stage === 1 ? 'center' : stage === 2 ? 'right' : 'left'}"]`).click()
      if (stage !== 2) await page.locator(`[data-action="indent-${stage === 1 ? 'increase' : 'decrease'}"]`).click()
      for (const [action, value] of [['indent-right', stage === 1 ? 12 : stage === 2 ? 18 : 0], ['space-before-value', stage === 1 ? 6 : 0], ['space-after-value', stage === 3 ? 0 : 9]]) {
        await page.locator('[data-tab-id="layout"]').click(); const input = page.locator(`[data-action="${action}"]`)
        assert.equal(await input.isEnabled(), true); await input.fill(String(value)); await input.press('Enter')
      }
      await home(); await page.locator('[data-action="line-spacing"]').click(); await page.locator(`[data-source-action="line-spacing-${stage === 1 ? 1.5 : stage === 2 ? 2 : 1}"]`).click()
    }
    const append = async (text, format) => {
      await first().click(); await page.keyboard.press('End')
      // 在末尾引用前的文字边界续写；引用之后的opaque caret继承另行记录，不放宽run来源校验。
      while (await editor.evaluate(element => !element.editor.state.selection.empty || element.editor.state.selection.$from.nodeBefore?.type.name === 'docNoteRef')) await page.keyboard.press('ArrowLeft')
      const before = await editor.evaluate(element => element.editor.getJSON().content[0])
      await page.keyboard.insertText(text)
      assert.ok((await first().textContent()).includes(text), JSON.stringify({ text, before, after: await editor.evaluate(element => element.editor.getJSON().content[0]), reason: await page.locator('.docx-notice').textContent() }))
      for (const char of Array.from(text)) { void char; await page.keyboard.press('Shift+ArrowLeft') }; await home(); await page.locator(`[data-action="${format}"]`).click()
    }
    await first().click(); await home(); await shade('FFC000'); await border('bottom'); await append('新增', 'bold'); await layout(1)
    if (fresh) { await first().click(); await page.keyboard.press('End'); await references(); await page.locator('[data-note-action="insert-footnote"]').click(); await commit('来源脚注更正') }
    else { await choose('footnote', '1'); await page.locator('[data-note-action="edit"]').click(); await commit('来源脚注更正') }
    await first().click(); await page.keyboard.press('End'); await references(); await page.locator('[data-note-action="insert-endnote"]').click(); await commit('组合尾注')
    await page.keyboard.press('Control+z'); await page.keyboard.press('Control+y')
    await page.reload(); await page.locator('.docx-source-home').waitFor(); assert.equal(await editor.locator('[data-note-kind]').count(), 2)
    assert.ok((await first().textContent()).includes('新增'))
    const revision2 = await save(2)
    assert.equal(revision2.body[0][1], 'A😀BC尾新增'); assert.equal(revision2.model.notes.footnotes[0].text, '来源脚注更正'); assert.equal(revision2.model.notes.endnotes[0].text, '组合尾注')
    assert.ok(revision2.paragraphDecorations[0].pBdr.bottom); assert.equal(revision2.paragraphDecorations[0].shd.fill, 'ffc000')
    assert.ok(savePayloads.get(1).operations.some(op => op.kind === 'patchParagraphRuns'))
    assert.ok(savePayloads.get(1).operations.some(op => op.kind === (fresh ? 'insertNote' : 'updateNote')))
    await open(2); await append('再改', 'italic'); await first().click(); await home(); await border('top'); await shade('0070C0'); await layout(2)
    await choose('endnote', '1'); await page.locator('[data-note-action="edit"]').click(); await commit('组合尾注更正')
    await choose('footnote', '1'); await page.locator('[data-note-action="delete"]').click()
    const revision3 = await save(3)
    assert.equal(revision3.body[0][1], 'A😀BC尾新增再改'); assert.deepEqual(revision3.model.notes.footnotes, []); assert.equal(revision3.model.notes.endnotes[0].text, '组合尾注更正')
    assert.ok(revision3.paragraphDecorations[0].pBdr.top); assert.equal(revision3.paragraphDecorations[0].shd.fill, '0070c0')
    await open(3); await first().click(); await home(); await border('none'); await shade('none'); await append('清除后', 'bold'); await layout(3)
    await choose('endnote', '1'); await page.locator('[data-note-action="delete"]').click()
    const revision4 = await save(4)
    assert.equal(revision4.body[0][1], 'A😀BC尾新增再改清除后'); assert.deepEqual(revision4.paragraphDecorations[0], {})
    assert.deepEqual(revision4.model.notes.footnotes, []); assert.deepEqual(revision4.model.notes.endnotes, []); assert.equal(revision4.model.blocks[0].editable, true)
    const allowedParts = new Set(['word/footnotes.xml', 'word/endnotes.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml', ...(combinedLayout ? ['docProps/core.xml'] : [])])
    for (const revision of [revision2, revision3, revision4]) {
      for (const [name, hash] of Object.entries(sourceInspection.packageParts)) if (!allowedParts.has(name)) assert.equal(revision.packageParts[name], hash, `保留${name}`)
      for (const name of Object.keys(revision.packageParts)) if (!(name in sourceInspection.packageParts)) assert.ok(allowedParts.has(name), `仅新增notes部件${name}`)
      if (combinedLayout) {
        const { modified, revision: coreRevision, ...otherCore } = revision.coreProperties
        const { modified: sourceModified, revision: sourceCoreRevision, ...sourceOtherCore } = sourceInspection.coreProperties
        assert.deepEqual(otherCore, sourceOtherCore); assert.match(modified, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
        assert.equal(Number(coreRevision), Number(sourceCoreRevision) + [revision2, revision3, revision4].indexOf(revision) + 1)
        assert.equal(revision.paragraphLayouts[0].keepNext, true); assert.deepEqual(revision.paragraphLayouts.slice(1), sourceInspection.paragraphLayouts.slice(1)) }
      else assert.deepEqual(revision.paragraphLayouts, sourceInspection.paragraphLayouts)
      assert.deepEqual(revision.body.slice(1), sourceInspection.body.slice(1))
      assert.ok(revision.emptyFormats[0].find(run => run[0] === 'A😀')[4]); assert.equal(revision.runs[0].find(run => run[0] === 'A😀')[1], true)
    }
    if (combinedLayout) {
      assert.deepEqual(revision2.paragraphLayouts[0], { alignment: 'CENTER (1)', left: 720, right: 240, before: 120, after: 180, line: 1.5, keepNext: true })
      assert.deepEqual(revision3.paragraphLayouts[0], { alignment: 'RIGHT (2)', left: 720, right: 360, before: 0, after: 180, line: 2, keepNext: true })
      assert.deepEqual(revision4.paragraphLayouts[0], { alignment: 'LEFT (0)', left: 0, right: 0, before: 0, after: 0, line: 1, keepNext: true })
    }
    await open(4); assert.equal(await editor.locator('[data-note-kind]').count(), 0); assert.equal(await first().textContent(), 'A😀BC尾新增再改清除后')
    if (builtPreview) { await Promise.all(chunkChecks); assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file))); assert.ok([...loadedChunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file))) }
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, loadedChunks: Object.fromEntries(loadedChunks), browserVersion: browser.version(), operations: [...savePayloads.values()].map(value => value.operations), notes: [revision2, revision3, revision4].map(value => value.model.notes), pageErrors, temporary }))
  } else if (smokeCase === 'body-decorations' || smokeCase === 'body-decorations-no-notes') {
    const noNotes = smokeCase.endsWith('-no-notes'), targetIndex = noNotes ? 1 : 0
    assert.equal(!!sourceInspection.model.notes, !noNotes)
    const target = () => editor.locator('p').nth(targetIndex)
    const home = () => page.locator('[data-tab-id="home"]').click()
    const shade = async action => { await page.locator('[data-action="shading-palette"]').click(); await page.locator(`[data-action="shading-${action}"]`).click(); await page.keyboard.press('Escape') }
    const border = async action => { await page.locator('[data-action="para-borders-menu"]').click(); await page.locator(`[data-action="para-border-${action}"]`).click(); await page.keyboard.press('Escape') }
    const append = async (text, format) => {
      await target().click(); await page.keyboard.press('End'); await page.keyboard.insertText(text)
      for (const char of Array.from(text)) { void char; await page.keyboard.press('Shift+ArrowLeft') }
      await home(); await page.locator(`[data-action="${format}"]`).click()
    }
    const original = sourceInspection.body[targetIndex][1]
    await target().click(); await home(); await shade('FFC000'); await border('bottom'); await append('新增', 'bold')
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    assert.equal(await target().textContent(), `${original}新增`); assert.equal(await target().locator('strong').textContent(), '新增')
    await target().click(); await page.keyboard.press('End'); await page.keyboard.press('Control+z'); await page.keyboard.press('Control+y')
    const revision2 = await save(2)
    assert.deepEqual(savePayloads.get(1).operations.map(op => op.kind), ['setParagraphShading', 'setParagraphBorders', 'patchParagraphRuns'])
    assert.equal(revision2.body[targetIndex][1], `${original}新增`)
    assert.equal(revision2.runs[targetIndex].filter(run => run[1]).map(run => run[0]).join(''), '新增')
    assert.ok(revision2.paragraphDecorations[targetIndex].pBdr.bottom); assert.equal(revision2.paragraphDecorations[targetIndex].shd.fill, 'ffc000')
    await open(2); await append('再改', 'italic'); await target().click(); await home(); await border('top'); await shade('0070C0')
    const revision3 = await save(3)
    assert.deepEqual(savePayloads.get(2).operations.map(op => op.kind), ['setParagraphShading', 'setParagraphBorders', 'patchParagraphRuns'])
    assert.equal(revision3.body[targetIndex][1], `${original}新增再改`)
    assert.ok(revision3.runs[targetIndex].some(run => run[0].includes('再改') && run[2]))
    assert.ok(revision3.paragraphDecorations[targetIndex].pBdr.top); assert.equal(revision3.paragraphDecorations[targetIndex].shd.fill, '0070c0')
    await open(3); await target().click(); await home(); await border('none'); await shade('none'); await append('清除后', 'italic')
    const revision4 = await save(4)
    assert.equal(revision4.body[targetIndex][1], `${original}新增再改清除后`)
    assert.deepEqual(revision4.paragraphDecorations[targetIndex], {})
    for (const revision of [revision2, revision3, revision4]) {
      assert.deepEqual(revision.notesParts, sourceInspection.notesParts)
      assert.deepEqual(revision.paragraphLayouts, sourceInspection.paragraphLayouts)
      assert.ok(revision.emptyFormats[targetIndex].every(run => run[4] === true), '来源noProof随最终run继承')
      assert.deepEqual(revision.body.filter((_, index) => index !== targetIndex), sourceInspection.body.filter((_, index) => index !== targetIndex))
      assert.deepEqual(revision.packageParts, sourceInspection.packageParts)
    }
    await open(4); assert.equal(await target().textContent(), `${original}新增再改清除后`)
    if (builtPreview) { await Promise.all(chunkChecks); assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file))); assert.ok([...loadedChunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file))) }
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, loadedChunks: Object.fromEntries(loadedChunks), browserVersion: browser.version(), operations: [...savePayloads.values()].map(value => value.operations), paragraphs: [revision2, revision3, revision4].map(value => value.body[targetIndex]), pageErrors, temporary }))
  } else if (smokeCase === 'paragraph-format-protected') {
    await editor.locator('p').first().click(); await page.locator('[data-tab-id="home"]').click()
    assert.equal(sourceInspection.model.blocks[0].paragraphShadingEditable, false)
    assert.equal(sourceInspection.model.blocks[0].paragraphBordersEditable, false)
    for (const action of ['shading', 'shading-palette', 'para-borders', 'para-borders-menu']) assert.equal(await page.locator(`[data-action="${action}"]`).isDisabled(), true)
    assert.equal(savePayloads.size, 0); assert.deepEqual(pageErrors, [])
    if (builtPreview) await Promise.all(chunkChecks)
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, loadedChunks: Object.fromEntries(loadedChunks), browserVersion: browser.version(), protectedControlsDisabled: true, pageErrors, temporary }))
  } else if (smokeCase === 'paragraph-format-combination') {
    const first = () => editor.locator('p').first()
    const home = () => page.locator('[data-tab-id="home"]').click()
    const shade = async action => { await page.locator('[data-action="shading-palette"]').click(); await page.locator(`[data-action="shading-${action}"]`).click(); await page.keyboard.press('Escape') }
    const border = async action => { await page.locator('[data-action="para-borders-menu"]').click(); await page.locator(`[data-action="para-border-${action}"]`).click(); await page.keyboard.press('Escape') }
    await first().click(); await home(); await shade('FFC000'); await border('bottom')
    await first().click(); await page.keyboard.press('Control+z')
    assert.equal(await first().evaluate(p => p.style.borderBottomStyle), '')
    await page.keyboard.press('Control+y')
    await page.reload(); await page.locator('.docx-source-home').waitFor(); await first().click(); await home()
    const revision2 = await save(2)
    assert.deepEqual(savePayloads.get(1).operations.map(op => op.kind), ['setParagraphShading', 'setParagraphBorders'])
    assert.equal(revision2.paragraphDecorations[0].shd.fill, 'ffc000')
    assert.ok(revision2.paragraphDecorations[0].pBdr.bottom)
    await open(2); await first().click(); await home()
    await border('top'); await shade('0070C0')
    const revision3 = await save(3)
    assert.equal(revision3.paragraphDecorations[0].shd.fill, '0070c0')
    assert.ok(revision3.paragraphDecorations[0].pBdr.top); assert.equal(revision3.paragraphDecorations[0].pBdr.bottom, undefined)
    await open(3); await first().click(); await home(); await border('none'); await shade('none')
    const revision4 = await save(4)
    assert.deepEqual(savePayloads.get(3).operations.map(op => op.kind), ['setParagraphShading', 'setParagraphBorders'])
    assert.deepEqual(revision4.paragraphDecorations, [{}, {}, {}])
    for (const revision of [revision2, revision3, revision4]) {
      assert.deepEqual(revision.packageParts, sourceInspection.packageParts)
      assert.deepEqual(revision.emptyFormats, sourceInspection.emptyFormats)
      assert.deepEqual(revision.paragraphLayouts, sourceInspection.paragraphLayouts)
      assert.deepEqual(revision.body, sourceInspection.body)
    }
    await open(4); assert.deepEqual(pageErrors, [])
    if (builtPreview) {
      await Promise.all(chunkChecks)
      assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
      assert.ok([...loadedChunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
    }
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, loadedChunks: Object.fromEntries(loadedChunks), browserVersion: browser.version(), operations: [...savePayloads.values()].map(value => value.operations), decorations: [revision2, revision3, revision4].map(value => value.paragraphDecorations[0]), pageErrors, temporary }))
  } else if (smokeCase === 'plain-no-notes') {
    assert.equal(sourceInspection.model.notes, undefined)
    const second = () => editor.locator('p').nth(1)
    await second().click(); await page.keyboard.press('End'); await page.keyboard.insertText('新增')
    await page.keyboard.press('Shift+ArrowLeft'); await page.keyboard.press('Shift+ArrowLeft')
    await page.locator('[data-tab-id="home"]').click(); await page.locator('[data-action="bold"]').click()
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    assert.ok((await second().textContent()).endsWith('新增')); assert.equal(await second().locator('strong').textContent(), '新增')
    await second().click(); await page.keyboard.press('End'); await page.keyboard.press('Control+z'); await page.keyboard.press('Control+y')
    const revision2 = await save(2)
    assert.equal(revision2.model.notes, undefined); assert.deepEqual(revision2.notesParts, sourceInspection.notesParts)
    assert.deepEqual(savePayloads.get(1).operations.map(op => op.kind), ['patchParagraphRuns'])
    assert.equal(revision2.runs[1].filter(run => run[1]).map(run => run[0]).join(''), '新增')
    await open(2); assert.equal(await second().locator('strong').textContent(), '新增')
    if (builtPreview) {
      await Promise.all(chunkChecks)
      assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)), '实际加载Word构建入口')
      assert.ok([...loadedChunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)), '实际加载Word构建引擎')
    }
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, loadedChunks: Object.fromEntries(loadedChunks), browserVersion: browser.version(), operations: savePayloads.get(1).operations, notesPartsPreserved: true, pageErrors, temporary }))
  } else if (smokeCase === 'notes-layout') {
    const first = () => editor.locator('p').first()
    const home = () => page.locator('[data-tab-id="home"]').click()
    const setLayoutField = async (action, value) => {
      await page.locator('[data-tab-id="layout"]').click()
      const input = page.locator(`[data-action="${action}"]`)
      assert.equal(await input.isEnabled(), true, `notes来源段落应允许${action}`)
      await input.fill(String(value)); await input.press('Enter')
    }
    const commit = async text => {
      const dialog = page.locator('.workbook-ribbon-note-dialog')
      await dialog.getByLabel('注释内容').fill(text)
      await dialog.getByRole('button', { name: '确定', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
    }
    await first().click(); await page.keyboard.press('Home'); await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight')
    await page.keyboard.insertText('新增')
    await home(); await page.locator('[data-action="align-center"]').click(); await page.locator('[data-action="indent-increase"]').click()
    await setLayoutField('indent-right', 12); await setLayoutField('space-before-value', 6)
    await home(); await page.locator('[data-action="line-spacing"]').click(); await page.locator('[data-source-action="line-spacing-1.5"]').click()
    await first().click(); await page.keyboard.press('End'); await page.keyboard.insertText('追加')
    await page.locator('[data-tab-id="references"]').click(); await page.locator('[data-note-action="insert-endnote"]').click(); await commit('同段布局尾注')
    await page.keyboard.press('Control+z'); await page.keyboard.press('Control+y')
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    const attrs = await editor.evaluate(element => element.editor.getJSON().content[0].attrs)
    assert.equal(attrs.align, 'center'); assert.equal(attrs.indentLeft, 720); assert.equal(attrs.indentRight, 240); assert.equal(attrs.spaceBefore, 120); assert.equal(attrs.lineSpacing, 1.5)
    const revision2 = await save(2)
    assert.deepEqual(revision2.paragraphLayouts[0], { alignment: 'CENTER (1)', left: 720, right: 240, before: 120, after: null, line: 1.5, keepNext: true })
    assert.equal(revision2.body[0][1], 'A😀新增BC尾追加')
    assert.equal(revision2.model.notes.footnotes[0].text, '来源脚注'); assert.equal(revision2.model.notes.endnotes[0].text, '同段布局尾注')
    assert.ok(revision2.emptyFormats[0].filter(run => run[0].includes('新增') || run[0] === 'A😀').every(run => run[4]))
    await open(2); await first().click(); await page.keyboard.press('End')
    await home(); await page.locator('[data-action="align-right"]').click(); await setLayoutField('space-after-value', 9)
    await page.locator('[data-tab-id="references"]').click(); await page.getByLabel('已有脚注和尾注').selectOption(JSON.stringify(['footnote', '1']))
    await page.locator('[data-note-action="edit"]').click(); await commit('来源脚注更正')
    const revision3 = await save(3)
    assert.equal(revision3.paragraphLayouts[0].alignment, 'RIGHT (2)'); assert.equal(revision3.paragraphLayouts[0].after, 180)
    assert.equal(revision3.model.notes.footnotes[0].text, '来源脚注更正')
    assert.ok(!savePayloads.get(2).operations.some(op => op.kind === 'patchParagraphRuns'))
    await open(3); assert.ok((await first().textContent()).includes('新增')); assert.equal(await editor.locator('[data-note-kind]').count(), 2)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), operations: [...savePayloads.values()].map(value => value.operations), layouts: revision3.paragraphLayouts[0], pageErrors, temporary }))
  } else if (smokeCase === 'notes-empty') {
    const paragraph = index => editor.locator('p').nth(index)
    const computed = index => paragraph(index).evaluate(element => {
      const target = [...element.querySelectorAll('span, strong, em')].find(node => node.textContent?.includes('新增') || node.textContent?.includes('New')) ?? element
      const style = getComputedStyle(target)
      return { font: style.fontFamily, size: parseFloat(style.fontSize), italic: style.fontStyle, weight: Number(style.fontWeight) }
    })
    const insertNote = async (kind, text) => {
      await page.locator('[data-tab-id="references"]').click()
      await page.locator(`[data-note-action="insert-${kind}"]`).click()
      const dialog = page.locator('.workbook-ribbon-note-dialog')
      await dialog.getByLabel('注释内容').fill(text)
      await dialog.getByRole('button', { name: '确定', exact: true }).click()
      await dialog.waitFor({ state: 'hidden' })
    }
    await paragraph(0).click(); await page.keyboard.insertText('新增😀')
    let style = await computed(0)
    assert.ok(style.font.includes('Arial')); assert.ok(Math.abs(style.size - 22 * 4 / 3) < .1); assert.equal(style.italic, 'italic')
    await insertNote('footnote', '空段脚注')
    await page.keyboard.press('Control+z'); await page.keyboard.press('Control+y')
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    assert.ok((await paragraph(0).textContent()).includes('新增😀'))
    style = await computed(0); assert.ok(style.font.includes('Arial')); assert.equal(style.italic, 'italic')
    const revision2 = await save(2)
    assert.deepEqual(revision2.emptyFormats[0].find(run => run[0]), ['新增😀', 'Arial', 22, true, true])
    assert.equal(revision2.model.notes.footnotes[0].text, '空段脚注')
    await open(2)
    await paragraph(1).click(); await page.keyboard.insertText('New style')
    style = await computed(1)
    assert.ok(style.font.includes('Cambria'), JSON.stringify(style)); assert.ok(Math.abs(style.size - 16 * 4 / 3) < .1); assert.equal(style.italic, 'italic'); assert.ok(style.weight >= 600)
    await insertNote('endnote', '空段样式尾注')
    const revision3 = await save(3)
    assert.equal(revision3.emptyFormats[1].find(run => run[0])[1], null)
    assert.equal(revision3.emptyFormats[1].find(run => run[0])[2], null)
    assert.equal(revision3.model.notes.endnotes[0].text, '空段样式尾注')
    await open(3)
    style = await computed(1); assert.ok(style.font.includes('Cambria')); assert.equal(style.italic, 'italic'); assert.ok(style.weight >= 600)
    assert.deepEqual(revision3.body.map(block => block[1]), ['新增😀', 'New style', '第三段'])
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), operations: [...savePayloads.values()].map(value => value.operations), inheritedStyle: style, pageErrors, temporary }))
  } else if (smokeCase === 'notes-inline') {
    const references = () => page.locator('[data-tab-id="references"]').click()
    const commit = async text => {
      const dialog = page.locator('.workbook-ribbon-note-dialog')
      await dialog.getByLabel('注释内容').fill(text)
      await dialog.getByRole('button', { name: '确定', exact: true }).click()
      await dialog.waitFor({ state: 'hidden' })
    }
    const first = () => editor.locator('p').first()
    const focusFirst = async () => {
      await first().click()
      await page.waitForFunction(() => { const view = document.querySelector('[aria-label="Word 文档编辑区"]').editor; return view.state.selection.empty && view.state.selection.$from.parent.attrs.docxIndex === 0 })
    }
    await focusFirst(); await page.keyboard.press('Home')
    await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight')
    await page.keyboard.insertText('新增')
    await references(); await page.locator('[data-note-action="insert-footnote"]').click(); await commit('同段混编脚注')
    await focusFirst(); await page.keyboard.press('End'); await page.keyboard.insertText('追加')
    await page.keyboard.press('Control+z'); await page.keyboard.press('Control+y')
    await focusFirst()
    await page.keyboard.press('Home'); await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight')
    await page.keyboard.press('Shift+ArrowRight'); await page.keyboard.press('Shift+ArrowRight')
    assert.equal(await page.evaluate(() => window.getSelection()?.toString()), '新增')
    await page.locator('[data-tab-id="home"]').click()
    await page.locator('[data-action="highlight-palette"]').click(); await page.locator('[data-action="highlight-cyan"]').click()
    await page.locator('[data-action="superscript"]').click()
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    assert.ok((await first().textContent()).includes('新增'))
    // 在恢复后的同段继续键入，不能丢失root注释意图或重复插marker。
    await focusFirst(); await page.keyboard.press('End'); await page.keyboard.insertText('续写')
    const revision2 = await save(2)
    assert.equal(revision2.body[0][1], 'A😀新增BC尾追加续写')
    assert.equal(revision2.model.notes.footnotes.length, 1)
    assert.equal(revision2.model.notes.footnotes[0].text, '同段混编脚注')
    assert.ok(savePayloads.get(1).operations.some(op => op.kind === 'patchParagraphRuns'))
    const highlighted = revision2.runFormats[0].filter(run => run[1] === 'cyan')
    assert.equal(highlighted.map(run => run[0]).join(''), '新增')
    assert.ok(highlighted.every(run => run[2] === 'superscript'))
    assert.equal(revision2.runs[0][0][0], 'A😀')
    assert.equal(revision2.runs[0][0][1], true)
    await open(2); await focusFirst(); await page.keyboard.press('End'); await page.keyboard.insertText('再改')
    await references(); await page.getByLabel('已有脚注和尾注').selectOption(JSON.stringify(['footnote', '1']))
    await page.locator('[data-note-action="delete"]').click()
    await focusFirst(); await page.keyboard.press('Home'); await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight')
    await page.locator('[data-note-action="insert-endnote"]').click(); await commit('改字并删除脚注后新增尾注')
    const revision3 = await save(3)
    assert.equal(revision3.body[0][1], 'A😀新增BC尾追加续写再改')
    assert.deepEqual(revision3.model.notes.footnotes, [])
    assert.equal(revision3.model.notes.endnotes.length, 1)
    assert.deepEqual(revision3.body.slice(1), revision2.body.slice(1))
    await open(3); await focusFirst(); await page.keyboard.press('End'); await page.keyboard.insertText('终')
    const revision4 = await save(4)
    assert.equal(revision4.body[0][1], 'A😀新增BC尾追加续写再改终')
    assert.equal(revision4.model.notes.endnotes.length, 1)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), operations: [...savePayloads.values()].map(payload => payload.operations), pageErrors, temporary }))
  } else if (smokeCase === 'notes') {
    const references = () => page.locator('[data-tab-id="references"]').click()
    const choose = (kind, id) => page.getByLabel('已有脚注和尾注').selectOption(JSON.stringify([kind, id]))
    const commit = async text => {
      const dialog = page.locator('.workbook-ribbon-note-dialog')
      await dialog.getByLabel('注释内容').fill(text)
      await dialog.getByRole('button', { name: '确定', exact: true }).click()
      await dialog.waitFor({ state: 'hidden' })
    }
    await editor.locator('p').filter({ hasText: '第一段正文' }).click()
    await page.keyboard.press('Home'); await page.keyboard.press('ArrowRight')
    await references()
    await page.locator('[data-note-action="insert-footnote"]').click(); await commit('脚注正文')
    await page.keyboard.press('Control+z'); assert.equal(await editor.locator('[data-note-kind]').count(), 0)
    await page.keyboard.press('Control+y')
    await choose('footnote', '1'); await page.locator('[data-note-action="edit"]').click(); await commit('脚注更正😀')
    await editor.locator('p').filter({ hasText: '第二段前半' }).click()
    await page.waitForFunction(() => {
      const view = document.querySelector('[aria-label="Word 文档编辑区"]').editor
      return view.state.selection.empty && view.state.selection.$from.parent.attrs.docxIndex === 1
    })
    await page.keyboard.press('Home'); await page.keyboard.press('ArrowRight')
    await page.locator('[data-note-action="insert-endnote"]').click(); await commit('尾注正文')
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    const revision2 = await save(2)
    assert.deepEqual(revision2.model.notes.footnotes.map(note => [note.id, note.text, note.references.length]), [['1', '脚注更正😀', 1]])
    assert.deepEqual(revision2.model.notes.endnotes.map(note => [note.id, note.text, note.references.length]), [['1', '尾注正文', 1]])
    assert.deepEqual(savePayloads.get(1).operations.map(op => op.kind), ['insertNote', 'insertNote'])
    assert.ok(savePayloads.get(1).operations.every(op => !('noteId' in op)))
    await open(2); await references()
    await choose('footnote', '1'); await page.locator('[data-note-action="edit"]').click(); await commit('保存后再次编辑')
    await choose('endnote', '1'); await page.locator('[data-note-action="delete"]').click()
    const revision3 = await save(3)
    assert.equal(revision3.model.notes.footnotes[0].text, '保存后再次编辑')
    assert.deepEqual(revision3.model.notes.endnotes, [])
    await open(3); await references()
    await choose('footnote', '1'); await page.locator('[data-note-action="delete"]').click()
    const revision4 = await save(4)
    assert.deepEqual(revision4.model.notes.footnotes, [])
    assert.equal(revision4.body[0][1], '第一段正文')
    assert.equal(revision4.body[1][1], '第二段前半第二段后半')
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), operations: [...savePayloads.values()].map(payload => payload.operations), pageErrors, temporary }))
  } else if (smokeCase === 'hf-same-save') {
    const choose = async () => {
      await page.locator('[data-tab-id="layout"]').click()
      await editor.locator('p').filter({ hasText: '第三段' }).click()
      await page.waitForFunction(() => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === '第 2 节，共 2 节')
      await page.locator('[data-tab-id="headerFooter"]').click()
    }
    const slot = (inspection, index = 1) => inspection.model.sections[index].headersFooters.parts['header.default']
    const type = async text => {
      const hfEditor = page.locator('.docx-hf-editor-host [contenteditable="true"]')
      await hfEditor.click(); await page.keyboard.press('Control+a'); await page.keyboard.type(text)
      await page.locator('[data-tab-id="layout"]').click()
    }
    page.on('dialog', dialog => dialog.accept())
    await choose()
    const linked = page.locator('[data-source-action="hf-link-previous"]')
    assert.equal(await linked.isChecked(), true)
    await linked.uncheck()
    await type('same-save independent picture and hyperlink')
    await page.reload(); await page.locator('.docx-source-home').waitFor(); await choose()
    assert.equal(await linked.isChecked(), false)
    assert.equal(await page.locator('.docx-hf-editor-host [contenteditable="true"]').textContent(), 'same-save independent picture and hyperlink')
    const revision2 = await save(2), own = slot(revision2)
    assert.equal(savePayload.operations.some(operation => operation.kind === 'setHeaderFooter' && operation.afterLink === true), true)
    assert.equal(own.text, 'same-save independent picture and hyperlink')
    assert.equal(own.linked, false)
    assert.equal(slot(revision2, 0).expectedPartSha256, slot(sourceInspection, 0).expectedPartSha256)
    assert.deepEqual(revision2.hfMedia[own.path], { pictures: 1, links: 1 })
    assert.deepEqual(revision2.mediaParts, sourceInspection.mediaParts)
    assert.deepEqual(revision2.body, sourceInspection.body)
    await open(2); await choose()
    assert.equal(await linked.isChecked(), false)
    await linked.check()
    await type('same-save shared owner picture and hyperlink')
    const revision3 = await save(3)
    assert.equal(slot(revision3).linked, true)
    assert.equal(slot(revision3).text, 'same-save shared owner picture and hyperlink')
    assert.equal(slot(revision3, 0).text, 'same-save shared owner picture and hyperlink')
    assert.equal(revision3.hfParts[own.path], revision2.hfParts[own.path])
    assert.deepEqual(revision3.hfMedia[slot(revision3).path], { pictures: 1, links: 1 })
    assert.deepEqual(revision3.mediaParts, sourceInspection.mediaParts)
    assert.deepEqual(revision3.body, sourceInspection.body)
    await open(3); await choose(); assert.equal(await linked.isChecked(), true)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), slot: slot(revision3), pageErrors }))
  } else if (smokeCase === 'hf-media') {
    const choose = async () => {
      await page.locator('[data-tab-id="layout"]').click()
      await editor.locator('p').filter({ hasText: '第三段' }).click()
      await page.waitForFunction(() => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === '第 2 节，共 2 节')
      await page.locator('[data-tab-id="headerFooter"]').click()
    }
    const slot = (inspection, index = 1) => inspection.model.sections[index].headersFooters.parts['header.default']
    await choose()
    const linked = page.locator('[data-source-action="hf-link-previous"]')
    assert.equal(await linked.isChecked(), true)
    assert.equal(await linked.isDisabled(), false)
    await linked.uncheck()
    const revision2 = await save(2)
    const original = slot(sourceInspection), own = slot(revision2)
    assert.equal(own.linked, false)
    assert.equal(own.expectedPartSha256, original.expectedPartSha256)
    assert.deepEqual(revision2.hfMedia[own.path], { pictures: 1, links: 1 })
    assert.equal(revision2.hfRelations[own.path.replace('word/', 'word/_rels/') + '.rels'], sourceInspection.hfRelations[original.path.replace('word/', 'word/_rels/') + '.rels'])
    assert.deepEqual(revision2.mediaParts, sourceInspection.mediaParts)
    await open(2); await choose()
    const hfEditor = page.locator('.docx-hf-editor-host [contenteditable="true"]')
    await hfEditor.click(); await page.keyboard.press('Control+a'); await page.keyboard.type('independent picture and hyperlink header')
    const revision3 = await save(3)
    assert.equal(slot(revision3).text, 'independent picture and hyperlink header')
    assert.equal(slot(revision3, 0).expectedPartSha256, slot(sourceInspection, 0).expectedPartSha256)
    assert.deepEqual(revision3.hfMedia[own.path], { pictures: 1, links: 1 })
    assert.deepEqual(revision3.hfRelations, revision2.hfRelations)
    assert.deepEqual(revision3.mediaParts, sourceInspection.mediaParts)
    assert.deepEqual(revision3.body, sourceInspection.body)
    await open(3); await choose()
    assert.equal(await linked.isChecked(), false)
    assert.equal(await hfEditor.textContent(), 'independent picture and hyperlink header')
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), slot: slot(revision3), hfMedia: revision3.hfMedia[own.path], mediaParts: revision3.mediaParts, pageErrors }))
  } else if (smokeCase === 'hf-link') {
    const choose = async (text, label) => {
      await page.locator('[data-tab-id="layout"]').click()
      await editor.locator('p').filter({ hasText: text }).click()
      await page.waitForFunction(expected => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === expected, label)
      await page.locator('[data-tab-id="headerFooter"]').click()
      await page.waitForFunction(expected => document.querySelector('[data-source-action="hf-current-section"]')?.textContent === expected, label)
    }
    const slot = inspection => inspection.model.sections.map(section => section.headersFooters.parts['header.default'])
    page.on('dialog', dialog => dialog.accept())
    const linked = page.locator('[data-source-action="hf-link-previous"]')
    await choose('第一段正文', '第 1 节，共 2 节')
    assert.equal(await linked.isDisabled(), true)
    await choose('第三段', '第 2 节，共 2 节')
    assert.equal(await linked.isChecked(), false)
    await linked.check()
    assert.equal(await page.locator('.docx-hf-editor-host [contenteditable="true"]').textContent(), '0:header')
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    await choose('第三段', '第 2 节，共 2 节'); assert.equal(await linked.isChecked(), true)
    const revision2 = await save(2)
    assert.equal(slot(revision2)[1].text, '0:header')
    assert.equal(slot(revision2)[1].ownRId, null)
    assert.deepEqual(revision2.hfParts, sourceInspection.hfParts)
    assert.deepEqual(revision2.body, sourceInspection.body)
    await open(2); await choose('第三段', '第 2 节，共 2 节')
    await linked.uncheck()
    const revision3 = await save(3)
    assert.equal(slot(revision3)[1].linked, false)
    assert.equal(slot(revision3)[1].expectedPartSha256, slot(revision3)[0].expectedPartSha256, 'unlink clones the original formatted XML exactly')
    assert.notEqual(slot(revision3)[1].rId, slot(revision3)[0].rId)
    await open(3); await choose('第三段', '第 2 节，共 2 节')
    const hfEditor = page.locator('.docx-hf-editor-host [contenteditable="true"]')
    await hfEditor.click(); await page.keyboard.press('Control+a'); await page.keyboard.type('new independent header')
    const revision4 = await save(4)
    assert.equal(slot(revision4)[0].text, '0:header')
    assert.equal(slot(revision4)[1].text, 'new independent header')
    assert.deepEqual(revision4.body, sourceInspection.body)
    await open(4); await choose('第三段', '第 2 节，共 2 节'); await linked.check()
    const revision5 = await save(5)
    assert.equal(slot(revision5)[1].linked, true)
    assert.equal(slot(revision5)[1].text, '0:header')
    assert.deepEqual(revision5.body, sourceInspection.body)
    for (const [name, hash] of Object.entries(sourceInspection.hfParts)) if (!name.endsWith('document.xml.rels')) assert.equal(revision5.hfParts[name], hash, name)
    await open(5); await choose('第三段', '第 2 节，共 2 节'); assert.equal(await linked.isChecked(), true)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), slots: slot(revision5), revisions: 5, pageErrors }))
  } else if (smokeCase === 'page-number') {
    const choose = async (text, label) => {
      await editor.locator('p').filter({ hasText: text }).click()
      await page.waitForFunction(expected => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === expected, label)
    }
    const edit = async (format, start) => {
      await page.locator('[data-source-action="page-number-format"]').click()
      await page.getByLabel('页码编号格式').selectOption(format)
      await page.getByLabel('起始页码', { exact: true }).fill(start)
      await page.getByRole('button', { name: '确定', exact: true }).click()
      await page.getByRole('dialog', { name: '页码格式' }).waitFor({ state: 'hidden' })
    }
    const echo = async (format, start) => {
      await page.locator('[data-source-action="page-number-format"]').click()
      assert.equal(await page.getByLabel('页码编号格式').inputValue(), format)
      assert.equal(await page.getByLabel('起始页码', { exact: true }).inputValue(), start)
      await page.locator('[data-source-action="page-number-cancel"]').click()
    }
    await page.locator('[data-tab-id="layout"]').click()
    await choose('第一段正文', '第 1 节，共 2 节'); await edit('upperRoman', '0')
    await choose('第三段', '第 2 节，共 2 节'); await edit('lowerLetter', '5')
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    await page.locator('[data-tab-id="layout"]').click()
    await choose('第一段正文', '第 1 节，共 2 节'); await echo('upperRoman', '0')
    await choose('第三段', '第 2 节，共 2 节'); await echo('lowerLetter', '5')
    const revision2 = await save(2)
    assert.deepEqual(revision2.sections.map(s => [s.pageNumberFmt, s.pageNumberStart]), [['upperRoman', 0], ['lowerLetter', 5]])
    assert.deepEqual(revision2.hfParts, sourceInspection.hfParts)
    await open(2); await page.locator('[data-tab-id="layout"]').click()
    await choose('第一段正文', '第 1 节，共 2 节'); await edit('decimal', '')
    const revision3 = await save(3)
    assert.deepEqual(revision3.sections.map(s => [s.pageNumberFmt, s.pageNumberStart]), [[null, null], ['lowerLetter', 5]])
    assert.deepEqual(revision3.hfParts, sourceInspection.hfParts)
    await open(3); await page.locator('[data-tab-id="layout"]').click()
    await choose('第一段正文', '第 1 节，共 2 节'); await echo('decimal', '')
    await choose('第三段', '第 2 节，共 2 节'); await echo('lowerLetter', '5')
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), sections: revision3.sections, preservedHfParts: Object.keys(revision3.hfParts), pageErrors }))
  } else if (smokeCase === 'odd-even') {
    const chooseSection = async (text, label) => {
      await editor.locator('p').filter({ hasText: text }).click()
      await page.waitForFunction(expected => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === expected, label)
    }
    const toggle = page.locator('[data-source-action="header-even-odd"]')
    await page.locator('[data-tab-id="layout"]').click()
    await chooseSection('第一段正文', '第 1 节，共 2 节')
    assert.equal(await toggle.isChecked(), false)
    await toggle.check()
    await chooseSection('第三段', '第 2 节，共 2 节')
    assert.equal(await toggle.isChecked(), true)
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    await page.locator('[data-tab-id="layout"]').click()
    await chooseSection('第一段正文', '第 1 节，共 2 节')
    assert.equal(await toggle.isChecked(), true)
    const revision2 = await save(2)
    assert.equal(revision2.evenAndOddHeaders, true)
    assert.deepEqual(revision2.hfParts, sourceInspection.hfParts)
    assert.deepEqual(revision2.sections, sourceInspection.sections)
    await open(2); await page.locator('[data-tab-id="layout"]').click()
    await chooseSection('第三段', '第 2 节，共 2 节')
    assert.equal(await toggle.isChecked(), true)
    await toggle.uncheck()
    const revision3 = await save(3)
    assert.equal(revision3.evenAndOddHeaders, false)
    assert.deepEqual(revision3.hfParts, sourceInspection.hfParts)
    assert.deepEqual(revision3.sections, sourceInspection.sections)
    await open(3); await page.locator('[data-tab-id="layout"]').click()
    await chooseSection('第一段正文', '第 1 节，共 2 节')
    assert.equal(await toggle.isChecked(), false)
    await chooseSection('第三段', '第 2 节，共 2 节')
    assert.equal(await toggle.isChecked(), false)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), evenAndOddHeaders: revision3.evenAndOddHeaders, preservedHfParts: Object.keys(revision3.hfParts), pageErrors }))
  } else if (smokeCase === 'title-page') {
    const chooseSection = async (text, expected) => {
      await editor.locator('p').filter({ hasText: text }).click()
      await page.waitForFunction(label => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === label, expected)
    }
    const toggle = page.locator('[data-source-action="header-title-page"]')
    await page.locator('[data-tab-id="layout"]').click()
    await chooseSection('第一段正文', '第 1 节，共 2 节')
    assert.equal(await toggle.isChecked(), false)
    await toggle.click()
    assert.equal(await toggle.isChecked(), true)
    await chooseSection('第三段', '第 2 节，共 2 节')
    assert.equal(await toggle.isChecked(), true)
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    await page.locator('[data-tab-id="layout"]').click()
    await chooseSection('第一段正文', '第 1 节，共 2 节')
    assert.equal(await toggle.isChecked(), true)
    const revision2 = await save(2)
    assert.deepEqual(revision2.sections.map(section => section.titlePg), [true, true])
    assert.deepEqual(revision2.hfParts, sourceInspection.hfParts)
    await open(2); await page.locator('[data-tab-id="layout"]').click()
    await chooseSection('第一段正文', '第 1 节，共 2 节')
    assert.equal(await toggle.isChecked(), true)
    await toggle.uncheck()
    const revision3 = await save(3)
    assert.deepEqual(revision3.sections.map(section => section.titlePg), [false, true])
    assert.deepEqual(revision3.hfParts, sourceInspection.hfParts)
    await open(3); await page.locator('[data-tab-id="layout"]').click()
    await chooseSection('第一段正文', '第 1 节，共 2 节')
    assert.equal(await toggle.isChecked(), false)
    await chooseSection('第三段', '第 2 节，共 2 节')
    assert.equal(await toggle.isChecked(), true)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), sections: revision3.sections, preservedHfParts: Object.keys(revision3.hfParts), pageErrors }))
  } else if (smokeCase === 'case') {
    await page.locator('[data-tab-id="home"]').click()
    await editor.locator('p').filter({ hasText: 'straße' }).click()
    await page.keyboard.press('Home'); await page.keyboard.press('Shift+End')
    await page.locator('[data-action="change-case"]').click()
    await page.locator('[data-action="change-case:upper"]').click()
    await editor.getByText('STRASSE', { exact: true }).waitFor()
    await page.keyboard.press('Control+z'); await editor.getByText('straße', { exact: true }).waitFor()
    await page.keyboard.press('Control+y'); await editor.getByText('STRASSE', { exact: true }).waitFor()
    await page.reload(); await page.locator('.docx-source-home').waitFor(); await editor.getByText('STRASSE', { exact: true }).waitFor()
    const revision2 = await save(2)
    assert.equal(revision2.body[0][1], 'STRASSE')
    assert.deepEqual(revision2.runs[0], [['STRASSE', true, false]])
    assert.equal(sourceInspection.body[0][1], 'straße')
    await open(2); await editor.getByText('STRASSE', { exact: true }).waitFor()
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), runs: revision2.runs, pageErrors, temporary }))
  } else if (smokeCase === 'picture') {
    await editor.locator('p').filter({ hasText: '第一段正文' }).click()
    await page.keyboard.press('Home'); await page.keyboard.press('ArrowRight')
    const chooser = page.waitForEvent('filechooser')
    await insert('insert-picture')
    await (await chooser).setFiles({ name: 'photo.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64') })
    await editor.locator('img').waitFor()
    // 刷新恢复本地草稿，再实际保存并通过 python-docx 回读图片。
    await page.reload(); await page.locator('.docx-source-home').waitFor(); await editor.locator('img').waitFor()
    const revision2 = await save(2)
    assert.equal(revision2.pictures.length, 1)
    assert.deepEqual(revision2.pictures[0], { width: 9525, height: 9525 })
    assert.ok(savePayloads.get(1).operations.some(op => op.kind === 'insertParagraphImage'))
    await open(2); await editor.locator('img').waitFor()
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), pictures: revision2.pictures, pageErrors, temporary }))
  } else if (smokeCase === 'clear') {
    await page.locator('[data-tab-id="home"]').click()
    await editor.locator('p').filter({ hasText: '第一段正文' }).click()
    await page.locator('[data-action="clear-formatting"]').click()
    await page.keyboard.press('Control+z')
    assert.equal(await editor.locator('p').first().locator('strong').count(), 1)
    await page.keyboard.press('Control+y')
    assert.equal(await editor.locator('p').first().locator('strong').count(), 0)
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    assert.equal(await editor.locator('p').first().locator('strong').count(), 0)
    const revision2 = await save(2)
    assert.deepEqual(savePayloads.get(1).operations.map(op => op.kind), ['clearParagraphFormatting'])
    assert.deepEqual(revision2.runs[0], [['第一段正文', false, false]])
    assert.deepEqual(revision2.runs[1], [['第二段前半第二段后半', true, false]])
    await open(2)
    assert.equal(await editor.locator('p').first().locator('strong').count(), 0)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), operations: savePayloads.get(1).operations, runs: revision2.runs, pageErrors, temporary }))
  } else if (smokeCase === 'selection-format') {
    const select = async () => {
      await editor.locator('p').filter({ hasText: 'A😀BC尾' }).click()
      await page.keyboard.press('Home'); await page.keyboard.press('ArrowRight')
      await page.keyboard.press('Shift+ArrowRight'); await page.keyboard.press('Shift+ArrowRight')
      assert.equal(await page.evaluate(() => window.getSelection()?.toString()), '😀B')
    }
    await page.locator('[data-tab-id="home"]').click()
    await select()
    await page.locator('[data-action="highlight-palette"]').click()
    await page.locator('[data-action="highlight-cyan"]').click()
    await page.locator('[data-action="superscript"]').click()
    await page.keyboard.press('Control+z')
    await page.keyboard.press('Control+y')
    await page.reload(); await page.locator('.docx-source-home').waitFor()
    const revision2 = await save(2)
    assert.deepEqual(revision2.runs[0], [['A', true, false], ['😀', true, false], ['B', false, true], ['C尾', false, true]])
    assert.deepEqual(revision2.runFormats[0], [['A', null, null], ['😀', 'cyan', 'superscript'], ['B', 'cyan', 'superscript'], ['C尾', null, null]])
    assert.deepEqual(savePayloads.get(1).operations.map(op => [op.kind, op.from, op.to]), [['formatRange', 1, 4]])
    await open(2); await select()
    await page.locator('[data-action="superscript"][aria-pressed="true"]').waitFor()
    await page.locator('[data-action="superscript"]').click()
    await page.locator('[data-action="highlight-palette"]').click()
    await page.locator('[data-action="highlight-none"]').click()
    const revision3 = await save(3)
    assert.deepEqual(revision3.runFormats[0], [['A', null, null], ['😀', 'none', 'baseline'], ['B', 'none', 'baseline'], ['C尾', null, null]])
    await open(3); await select()
    await page.locator('[data-action="subscript"]').click()
    const revision4 = await save(4)
    assert.deepEqual(revision4.runFormats[0], [['A', null, null], ['😀', 'none', 'subscript'], ['B', 'none', 'subscript'], ['C尾', null, null]])
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), runFormats: revision4.runFormats[0], pageErrors, temporary }))
  } else if (smokeCase === 'format') {
    // 开始▸加粗作用于选中文字：选中“一段”（第 2-3 字）加粗，“第三段”整段（光标折叠）倾斜。
    await page.locator('[data-tab-id="home"]').click()
    await editor.locator('p').filter({ hasText: '第一段正文' }).click()
    await page.keyboard.press('Home'); await page.keyboard.press('ArrowRight')
    await page.keyboard.press('Shift+ArrowRight'); await page.keyboard.press('Shift+ArrowRight')
    await page.locator('[data-action="bold"]').click()
    await editor.locator('p').filter({ hasText: '第三段' }).click()
    await page.locator('[data-action="italic"]').click()
    const revision2 = await save(2)
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), ops: savePayloads.get(1).operations.map(op => [op.kind, op.from, op.to, op.style]), runs: revision2.runs, pageErrors }))
    assert.deepEqual(savePayloads.get(1).operations.map(op => op.kind), ['formatRange', 'formatParagraph'])
    assert.deepEqual(revision2.runs[0], [['第', false, false], ['一段', true, false], ['正文', false, false]])
    assert.deepEqual(revision2.runs[2], [['第三段', false, true]])
    assert.deepEqual(pageErrors, [])
  } else if (['sections', 'paper', 'margins-wide'].includes(smokeCase)) {
    // 修订 1：在“第二段”后插入连续分节符（一节拆为两节）。
    await editor.locator('p').filter({ hasText: '第二段' }).click()
    await page.locator('[data-tab-id="layout"]').click()
    await page.locator('[data-source-action="layout-section-break-continuous"]').click()
    const revision2 = await save(2)
    // 修订 2：第一节窄边距，第二节（尾节）横向；节标签随光标切换。
    await open(2)
    await page.locator('[data-tab-id="layout"]').click()
    await editor.locator('p').filter({ hasText: '第一段正文' }).click()
    await page.waitForFunction(() => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === '第 1 节，共 2 节', null, { timeout: 10000 })
    await page.locator('[data-source-action="layout-margins"]').selectOption(smokeCase === 'margins-wide' ? 'wide' : '720')
    if (smokeCase === 'paper') await page.locator('[data-source-action="layout-paper-size"]').selectOption('a5')
    await editor.locator('p').filter({ hasText: '第三段' }).click()
    // ProseMirror 异步读取 DOM 选区；等待节标签随光标切换。
    await page.waitForFunction(() => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === '第 2 节，共 2 节', null, { timeout: 10000 })
    assert.equal(await page.locator('[data-source-action="layout-margin-left"]').inputValue(), String(revision2.sections[1].left))
    await page.locator('[data-source-action="layout-orientation"]').selectOption('landscape')
    if (smokeCase === 'paper') {
      await page.locator('[data-source-action="layout-paper-size"]').selectOption('a3')
      // 页面设置草稿恢复后仍按光标所在节回显，不能泄漏相邻节纸型。
      await page.reload(); await page.locator('.docx-source-home').waitFor()
      await page.locator('[data-tab-id="layout"]').click()
      await editor.locator('p').filter({ hasText: '第三段' }).click()
      await page.waitForFunction(() => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === '第 2 节，共 2 节')
      assert.equal(await page.locator('[data-source-action="layout-paper-size"]').inputValue(), 'a3')
    }
    const revision3 = await save(3)
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), rev2Ops: savePayloads.get(1).operations, rev3Ops: savePayloads.get(2).operations.map(op => [op.kind, op.values]), rev2Sections: revision2.sections, rev3Sections: revision3.sections, pageErrors }))
    assert.deepEqual(savePayloads.get(1).operations.map(op => [op.kind, op.type]), [['insertSectionBreak', 'continuous']])
    assert.equal(revision2.sections.length, 2)
    assert.equal(revision2.sections[1].start, 'CONTINUOUS (0)')
    assert.deepEqual(revision3.sections.map(sec => [sec.left, sec.orientation]), [[smokeCase === 'margins-wide' ? 2880 : 720, 'PORTRAIT (0)'], [revision2.sections[1].left, 'LANDSCAPE (1)']])
    assert.equal(revision3.sections[1].start, 'CONTINUOUS (0)')
    assert.deepEqual(revision3.body.filter(item => item[1]).map(item => item[1]), ['第一段正文', '第二段前半第二段后半', '第三段'])
    if (smokeCase === 'paper') {
      assert.deepEqual(revision3.sections.map(sec => [sec.width, sec.height]), [[8391, 11906], [23811, 16838]])
      await open(3); await page.locator('[data-tab-id="layout"]').click()
      for (const [text, label, paper] of [['第一段正文', '第 1 节，共 2 节', 'a5'], ['第三段', '第 2 节，共 2 节', 'a3']]) {
        await editor.locator('p').filter({ hasText: text }).click()
        await page.waitForFunction(expected => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === expected, label)
        assert.equal(await page.locator('[data-source-action="layout-paper-size"]').inputValue(), paper)
      }
    }
    if (smokeCase === 'margins-wide') {
      assert.deepEqual(revision3.sections.map(sec => [sec.top, sec.right, sec.bottom, sec.left]), [
        [1440, 2880, 1440, 2880],
        [revision2.sections[1].top, revision2.sections[1].right, revision2.sections[1].bottom, revision2.sections[1].left],
      ])
      await open(3); await page.locator('[data-tab-id="layout"]').click()
      await editor.locator('p').filter({ hasText: '第一段正文' }).click()
      await page.waitForFunction(() => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === '第 1 节，共 2 节')
      assert.equal(await page.locator('[data-source-action="layout-margins"]').inputValue(), 'wide')
      await editor.locator('p').filter({ hasText: '第三段' }).click()
      await page.waitForFunction(() => document.querySelector('[data-source-action="layout-section-label"]')?.textContent === '第 2 节，共 2 节')
      assert.notEqual(await page.locator('[data-source-action="layout-margins"]').inputValue(), 'wide')
    }
    assert.deepEqual(pageErrors, [])
  } else if (smokeCase === 'followup') {
    // 修订 1：经典封面 → 替换为色带封面 → 改标题占位；第三段末尾插入 1×2 表格。
    await editor.locator('p').filter({ hasText: '第一段正文' }).click()
    await insert('insert-cover-page'); await page.locator('[data-cover-preset="classic"]').click()
    await insert('insert-cover-page'); await page.locator('[data-cover-preset="banded"]').click()
    await editor.locator('p').filter({ hasText: '文档标题' }).click(); await page.keyboard.press('End'); await page.keyboard.press('Shift+Home')
    await page.keyboard.type('年度经营报告')
    await editor.locator('p').filter({ hasText: '第三段' }).click(); await page.keyboard.press('End')
    await insert('insert-table'); await page.locator('[data-table-size="1x2"]').click()
    const revision2 = await save(2)
    // 修订 2：重开后编辑已保存表格首格；删除封面。
    await open(2)
    await page.locator('[data-tab-id="insert"]').click()
    await editor.locator('td p, th p').first().click(); await page.keyboard.type('后填')
    await delay(500)
    await insert('insert-cover-page'); await page.locator('[data-action="remove-cover-page"]').click()
    const revision3 = await save(3)
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), rev2Ops: savePayloads.get(1).operations.map(op => op.kind), rev3Ops: savePayloads.get(2).operations.map(op => op.kind), rev2: revision2.body, rev2Bookmarks: revision2.bookmarks, rev3: revision3.body, rev3Bookmarks: revision3.bookmarks, pageErrors }))
    const rev2Cover = revision2.body.slice(0, revision2.body.findIndex(item => item[1] === '第一段正文'))
    assert.ok(rev2Cover.some(item => item[1] === '年度经营报告'), '修订 2 封面标题为编辑后的文字')
    assert.ok(!rev2Cover.some(item => item[1] === '文档标题'), '替换后不残留旧封面')
    assert.equal(revision2.bookmarks.filter(name => name === '_GenOfficeCoverPage').length, 1, '只有一个封面')
    assert.deepEqual(revision2.body.slice(-2), [['tbl', 1, 2, ['', '']], ['p', '', false]])
    assert.deepEqual(revision3.body, [['p', '第一段正文', false], ['p', '第二段前半第二段后半', false], ['p', '第三段', false], ['tbl', 1, 2, ['后填', '']], ['p', '', false]])
    assert.ok(!revision3.bookmarks.includes('_GenOfficeCoverPage'))
    assert.deepEqual(pageErrors, [])
    process.exitCode = 0
  } else {

  // 1. 封面（经典）。
  await editor.locator('p').filter({ hasText: '第一段正文' }).click()
  await insert('insert-cover-page'); await page.locator('[data-cover-preset="classic"]').click()
  // 2. 分页符：第二段"第二段前半|第二段后半"。
  await editor.locator('p').filter({ hasText: '第二段前半' }).click(); await page.keyboard.press('Home')
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight')
  await insert('insert-page-break')
  // 3. 空白页：第三段末尾（文档末尾，不加尾随分页）。
  await editor.locator('p').filter({ hasText: '第三段' }).click(); await page.keyboard.press('End')
  await insert('insert-blank-page')
  // 4. 插入表格：光标在空白页空段 → 表格插在其上；首格输入文字。
  await insert('insert-table'); await page.locator('[data-table-size="2x3"]').click()
  await page.keyboard.type('单元格甲')
  await delay(500)

  const reopened = await save(2)
  console.log(JSON.stringify({ ok: true, browserVersion: browser.version(), operationKinds: savePayload.operations.map(op => op.kind), body: reopened.body, bookmarks: reopened.bookmarks, pageErrors }))
  const body = reopened.body
  const firstBody = body.findIndex(item => item[0] === 'p' && item[1] === '第一段正文')
  assert.ok(firstBody > 0, '封面位于正文之前')
  assert.equal(body[firstBody - 1][2], true, '封面以分页段结束')
  assert.deepEqual(reopened.bookmarks.slice(0, 2), ['_GenOfficeCoverPage', '_GenOfficeCoverPageEnd'])
  assert.deepEqual(body.slice(firstBody), [
    ['p', '第一段正文', false], ['p', '第二段前半', false], ['p', '第二段后半', true], ['p', '第三段', false],
    ['tbl', 2, 3, ['单元格甲', '', '']], ['p', '', true],
  ])
  assert.deepEqual(pageErrors, [])
  }
  if (builtPreview) {
    await Promise.all(chunkChecks)
    assert.ok([...loadedChunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
    assert.equal(sha256(await readFile(manifestPath)), manifestSha256, '验收期间构建身份不得变化')
    console.log(JSON.stringify({ builtChunkIdentityVerified: true, manifestSha256, loadedChunks: Object.fromEntries(loadedChunks), chunkCount: loadedChunks.size }))
  }
  if (process.env.DOCX_INSERT_EVIDENCE_OUTPUT) await writeFile(process.env.DOCX_INSERT_EVIDENCE_OUTPUT, JSON.stringify({ ok:true, case:smokeCase, builtPreview, manifestSha256, sourcePath,
    revisions:[...revisions].map(([revision,bytes]) => ({ revision,sha256:sha256(bytes),size:bytes.length,path:join(temporary,`revision-${revision}.docx`) })),
    operations:[...savePayloads].map(([revision,payload]) => ({revision,operations:payload.operations})),
    sections:[...inspections].map(([revision,inspection]) => ({revision,sections:inspection.sections,hfParts:inspection.hfParts})), pageErrors,loadedChunks:Object.fromEntries(loadedChunks) },null,2))
} finally {
  await browser?.close()
  server?.kill()
}
