import {expect,it} from 'vitest'
import {paintDrawing} from './pdf-drawing-shapes'
import {pdfToView,viewToPdf} from './genoffice-pdf-annotations'
import type {NativeOperation} from './native-draft'
const ns='http://www.w3.org/2000/svg',base={kind:'addDrawing',pageId:'p',color:[1,0,0],width:2}
// Tm values independently read from the actual pinned writer's AP streams in
// /tmp/pdf-measure-label-bounds-final/independent.json; not an SVG angle formula.
const measures=[
 {name:'horizontal',from:[80,200],to:[240,200],label:'3.00 m',tm:[1,0,0,1,160,206]},
 {name:'diagonal rounded',from:[80.003,80.007],to:[82.991,82.003],label:'W'.repeat(64),tm:[.83,.56,-.56,.83,81.5,87.01]},
 {name:'reverse',from:[280,180],to:[80,180],label:'AV To (gj)\\',tm:[1,0,0,1,180,186]},
 {name:'vertical',from:[100,80],to:[100,280],label:'To AV',tm:[0,1,-1,0,100,186]},
]
function viewport(rotation:number,zoom:number){const g={pw:800,ph:1000,x0:10,y0:20,userUnit:2,rot:rotation};return {width:(rotation%180?1000:800)*zoom,height:(rotation%180?800:1000)*zoom,convertToViewportPoint:(x:number,y:number)=>pdfToView(g,x,y).map(v=>v*zoom),convertToPdfPoint:(x:number,y:number)=>viewToPdf(g,x/zoom,y/zoom)}}
function near(actual:number[],expected:number[]){expect(actual).toHaveLength(expected.length);actual.forEach((v,i)=>expect(v).toBeCloseTo(expected[i]!,8))}
const views=[0,90,180,270].flatMap(rotation=>[.5,2].map(zoom=>({rotation,zoom})))
for(const view of views){
 it.each(measures)('maps actual $name Tm through cropped UserUnit viewport at '+view.rotation+' degrees and '+view.zoom+' zoom',measure=>{
  const group=document.createElementNS(ns,'g'),vp=viewport(view.rotation,view.zoom),op:NativeOperation={...base,shape:'measure',from:measure.from,to:measure.to,label:measure.label},original=structuredClone(op)
  paintDrawing(group,op,vp,view.zoom);expect(op).toEqual(original)
  const label=group.querySelector('[data-pdf-measure-label]')!
  expect(label.getAttribute('text-anchor')).toBe('start');expect(label.getAttribute('font-size')).toBe('9');expect(label.getAttribute('font-family')).toBe('Helvetica, Arial, sans-serif');expect((label as SVGTextElement).style.fontKerning).toBe('none');expect((label as SVGTextElement).style.fontVariantLigatures).toBe('none');expect(label.getAttribute('dominant-baseline')).toBe('alphabetic');expect(label.getAttribute('x')).toBe('0');expect(label.getAttribute('y')).toBe('0');expect(label.textContent).toBe(measure.label)
  const match=/^matrix\(([^)]+)\)$/.exec(label.getAttribute('transform')??'');expect(match).not.toBeNull();const [a,b,c,d,e,f]=match![1]!.split(/[ ,]+/).map(Number),[ta,tb,tc,td,te,tf]=measure.tm
  // Glyph-space y points down in SVG and up in PDF. Check multiple glyph
  // coordinates against the actual native Tm followed by the viewport.
  for(const [x,y] of [[0,0],[9,0],[0,-9],[37.2,2.1]])near([a!*x+c!*y+e!,b!*x+d!*y+f!],vp.convertToViewportPoint(te!+ta!*x-tc!*y,tf!+tb!*x-td!*y))
  const hit=group.querySelector('[data-pdf-shape-hit]')!;expect(hit.tagName).toBe('line');expect(hit.getAttribute('stroke')).toBe('transparent');expect(hit.getAttribute('fill')).toBe('none')
 })
 it('maps native filled caret vertices and retains transparent hit outline at '+view.rotation+' degrees and '+view.zoom+' zoom',()=>{
  const group=document.createElementNS(ns,'g'),vp=viewport(view.rotation,view.zoom),op:NativeOperation={...base,shape:'caret',point:[100.003,150.007]},original=structuredClone(op)
  paintDrawing(group,op,vp,view.zoom);expect(op).toEqual(original)
  const caret=group.querySelector('[data-pdf-drawing="caret"]')!,hit=group.querySelector('[data-pdf-shape-hit]')!,expected=[[100,150.01],[92,144.01],[108,144.01]].flatMap(([x,y])=>vp.convertToViewportPoint(x!,y!))
  expect(caret.getAttribute('fill')).toBe('rgb(255,0,0)');expect(caret.getAttribute('stroke')).toBe('none');expect(caret.getAttribute('d')).toMatch(/ Z$/);near(caret.getAttribute('d')!.match(/-?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi)!.map(Number),expected)
  expect(hit.getAttribute('d')).toBe(caret.getAttribute('d'));expect(hit.getAttribute('fill')).toBe('none');expect(hit.getAttribute('stroke')).toBe('transparent');expect(hit.getAttribute('stroke-width')).toBe('16')
 })
}
it('sets browser kerning and ligature controls as CSS properties rather than ignored SVG attributes',()=>{
 const group=document.createElementNS(ns,'g');paintDrawing(group,{...base,shape:'measure',from:[80,200],to:[240,200],label:'AV To ffi'},viewport(0,1),1)
 const label=group.querySelector<SVGTextElement>('[data-pdf-measure-label]')!
 expect(label.style.fontKerning).toBe('none');expect(label.style.fontVariantLigatures).toBe('none')
})
