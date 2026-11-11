import {expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {normalizeTableAltText} from './docx-table-alt-text-core'
import {projectDocxTableAltText} from './docx-table-alt-text'
const schema=new Schema({nodes:{doc:{content:'docTable'},text:{},p:{},docTable:{content:'p',attrs:{tblCaption:{default:'old'},tblDescription:{default:'old desc'},nativeTableAltText:{default:null},tblAltEdited:{default:false},nativeTableCellWrap:{default:null},indentTwips:{default:-142}}}}})
const source=()=>schema.node('docTable',null,schema.node('p')).toJSON()
const anchor={tableAltTextEditable:true,tableAltTextSource:{title:'old',description:'old desc',rawTitle:'<w:tblCaption w:val="old"/>',rawDescription:'<w:tblDescription w:val="old desc"/>'}}
it('normalizes the complete value pair with explicit length and XML control boundaries',()=>{
 expect(normalizeTableAltText({title:'  标题 & <A>  ',description:'  第一行\r\n第二行\t内容  '})).toEqual({title:'标题 & <A>',description:'第一行\r\n第二行\t内容'})
 expect(normalizeTableAltText({title:'x'.repeat(255),description:'x'.repeat(4096)}).description).toHaveLength(4096)
 for(const value of [{title:'x'.repeat(256),description:''},{title:'',description:'x'.repeat(4097)},{title:'a\nb',description:''},{title:'',description:'bad\0'},{title:'',description:'\ud800'},{title:'',description:'',raw:'x'},{title:null,description:''}])expect(()=>normalizeTableAltText(value)).toThrow()
})
it('projects only title description and final dedicated intent with repeated replacements and empty removal',()=>{
 const first=projectDocxTableAltText(source(),anchor,{title:' new ',description:'line1\nline2'},schema),last=projectDocxTableAltText(first,anchor,{title:'',description:''},schema)
 expect(first.attrs).toEqual({...source().attrs,tblCaption:'new',tblDescription:'line1\nline2',nativeTableAltText:{title:'new',description:'line1\nline2'}})
 expect(last.attrs!.tblCaption).toBeNull();expect(last.attrs!.tblDescription).toBeNull();expect(last.content).toEqual(source().content)
})
it('rejects stale source attributes, protection capability, malformed intent and other native operations',()=>{
 const stale=source();stale.attrs!.tblCaption='forged';expect(()=>projectDocxTableAltText(stale,anchor,{title:'a',description:'b'},schema)).toThrow()
 expect(()=>projectDocxTableAltText(source(),{...anchor,tableAltTextEditable:false},{title:'a',description:'b'},schema)).toThrow()
 const mixed=source();mixed.attrs!.nativeTableCellWrap={steps:[]};expect(()=>projectDocxTableAltText(mixed,anchor,{title:'a',description:'b'},schema)).toThrow()
})
