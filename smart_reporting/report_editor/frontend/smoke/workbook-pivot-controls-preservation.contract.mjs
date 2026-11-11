// 复用 --geometry-only 的真实 XLSX 产物，故障注入证明文件保留断言能拒绝误改。
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const source = process.env.WORKBOOK_SMOKE_SOURCE_XLSX, saved = process.env.WORKBOOK_SMOKE_SAVED_XLSX
assert(source && saved, '需要 WORKBOOK_SMOKE_SOURCE_XLSX 和 WORKBOOK_SMOKE_SAVED_XLSX 指向已有几何验收产物')
const directory = await mkdtemp(join(tmpdir(), 'xlsx-geometry-preservation-'))
const cases = ['pivot', 'timeline', 'timeline-cache', 'sibling-anchor', 'slicer-caption', 'slicer-cache', 'extra-part', 'missing-part']
try {
  const injected = spawnSync(resolve('../../../.venv/bin/python'), ['-c', `
import json,sys
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from xml.etree import ElementTree as ET
source,directory,cases=json.load(sys.stdin)
with ZipFile(source) as z: original={n:z.read(n) for n in z.namelist()}
ns={'xdr':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'}
for case in cases:
 parts=dict(original)
 paths={'pivot':'xl/pivotTables/pivotTable1.xml','timeline':'xl/timelines/timeline1.xml','timeline-cache':'xl/timelineCaches/timelineCache1.xml','slicer-caption':'xl/slicers/slicer1.xml','slicer-cache':'xl/slicerCaches/slicerCache1.xml'}
 if case in paths:
  path=paths[case];r=ET.fromstring(parts[path])
  if case=='pivot':
   node=next(n for n in r.iter() if n.tag.endswith('}dataField'));node.set('name','Changed amount')
  elif case in ('timeline','slicer-caption'):
   node=next(n for n in r.iter() if n.tag.endswith('}timeline') or n.tag.endswith('}slicer'));node.set('caption','Changed caption')
  else:r.set('sourceName','Changed source')
  parts[path]=ET.tostring(r)
 elif case=='sibling-anchor':
  path='xl/drawings/drawing1.xml';r=ET.fromstring(parts[path])
  a=next(a for a in r if any(n.attrib.get('name')=='Timeline_P1_F0' for n in a.iter()))
  a.find('xdr:from/xdr:row',ns).text='99';parts[path]=ET.tostring(r)
 elif case=='extra-part':parts['xl/timelines/unexpected.xml']=b'<unexpected/>'
 elif case=='missing-part':del parts['xl/pivotCache/pivotCacheRecords1.xml']
 with ZipFile(Path(directory)/(case+'.xlsx'),'w',ZIP_DEFLATED) as z:
  for name,data in parts.items():z.writestr(name,data)
`], { input: JSON.stringify([resolve(saved), directory, cases]), encoding: 'utf8' })
  assert.equal(injected.status, 0, injected.stderr)
  const inspect = (file, name, environment = {}) => spawnSync(process.execPath, ['smoke/workbook-pivot-protection-built-smoke.mjs', '--geometry-only', '--inspect-only'], {
    env: { ...process.env, WORKBOOK_SMOKE_SOURCE_XLSX: resolve(source), WORKBOOK_SMOKE_SAVED_XLSX: file, WORKBOOK_SMOKE_EVIDENCE_DIR: join(directory, name), ...environment },
    encoding: 'utf8', timeout: 90000,
  })
  const valid = inspect(resolve(saved), 'valid')
  assert.equal(valid.status, 0, valid.stderr)
  assert.equal(JSON.parse(valid.stdout.trim()).inspectionOnly, true)
  const receipt = join(directory, 'valid', 'inspection-receipt.json')
  for (const name of cases) {
    // 同一证据目录已有成功回执时，本轮失败必须将其清除。
    await writeFile(receipt, JSON.stringify({ ok: true, savedSha256: 'stale' }))
    const result = inspect(join(directory, `${name}.xlsx`), 'valid')
    assert.notEqual(result.status, 0, `${name}: 几何保存误改未被拒绝`)
    assert.match(result.stderr, /几何保存保留/, `${name}: 应由保留断言拒绝，不能依赖解析器偶然失败`)
    await assert.rejects(readFile(receipt), { code: 'ENOENT' }, `${name}: 失败后仍遗留成功回执`)
  }
  for (const name of ['missing-source', 'missing-saved']) {
    await mkdir(join(directory, name))
    const path = join(directory, name, 'inspection-receipt.json')
    await writeFile(path, JSON.stringify({ ok: true }))
    const missing = join(directory, 'missing.xlsx')
    const result = inspect(name === 'missing-saved' ? missing : resolve(saved), name, name === 'missing-source' ? { WORKBOOK_SMOKE_SOURCE_XLSX: missing } : {})
    assert.notEqual(result.status, 0, `${name}: 缺失输入必须失败`)
    assert.match(result.stderr, /ENOENT/)
    await assert.rejects(readFile(path), { code: 'ENOENT' }, `${name}: 读取失败后仍遗留成功回执`)
  }
  const recovered = inspect(resolve(saved), 'valid')
  assert.equal(recovered.status, 0, recovered.stderr)
  assert.equal(JSON.parse(await readFile(receipt, 'utf8')).savedSha256, JSON.parse(valid.stdout.trim()).savedSha256)
  console.log(JSON.stringify({ ok: true, validFiles: 2, rejectedMutations: cases, staleReceiptsCleared: 10, recovery: true }))
} finally {
  await rm(directory, { recursive: true, force: true })
}
