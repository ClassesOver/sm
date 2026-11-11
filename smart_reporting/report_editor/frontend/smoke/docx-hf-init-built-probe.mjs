// 构建依赖拆分后的窄启动探针，不重复保存全链。
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { spawn } from 'node:child_process'
const source = new URL('./docx-insert-gui-smoke.mjs', import.meta.url)
const temporary = new URL(`./.hf-init-probe-${process.pid}.mjs`, import.meta.url)
let code = await readFile(source, 'utf8')
const anchor = "  if (smokeCase === 'hf-insert-delete') {"
assert.equal(code.split(anchor).length, 2)
code = code.replace(anchor, `  if (smokeCase === 'hf-insert-init') {
    await page.locator('[data-action="insert-header"]').click()
    await page.locator('.docx-source-insert .layout-menu').getByRole('button', {name:'编辑页眉',exact:true}).waitFor()
    assert.equal(await page.locator('.docx-source-insert .layout-menu').getByRole('button', {name:'编辑页眉',exact:true}).isEnabled(),true)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ok:true,case:smokeCase,builtPreview,pageErrors,saveRequests:savePayloads.size}))
  } else if (smokeCase === 'hf-insert-delete') {`)
try {
  await writeFile(temporary, code)
  process.exitCode = await new Promise(resolve => spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,NATIVE_GUI_PREVIEW:'1',DOCX_INSERT_CASE:'hf-insert-init'}}).on('exit',resolve)) ?? 1
} finally { await unlink(temporary).catch(()=>{}) }
