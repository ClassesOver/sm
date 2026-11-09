import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { verifyBrowserTextInput } from './browser-input-preflight.mjs'

const frontend = process.cwd()
const repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.PPTX_SMOKE_PORT ?? 4191)
const baseUrl = `http://127.0.0.1:${port}`
const smokeMode = process.env.PPTX_SMOKE_MODE ?? 'textbox'
const listVariant = process.env.PPTX_LIST_VARIANT ?? 'number'
if (!['number', 'glyph', 'none'].includes(listVariant)) throw new Error('Unknown list variant')
const paperPreset = process.env.PPTX_SMOKE_PRESET ?? 'A4'
const paperSizes = { A4: { cx: 7560000, cy: 10692000 }, A3: { cx: 10692000, cy: 15120000 } }
if (smokeMode === 'slide-size-presets' && !paperSizes[paperPreset]) throw new Error(`Unknown paper preset: ${paperPreset}`)
const targetSize = smokeMode === 'slide-size-custom' ? { cx: 9000000, cy: 7200000 } : smokeMode === 'slide-size-presets' ? paperSizes[paperPreset] : { cx: 12192000, cy: 6858000 }
const runPython = input => {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64, json, sys
from io import BytesIO
from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
from smart_reporting.report_editor.native_office import inspect_office, patch_office
payload = json.load(sys.stdin)
if payload['mode'] == 'create':
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    shape = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    shape.text = 'Native browser formatting fixture'
    if payload.get('spacingSample'):
        p = shape.text_frame.paragraphs[0]; p.line_spacing = 1.0; p.space_before = Pt(0); p.space_after = Pt(6); p.alignment = PP_ALIGN.LEFT
        p._p.get_or_add_pPr().set('rtl', '1')
        bullet = OxmlElement('a:buChar'); bullet.set('char', '•'); p._p.get_or_add_pPr().append(bullet)
        p = shape.text_frame.add_paragraph(); p.text = 'Second paragraph'; p.line_spacing = 1.5; p.space_before = Pt(12); p.space_after = Pt(0); p.alignment = PP_ALIGN.CENTER
        other = slide.shapes.add_textbox(Inches(1), Inches(4), Inches(4), Inches(1)); other.text = 'Untouched object'
        p = other.text_frame.paragraphs[0]; p.line_spacing = 1.37; p.space_before = Pt(8.25); p.space_after = Pt(9.75)
        p.runs[0].font.bold = True
    if payload.get('extraSlide'):
        extra = presentation.slides.add_slide(presentation.slide_layouts[6])
        extra.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = 'Second source slide'
    if payload.get('listsSample'):
        for index, paragraph in enumerate(shape.text_frame.paragraphs):
            paragraph._p.get_or_add_pPr().set('lvl', '0' if index == 0 else '8')
        props = shape.text_frame.paragraphs[0]._p.get_or_add_pPr()
        props.set('marL', '285750'); props.set('indent', '-285750')
    stream = BytesIO(); presentation.save(stream)
    print(base64.b64encode(stream.getvalue()).decode())
elif payload['mode'] == 'inspect':
    content = base64.b64decode(payload['bytes'])
    model = inspect_office('pptx', content)
    targets = [item for item in model['slides'][0]['elements'] if item['text'].strip()]
    presentation = Presentation(BytesIO(content))
    python_pptx_texts = [shape.text for shape in presentation.slides[0].shapes if shape.has_text_frame and shape.text.strip()]
    python_pptx_geometry = [{'x': shape.left, 'y': shape.top, 'width': shape.width, 'height': shape.height} for shape in presentation.slides[0].shapes if shape.has_text_frame and shape.text.strip()]
    python_pptx_paragraphs = []
    for shape in presentation.slides[0].shapes:
        if not shape.has_text_frame or not shape.text.strip(): continue
        paragraphs = []
        for p in shape.text_frame.paragraphs:
            props = p._p.find(qn('a:pPr')); bullet = props.find(qn('a:buChar')) if props is not None else None
            spacing = p.line_spacing
            paragraphs.append({'text': p.text, 'align': int(p.alignment) if p.alignment is not None else None,
                'lineSpacingPct': spacing * 100 if isinstance(spacing, float) else None,
                'lineSpacingPt': spacing.pt if spacing is not None and not isinstance(spacing, float) else None,
                'spaceBeforePt': p.space_before.pt if p.space_before is not None else None,
                'spaceAfterPt': p.space_after.pt if p.space_after is not None else None,
                'bullet': bullet.get('char') if bullet is not None else None,
                'rtl': props.get('rtl') if props is not None else None,
                'level': int(props.get('lvl', '0')) if props is not None else 0,
                'margin': int(props.get('marL')) if props is not None and props.get('marL') is not None else None,
                'indent': int(props.get('indent')) if props is not None and props.get('indent') is not None else None,
                'bulletFont': props.find(qn('a:buFont')).get('typeface') if props is not None and props.find(qn('a:buFont')) is not None else None,
                'numberType': props.find(qn('a:buAutoNum')).get('type') if props is not None and props.find(qn('a:buAutoNum')) is not None else None,
                'startAt': int(props.find(qn('a:buAutoNum')).get('startAt')) if props is not None and props.find(qn('a:buAutoNum')) is not None and props.find(qn('a:buAutoNum')).get('startAt') is not None else None,
                'bulletSize': int(props.find(qn('a:buSzPct')).get('val')) / 1000 if props is not None and props.find(qn('a:buSzPct')) is not None else None,
                'bulletColor': props.find(qn('a:buClr')).find(qn('a:srgbClr')).get('val') if props is not None and props.find(qn('a:buClr')) is not None and props.find(qn('a:buClr')).find(qn('a:srgbClr')) is not None else None})
        python_pptx_paragraphs.append({'paragraphs': paragraphs, 'xml': shape._element.xml})
    slides = [{'transition': slide.get('transition'), 'animations': slide.get('animations', [])} for slide in model['slides']]
    print(json.dumps({'revision': payload.get('revision'), 'sha256': __import__('hashlib').sha256(content).hexdigest(), 'size': model['size'], 'pythonPptxSize': [presentation.slide_width, presentation.slide_height], 'pythonPptxParagraphs': python_pptx_paragraphs, 'pythonPptxGeometry': python_pptx_geometry, 'texts': [item['text'] for item in targets], 'elements': targets, 'pythonPptxTexts': python_pptx_texts, 'slides': slides, 'slideCount': len(model['slides'])}))
elif payload['mode'] == 'patch':
    content = base64.b64decode(payload['bytes'])
    edited = patch_office('pptx', content, payload['operations'])
    print(base64.b64encode(edited).decode())
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}

const sourceBytes = Buffer.from(runPython({ mode: 'create', spacingSample: ['paragraph-spacing', 'paragraph-lists'].includes(smokeMode), listsSample: smokeMode === 'paragraph-lists', extraSlide: smokeMode === 'new-slide' }), 'base64')
const sourceIdentity = createHash('sha256').update(sourceBytes).digest('hex')
const sourceSha = sourceIdentity
let activeBytes = sourceBytes
let activeSha = sourceSha
let activeRevision = 1
const inspected = (() => {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from smart_reporting.report_editor.native_office import inspect_office
model=inspect_office('pptx',base64.b64decode(json.load(sys.stdin)['bytes']))
print(json.dumps(model))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ bytes: sourceBytes.toString('base64') }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr)
  return JSON.parse(result.stdout)
})()
let savedBytes
let savePayload
let saveReceipt
const saveAttempts = []
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 120; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const inputBaseline = await verifyBrowserTextInput(browser)
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
  const pageErrors = []
  const failedResponses = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('response', response => { if (response.status() >= 400) failedResponses.push({ status: response.status(), url: response.url() }) })
  await page.route('**/favicon.ico', route => route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg"/>' }))

  await page.route('**/reports/v1/native/fixture-pptx/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'fixture-pptx', format: 'pptx', revision: activeRevision, parentRevision: activeRevision === 1 ? null : 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'fixture.pptx', size: activeBytes.length, sha256: activeSha, mediaType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }, origin: 'upload' },
    csrfToken: 'fixture-csrf', capabilities: { pptx_editor: true }, editingEnabled: true,
  } }))
  await page.route('**/reports/v1/native/fixture-pptx/*/api/file', route => route.fulfill({ body: activeBytes, contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }))
  await page.route('**/reports/v1/native/fixture-pptx/*/api/preview.pdf*', route => route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' }))
  await page.route('**/reports/v1/native/fixture-pptx/*/api/preview', async route => {
    const payload = route.request().postDataJSON()
    assert.equal(payload.expectedSha256, activeSha)
    const operations = payload.operations
    const receipt = await new Promise((resolve, reject) => {
      const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `import base64,json,sys\nfrom smart_reporting.report_editor.native_office import inspect_office,patch_office\np=json.load(sys.stdin); b=base64.b64decode(p['source']); b=patch_office('pptx',b,p['operations']) if p['operations'] else b; print(json.dumps({'model':inspect_office('pptx',b),'draftSha256':__import__('hashlib').sha256(b).hexdigest()}))`], {
        cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ source: activeBytes.toString('base64'), operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024,
      })
      result.status === 0 ? resolve(JSON.parse(result.stdout)) : reject(new Error(result.stderr))
    })
    await route.fulfill({ json: { sourceSha256: activeSha, draftSha256: receipt.draftSha256, model: receipt.model } })
  })
  await page.route('**/reports/v1/native/fixture-pptx/*/api/render-tree', async route => {
    const payload = route.request().postDataJSON()
    assert.equal(payload.expectedSha256, activeSha)
    const operations = payload.operations
    const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `import base64,json,sys\nfrom smart_reporting.report_editor.native_office import patch_office\nfrom smart_reporting.report_editor.slides_render import render_pptx_tree\np=json.load(sys.stdin); b=base64.b64decode(p['source']); b=patch_office('pptx',b,p['operations']) if p['operations'] else b; print(json.dumps(render_pptx_tree(b)))`], {
      cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ source: activeBytes.toString('base64'), operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024,
    })
    if (result.status !== 0) return route.fulfill({ status: 500, body: result.stderr })
    await route.fulfill({ json: JSON.parse(result.stdout) })
  })
  await page.route('**/reports/v1/native/fixture-pptx/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    assert.equal(savePayload.expectedSha256, sourceIdentity)
    saveAttempts.push(savePayload)
    if (smokeMode === 'slide-size-recovery' && saveAttempts.length <= 2) {
      await route.fulfill({ status: 503, json: { detail: { code: 'fixture_save_unavailable', message: '故障注入：保存暂不可用' } } })
      return
    }
    savedBytes = Buffer.from(runPython({ mode: 'patch', bytes: sourceBytes.toString('base64'), operations: savePayload.operations }), 'base64')
    saveReceipt = { documentId: 'fixture-pptx', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pptx: { downloadUrl: '/fixture-download.pptx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } },
      editor: { openUrl: '/reports/v1/native/fixture-pptx/2' }, validation: { ok: true, issues: [] } }
    await route.fulfill({ json: saveReceipt })
  })
  await page.route('**/fixture-download.pptx', route => route.fulfill({ body: savedBytes, contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }))
  await page.addInitScript(() => {
    if (location.origin !== 'null') history.replaceState(null, '', `/reports/v1/native/fixture-pptx/${new URL(location.href).searchParams.get('smokeRevision') === '2' ? 2 : 1}`)
  })
  await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
  try { await page.locator('.slides-native-ribbon').waitFor({ timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1200), pageErrors, failedResponses })) }
  try { await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ phase: 'canvas', body: (await page.locator('body').innerText()).slice(-2500), pageErrors, failedResponses })) }
  await page.waitForFunction(() => document.querySelector('.canvas-status')?.textContent.includes('点击对象选择'))

  if (smokeMode === 'new-slide') {
    // 固定源 Home ▸ New Slide（onAddSlide）：在当前页后新建沿用当前页版式的空白页；保存前可移动、移除，不可编辑内容。
    await page.locator('[data-ribbon-tab="home"]').click()
    const add = page.locator('[data-command="addSlide"][data-source-action="onAddSlide"]').first()
    assert.equal(await add.isEnabled(), true)
    await add.click()
    await page.waitForFunction(() => document.querySelectorAll('.slide-row').length === 3)
    assert.equal(await page.locator('.slide-row').nth(1).locator('.slide-title').textContent(), '新建幻灯片（保存后写入）')
    assert.equal(await page.locator('.slide-row').nth(1).getAttribute('data-selected'), 'true')
    assert.equal(await page.locator('#background-color').isDisabled(), true)
    await page.locator('.slides-canvas canvas').first().waitFor()
    await add.click()
    await page.waitForFunction(() => document.querySelectorAll('.slide-row').length === 4)
    await page.locator('.slide-row').nth(2).getByRole('button', { name: '移除新建的幻灯片' }).click()
    await page.waitForFunction(() => document.querySelectorAll('.slide-row').length === 3)
    // 删除幻灯片：新页沿用其版式的来源页不可删除；另一来源页可删除，保存时由引擎按部件路径删除。
    await page.locator('.slide-row').nth(0).getByRole('button', { name: '删除幻灯片' }).click()
    await page.waitForFunction(() => document.querySelector('.slides-statusbar')?.textContent?.includes('被新建页沿用版式'))
    assert.equal(await page.locator('.slide-row').count(), 3)
    await page.locator('.slide-row').nth(2).getByRole('button', { name: '删除幻灯片' }).click()
    await page.waitForFunction(() => document.querySelectorAll('.slide-row').length === 2)
    assert.equal(await page.locator('.slide-row').filter({ hasText: 'Second source slide' }).count(), 0)
    await page.locator('.slide-row').nth(1).locator('.slide-open').click()
    await page.locator('[data-command="movePrevious"]').first().click()
    assert.equal(await page.locator('.slide-row').nth(0).locator('.slide-title').textContent(), '新建幻灯片（保存后写入）')
    // 复制幻灯片（固定源 duplicateSlide）：副本插在来源页之后，展示已保存内容，保存前只读。
    await page.locator('.slide-row').nth(1).getByRole('button', { name: '复制幻灯片' }).click()
    await page.waitForFunction(() => document.querySelectorAll('.slide-row').length === 3)
    assert.equal(await page.locator('.slide-row').nth(2).locator('.slide-title').textContent(), '副本：Native browser formatting fixture（保存后写入）')
    assert.equal(await page.locator('#object-text').isDisabled(), true)
    if (process.env.PPTX_NEW_SLIDE_SCREENSHOT) await page.screenshot({ path: process.env.PPTX_NEW_SLIDE_SCREENSHOT })
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.waitForFunction(() => document.querySelectorAll('.slide-row').length === 3)
    assert.equal(await page.locator('.slide-row').nth(0).locator('.slide-title').textContent(), '新建幻灯片（保存后写入）')
  } else if (smokeMode === 'textbox') {
    await page.locator('[data-ribbon-tab="insert"]').click()
    const textBoxCommand = page.locator('[data-command="addText"][data-source-action="onInsert"]')
    await textBoxCommand.click()
    const textBoxInput = page.locator('[aria-label="新增文本内容"]')
    await textBoxInput.fill('Ribbon inserted textbox smoke')
  } else if (smokeMode === 'transitions-animations') {
    const target = inspected.slides[0].elements.find(item => item.editable && item.text.trim())
    assert.ok(target)
    await page.locator('#object-select').selectOption(target.id)
    await page.locator('[data-ribbon-tab="transitions"]').click()
    await page.locator('[data-command="transition"][data-source-action="onTransition"]').selectOption('wipe')
    await page.locator('[data-ribbon-tab="animations"]').click()
    await page.locator('[data-command="animationEffect"][data-source-action="onApplyAnimation"]').selectOption('flyIn')
    await page.locator('[data-command="animationDirection"]').selectOption('right')
    await page.locator('[data-command="animationTrigger"][data-source-action="onAnimTiming"]').selectOption('afterPrev')
    await page.locator('[data-command="animationDuration"]').fill('1250')
    await page.locator('[data-command="animationDelay"]').fill('300')
    await page.locator('[data-command="addAnimation"][data-source-action="onAddAnimation"]').click()
  } else if (smokeMode === 'paragraph-lists') {
    const target = inspected.slides[0].elements.find(item => item.text.includes('Native browser formatting fixture'))
    await page.locator('#object-select').selectOption(target.id)
    const command = id => page.locator(`[data-command="${id}"]`)
    assert.equal(await command('pictureBullet').isDisabled(), true)
    await command('indentIncrease').click(); await command('indentDecrease').click()
    await command('bulletCustomChar').fill('😀rest'); await command('bulletCustomChar').press('Enter')
    await command('bulletCharPreset').selectOption('2')
    if (listVariant !== 'glyph') {
      await command('bulletNumber').click()
      await command('numType').selectOption('romanLcPeriod')
      await command('startAt').fill('3'); await command('startAt').press('Enter')
    }
    await command('bulletSizePct').selectOption('125')
    await command('bulletColorPreset').selectOption('#0F9ED5')
    await command('bulletColor').fill('#c43e1c')
    await command('bulletHangEmu').selectOption('171450')
    await command('directionRtl').click(); await command('directionLtr').click()
    await command('paragraphAlignRight').click()
    await command('lineSpacingPct').selectOption('200')
    await command('spaceBeforePt').fill('12,5'); await command('spaceBeforePt').press('Enter')
    await command('spaceAfterPt').fill('0'); await command('spaceAfterPt').press('Enter')
    if (listVariant === 'none') await command('bulletNone').click()
    await page.locator('[data-source-action="onUndo"]').click()
    await page.locator('[data-source-action="onRedo"]').click()
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
    try { await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 }) }
    catch { throw new Error(JSON.stringify({ phase: 'lists-refresh', listVariant, body: (await page.locator('body').innerText()).slice(-4000), pageErrors, failedResponses })) }
    await page.locator('#object-select').selectOption(target.id)
    assert.equal(await command('directionLtr').getAttribute('aria-pressed'), 'true')
    assert.equal(await command('spaceBeforePt').inputValue(), '12.5')
    if (listVariant === 'number') assert.equal(await command('numType').inputValue(), 'romanLcPeriod')
    if (listVariant === 'glyph') assert.equal(await command('bulletCharPreset').inputValue(), '2')
    if (listVariant === 'none') assert.equal(await command('bulletSizePct').isDisabled(), true)
  } else if (smokeMode === 'paragraph-spacing') {
    const target = inspected.slides[0].elements.find(item => item.editable && item.text.includes('Native browser formatting fixture'))
    const other = inspected.slides[0].elements.find(item => item.text === 'Untouched object')
    assert.ok(target && other)
    await page.locator('#object-select').selectOption(target.id)
    const line = page.locator('[data-command="lineSpacingPct"]')
    const before = page.locator('[data-command="spaceBeforePt"]')
    const after = page.locator('[data-command="spaceAfterPt"]')
    for (const control of [line, before, after]) {
      assert.equal(await control.getAttribute('data-source-action'), 'onParagraphFormat')
      assert.equal(await control.inputValue(), '', 'Mixed source spacing must not display a fabricated value')
    }
    await page.locator('[data-command="paragraphAlignRight"]').click()
    await line.selectOption('200')
    await before.fill('12,5'); await before.press('Enter')
    await after.fill('0'); await after.press('Enter')
    const draft = () => page.evaluate(() => {
      const key = Object.keys(localStorage).find(key => key.startsWith('native-editor-draft:'))
      return key ? JSON.parse(localStorage.getItem(key)).operations : []
    })
    const snapshot = await draft()
    await before.fill('-1'); await before.press('Enter')
    assert.deepEqual(await draft(), snapshot, 'Rejected numeric input must not mutate the saved draft')
    await before.fill('12.5'); await before.press('Enter')
    await page.locator('[data-source-action="onUndo"]').click()
    assert.equal(await after.inputValue(), '')
    await page.locator('[data-source-action="onRedo"]').click()
    assert.equal(await after.inputValue(), '0')
    await page.locator('#object-select').selectOption(other.id)
    assert.equal(await before.inputValue(), '8.25')
    assert.equal(await after.inputValue(), '9.75')
    await page.locator('#object-select').selectOption(target.id)
    assert.equal(await before.inputValue(), '12.5')
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.locator('#object-select').selectOption(target.id)
    assert.equal(await before.inputValue(), '12.5')
    assert.equal(await after.inputValue(), '0')
    assert.equal(await line.inputValue(), '200')
  } else {
    assert.ok(['slide-size', 'slide-size-recovery', 'slide-size-presets', 'slide-size-custom'].includes(smokeMode))
    await page.locator('[data-ribbon-tab="design"]').click()
    if (smokeMode === 'slide-size-custom') {
      await page.locator('[data-command="customSlideSize"]').click()
      await page.getByLabel('Slide Width', { exact: true }).fill('25')
      await page.getByLabel('Slide Height', { exact: true }).fill('20')
      assert.equal(await page.getByLabel('Slide Width', { exact: true }).inputValue(), '25')
      assert.equal(await page.getByLabel('Slide Height', { exact: true }).inputValue(), '20')
      await page.locator('[data-command="applyCustomSlideSize"]').click()
      await page.locator('[data-command="slideOrientation"]').selectOption('portrait')
      await page.locator('[data-command="slideOrientation"]').selectOption('landscape')
      await page.locator('[data-source-action="onUndo"]').click()
      await page.locator('[data-source-action="onRedo"]').click()
    } else {
      await page.locator('[data-command="slideSize"][data-source-action="onSlideSize"]').selectOption(smokeMode === 'slide-size-presets' ? paperPreset : '16:9')
    }
    if (smokeMode === 'slide-size-presets') {
      await page.locator('[data-command="slideOrientation"][data-source-action="onSlideSize"]').selectOption('portrait')
      for (const [name, value] of Object.entries({ x: 75, y: 80, width: 300, height: 90 })) {
        const input = page.locator(`.geometry-grid input[name="${name}"]`)
        await input.fill(String(value))
        await input.dispatchEvent('change')
      }
      await page.locator('[data-source-action="onUndo"]').click()
      await page.locator('[data-source-action="onRedo"]').click()
    }
  }
  await page.screenshot({ path: `/tmp/pptx-native-ribbon-${smokeMode}-after-edit.png`, fullPage: true })
  await page.locator('[data-action="save"]').click()
  if (smokeMode === 'slide-size-recovery') {
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '保存失败')
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.locator('[data-ribbon-tab="design"]').click()
    assert.equal(await page.locator('[data-command="slideSize"][data-source-action="onSlideSize"]').inputValue(), '16:9')
    assert.equal(await page.locator('[data-source-action="onUndo"]').isDisabled(), true, '刷新只恢复草稿内容，不虚构旧撤销历史')
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '保存失败')
    assert.deepEqual(saveAttempts[1], saveAttempts[0], '未修改恢复草稿的失败重试必须保持请求身份')
    await page.locator('#object-text').fill('PPTX recovered after failure')
    await page.locator('[data-action="save"]').click()
  }
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存', null, { timeout: 30000 })

  const operation = savePayload?.operations?.[0]
  assert.equal(operation?.kind, 'editSlides')
  if (smokeMode === 'textbox') {
    assert.deepEqual(operation.textBoxes, [{
      slideIndex: 0,
      text: 'Ribbon inserted textbox smoke',
      geometry: { x: Math.round(inspected.size.cx / 9525 * 0.1), y: Math.round(inspected.size.cy / 9525 * 0.2), width: Math.round(inspected.size.cx / 9525 * 0.6), height: 90 },
      fontSize: 28,
      fontFamily: 'Microsoft YaHei',
      color: '#1B2A41',
    }])
  } else if (smokeMode === 'transitions-animations') {
    assert.deepEqual(operation.transitions, [{ slideIndex: 0, kind: 'wipe' }])
    assert.deepEqual(operation.animations, [{
      slideIndex: 0, elementId: inspected.slides[0].elements.find(item => item.editable && item.text.trim()).id,
      effect: 'flyIn', trigger: 'afterPrev', durationMs: 1250, delayMs: 300, direction: 'right', append: true,
    }])
  } else if (smokeMode === 'paragraph-lists') {
    assert.deepEqual(operation.paragraphFormatting.filter(record => record.indentDelta != null).map(record => record.indentDelta), [1, -1])
    assert.ok(operation.paragraphFormatting.some(record => record.bulletChar === '😀'))
    assert.ok(operation.paragraphFormatting.some(record => record.rtl === false))
  } else if (smokeMode === 'paragraph-spacing') {
    const target = inspected.slides[0].elements.find(item => item.text.includes('Native browser formatting fixture'))
    assert.ok(operation.paragraphFormatting.every(record => record.slideIndex === 0 && record.elementId === target.id))
    assert.deepEqual(operation.paragraphFormatting.reduce((value, patch) => ({ ...value, ...patch }), {}), { slideIndex: 0, elementId: target.id, align: 'right', lineSpacingPct: 200, spaceBeforePt: 12.5, spaceAfterPt: 0 })
  } else if (smokeMode === 'new-slide') {
    assert.deepEqual(operation.newSlides, [{ layoutFrom: 0 }, { duplicateOf: 0 }])
    assert.deepEqual(operation.deletedSlides, [1])
    assert.deepEqual(operation.order, [2, 0, 3])
  } else {
    assert.deepEqual(operation.slideSize, targetSize)
    if (smokeMode === 'slide-size-presets') assert.deepEqual(operation.edits[0].geometry, { x: 75, y: 80, width: 300, height: 90 })
    if (smokeMode === 'slide-size-recovery') {
      assert.equal(saveAttempts.length, 3)
      assert.notEqual(saveAttempts[2].requestId, saveAttempts[0].requestId)
      assert.equal(operation.edits[0].text, 'PPTX recovered after failure')
      assert.equal(await page.evaluate(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:'))), false)
    }
  }
  assert.equal(saveReceipt.revision, 2)
  assert.equal(saveReceipt.parentRevision, 1)
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceIdentity, 'saving must not mutate the source bytes')
  const download = await page.evaluate(async () => {
    const response = await fetch('/fixture-download.pptx')
    return { status: response.status, bytes: Array.from(new Uint8Array(await response.arrayBuffer())) }
  })
  assert.equal(download.status, 200)
  const downloaded = Buffer.from(download.bytes)
  assert.equal(createHash('sha256').update(downloaded).digest('hex'), saveReceipt.artifacts.pptx.sha256)
  assert.equal(downloaded.length, saveReceipt.artifacts.pptx.size)
  const reopened = JSON.parse(runPython({ mode: 'inspect', bytes: downloaded.toString('base64'), revision: saveReceipt.revision }))
  assert.equal(reopened.revision, 2)
  assert.equal(reopened.sha256, saveReceipt.artifacts.pptx.sha256)
  if (smokeMode === 'new-slide') {
    const independent = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys\nfrom io import BytesIO\nfrom pptx import Presentation\np=Presentation(BytesIO(sys.stdin.buffer.read()))\nprint(json.dumps([[s.slide_layout.name,[sh.text for sh in s.shapes if sh.has_text_frame]] for s in p.slides]))'], { input: downloaded, encoding: 'utf8' })
    if (independent.status !== 0) throw new Error(independent.stderr)
    const slides = JSON.parse(independent.stdout)
    assert.equal(slides.length, 3)
    assert.deepEqual(slides[0][1], [])
    assert.equal(slides[0][0], slides[1][0])
    assert.deepEqual(slides[1][1], ['Native browser formatting fixture'])
    assert.deepEqual(slides[2], slides[1])
  }
  if (smokeMode === 'textbox') {
    assert.ok(reopened.texts.includes('Ribbon inserted textbox smoke'))
    assert.ok(reopened.pythonPptxTexts.includes('Ribbon inserted textbox smoke'))
    const inserted = reopened.elements.find(item => item.text === 'Ribbon inserted textbox smoke')
    assert.ok(inserted)
    assert.equal(inserted.type, 'text')
    assert.equal(inserted.geometry.x, Math.round(inspected.size.cx / 9525 * 0.1))
    assert.equal(inserted.geometry.y, Math.round(inspected.size.cy / 9525 * 0.2))
  } else if (smokeMode === 'transitions-animations') {
    const reopenedSlide = reopened.slides[0]
    assert.equal(reopenedSlide.transition, 'wipe')
    assert.deepEqual(reopenedSlide.animations.map(({ spid, ...animation }) => animation), [{
      elementId: operation.animations[0].elementId, effect: 'flyIn', trigger: 'afterPrev',
      durationMs: 1250, delayMs: 300, direction: 'right',
    }])
  } else if (smokeMode === 'paragraph-lists') {
    const original = JSON.parse(runPython({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    assert.deepEqual(reopened.pythonPptxParagraphs[1], original.pythonPptxParagraphs[1])
    const paragraphs = reopened.pythonPptxParagraphs[0].paragraphs
    assert.deepEqual(paragraphs.map(item => item.level), [0, 7], 'Relative clamp operations must remain ordered')
    for (let index = 0; index < paragraphs.length; index++) {
      const value = paragraphs[index]
      assert.equal(value.text, original.pythonPptxParagraphs[0].paragraphs[index].text)
      assert.equal(value.rtl, '0'); assert.equal(value.align, 3)
      assert.equal(value.lineSpacingPct, 200); assert.equal(value.spaceBeforePt, 12.5); assert.equal(value.spaceAfterPt, 0)
      if (listVariant === 'none') {
        assert.equal(value.bullet, null); assert.equal(value.numberType, null)
        assert.equal(value.margin, 0); assert.equal(value.indent, 0)
      } else {
        assert.equal(value.bulletSize, 125); assert.equal(value.bulletColor, 'C43E1C')
        assert.equal(value.margin, 171450 * (value.level + 1)); assert.equal(value.indent, -171450)
        if (listVariant === 'glyph') { assert.equal(value.bullet, '§'); assert.equal(value.bulletFont, 'Wingdings') }
        else { assert.equal(value.numberType, 'romanLcPeriod'); assert.equal(value.startAt, 3) }
      }
    }
    activeBytes = downloaded; activeSha = saveReceipt.artifacts.pptx.sha256; activeRevision = 2
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html?smokeRevision=2`)
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.locator('#object-select').selectOption(reopened.elements[0].id)
    assert.equal(await page.locator('[data-command="directionLtr"]').getAttribute('aria-pressed'), 'true')
    assert.equal(await page.locator('[data-command="spaceBeforePt"]').inputValue(), '12.5')
    if (listVariant === 'number') {
      assert.equal(await page.locator('[data-command="numType"]').inputValue(), 'romanLcPeriod')
      assert.equal(await page.locator('[data-command="startAt"]').inputValue(), '3')
    }
    if (listVariant === 'glyph') assert.equal(await page.locator('[data-command="bulletCharPreset"]').inputValue(), '2')
    if (listVariant === 'none') assert.equal(await page.locator('[data-command="bulletSizePct"]').isDisabled(), true)
  } else if (smokeMode === 'paragraph-spacing') {
    const original = JSON.parse(runPython({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    assert.deepEqual(reopened.size, original.size)
    const changed = reopened.pythonPptxParagraphs[0].paragraphs
    assert.equal(changed.length, 2)
    for (let index = 0; index < changed.length; index++) {
      assert.deepEqual(changed[index], { ...original.pythonPptxParagraphs[0].paragraphs[index], align: 3,
        lineSpacingPct: 200, lineSpacingPt: null, spaceBeforePt: 12.5, spaceAfterPt: 0 })
    }
    assert.deepEqual(reopened.pythonPptxParagraphs[1], original.pythonPptxParagraphs[1], 'Unselected object XML must remain unchanged')
    activeBytes = downloaded; activeSha = saveReceipt.artifacts.pptx.sha256; activeRevision = 2
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html?smokeRevision=2`)
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.locator('#object-select').selectOption(reopened.elements[0].id)
    assert.equal(await page.locator('[data-command="lineSpacingPct"]').inputValue(), '200')
    assert.equal(await page.locator('[data-command="spaceBeforePt"]').inputValue(), '12.5')
    assert.equal(await page.locator('[data-command="spaceAfterPt"]').inputValue(), '0')
  } else if (smokeMode === 'new-slide') {
    // 修订 2 重开：新页成为普通来源页，不再标记为待写入。
    activeBytes = downloaded; activeSha = saveReceipt.artifacts.pptx.sha256; activeRevision = 2
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html?smokeRevision=2`)
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.waitForFunction(() => document.querySelectorAll('.slide-row').length === 3)
    assert.equal(await page.locator('.slide-row[data-new-slide]').count(), 0)
  } else {
    assert.deepEqual(reopened.size, targetSize)
    assert.deepEqual(reopened.pythonPptxSize, [targetSize.cx, targetSize.cy])
    let expectedGeometry = { x: 128, y: 96, width: 640, height: 96 }
    if (smokeMode === 'slide-size-custom') {
      const original = JSON.parse(runPython({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
      const expectedEmu = Object.fromEntries(Object.entries(original.pythonPptxGeometry[0]).map(([key, value]) => {
        const axis = key === 'x' || key === 'width' ? 0 : 1
        return [key, Math.round(value * [targetSize.cx, targetSize.cy][axis] / original.pythonPptxSize[axis])]
      }))
      assert.deepEqual(reopened.pythonPptxGeometry[0], expectedEmu)
      expectedGeometry = Object.fromEntries(Object.entries(expectedEmu).map(([key, value]) => [key, value / 9525]))
    }
    if (smokeMode === 'slide-size-presets') {
      const expectedEmu = { x: Math.round(75 * targetSize.cx / 960), y: Math.round(80 * targetSize.cy / 720),
        width: Math.round(300 * targetSize.cx / 960), height: Math.round(90 * targetSize.cy / 720) }
      assert.deepEqual(reopened.pythonPptxGeometry[0], expectedEmu)
      expectedGeometry = Object.fromEntries(Object.entries(expectedEmu).map(([key, value]) => [key, value / 9525]))
    }
    assert.deepEqual(reopened.elements[0].geometry, expectedGeometry)
    if (smokeMode === 'slide-size-recovery') {
      assert.ok(reopened.texts.includes('PPTX recovered after failure'))
      assert.ok(reopened.pythonPptxTexts.includes('PPTX recovered after failure'))
    }
    activeBytes = downloaded
    activeSha = saveReceipt.artifacts.pptx.sha256
    activeRevision = 2
    await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html?smokeRevision=2`)
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.locator('[data-ribbon-tab="design"]').click()
    assert.equal(await page.locator('[data-command="slideSize"][data-source-action="onSlideSize"]').inputValue(), smokeMode === 'slide-size-custom' ? '' : smokeMode === 'slide-size-presets' ? paperPreset : '16:9')
    assert.equal(await page.locator('[data-command="slideOrientation"][data-source-action="onSlideSize"]').inputValue(), smokeMode === 'slide-size-presets' ? 'portrait' : 'landscape')
    assert.equal(Number(await page.locator('.geometry-grid input[name="x"]').inputValue()), expectedGeometry.x)
  }
  assert.equal(reopened.slideCount, smokeMode === 'new-slide' ? 3 : 1)
  if (smokeMode === 'slide-size-recovery') {
    assert.equal(failedResponses.length, 2)
    assert.ok(failedResponses.every(item => item.status === 503 && item.url.endsWith('/api/save')))
    assert.equal(pageErrors.length, 2)
    assert.ok(pageErrors.every(item => typeof item === 'object' && item.text.includes('503')))
  } else {
    assert.deepEqual(pageErrors, [])
    assert.deepEqual(failedResponses, [])
  }
  const receipt = { ok: true, inputBaseline, mode: smokeMode, revision: reopened.revision, originalSha256: sourceIdentity,
    downloadedSha256: reopened.sha256, size: reopened.size, transitions: reopened.slides[0].transition,
    animations: reopened.slides[0].animations, operationKinds: savePayload.operations.map(item => item.kind),
    ...(['paragraph-spacing', 'paragraph-lists'].includes(smokeMode) ? { listVariant: smokeMode === 'paragraph-lists' ? listVariant : undefined, paragraphs: reopened.pythonPptxParagraphs.map(shape => shape.paragraphs) } : {}),
  }
  if (process.env.PPTX_SMOKE_EVIDENCE_DIR) {
    const root = resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR)
    await mkdir(root, { recursive: true })
    await writeFile(join(root, 'source.pptx'), sourceBytes)
    await writeFile(join(root, 'downloaded.pptx'), downloaded)
    await writeFile(join(root, 'evidence.json'), JSON.stringify(receipt, null, 2) + '\n')
  }
  console.log(JSON.stringify(receipt))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
