import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import {afterEach,expect,it} from 'vitest'
import {Editor} from '@tiptap/core'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {normalizeDocxColumnWidthSources} from './docx-table-column-width'
import {normalizeDocxAutoFitSources} from './docx-table-autofit'
import {createDocxEquations} from './docx-equations'
import {replayDocxTrackedChanges} from './docx-tracked-changes'
import type {DocxAnchor,DocxPmNode} from './docx-operations'

// 提取真实入口的三处程序性安装，保留原生修订插件，不用替代实现遮蔽启动/恢复问题。
const source=ts.createSourceFile('docx-main.tsx',readFileSync('src/docx-main.tsx','utf8'),ts.ScriptTarget.Latest,true)
const statements:string[]=[]
const visit=(node:ts.Node)=>{
 if(ts.isExpressionStatement(node)&&node.getText(source).startsWith('editor.chain()')&&node.getText(source).includes('.setContent('))statements.push(node.getText(source))
 ts.forEachChild(node,visit)
}
visit(source)
if(statements.length!==3)throw new Error('main programmatic content installations not found')
const execute=(index:number,scope:Record<string,unknown>)=>vm.runInNewContext(ts.transpileModule(statements[index],{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,scope)
const editors:Editor[]=[]
afterEach(()=>editors.splice(0).forEach(editor=>editor.destroy()))
function setup(){
 const editor=new Editor({extensions:editorExtensions,editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[
  {type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'前置不变'}]},
  {type:'docParagraph',attrs:{docxIndex:1},content:[{type:'text',text:'开头😀｜中间保留｜待删中文😀｜结尾'}]},
  {type:'docParagraph',attrs:{docxIndex:2},content:[{type:'text',text:'末尾不变'}]},
 ]}})
 editors.push(editor)
 const baseline=editor.getJSON() as DocxPmNode
 const anchors:DocxAnchor[]=[0,1,2].map(docxIndex=>({docxIndex,blockId:`p-${docxIndex}`,expectedObjectSha256:`sha-${docxIndex}`,editable:true}))
 editor.storage.trackChanges.enabled=true;editor.storage.trackChanges.author='user'
 const scope={editor,anchors,normalizeDocxColumnWidthSources,normalizeDocxAutoFitSources,equationSource:createDocxEquations(undefined)}
 const operations=[{kind:'recordTextRevision',blockId:'p-1',expectedObjectSha256:'sha-1',from:4,to:4,text:'新增中文😀'},{kind:'recordTextRevision',blockId:'p-1',expectedObjectSha256:'sha-1',from:10,to:16,text:''}]
 return {editor,baseline,anchors,scope,operations}
}
const summary=(editor:Editor)=>(editor.getJSON() as DocxPmNode).content?.map(node=>({index:node.attrs?.docxIndex,text:node.content?.map(n=>n.text??'').join(''),marks:node.content?.flatMap(n=>n.marks?.map(m=>m.type)??[])}))
for(const index of [0,1])it(`main initialization ${index} keeps clean source identities when tracked changes are enabled`,()=>{
 const f=setup()
 execute(index,f.scope)
 console.info('initialization',index,JSON.stringify(summary(f.editor)))
 expect(f.editor.getJSON()).toEqual(f.baseline)
 const restored=replayDocxTrackedChanges(f.editor.getJSON() as DocxPmNode,f.operations,f.anchors,f.editor.schema,'user',null)
 expect(restored.content).toHaveLength(3)
})
it('main recovery installs a tracked draft exactly without recording the installation as another edit',()=>{
 const f=setup(),expected=f.editor.schema.nodeFromJSON(replayDocxTrackedChanges(f.baseline,f.operations,f.anchors,f.editor.schema,'user',null))
 execute(2,{...f.scope,expected})
 console.info('recovery',JSON.stringify(summary(f.editor)))
 expect(f.editor.state.doc.eq(expected)).toBe(true)
 expect(f.editor.getJSON().content?.map(node=>node.attrs?.docxIndex)).toEqual([0,1,2])
 const runs=(f.editor.getJSON() as DocxPmNode).content![1].content!
 expect(runs.filter(node=>node.marks?.some(mark=>mark.type==='ins')).map(node=>node.text).join('')).toBe('新增中文😀')
 expect(runs.filter(node=>node.marks?.some(mark=>mark.type==='del')).map(node=>node.text).join('')).toBe('待删中文😀')
 expect(f.editor.storage.trackChanges.enabled).toBe(true)
 f.editor.commands.insertContentAt(2,'继续')
 const continued=(f.editor.getJSON() as DocxPmNode).content![0].content!
 expect(continued.filter(node=>node.marks?.some(mark=>mark.type==='ins')).map(node=>node.text).join('')).toBe('继续')
 expect(f.editor.getJSON().content?.map(node=>node.attrs?.docxIndex)).toEqual([0,1,2])
})
