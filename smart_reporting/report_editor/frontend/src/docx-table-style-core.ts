/** Fixed f8c17004 Ribbon TABLE_PRESETS and table-properties look defaults. */
export interface TableStyleLook {firstRow:boolean;lastRow:boolean;firstColumn:boolean;lastColumn:boolean;bandedRows:boolean;bandedColumns:boolean}
export const DEFAULT_TABLE_LOOK:TableStyleLook={firstRow:true,lastRow:false,firstColumn:true,lastColumn:false,bandedRows:true,bandedColumns:false}
export const TABLE_STYLE_PRESETS={
 'grid':{headerFill:null,band1Fill:null,band2Fill:null,borderColor:'808080'},
 'blue-header':{headerFill:'D9EAF7',band1Fill:null,band2Fill:null,borderColor:'5B9BD5'},
 'blue-banded':{headerFill:'BDD7EE',band1Fill:'DDEBF7',band2Fill:'FFFFFF',borderColor:'9DC3E6'},
 'gray-banded':{headerFill:'D9E1F2',band1Fill:'E7E6E6',band2Fill:'FFFFFF',borderColor:'A5A5A5'},
 'green-header':{headerFill:'E2F0D9',band1Fill:null,band2Fill:null,borderColor:'70AD47'},
} as const
export type TableStyleChoice={kind:'none'}|{kind:'preset';id:keyof typeof TABLE_STYLE_PRESETS}|{kind:'document';styleId:string}
export interface TableStylePatch {style?:TableStyleChoice;look?:TableStyleLook;preset?:keyof typeof TABLE_STYLE_PRESETS}
export interface TableStyleSource {styleId:string|null;look:TableStyleLook}
export interface TableStyleOption {styleId:string;name:string}
function fail():never{throw Error('docx_table_style_invalid')}
function record(value:unknown):Record<string,unknown>{if(!value||typeof value!=='object'||Array.isArray(value)||Object.getPrototypeOf(value)!==Object.prototype)fail();return value as Record<string,unknown>}
function keys(value:Record<string,unknown>,allowed:string[]){if(Object.keys(value).some(k=>!allowed.includes(k)))fail()}
export function normalizeTableStylePatch(input:unknown):TableStylePatch {
 const value=record(input);keys(value,['style','look','preset']);if(!Object.keys(value).length)fail()
 const result:TableStylePatch={}
 if(Object.hasOwn(value,'preset')){if(typeof value.preset!=='string'||!Object.hasOwn(TABLE_STYLE_PRESETS,value.preset))fail();result.preset=value.preset as keyof typeof TABLE_STYLE_PRESETS}
 if(Object.hasOwn(value,'style')){const style=record(value.style)
  if(style.kind==='none'){keys(style,['kind']);result.style={kind:'none'}}
  else if(style.kind==='preset'){keys(style,['kind','id']);if(typeof style.id!=='string'||!Object.hasOwn(TABLE_STYLE_PRESETS,style.id))fail();result.style={kind:'preset',id:style.id as keyof typeof TABLE_STYLE_PRESETS}}
  else if(style.kind==='document'){keys(style,['kind','styleId']);if(typeof style.styleId!=='string'||!style.styleId.length||style.styleId.length>512||/[\x00-\x1f]/.test(style.styleId))fail();result.style={kind:'document',styleId:style.styleId}}
  else fail()
 }
 if(Object.hasOwn(value,'look')){const look=record(value.look),names=Object.keys(DEFAULT_TABLE_LOOK);keys(look,names);if(names.some(k=>typeof look[k]!=='boolean'))fail();result.look=Object.fromEntries(names.map(k=>[k,look[k]])) as unknown as TableStyleLook}
 if(result.style?.kind==='preset'&&result.preset&&result.style.id!==result.preset)fail()
 return result
}
export function tablePresetCell(id:keyof typeof TABLE_STYLE_PRESETS,rowIndex:number){
 const preset=TABLE_STYLE_PRESETS[id],border={style:'single',szEighths:4,color:preset.borderColor}
 return{fill:rowIndex===0?preset.headerFill:rowIndex%2===0?preset.band2Fill:preset.band1Fill,borders:{top:border,right:border,bottom:border,left:border}}
}
