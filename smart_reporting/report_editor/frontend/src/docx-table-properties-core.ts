/** 五页签共享受控协议；坐标均为来源表格逻辑网格，尺寸单位 twip。 */
export interface PropertyMargins { top: number; right: number; bottom: number; left: number }
export interface TablePropertiesPatch {
 table?: { autoFit?: 'contents'|'window'|'fixed'; align?: 'left'|'center'|'right'; wrap?: 'none'|'left'|'right'; xTwips?: number; yTwips?: number; distanceTwips?: number; margins?: PropertyMargins }
 rows?: Array<{index:number;heightTwips?:number|null;heightRule?:'atLeast'|'exact'|null;cantSplit?:boolean;repeatHeader?:boolean}>
 widthsTwips?: number[]
 cells?: Array<{row:number;column:number;vAlign?:'top'|'center'|'bottom';noWrap?:boolean;margins?:PropertyMargins|null}>
 alt?:{title:string;description:string}
}
const fail=():never=>{throw new Error('docx_table_properties_invalid')}
const object=(v:unknown,allowed:string[]):Record<string,any>=>{if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).some(k=>!allowed.includes(k)))fail();return v as Record<string,any>}
const integer=(v:unknown,min:number,max:number)=>{if(typeof v!=='number'||!Number.isSafeInteger(v)||v<min||v>max)fail()}
const margins=(v:unknown)=>{const m=object(v,['top','right','bottom','left']);if(Object.keys(m).length!==4)fail();Object.values(m).forEach(n=>integer(n,0,28350))}
const enumOf=(v:unknown,values:unknown[])=>{if(!values.includes(v))fail()}
export function normalizeTablePropertiesPatch(value:unknown):TablePropertiesPatch{
 const p=object(value,['table','rows','widthsTwips','cells','alt']);if(!Object.keys(p).length)fail()
 if(p.table!==undefined){const t=object(p.table,['autoFit','align','wrap','xTwips','yTwips','distanceTwips','margins']);if(!Object.keys(t).length)fail();if(t.autoFit!==undefined)enumOf(t.autoFit,['contents','window','fixed']);if(t.align!==undefined)enumOf(t.align,['left','center','right']);if(t.wrap!==undefined)enumOf(t.wrap,['none','left','right']);for(const k of ['xTwips','yTwips'])if(t[k]!==undefined)integer(t[k],-28350,28350);if(t.distanceTwips!==undefined)integer(t.distanceTwips,0,28350);if(t.margins!==undefined)margins(t.margins);if(['xTwips','yTwips','distanceTwips'].some(k=>t[k]!==undefined)&&t.wrap===undefined)fail()}
 if(p.widthsTwips!==undefined){if(!Array.isArray(p.widthsTwips)||!p.widthsTwips.length||p.widthsTwips.length>200)fail();p.widthsTwips.forEach((n:unknown)=>integer(n,600,31680))}
 if(p.rows!==undefined){if(!Array.isArray(p.rows)||!p.rows.length||p.rows.length>1000)fail();const seen=new Set();for(const value of p.rows){const r=object(value,['index','heightTwips','heightRule','cantSplit','repeatHeader']);integer(r.index,0,999);if(seen.has(r.index)||Object.keys(r).length<2)fail();seen.add(r.index);if(r.heightTwips!==undefined&&r.heightTwips!==null)integer(r.heightTwips,1,28350);if(r.heightRule!==undefined)enumOf(r.heightRule,['atLeast','exact',null]);if((r.heightTwips===null)!==(r.heightRule===null)||r.heightTwips!==undefined&&r.heightRule===undefined||r.heightRule!==undefined&&r.heightTwips===undefined)fail();for(const k of ['cantSplit','repeatHeader'])if(r[k]!==undefined&&typeof r[k]!=='boolean')fail();if(r.repeatHeader!==undefined&&r.index!==0)fail()}}
 if(p.cells!==undefined){if(!Array.isArray(p.cells)||!p.cells.length||p.cells.length>10000)fail();const seen=new Set();for(const value of p.cells){const c=object(value,['row','column','vAlign','noWrap','margins']);integer(c.row,0,999);integer(c.column,0,199);const key=c.row+':'+c.column;if(seen.has(key)||Object.keys(c).length<3)fail();seen.add(key);if(c.vAlign!==undefined)enumOf(c.vAlign,['top','center','bottom']);if(c.noWrap!==undefined&&typeof c.noWrap!=='boolean')fail();if(c.margins!==undefined&&c.margins!==null)margins(c.margins)}}
 if(p.alt!==undefined){const a=object(p.alt,['title','description']);for(const k of ['title','description']){const s=a[k];if(typeof s!=='string'||s.length>(k==='title'?255:4096)||/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(s)||k==='title'&&/[\r\n]/.test(s))fail()}}
 return structuredClone(p) as TablePropertiesPatch
}
