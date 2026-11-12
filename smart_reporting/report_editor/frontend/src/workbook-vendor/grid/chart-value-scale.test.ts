import { expect, it } from 'vitest'
import { barValueFraction } from './chart-value-scale'

it('keeps the prior automatic mapping when manual bounds are removed',()=>{
 const manual=barValueFraction([[3,6]],{min:2,max:8,reversed:false})!
 const automatic=barValueFraction([[3,6]])!
 expect(manual(3)).toBeCloseTo(1/6);expect(automatic(3)).toBeCloseTo(0.5);expect(automatic(6)).toBe(1)
})
it('supports a single minimum or maximum without dropping the other automatic endpoint',()=>{
 expect(barValueFraction([[3,6]],{min:2,reversed:false})!(3)).toBeCloseTo(0.25)
 expect(barValueFraction([[3,6]],{max:8,reversed:false})!(3)).toBeCloseTo(0.375)
})
it('expands an automatic endpoint when the fixed bound excludes all data',()=>{
 const above=barValueFraction([[3]],{min:5,reversed:false})!,below=barValueFraction([[3]],{max:-5,reversed:false})!
 expect(above(3)).toBe(0);expect(above(5.5)).toBeCloseTo(0.5)
 expect(below(3)).toBe(1);expect(below(-5.5)).toBeCloseTo(0.5)
})
it('clamps a negative-only range and its off-range zero baseline',()=>{
 const fraction=barValueFraction([[-5,-12]],{min:-8,max:-2,reversed:false})!
 expect(fraction(0)).toBe(1);expect(fraction(-5)).toBeCloseTo(0.5);expect(fraction(-12)).toBe(0)
})
it('preserves finite ratios across overflowing spans and narrowly separated large bounds',()=>{
 expect(barValueFraction([[Number.MAX_VALUE,-Number.MAX_VALUE]])!(0)).toBeCloseTo(0.5)
 const fraction=barValueFraction([[1e16,1e16+2]],{min:1e16,max:1e16+2,reversed:false})!
 expect(fraction(1e16)).toBe(0);expect(fraction(1e16+2)).toBe(1)
})
it.each([{min:5,max:2,reversed:false},{reversed:false,unsupported:'logarithmic' as const}])('declines unsupported scaling %j',scaling=>{
 expect(barValueFraction([[3,6]],scaling)).toBeUndefined()
})
