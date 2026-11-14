import { expect, it } from 'vitest'
import { barValueFraction, barValueScale, scatterAxisScale } from './chart-value-scale'

it.each([
 {values:[300,-500],min:-600,max:400,ticks:[-600,-500,-400,-300,-200,-100,0,100,200,300,400]},
 {values:[3,6],min:0,max:7,ticks:[0,1,2,3,4,5,6,7]},
 {values:[-10,-20],min:-22.5,max:0,ticks:[-22.5,-17.5,-12.5,-7.5,-2.5]},
 {values:[0,0],min:0,max:1,ticks:[0,0.2,0.4,0.6,0.8,1]},
 {values:[877],min:0,max:1000,ticks:[0,100,200,300,400,500,600,700,800,900,1000]},
])('uses the pinned source automatic range for $values',({values,min,max,ticks})=>{
 const scale=barValueScale([values])!
 expect(scale.min).toBe(min);expect(scale.max).toBe(max);expect(scale.ticks).toEqual(ticks)
})

it('places reversed ticks on the same mapping as the actual bars',()=>{
 const scale=barValueScale([[3,6]],{min:2,max:8,reversed:true})!
 expect(scale.ticks).toEqual([2,3,4,5,6,7,8])
 expect(scale.fraction(2)).toBe(1);expect(scale.fraction(8)).toBe(0)
})

it('samples a dense saved major unit across the complete domain without an unbounded loop',()=>{
 const scale=barValueScale([[3,6]],{min:0,max:10,majorUnit:0.1,reversed:false})!
 expect(scale.ticks).toEqual([0,1,2,3,4,5,6,7,8,9,10])
 expect(barValueScale([[3,6]],{min:0,max:10,majorUnit:Number.MIN_VALUE,reversed:false})!.ticks).toEqual([0,10])
})

it('keeps automatic extreme and subnormal domains finite with bounded ticks',()=>{
 for(const values of [[Number.MAX_VALUE,-Number.MAX_VALUE],[Number.MIN_VALUE],[-Number.MIN_VALUE]]){
  const scale=barValueScale([values])!
  expect([scale.min,scale.max,...scale.ticks].every(Number.isFinite)).toBe(true)
  expect(scale.max).toBeGreaterThan(scale.min);expect(scale.ticks.length).toBeLessThanOrEqual(12)
  expect(values.map(scale.fraction).every(Number.isFinite)).toBe(true)
 }
})

it('restores the source automatic range and headroom when manual bounds are removed',()=>{
 const manual=barValueFraction([[3,6]],{min:2,max:8,reversed:false})!
 const automatic=barValueFraction([[3,6]])!
 expect(manual(3)).toBeCloseTo(1/6);expect(automatic(3)).toBeCloseTo(3/7);expect(automatic(6)).toBeCloseTo(6/7)
})
it('supports a single minimum or maximum without dropping the other automatic endpoint',()=>{
 expect(barValueFraction([[3,6]],{min:2,reversed:false})!(3)).toBeCloseTo(1/4.5)
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
it('scales a large scatter vector without spreading it into function arguments',()=>{
 const values=Array.from({length:200_000},(_,index)=>index%10_000)
 const scale=scatterAxisScale(values)
 expect(scale.min).toBe(0);expect(scale.max).toBe(10_000)
})
it.each([{min:5,max:2,reversed:false},{reversed:false,unsupported:'logarithmic' as const}])('declines unsupported scaling %j',scaling=>{
 expect(barValueFraction([[3,6]],scaling)).toBeUndefined()
})
