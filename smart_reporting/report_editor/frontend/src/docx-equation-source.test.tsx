// @vitest-environment jsdom
import React from 'react'
import {act} from 'react'
import {createRoot} from 'react-dom/client'
import {describe,it,expect,vi} from 'vitest'
import {Editor} from '@tiptap/core'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {NativeDocxEquations,createDocxEquations} from './docx-equations'
import {BUILTIN_EQUATIONS,EquationGallery,EquationModal} from './docx-equation-source'
describe('fixed-source equation family UI',()=>{
 it('renders all eight MathML previews and inserts from gallery through LaTeX intentions',async()=>{
  const source=createDocxEquations({sourceId:'a'.repeat(64),targets:[{targetId:'p',blockIndex:0,paragraphOrdinal:0,container:'body',text:'Original',expectedParagraphSha256:'b'.repeat(64),formulas:[]}]}),editor=new Editor({extensions:[...editorExtensions,NativeDocxEquations],content:source.annotate({type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'Original'}]}]})}),host=document.body.appendChild(document.createElement('div')),root=createRoot(host),picked=vi.fn()
  try{source.controls(editor,()=>[]);editor.commands.setTextSelection(5);await act(async()=>root.render(<EquationGallery editor={editor} onPick={picked} onCustom={()=>{}}/>));expect(BUILTIN_EQUATIONS).toHaveLength(8);expect(host.querySelectorAll('.equation-gallery-item math')).toHaveLength(8);await act(async()=>host.querySelector<HTMLButtonElement>('.equation-gallery-item')!.click());expect(picked).toHaveBeenCalled();expect(editor.state.doc.attrs.nativeEquationOperation.steps[0].latex).toBe(BUILTIN_EQUATIONS[0].latex);expect(editor.state.doc.child(0).textContent).toBe('Orig');expect(editor.state.doc.child(2).textContent).toBe('inal')
  }finally{await act(async()=>root.unmount());editor.destroy();host.remove()}
 })
 it('keeps invalid LaTeX disabled and exposes source inline toggle, preview and cancel',async()=>{
  const editor=new Editor({extensions:editorExtensions}),host=document.body.appendChild(document.createElement('div')),root=createRoot(host),close=vi.fn()
  try{await act(async()=>root.render(<EquationModal editor={editor} onClose={close}/>));expect(host.querySelector('[role=dialog]')).not.toBeNull();expect(host.querySelector('input[type=checkbox]')).not.toBeNull();expect(host.querySelector('.equation-preview-hint')).not.toBeNull();expect(host.querySelector<HTMLButtonElement>('.btn-primary')!.disabled).toBe(true);await act(async()=>host.querySelector<HTMLButtonElement>('.btn-ghost')!.click());expect(close).toHaveBeenCalled()
  }finally{await act(async()=>root.unmount());editor.destroy();host.remove()}
 })
})
