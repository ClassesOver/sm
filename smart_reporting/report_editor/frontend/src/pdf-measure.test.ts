import { describe, expect, it } from 'vitest'
import { formatLength, parseCalibration } from './vendor/genoffice-pdf/renderer/measure'
import { pdfDrawingOperation, pdfLineLength, pdfMeasurementOperation, validatePdfDrawing } from './pdf-operations'

const box = { x: 10, y: 20, width: 300, height: 400 }
const red: [number, number, number] = [0.86, 0.15, 0.15]

describe('PDF measure tool (pinned measure.ts + engine measure drawing)', () => {
  it('calibrates from the reference line and labels later lines with the session scale', () => {
    const reference = pdfDrawingOperation('p1', 'measure', [[20, 100], [220, 100]], box, red, { label: '0' })
    const scale = parseCalibration('4', 'm', pdfLineLength(reference.from as number[], reference.to as number[]))!
    expect(scale).toEqual({ unitsPerPt: 50, unit: 'm' })
    expect(formatLength(117.5, scale)).toBe('2.35 m')
    const line = pdfDrawingOperation('p1', 'measure', [[20, 100], [20, 9999]], box, red, { label: formatLength(320, scale) })
    expect(line).toEqual({ kind: 'addDrawing', pageId: 'p1', shape: 'measure', color: red, width: 2, from: [20, 100], to: [20, 420], label: '6.40 m' })
  })

  it('rejects invalid calibrations, non-ASCII or oversized labels and stray fields', () => {
    expect(parseCalibration('0', 'm', 100)).toBeNull()
    expect(parseCalibration('abc', 'm', 100)).toBeNull()
    expect(parseCalibration('1', ' ', 100)).toBeNull()
    expect(parseCalibration('1', 'x'.repeat(13), 100)).toBeNull()
    expect(() => pdfDrawingOperation('p1', 'measure', [[20, 100], [220, 100]], box, red, { label: '2 米' })).toThrow('测量标签')
    expect(() => pdfDrawingOperation('p1', 'measure', [[20, 100], [220, 100]], box, red, { label: 'x'.repeat(65) })).toThrow('测量标签')
    expect(() => pdfDrawingOperation('p1', 'measure', [[20, 100], [20.5, 100]], box, red, { label: '1 m' })).toThrow('测量线太短或超出页面')
    const valid = pdfDrawingOperation('p1', 'measure', [[20, 100], [220, 100]], box, red, { label: '1 m' })
    expect(() => validatePdfDrawing({ ...valid, rect: [0, 0, 1, 1] }, box)).toThrow('绘图参数无效')
    expect(() => validatePdfDrawing({ ...pdfDrawingOperation('p1', 'arrow', [[20, 100], [220, 100]], box, red), label: '1 m' }, box)).toThrow('绘图参数无效')
  })
})

it('refuses unrepresentable measurement scales before committing a label', async()=>{
  const {pdfMeasurementOperation}=await import('./pdf-operations')
  for(const scale of [{unitsPerPt:0,unit:'m'},{unitsPerPt:Infinity,unit:'m'},{unitsPerPt:1e-320,unit:'m'}]) expect(()=>pdfMeasurementOperation('p1',[[20,100],[220,100]],box,red,scale)).toThrow()
})


it.each([
 {referenceUnit:2,targetUnit:1,targetRawLength:100,expected:'1.00 m'},
 {referenceUnit:2,targetUnit:1,targetRawLength:200,expected:'2.00 m'},
 {referenceUnit:2,targetUnit:2,targetRawLength:100,expected:'2.00 m'},
 {referenceUnit:1,targetUnit:2,targetRawLength:100,expected:'4.00 m'},
])('shares a physical-point calibration across UserUnit $referenceUnit → $targetUnit ($targetRawLength raw)',({referenceUnit,targetUnit,targetRawLength,expected})=>{
 const from=[20,100],referenceTo=[120,100],to=[20+targetRawLength,100]
 const calibration=parseCalibration('2','m',pdfLineLength(from,referenceTo,referenceUnit))!
 expect(calibration.unitsPerPt).toBe(100*referenceUnit/2)
 const operation=pdfMeasurementOperation('target',[from,to],box,red,calibration,targetUnit)
 expect(operation.label).toBe(expected)
 expect(operation.from).toEqual(from);expect(operation.to).toEqual(to)
 expect(operation).not.toHaveProperty('userUnit')
})

it.each([0,-1,NaN,Infinity])('refuses unreadable UserUnit %s instead of storing an incorrect label',userUnit=>{
 expect(()=>pdfLineLength([20,100],[120,100],userUnit)).toThrow()
 expect(()=>pdfMeasurementOperation('p',[[20,100],[120,100]],box,red,{unitsPerPt:50,unit:'m'},userUnit)).toThrow()
})

it('keeps the default UserUnit1 API and catches physical-length overflow',()=>{
 expect(pdfLineLength([20,100],[120,100])).toBe(100)
 expect(pdfMeasurementOperation('p',[[20,100],[120,100]],box,red,{unitsPerPt:50,unit:'m'}).label).toBe('2.00 m')
 expect(()=>pdfLineLength([20,100],[120,100],Number.MAX_VALUE)).toThrow()
})
