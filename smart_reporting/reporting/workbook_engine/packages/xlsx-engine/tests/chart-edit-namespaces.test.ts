import {mkdir, writeFile} from 'node:fs/promises'
import JSZip from 'jszip'
import {SaxesParser} from 'saxes'
import {expect, it} from 'vitest'
import {applyChartEdits} from '../src/rules'
import {createBlankWorkbook} from '../src/blank'
import {applyChartAdditions} from '../src/chart-add'

const CHART = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
const DRAWING = 'http://schemas.openxmlformats.org/drawingml/2006/main'
const path = 'xl/charts/chart1.xml'
const foreign = '<c:extension xmlns:c="urn:vendor:chart"><c:title keep="yes">vendor title</c:title><c:ser/></c:extension>'
const evidence = process.env.XLSX_NAMESPACE_EVIDENCE_DIR

async function fixture(prefix: string, drawingPrefix: string): Promise<Uint8Array> {
  const c = (local: string) => prefix ? `${prefix}:${local}` : local
  const a = (local: string) => `${drawingPrefix}:${local}`
  const zip = await JSZip.loadAsync(await applyChartAdditions(await createBlankWorkbook(), [{
    worksheetSheetName: 'Sheet1',
    anchor: {fromRow: 0, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0, toRow: 15, toColumn: 10, toRowOffset: 0, toColumnOffset: 0},
    chart: {chartType: 'column', title: 'Original & title', series: [{name: 'Sales', categories: ['Q1'], values: [42]}]},
  }]))
  zip.file('custom/opaque.bin', Uint8Array.from([0, 255, 41, 128, 0]))
  zip.file(path, `<?xml version="1.0"?><${c('chartSpace')} xmlns${prefix ? ':' + prefix : ''}="${CHART}" xmlns:${drawingPrefix}="${DRAWING}"><${c('chart')}><${c('title')}><${c('tx')}><${c('rich')}><${a('p')}><${a('r')}><${a('t')}>Original &amp; title</${a('t')}></${a('r')}></${a('p')}></${c('rich')}></${c('tx')}></${c('title')}><${c('plotArea')}><${c('barChart')}><${c('barDir')} val="col"/><${c('grouping')} val="clustered"/><${c('ser')}><${c('idx')} val="0"/><${c('order')} val="0"/><${c('tx')}><${c('v')}>Sales</${c('v')}></${c('tx')}><${c('val')}><${c('numLit')}><${c('formatCode')}>0.00</${c('formatCode')}><${c('ptCount')} val="1"/><${c('pt')} idx="0"><${c('v')}>42</${c('v')}></${c('pt')}></${c('numLit')}></${c('val')}></${c('ser')}></${c('barChart')}></${c('plotArea')}><${c('extLst')}><${c('ext')} uri="vendor">${foreign}</${c('ext')}></${c('extLst')}></${c('chart')}></${c('chartSpace')}>`)
  const xml = await zip.file(path)!.async('string')
  const ids = `<${c('axId')} val="111"/><${c('axId')} val="222"/>`
  const axis = (kind: string, id: number, pos: string, cross: number) => `<${c(kind)}><${c('axId')} val="${id}"/><${c('scaling')}><${c('orientation')} val="minMax"/></${c('scaling')}><${c('axPos')} val="${pos}"/><${c('crossAx')} val="${cross}"/></${c(kind)}>`
  zip.file(path, xml.replace(`</${c('barChart')}>`, ids + `</${c('barChart')}>`).replace(`</${c('plotArea')}>`, axis('catAx', 111, 'b', 222) + axis('valAx', 222, 'l', 111) + `</${c('plotArea')}>`))
  return zip.generateAsync({type: 'uint8array'})
}

// Independently resolve namespace URIs in the saved XML; never use readCharts.
function inspect(xml: string) {
  const parser = new SaxesParser({xmlns: true})
  const names: string[] = [], text: string[] = [], colors: string[] = []
  parser.on('opentag', node => {
    names.push(`${node.uri}|${node.local}`)
    if (node.uri === DRAWING && node.local === 'srgbClr') colors.push(node.attributes.val!.value)
  })
  parser.on('text', value => text.push(value))
  parser.write(xml).close()
  return {names, text, colors}
}

it.each([['', 'drawing'], ['chart', 'ink'], ['c', 'a']])('真实ZIP图表写入保留命名空间 %s/%s 与无关部件', async (prefix, drawingPrefix) => {
  const source = await fixture(prefix, drawingPrefix)
  const originalXml = await (await JSZip.loadAsync(source)).file(path)!.async('string')
  const titleOnly = await applyChartEdits(source, [{chartPath: path, title: 'Edited & 标题'}])
  const titleXml = await (await JSZip.loadAsync(titleOnly)).file(path)!.async('string')
  expect(inspect(titleXml).text).toContain('Edited & 标题')
  expect(titleXml).toBe(originalXml.replace('Original &amp; title', 'Edited &amp; 标题'))
  const legendOnly = await applyChartEdits(source, [{chartPath: path, legend: 'bottom'}])
  const legendXml = await (await JSZip.loadAsync(legendOnly)).file(path)!.async('string')
  expect(inspect(legendXml).names).toContain(`${CHART}|legend`)
  expect(inspect(legendXml).text).toContain('Original & title')
  const edited = await applyChartEdits(source, [{chartPath: path, title: 'Edited & 标题', seriesColors: {'0': '#2F9E6E'}, legend: 'bottom', dataLabels: 'value'}])
  const before = await JSZip.loadAsync(source), after = await JSZip.loadAsync(edited)
  const xml = await after.file(path)!.async('string'), parsed = inspect(xml)
  expect(parsed.text).toContain('Edited & 标题')
  expect(parsed.text).not.toContain('Original & title')
  expect(parsed.colors).toEqual(['2F9E6E', '2F9E6E'])
  expect(parsed.names).toContain(`${CHART}|legend`)
  expect(parsed.names).toContain(`${CHART}|dLbls`)
  expect(xml).toContain(`<${prefix ? prefix + ':' : ''}chartSpace `)
  expect(xml).toContain(`<${drawingPrefix}:t>Edited &amp; 标题</${drawingPrefix}:t>`)
  expect(xml).toContain(foreign)
  expect(xml).toContain(`<${prefix ? prefix + ':' : ''}formatCode>0.00</${prefix ? prefix + ':' : ''}formatCode>`)
  expect(Object.keys(after.files).sort()).toEqual(Object.keys(before.files).sort())
  for (const name of Object.keys(before.files).filter(name => !before.files[name]!.dir && name !== path)) {
    expect(await after.file(name)!.async('uint8array')).toEqual(await before.file(name)!.async('uint8array'))
  }
  if (evidence) {
    await mkdir(evidence, {recursive: true})
    await writeFile(`${evidence}/${prefix || 'default'}-source.xlsx`, source)
    await writeFile(`${evidence}/${prefix || 'default'}-edited.xlsx`, edited)
  }
})

it('既有c/a图表保留无关扩展内的同URI别名与局部前缀重绑定', async () => {
  const zip = await JSZip.loadAsync(await fixture('c', 'a'))
  const extension = `<c:extLst><c:ext uri="aliases"><alt:title xmlns:alt="${CHART}"><ink:p xmlns:ink="${DRAWING}"><ink:r><ink:t>Keep alias</ink:t></ink:r></ink:p></alt:title><a:foreign xmlns:a="urn:vendor:other"><c:payload xmlns:c="${DRAWING}">keep rebound</c:payload></a:foreign></c:ext></c:extLst>`
  const xml = (await zip.file(path)!.async('string')).replace(/<c:extLst>[\s\S]*?<\/c:extLst>/, () => extension)
  zip.file(path, xml)
  const after = await applyChartEdits(await zip.generateAsync({type: 'uint8array'}), [{chartPath: path, title: 'Edited & 标题'}])
  const saved = await (await JSZip.loadAsync(after)).file(path)!.async('string')
  expect(saved).toBe(xml.replace('Original &amp; title', 'Edited &amp; 标题'))
  expect(inspect(saved).text).toContain('Keep alias')
})

it('局部DrawingML声明、注释及处理指令在标题编辑后原样保留', async () => {
  const zip = await JSZip.loadAsync(await fixture('c', 'a'))
  const xml = (await zip.file(path)!.async('string'))
    .replace(` xmlns:a="${DRAWING}"`, '')
    .replace('<a:p>', `<a:p xmlns:a="${DRAWING}">`)
    .replace('<c:chart>', '<?keep <c:title>?>\n<!-- <a:t>keep</a:t> --><c:chart>')
  zip.file(path, xml)
  const source = await zip.generateAsync({type: 'uint8array'})
  const after = await applyChartEdits(source, [{chartPath: path, title: 'Edited & 标题'}])
  expect(await (await JSZip.loadAsync(after)).file(path)!.async('string')).toBe(xml.replace('Original &amp; title', 'Edited &amp; 标题'))
  const color = await applyChartEdits(source, [{chartPath: path, seriesColors: {'0': '#123456'}}])
  const colored = await (await JSZip.loadAsync(color)).file(path)!.async('string')
  expect(inspect(colored).colors).toEqual(['123456', '123456'])
  expect(colored).toContain('<a:p xmlns:a="' + DRAWING + '">')
})

it.each(['title', 'chart', 'barChart'])('默认命名空间的%s附局部声明仍正确编辑且不重复标题', async local => {
  const zip = await JSZip.loadAsync(await fixture('', 'drawing'))
  let xml = (await zip.file(path)!.async('string')).replace(`<${local}>`, `<${local} xmlns:unused="urn:unused">`)
  if (local === 'chart') xml = xml.replace(/<title>[\s\S]*?<\/title>/, '')
  zip.file(path, xml)
  const edit = local === 'barChart' ? {dataLabels: 'value' as const} : {title: 'Edited & 标题'}
  const edited = await applyChartEdits(await zip.generateAsync({type: 'uint8array'}), [{chartPath: path, ...edit}])
  const saved = await (await JSZip.loadAsync(edited)).file(path)!.async('string'), parsed = inspect(saved)
  expect(saved).toContain(`<${local} xmlns:unused="urn:unused">`)
  expect(parsed.names.filter(name => name === `${CHART}|title`)).toHaveLength(1)
  if (local === 'barChart') expect(parsed.names).toContain(`${CHART}|dLbls`)
  else {expect(parsed.text).toContain('Edited & 标题'); expect(parsed.text).not.toContain('Original & title')}
})

it.each([['', 'title'], ['', 'ser'], ['', 'barChart'], ['c', 'title'], ['c', 'ser'], ['c', 'barChart']])('实际编辑目标混用同URI别名 %s/%s', async (prefix, local) => {
  const zip = await JSZip.loadAsync(await fixture(prefix, 'a'))
  const original = prefix ? `${prefix}:${local}` : local
  const xml = (await zip.file(path)!.async('string')).replace(`<${original}>`, `<alt:${local} xmlns:alt="${CHART}">`).replace(`</${original}>`, `</alt:${local}>`)
  zip.file(path, xml)
  const edit = local === 'title' ? {title: 'Edited & 标题'} : local === 'ser' ? {seriesColors: {'0': '#123456'}} : {dataLabels: 'value' as const}
  const source = await zip.generateAsync({type: 'uint8array'})
  const edited = await applyChartEdits(source, [{chartPath: path, ...edit}])
  const saved = await (await JSZip.loadAsync(edited)).file(path)!.async('string'), parsed = inspect(saved)
  expect(parsed.names.filter(name => name === `${CHART}|title`)).toHaveLength(1)
  expect(parsed.names.filter(name => name === `${CHART}|ser`)).toHaveLength(1)
  if (local === 'title') {expect(parsed.text).toContain('Edited & 标题'); expect(parsed.text).not.toContain('Original & title')}
  else if (local === 'ser') expect(parsed.colors).toEqual(['123456', '123456'])
  else expect(parsed.names).toContain(`${CHART}|dLbls`)
  expect(saved).toContain(foreign)
  if (evidence) {
    await mkdir(evidence, {recursive: true})
    await writeFile(`${evidence}/${prefix || 'default'}-actual-${local}-source.xlsx`, source)
    await writeFile(`${evidence}/${prefix || 'default'}-actual-${local}-edited.xlsx`, edited)
  }
})

it.each(['', 'c'])('主前缀被局部遮蔽时新增元素仍属于Chart命名空间 %s', async prefix => {
  const zip = await JSZip.loadAsync(await fixture(prefix, 'a'))
  const c = prefix ? 'c:' : ''
  const xml = (await zip.file(path)!.async('string')).replace(new RegExp(`<${c}ser>[\\s\\S]*?</${c}ser>`), series => series
    .replace(/<(\/?)(?:c:)?([A-Za-z][\w.-]*)/g, '<$1alt:$2')
    .replace('<alt:ser>', `<alt:ser xmlns:alt="${CHART}" xmlns${prefix ? ':c' : ''}="urn:vendor:shadow">`))
  zip.file(path, xml)
  const source = await zip.generateAsync({type: 'uint8array'})
  const edited = await applyChartEdits(source, [{chartPath: path, seriesColors: {'0': '#123456'}}])
  const saved = await (await JSZip.loadAsync(edited)).file(path)!.async('string'), parsed = inspect(saved)
  expect(parsed.names.filter(name => name === `${CHART}|ser`)).toHaveLength(1)
  expect(parsed.names.filter(name => name === `${CHART}|spPr`)).toHaveLength(1)
  expect(parsed.names.filter(name => name === `${CHART}|val`)).toHaveLength(1)
  expect(parsed.colors).toEqual(['123456', '123456'])
  expect(parsed.names.some(name => name.startsWith('urn:vendor:shadow|'))).toBe(false)
  expect(saved).toContain(foreign)
  if (evidence) {
    await mkdir(evidence, {recursive: true})
    await writeFile(`${evidence}/${prefix || 'default'}-shadow-source.xlsx`, source)
    await writeFile(`${evidence}/${prefix || 'default'}-shadow-edited.xlsx`, edited)
  }
})
