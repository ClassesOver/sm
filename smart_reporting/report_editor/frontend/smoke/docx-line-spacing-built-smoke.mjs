// 真实 Chromium、DOCX 引擎与下载回读；授权和修订登记路由为 fixture。
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const staticRoot = resolve(process.env.DOCX_TEST_DIST ?? new URL('../../static', import.meta.url).pathname)
const characterIndent = process.env.DOCX_TEST_CHARACTER_INDENT === '1'
const specialIndent = characterIndent || process.env.DOCX_TEST_SPECIAL_INDENT === '1'
const output = await mkdtemp(join(tmpdir(), characterIndent ? 'word-character-indent-built-' : specialIndent ? 'word-special-indent-built-' : 'word-line-spacing-built-'))
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = sha(await readFile(join(staticRoot, '.vite/manifest.json')))
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const runPython = payload => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', String.raw`
import json, sys
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from hashlib import sha256
from copy import deepcopy
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.style import WD_STYLE_TYPE
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
p=json.load(sys.stdin)
path=Path(p['path'])
if p['mode']=='fixture':
    doc=Document()
    doc.sections[0].header.paragraphs[0].text='保留页眉'
    target=doc.add_paragraph();target.add_run('行距目标').bold=True;target.add_run('中文 mixed').italic=True
    target.paragraph_format.line_spacing=1.5
    target.paragraph_format.space_after=Pt(6)
    target.paragraph_format.keep_with_next=True
    if p['specialIndent']:
        style=doc.styles.add_style('SpecialSource',WD_STYLE_TYPE.PARAGRAPH)
        inherited=OxmlElement('w:ind');inherited.set(qn('w:hangingChars'),'100');style.element.get_or_add_pPr().append(inherited)
        target.style=style
        for run in target.runs:run.font.size=Pt(12)
        ind=OxmlElement('w:ind')
        for key,value in {'left':'720','leftChars':'300','right':'360','rightChars':'0','firstLine':'180','firstLineChars':'200'}.items():ind.set(qn('w:'+key),value)
        target._p.pPr.append(ind)
    doc.add_paragraph('旁边段落不得改变')
    doc.add_table(rows=1, cols=1).cell(0,0).text='表格保持原样'
    doc.save(path)
elif p['mode']=='patch':
    data=patch_docx(Path(p['source']).read_bytes(), p['operations']);path.write_bytes(data)
data=path.read_bytes();doc=Document(BytesIO(data))
spacing=doc.paragraphs[0]._p.pPr.find(qn('w:spacing'))
with ZipFile(BytesIO(data)) as package:
    parts={n:sha256(package.read(n)).hexdigest() for n in package.namelist() if not n.endswith('/')}
if p['mode']=='verify':
    source=Path(p['source']).read_bytes();original=Document(BytesIO(source))
    if p['specialIndent']:
        value=p['twips'];ind=doc.paragraphs[0]._p.pPr.find(qn('w:ind'))
        expected={'left':'720','leftChars':'300','right':'360','rightChars':'0','firstLineChars':str(p.get('firstLineChars',0)),'hangingChars':'0'}
        expected['hanging' if value<0 else 'firstLine']=str(abs(value))
        assert dict(ind.attrib)=={qn('w:'+k):v for k,v in expected.items()}
        assert doc.paragraphs[0].paragraph_format.first_line_indent.twips==value
    else:
        assert spacing.get(qn('w:lineRule'))==p['rule']
        assert spacing.get(qn('w:line'))==str(p['twips'])
    assert doc.paragraphs[0].text==original.paragraphs[0].text
    assert doc.paragraphs[0].paragraph_format.space_after.twips==120
    assert doc.paragraphs[0].paragraph_format.keep_with_next is True
    normalize=lambda r:r._r.xml.replace(' xml:space="preserve"','')
    assert [normalize(r) for r in doc.paragraphs[0].runs]==[normalize(r) for r in original.paragraphs[0].runs]
    assert [n.xml for n in list(doc._element.body)[1:]]==[n.xml for n in list(original._element.body)[1:]]
    properties=[]
    for d in (original,doc):
        props=deepcopy(d.paragraphs[0]._p.pPr)
        for child in list(props):
            if p['specialIndent'] and child.tag==qn('w:ind'):props.remove(child)
            elif not p['specialIndent'] and child.tag==qn('w:spacing'):
                for key in ('line','lineRule'):child.attrib.pop(qn('w:'+key),None)
        properties.append(props.xml)
    assert properties[0]==properties[1]
    with ZipFile(BytesIO(source)) as before:
        assert {n for n in before.namelist() if not n.endswith('/')}==set(parts)
        for n in parts:
            if n not in ('word/document.xml','docProps/core.xml'):assert sha256(before.read(n)).hexdigest()==parts[n],n
print(json.dumps({'sha256':sha256(data).hexdigest(),'model':inspect_docx(data),'parts':parts,'spacing':dict(spacing.attrib)},ensure_ascii=False))
`], { cwd: repo, input: JSON.stringify({ ...payload, specialIndent }), encoding: 'utf8', timeout: 120000, maxBuffer: 16 * 1024 * 1024 })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(result.stderr || `Python exited ${result.status}`)
  return JSON.parse(result.stdout)
}
const pathOf = revision => join(output, `revision-${revision}.docx`)
const revisions = new Map([[1, runPython({ mode: 'fixture', path: pathOf(1) })]])
const prefix = '/reports/v1/editor/assets/'
const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, 'http://127.0.0.1').pathname
    if (path.startsWith('/download/')) {
      const revision = Number(path.split('/').at(-1)); assert.ok(revisions.has(revision))
      const data = await readFile(pathOf(revision))
      res.writeHead(200, { 'Content-Type': mediaType, 'Content-Disposition': 'attachment; filename=line-spacing.docx' }); res.end(data); return
    }
    const file = path.startsWith(prefix) ? resolve(staticRoot, path.slice(prefix.length)) : join(staticRoot, 'native.html')
    assert.ok(file.startsWith(staticRoot + '/'))
    res.writeHead(200, { 'Content-Type': ({ '.js': 'application/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2' })[extname(file)] ?? 'application/octet-stream' }); res.end(await readFile(file))
  } catch { res.writeHead(404); res.end() }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`
let browser, page
const errors = [], chunks = {}, identities = [], saves = [], checks = []
try {
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (!path.startsWith(prefix) || !path.endsWith('.js')) return
    identities.push((async () => {
      assert.equal(response.status(), 200)
      const actual = sha(await response.body()); assert.equal(actual, sha(await readFile(resolve(staticRoot, path.slice(prefix.length)))))
      chunks[path] = actual
    })())
  })
  await page.route('**/favicon.ico', route => route.fulfill({ status: 200, body: '' }))
  await page.route('**/reports/v1/native/line-spacing/*/api/**', async route => {
    try {
      const path = new URL(route.request().url()).pathname, revision = Number(path.split('/')[5]), current = revisions.get(revision)
      if (path.endsWith('/context')) return route.fulfill({ json: {
        context: { documentId: 'line-spacing', revision, parentRevision: revision > 1 ? revision - 1 : null, format: 'docx', scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: pathOf(revision), sha256: current.sha256, size: (await readFile(pathOf(revision))).length, mediaType }, origin: 'report' },
        editingEnabled: true, csrfToken: 'fixture', capabilities: { docx_editor: true },
      } })
      if (path.endsWith('/file')) return route.fulfill({ body: await readFile(pathOf(revision)), contentType: mediaType })
      if (path.endsWith('/preview')) return route.fulfill({ json: { sourceSha256: current.sha256, draftSha256: current.sha256, model: current.model } })
      assert.ok(path.endsWith('/save'))
      const payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, current.sha256)
      const next = revision + 1, result = runPython({ mode: 'patch', source: pathOf(revision), path: pathOf(next), operations: payload.operations })
      revisions.set(next, result); saves.push(payload)
      return route.fulfill({ json: { documentId: 'line-spacing', revision: next, parentRevision: revision, revisionRegistered: true,
        validation: { ok: false, issues: ['fixture_validation_warning'] },
        artifacts: { word: { downloadUrl: `${base}/download/${next}`, sha256: result.sha256 } }, editor: { openUrl: `/reports/v1/native/line-spacing/${next}` } } })
    } catch (error) { errors.push(String(error)); return route.fulfill({ status: 500, json: { detail: String(error) } }) }
  })
  const open = async revision => { await page.goto(`${base}/reports/v1/native/line-spacing/${revision}`); await page.locator('.docx-source-home').waitFor({ timeout: 30000 }) }
  const body = () => page.getByRole('textbox', { name: 'Word 文档编辑区', exact: true })
  const choose = async () => { await body().locator('p').first().click(); await page.locator('[data-tab-id=home]').click() }
  const dialog = () => page.getByRole('dialog', { name: specialIndent ? '特殊缩进' : '段落行距', exact: true })
  const openDialog = async () => { await choose(); await page.locator('[data-action=line-spacing]').click(); await page.locator(`[data-action=${specialIndent ? 'special-indent-options' : 'line-spacing-options'}]`).click(); await dialog().waitFor() }
  const draft = () => page.evaluate(() => Object.values(localStorage).filter(value => value.includes('line-spacing')).map(value => JSON.parse(value)).flatMap(value => value.operations ?? []))
  if (specialIndent) {
    await open(1); const text = await body().innerText()
    await openDialog(); assert.equal(await dialog().getByLabel('特殊缩进类型', { exact: true }).inputValue(), 'firstLine')
    assert.equal(await dialog().getByLabel('特殊缩进单位', { exact: true }).inputValue(), 'chars')
    assert.equal(await dialog().getByLabel('缩进值（字符）', { exact: true }).inputValue(), '2')
    assert.ok(await dialog().locator('[data-character-warning]').isVisible())
    await page.screenshot({ path: join(output, 'character-source-dialog.png'), fullPage: true })
    await dialog().getByRole('button', { name: '取消', exact: true }).click(); assert.deepEqual(await draft(), [])
    await openDialog()
    if (!characterIndent) await dialog().getByLabel('特殊缩进单位', { exact: true }).selectOption('pt')
    const valueLabel = characterIndent ? '缩进值（字符）' : '缩进值（pt）'
    for (const invalid of characterIndent ? ['0', '100.01', '2.345', '61'] : ['0', '720.05', '18.123']) {
      await dialog().getByLabel(valueLabel, { exact: true }).fill(invalid)
      await dialog().getByRole('button', { name: '确定', exact: true }).click()
      assert.ok((await dialog().getByRole('alert').innerText()).includes('0.05–720')); assert.deepEqual(await draft(), [])
    }
    const firstTwips = characterIndent ? 564 : 365
    await dialog().getByLabel(valueLabel, { exact: true }).fill(characterIndent ? '2.35' : '18.25'); await dialog().getByRole('button', { name: '确定', exact: true }).click()
    assert.equal((await draft())[0].twips, firstTwips)
    if (characterIndent) assert.equal((await draft())[0].firstLineChars, 235)
    await choose(); await body().focus(); await page.keyboard.press('Control+z'); assert.deepEqual(await draft(), [])
    await page.keyboard.press('Control+Shift+z'); assert.equal((await draft())[0].twips, firstTwips)
    await page.reload(); await page.locator('.docx-source-home').waitFor(); assert.equal((await draft())[0].twips, firstTwips)
    if (characterIndent) assert.equal((await draft())[0].firstLineChars, 235)
    checks.push('character-source/cancel/invalid/undo/redo/reload')
    const steps = characterIndent
      ? [[1, 'firstLine', '2.35', 564, 'chars'], [2, 'firstLine', '18.25', 365, 'pt'], [3, 'hanging', '24', -480, 'pt'], [4, 'none', '', 0, 'pt']]
      : [[1, 'firstLine', '18.25', 365, 'pt'], [2, 'hanging', '24', -480, 'pt'], [3, 'none', '', 0, 'pt']]
    for (const [revision, kind, value, twips, unit] of steps) {
      if (revision > 1) {
        await open(revision); await openDialog()
        const previous = steps[revision - 2]
        assert.equal(await dialog().getByLabel('特殊缩进类型', { exact: true }).inputValue(), previous[1])
        assert.equal(await dialog().getByLabel('特殊缩进单位', { exact: true }).inputValue(), previous[4])
        assert.equal(await dialog().getByLabel(previous[4] === 'chars' ? '缩进值（字符）' : '缩进值（pt）', { exact: true }).inputValue(), previous[2])
        await dialog().getByLabel('特殊缩进类型', { exact: true }).selectOption(kind)
        if (kind === 'firstLine') await dialog().getByLabel('特殊缩进单位', { exact: true }).selectOption(unit)
        if (kind !== 'none') await dialog().getByLabel('缩进值（pt）', { exact: true }).fill(value)
        await dialog().getByRole('button', { name: '确定', exact: true }).click()
      }
      assert.equal((await draft())[0].kind, 'setParagraphSpecialIndent'); assert.equal((await draft())[0].twips, twips)
      await page.locator('[data-action=save]').click()
      await page.waitForFunction(n => document.querySelector('.save-state-label')?.textContent?.includes(`已保存修订 ${n}`), revision + 1)
      const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: '下载 Word', exact: true }).click()])
      const bytes = await readFile(await download.path()); assert.equal(sha(bytes), revisions.get(revision + 1).sha256)
      const path = join(output, `downloaded-${revision + 1}.docx`); await writeFile(path, bytes)
      runPython({ mode: 'verify', source: pathOf(revision), path, twips, firstLineChars: unit === 'chars' ? 235 : 0 }); checks.push(`save/download/independent-readback-${kind}-${unit}`)
    }
    await open(steps.length + 1); assert.equal(await body().innerText(), text); await openDialog()
    assert.equal(await dialog().getByLabel('特殊缩进类型', { exact: true }).inputValue(), 'none')
    await dialog().getByRole('button', { name: '取消', exact: true }).click()
  } else {
  await open(1); const text = await body().innerText()
  await openDialog(); await page.screenshot({ path: join(output, 'dialog.png'), fullPage: true }); await dialog().getByRole('button', { name: '取消', exact: true }).click(); assert.deepEqual(await draft(), [])
  await openDialog(); await dialog().getByLabel('行距类型', { exact: true }).selectOption('exact'); await dialog().getByLabel('行距值（pt）', { exact: true }).fill('0')
  await dialog().getByRole('button', { name: '确定', exact: true }).click(); assert.ok((await dialog().getByRole('alert').innerText()).includes('1–1584')); assert.deepEqual(await draft(), [])
  await dialog().getByLabel('行距值（pt）', { exact: true }).fill('18.25'); await dialog().getByRole('button', { name: '确定', exact: true }).click()
  assert.equal((await draft())[0].lineRawTwips, 365)
  await choose(); await body().focus(); await page.keyboard.press('Control+z'); assert.deepEqual(await draft(), [])
  await page.keyboard.press('Control+Shift+z'); assert.equal((await draft())[0].lineRule, 'exact')
  await page.reload(); await page.locator('.docx-source-home').waitFor(); assert.equal((await draft())[0].lineRawTwips, 365); checks.push('cancel/invalid/undo/redo/reload')
  for (const [revision, rule, value, twips] of [[1, 'exact', '18.25', 365], [2, 'atLeast', '24', 480], [3, 'multiple', '1.23', 295], [4, 'multiple', '1.5', 360]]) {
    if (revision > 1) {
      await open(revision); await openDialog()
      assert.equal(await dialog().getByLabel('行距类型', { exact: true }).inputValue(), revision === 2 ? 'exact' : revision === 3 ? 'atLeast' : 'multiple')
      await dialog().getByLabel('行距类型', { exact: true }).selectOption(rule)
      if (revision === 4) {
        assert.equal(await dialog().getByLabel('行距倍数', { exact: true }).inputValue(), '1.23')
        await page.screenshot({ path: join(output, 'custom-multiple-dialog.png'), fullPage: true })
        for (const invalid of ['0.05', '1.234', '132.01']) {
          await dialog().getByLabel('行距倍数', { exact: true }).fill(invalid)
          await dialog().getByRole('button', { name: '确定', exact: true }).click()
          assert.ok((await dialog().getByRole('alert').innerText()).includes('0.06–132')); assert.deepEqual(await draft(), [])
        }
        await dialog().getByRole('button', { name: '取消', exact: true }).click(); assert.deepEqual(await draft(), [])
        await choose(); await page.locator('[data-action=line-spacing]').click(); await page.locator('[data-source-action="line-spacing-1.5"]').click()
        checks.push('custom-multiple-reopen/invalid/cancel/preset-switch')
      } else {
        await dialog().getByLabel(rule === 'multiple' ? '行距倍数' : '行距值（pt）', { exact: true }).fill(value)
        await dialog().getByRole('button', { name: '确定', exact: true }).click()
        if (revision === 3) {
          assert.equal((await draft())[0].lineSpacing, 1.23)
          await choose(); await body().focus(); await page.keyboard.press('Control+z'); assert.deepEqual(await draft(), [])
          await page.keyboard.press('Control+Shift+z'); assert.equal((await draft())[0].lineSpacing, 1.23)
          await page.reload(); await page.locator('.docx-source-home').waitFor(); assert.equal((await draft())[0].lineSpacing, 1.23)
          checks.push('custom-multiple-undo/redo/reload')
        }
      }
    }
    await page.locator('[data-action=save]').click()
    await page.waitForFunction(n => document.querySelector('.save-state-label')?.textContent?.includes(`已保存修订 ${n}`), revision + 1)
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: '下载 Word', exact: true }).click()])
    const bytes = await readFile(await download.path()); assert.equal(sha(bytes), revisions.get(revision + 1).sha256)
    const path = join(output, `downloaded-${revision + 1}.docx`); await writeFile(path, bytes)
    runPython({ mode: 'verify', source: pathOf(revision), path, rule: rule === 'multiple' ? 'auto' : rule, twips })
    checks.push(`save/download/independent-readback-${rule}-${value}`)
  }
  await open(5); assert.equal(await body().innerText(), text)
  await openDialog(); assert.equal(await dialog().getByLabel('行距类型', { exact: true }).inputValue(), 'multiple'); assert.equal(await dialog().getByLabel('行距倍数', { exact: true }).inputValue(), '1.5')
  await dialog().getByRole('button', { name: '取消', exact: true }).click()
  }
  await page.screenshot({ path: join(output, 'reopened.png'), fullPage: true })
  await Promise.all(identities); assert.deepEqual(errors, []); assert.equal(sha(await readFile(join(staticRoot, '.vite/manifest.json'))), manifestSha256)
  const result = { ok: true, output, manifestSha256, browser: browser.version(), checks, saves, chunks, errors }
  await writeFile(join(output, 'result.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify({ ...result, chunks: Object.keys(chunks).length }))
} catch (error) {
  if (page) { await page.screenshot({ path: join(output, 'failure.png'), fullPage: true }); await writeFile(join(output, 'failure.html'), await page.content()) }
  console.error(JSON.stringify({ output, errors })); throw error
} finally { await browser?.close(); await new Promise(resolve => server.close(resolve)) }
