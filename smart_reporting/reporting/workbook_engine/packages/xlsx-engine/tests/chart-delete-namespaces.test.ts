import JSZip from 'jszip'
import {expect, it} from 'vitest'
import {applyChartAdditions} from '../src/chart-add'
import {applyChartDeletions} from '../src/chart-delete'
import {createBlankWorkbook} from '../src/blank'

const XDR = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
const CHART = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
const DRAWING = 'http://schemas.openxmlformats.org/drawingml/2006/main'
const REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const PACKAGE = 'http://schemas.openxmlformats.org/package/2006/relationships'
const drawingPath = 'xl/drawings/drawing1.xml', relsPath = 'xl/drawings/_rels/drawing1.xml.rels'
const chartPath = 'xl/charts/chart1.xml'

async function fixture(prefix: string, kind: string, id = 'chart&one') {
  const added = {worksheetSheetName:'Sheet1',anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},
    chart:{chartType:'column' as const,title:'Keep chart',series:[{name:'Sales',categories:['Q1'],values:[42]}]}}
  const zip = await JSZip.loadAsync(await applyChartAdditions(await createBlankWorkbook(), [added, added]))
  const x = (name: string) => prefix ? `${prefix}:${name}` : name
  const attributeId = id.replaceAll('&','&amp;').replaceAll('"','&quot;')
  const geometry = kind === 'absoluteAnchor' ? `<${x('pos')} x="100" y="200"/><${x('ext')} cx="300" cy="400"/>`
    : `<${x('from')}><${x('col')}>3</${x('col')}><${x('colOff')}>0</${x('colOff')}><${x('row')}>0</${x('row')}><${x('rowOff')}>0</${x('rowOff')}></${x('from')}>` +
      (kind === 'oneCellAnchor' ? `<${x('ext')} cx="300" cy="400"/>` : `<${x('to')}><${x('col')}>11</${x('col')}><${x('colOff')}>0</${x('colOff')}><${x('row')}>9</${x('row')}><${x('rowOff')}>0</${x('rowOff')}></${x('to')}>`)
  const anchor = (relationshipId: string) => `<${x(kind)}>${geometry}<${x('graphicFrame')}><${x('nvGraphicFramePr')}><${x('cNvPr')} id="1" name="Chart"/><${x('cNvGraphicFramePr')}/></${x('nvGraphicFramePr')}><${x('xfrm')}/><ink:graphic xmlns:ink="${DRAWING}"><ink:graphicData uri="${CHART}"><chart xmlns="${CHART}" xmlns:link="${REL}" link:id="${relationshipId}"/></ink:graphicData></ink:graphic></${x('graphicFrame')}><${x('clientData')}/></${x(kind)}>`
  const first = anchor(attributeId), second = anchor('keep')
  const opaque = '<!-- <xdr:graphicFrame><c:chart r:id="keep"/></xdr:graphicFrame> --><vendor:extra xmlns:vendor="urn:vendor">Keep &amp; metadata</vendor:extra>'
  const beforeDrawing = `<?xml version="1.0"?><${x('wsDr')} xmlns${prefix ? ':'+prefix : ''}="${XDR}">${first}${opaque}${second}</${x('wsDr')}>`
  const firstRel = `<pkg:Relationship Id="${attributeId}" Type="${REL}/chart" Target="../charts/chart1.xml"/>`
  const secondRel = `<pkg:Relationship Id="keep" Type="${REL}/chart" Target="../charts/chart2.xml"/>`
  const beforeRels = `<pkg:Relationships xmlns:pkg="${PACKAGE}">${firstRel}${secondRel}</pkg:Relationships>`
  zip.file(drawingPath,beforeDrawing);zip.file(relsPath,beforeRels)
  zip.file('custom/keep.bin',Uint8Array.from([0,255,7,128]))
  return {zip,first,second,firstRel,beforeDrawing,beforeRels,expectedDrawing:beforeDrawing.replace(first,''),expectedRels:beforeRels.replace(firstRel,'')}
}

for (const kind of ['twoCellAnchor','oneCellAnchor','absoluteAnchor']) {
  it.each(['','drawing','xdr'])('删除%s来源'+kind+'的精确图表且其余XML字节保持', async prefix => {
    const f = await fixture(prefix,kind), source = await f.zip.generateAsync({type:'uint8array'}), original = source.slice()
    const output = await applyChartDeletions(source,[{sheetName:'Sheet1',chartPath}]), saved = await JSZip.loadAsync(output)
    expect(source).toEqual(original)
    expect(await saved.file(drawingPath)!.async('string')).toBe(f.expectedDrawing)
    expect(await saved.file(relsPath)!.async('string')).toBe(f.expectedRels)
    expect(saved.file(chartPath)).toBeNull()
    expect(Object.keys(saved.files).filter(path=>!saved.files[path]!.dir).sort())
      .toEqual(Object.keys(f.zip.files).filter(path=>!f.zip.files[path]!.dir && path!==chartPath).sort())
    for (const path of Object.keys(f.zip.files).filter(path=>!f.zip.files[path]!.dir && ![chartPath,drawingPath,relsPath,'[Content_Types].xml'].includes(path))) {
      expect(await saved.file(path)!.async('uint8array')).toEqual(await f.zip.file(path)!.async('uint8array'))
    }
    const types = await saved.file('[Content_Types].xml')!.async('string')
    expect(types).not.toContain('/xl/charts/chart1.xml')
    expect(types).toContain('/xl/charts/chart2.xml')
  })
}

it('同一默认命名空间绘图中多次删除保留累积结果及外来元数据', async () => {
  const f = await fixture('','oneCellAnchor')
  const output = await applyChartDeletions(await f.zip.generateAsync({type:'uint8array'}),[
    {sheetName:'Sheet1',chartPath},{sheetName:'Sheet1',chartPath:'xl/charts/chart2.xml'},
  ])
  const zip = await JSZip.loadAsync(output)
  expect(await zip.file(drawingPath)!.async('string')).toBe(f.expectedDrawing.replace(f.second,''))
  expect(await zip.file(relsPath)!.async('string')).not.toContain('Relationship Id=')
})

it.each(['foreign-chart','foreign-id','duplicate-target','mixed-objects','shared-part'])('不删除身份不可信或会连带其他对象的图表 %s', async mode => {
  const f = await fixture('drawing','absoluteAnchor')
  let xml = f.beforeDrawing
  if (mode === 'foreign-chart') xml = xml.replace(`xmlns="${CHART}"`,`xmlns="urn:foreign:chart"`)
  if (mode === 'foreign-id') xml = xml.replace(`xmlns:link="${REL}"`,`xmlns:link="urn:foreign:rel"`)
  if (mode === 'duplicate-target') xml = xml.replace(f.second,f.first)
  if (mode === 'mixed-objects') xml = xml.replace('<drawing:clientData/>','<drawing:pic/><drawing:clientData/>')
  if (mode === 'shared-part') f.zip.file(relsPath,f.beforeRels.replace('</pkg:Relationships>',`<pkg:Relationship Id="shared" Type="${REL}/chart" Target="../charts/chart1.xml"/></pkg:Relationships>`))
  f.zip.file(drawingPath,xml)
  const source = await f.zip.generateAsync({type:'uint8array'}), original = source.slice()
  await expect(applyChartDeletions(source,[{sheetName:'Sheet1',chartPath}])).rejects.toThrow()
  expect(source).toEqual(original)
})
