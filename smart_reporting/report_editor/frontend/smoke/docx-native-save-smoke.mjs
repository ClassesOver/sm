import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

// 原生 API 仅模拟授权和修订登记；预览、保存和独立回读均处理真实 DOCX。
const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_SMOKE_PORT ?? 4192)
const sectionLayout = process.env.DOCX_SMOKE_MODE === 'section-layout'
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-ribbon-smoke-'))
const sourcePath = join(temporary, 'revision-1.docx')
const savedPath = join(temporary, 'revision-2.docx')
const runPython = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64, json, sys
from io import BytesIO
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
payload = json.load(sys.stdin)
if payload['mode'] == 'create':
    document = Document()
    for text in ['经营收入100万元', '删除此段落', '保留此段落', '缩进段落']:
        document.add_paragraph(text)
    document.save(payload['path'])
    print(base64.b64encode(Path(payload['path']).read_bytes()).decode())
elif payload['mode'] == 'patch':
    content = Path(payload['sourcePath']).read_bytes()
    result = patch_docx(content, payload['operations'])
    Path(payload['outputPath']).write_bytes(result)
    print(base64.b64encode(result).decode())
elif payload['mode'] == 'inspect':
    content = base64.b64decode(payload['bytes'])
    document = Document(BytesIO(content))
    paragraph = document.paragraphs[0]
    section = document.sections[-1]
    indent_paragraph = next(p for p in document.paragraphs if p.text == '缩进段落')
    print(json.dumps({'model': inspect_docx(content), 'paragraphs': [p.text for p in document.paragraphs],
        'alignment': str(paragraph.alignment),
        'section': {
            'orientation': str(section.orientation),
            'pageWidth': section.page_width.twips, 'pageHeight': section.page_height.twips,
            'marginTop': section.top_margin.twips, 'marginRight': section.right_margin.twips,
            'marginBottom': section.bottom_margin.twips, 'marginLeft': section.left_margin.twips,
            'columns': int(section._sectPr.find(qn('w:cols')).get(qn('w:num'), '1')),
            'headerDist': section.header_distance.twips, 'footerDist': section.footer_distance.twips,
        },
        'spacing': {
            'beforeTwips': paragraph.paragraph_format.space_before.twips if paragraph.paragraph_format.space_before else 0,
            'afterTwips': paragraph.paragraph_format.space_after.twips if paragraph.paragraph_format.space_after else 0,
            'lineSpacing': paragraph.paragraph_format.line_spacing,
        },
        'leftIndentTwips': indent_paragraph.paragraph_format.left_indent.twips if indent_paragraph.paragraph_format.left_indent else 0,
        'rightIndentTwips': indent_paragraph.paragraph_format.right_indent.twips if indent_paragraph.paragraph_format.right_indent else 0,
        'runs': [{'text': r.text, 'bold': r.bold, 'italic': r.italic, 'underline': r.underline,
            'fontFamily': r.font.name, 'fontSize': r.font.size.pt if r.font.size else None,
            'color': str(r.font.color.rgb) if r.font.color.rgb else None} for r in paragraph.runs]}, ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server
let browser
try {
  const sourceBytes = Buffer.from(runPython({ mode: 'create', path: sourcePath }), 'base64')
  const sourceSha = sha256(sourceBytes)
  const sourceInspection = JSON.parse(runPython({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
  let savedBytes, savedInspection, savePayload
  server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  let ready = false
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) { ready = true; break } } catch {}
    await delay(250)
  }
  assert.ok(ready, 'Vite did not become ready')
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true })
  const pageErrors = [], failedResponses = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()) })
  page.on('response', response => { if (response.status() >= 400) failedResponses.push({ status: response.status(), url: response.url() }) })
  await page.route('**/reports/v1/native/fixture-docx/*/api/context', route => {
    const revision = Number(new URL(route.request().url()).pathname.split('/')[5])
    const bytes = revision === 1 ? sourceBytes : savedBytes
    return route.fulfill({ json: {
      context: { documentId: 'fixture-docx', format: 'docx', revision, parentRevision: revision === 1 ? null : 1,
        scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
        sourceFile: { path: `revision-${revision}.docx`, size: bytes.length, sha256: sha256(bytes), mediaType }, origin: 'report' },
      csrfToken: 'fixture-csrf', capabilities: { docx_editor: true }, editingEnabled: true,
    } })
  })
  await page.route('**/reports/v1/native/fixture-docx/*/api/file', route => route.fulfill({
    body: route.request().url().includes('/1/api/') ? sourceBytes : savedBytes, contentType: mediaType,
  }))
  await page.route('**/reports/v1/native/fixture-docx/*/api/preview', route => {
    const payload = route.request().postDataJSON()
    const inspection = route.request().url().includes('/1/api/') ? sourceInspection : savedInspection
    assert.equal(payload.expectedSha256, inspection.model.sourceSha256)
    assert.deepEqual(payload.operations, [])
    return route.fulfill({ json: { sourceSha256: inspection.model.sourceSha256, draftSha256: inspection.model.sourceSha256, model: inspection.model } })
  })
  await page.route('**/reports/v1/native/fixture-docx/1/api/save', async route => {
    assert.equal(route.request().headers()['x-csrf-token'], 'fixture-csrf')
    savePayload = route.request().postDataJSON()
    assert.equal(savePayload.expectedSha256, sourceSha)
    savedBytes = Buffer.from(runPython({ mode: 'patch', sourcePath, outputPath: savedPath, operations: savePayload.operations }), 'base64')
    savedInspection = JSON.parse(runPython({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    await route.fulfill({ json: { documentId: 'fixture-docx', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { word: { downloadUrl: '/fixture-download-revision-2.docx', size: savedBytes.length, sha256: sha256(savedBytes) } },
      editor: { openUrl: '/reports/v1/native/fixture-docx/2' }, validation: { ok: false, issues: [{ code: 'fixture_review', message: '验收待复核，保留 Word 下载' }] } } })
  })
  await page.route('**/fixture-download-revision-2.docx', route => route.fulfill({ body: savedBytes,
    contentType: mediaType, headers: { 'Content-Disposition': 'attachment; filename="revision-2.docx"' } }))
  await page.route(/\/reports\/v1\/native\/fixture-docx\/[12]$/, async route => {
    const html = await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` })
    await route.fulfill({ response: html })
  })
  const openRevision = async revision => {
    await page.goto(`${baseUrl}/reports/v1/native/fixture-docx/${revision}`)
    try { await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) }
    catch { throw new Error(JSON.stringify({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1500), pageErrors, failedResponses })) }
  }
  await openRevision(1)
  const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' })
  await editor.locator('p').filter({ hasText: '经营收入100万元' }).click()
  const home = page.locator('.docx-source-home')
  await home.locator('[data-action="bold"]').click()
  await home.locator('[data-action="italic"]').click()
  await home.locator('[data-action="underline"]').click()
  const family = home.locator('[data-action="font-family"]')
  await family.fill('Microsoft YaHei')
  await family.press('Enter')
  await home.locator('[data-action="font-size"]').fill('16')
  await home.locator('[data-action="grow-font"]').click()
  await home.locator('[data-action="font-color"]').fill('#aabbcc')
  await home.locator('[data-action="align-center"]').click()
  await home.locator('[data-action="line-spacing"]').click()
  await home.locator('[data-source-action="line-spacing-2"]').click()
  await home.locator('[data-action="line-spacing"]').click()
  await home.locator('[data-source-action="toggle-space-before"]').click()
  await home.locator('[data-source-action="toggle-space-after"]').click()
  await home.locator('[data-action="bullets"]').click()
  await home.locator('[data-action="add-paragraph"]').click()
  await editor.locator('p').filter({ hasText: '删除此段落' }).click()
  await home.locator('[data-action="delete-paragraph"]').click()
  await editor.locator('p').filter({ hasText: '保留此段落' }).click()
  await page.keyboard.press('End')
  await page.locator('[data-tab-id="insert"]').click()
  await page.locator('.docx-source-insert [data-action="insert-symbol"]').click()
  await page.locator('.symbol-cell').getByText('¥', { exact: true }).click()
  await page.locator('[data-tab-id="home"]').click()
  await home.locator('[data-action="numbering"]').click()
  await editor.locator('p').filter({ hasText: '缩进段落' }).click()
  await home.locator('[data-action="indent-increase"]').click()
  await page.locator('[data-tab-id="layout"]').click()
  const rightIndent = page.locator('[data-action="indent-right"]')
  await rightIndent.fill('18')
  await rightIndent.press('Enter')
  if (sectionLayout) {
    const layout = page.locator('.docx-source-layout')
    await layout.locator('[data-source-action="layout-orientation"]').selectOption('landscape')
    await layout.locator('[data-source-action="layout-paper-size"]').selectOption('a4')
    await layout.locator('[data-source-action="layout-margins"]').selectOption('720')
    await layout.locator('[data-source-action="layout-margin-left"]').fill('1200')
    await layout.locator('[data-source-action="layout-columns"]').selectOption('2')
    await layout.locator('[data-source-action="layout-header-distance"]').fill('800')
    await layout.locator('[data-source-action="layout-footer-distance"]').fill('900')
    // 改变选区并切换标签，确认设置没有被旧 section 数据覆盖。
    await editor.locator('p').filter({ hasText: '缩进段落' }).click()
    await page.locator('[data-tab-id="home"]').click()
    await page.locator('[data-tab-id="layout"]').click()
    assert.equal(await layout.locator('[data-source-action="layout-orientation"]').inputValue(), 'landscape')
    assert.equal(await layout.locator('[data-source-action="layout-columns"]').inputValue(), '2')
  }
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  const target = sourceInspection.model.blocks.find(block => block.text === '经营收入100万元')
  const removed = sourceInspection.model.blocks.find(block => block.text === '删除此段落')
  const indented = sourceInspection.model.blocks.find(block => block.text === '缩进段落')
  assert.deepEqual(savePayload.operations.find(operation => operation.kind === 'formatParagraph'), {
    kind: 'formatParagraph', blockId: target.blockId, expectedObjectSha256: target.expectedObjectSha256,
    style: { bold: true, italic: true, underline: true, color: 'AABBCC', fontSize: 17, fontFamily: 'Microsoft YaHei' },
  })
  assert.ok(savePayload.operations.some(operation => operation.kind === 'insertParagraph' && operation.text === '新段落'))
  assert.ok(savePayload.operations.some(operation => operation.kind === 'deleteParagraph' && operation.blockId === removed.blockId))
  assert.ok(savePayload.operations.some(operation => operation.kind === 'replaceParagraph' && operation.text === '保留此段落¥'))
  assert.deepEqual(savePayload.operations.find(operation => operation.kind === 'setParagraphAlignment'), {
    kind: 'setParagraphAlignment', blockId: target.blockId, expectedObjectSha256: target.expectedObjectSha256, alignment: 'center',
  })
  assert.deepEqual(savePayload.operations.find(operation => operation.kind === 'setParagraphSpacing'), {
    kind: 'setParagraphSpacing', blockId: target.blockId, expectedObjectSha256: target.expectedObjectSha256,
    spaceBefore: 240, spaceAfter: 240, lineSpacing: 2,
  })
  assert.deepEqual(savePayload.operations.filter(operation => operation.kind === 'setParagraphList').map(operation => operation.list), ['bullet', 'ordered'])
  assert.deepEqual(savePayload.operations.find(operation => operation.kind === 'setParagraphIndent'), {
    kind: 'setParagraphIndent', blockId: indented.blockId, expectedObjectSha256: indented.expectedObjectSha256, twips: 720,
  })
  assert.deepEqual(savePayload.operations.find(operation => operation.kind === 'setParagraphRightIndent'), {
    kind: 'setParagraphRightIndent', blockId: indented.blockId, expectedObjectSha256: indented.expectedObjectSha256, twips: 360,
  })
  if (sectionLayout) {
    const section = sourceInspection.model.sections.at(-1)
    assert.deepEqual(savePayload.operations.find(operation => operation.kind === 'setSectionLayout'), {
      kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256,
      values: { orientation: 'landscape', pageWidth: 16838, pageHeight: 11906,
        marginTop: 720, marginRight: 720, marginBottom: 720, marginLeft: 1200,
        columns: 2, headerDist: 800, footerDist: 900 },
    })
  }
  assert.equal(savePayload.operations.length, sectionLayout ? 11 : 10)
  await page.getByText('验收待复核，保留 Word 下载', { exact: true }).waitFor()
  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('link', { name: '下载 Word', exact: true }).click()
  const download = await downloadEvent
  assert.equal(download.suggestedFilename(), 'revision-2.docx')
  const downloadPath = join(temporary, 'downloaded-revision-2.docx')
  await download.saveAs(downloadPath)
  const downloaded = await readFile(downloadPath)
  assert.equal(sha256(downloaded), sha256(savedBytes))
  assert.notEqual(sha256(downloaded), sourceSha)
  const reopened = JSON.parse(runPython({ mode: 'inspect', bytes: downloaded.toString('base64') }))
  assert.deepEqual(reopened.paragraphs, ['经营收入100万元', '新段落', '保留此段落¥', '缩进段落'])
  assert.deepEqual(reopened.runs, [{ text: '经营收入100万元', bold: true, italic: true, underline: true,
    fontFamily: 'Microsoft YaHei', fontSize: 17, color: 'AABBCC' }])
  assert.equal(reopened.model.sourceSha256, sha256(downloaded))
  assert.equal(reopened.alignment, 'CENTER (1)')
  assert.deepEqual(reopened.spacing, { beforeTwips: 240, afterTwips: 240, lineSpacing: 2 })
  assert.equal(reopened.leftIndentTwips, 720)
  assert.equal(reopened.rightIndentTwips, 360)
  if (sectionLayout) assert.deepEqual(reopened.section, {
    orientation: 'LANDSCAPE (1)', pageWidth: 16838, pageHeight: 11906,
    marginTop: 720, marginRight: 720, marginBottom: 720, marginLeft: 1200,
    columns: 2, headerDist: 800, footerDist: 900,
  })
  assert.equal(reopened.model.blocks.find(block => block.text === '经营收入100万元').list.kind, 'bullet')
  assert.equal(reopened.model.blocks.find(block => block.text === '保留此段落¥').list.kind, 'ordered')
  assert.deepEqual(await readFile(sourcePath), sourceBytes)
  await page.locator('.native-next-revision').evaluate(link => {
    if (!link.href.endsWith('/fixture-docx/2')) throw new Error('next revision identity is missing')
  })
  await openRevision(2)
  assert.equal(await editor.innerText(), '经营收入100万元\n\n新段落\n\n保留此段落¥\n\n缩进段落')
  assert.equal(await editor.locator('.doc-li-bullet').filter({ hasText: '经营收入100万元' }).evaluate(paragraph => getComputedStyle(paragraph).textAlign), 'center')
  assert.equal(await editor.locator('.doc-li-ordered').filter({ hasText: '保留此段落¥' }).count(), 1)
  assert.equal(await editor.locator('p').filter({ hasText: '缩进段落' }).evaluate(paragraph => getComputedStyle(paragraph).marginInlineStart), '48px')
  assert.equal(await editor.locator('p').filter({ hasText: '缩进段落' }).evaluate(paragraph => getComputedStyle(paragraph).marginInlineEnd), '24px')
  await page.getByText('DOCX · 修订 2', { exact: true }).waitFor()
  if (sectionLayout) {
    await page.locator('[data-tab-id="layout"]').click()
    const layout = page.locator('.docx-source-layout')
    for (const [action, value] of Object.entries({ 'layout-orientation': 'landscape', 'layout-paper-size': 'a4',
      'layout-columns': '2', 'layout-margin-left': '1200', 'layout-margin-top': '720',
      'layout-header-distance': '800', 'layout-footer-distance': '900' })) {
      assert.equal(await layout.locator(`[data-source-action="${action}"]`).inputValue(), value)
    }
  }
  assert.deepEqual(pageErrors, [])
  assert.deepEqual(failedResponses, [])
  console.log(JSON.stringify({ ok: true, operationKinds: savePayload.operations.map(operation => operation.kind),
    sourceSha256: sourceSha, downloadedSha256: sha256(downloaded), downloadedBytes: downloaded.length,
    sourceUnchanged: true, reopenedRevision: 2, validationFailureRetainsDownload: true, alignment: reopened.alignment,
    section: sectionLayout ? reopened.section : undefined,
    leftIndentTwips: reopened.leftIndentTwips, rightIndentTwips: reopened.rightIndentTwips, paragraphs: reopened.paragraphs, runs: reopened.runs }))
} finally {
  await browser?.close()
  if (server && server.exitCode === null) {
    const exited = new Promise(resolve => server.once('exit', resolve))
    server.kill('SIGTERM')
    await exited
  }
  await rm(temporary, { recursive: true, force: true })
}
