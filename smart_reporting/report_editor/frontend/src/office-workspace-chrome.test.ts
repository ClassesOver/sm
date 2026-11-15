import {afterEach,expect,it} from 'vitest'
import {configureOfficeWorkspaceChrome} from './office-workspace-chrome'
import {createEditorShell} from './shell'
afterEach(()=>document.body.replaceChildren())
function fixture(){const root=document.body.appendChild(document.createElement('main'));return{root,shell:createEditorShell(root,'full','pdf')}}
it('removes the report toolbar and preserves all four Office ribbons',async()=>{
 const {readFileSync}=await import('node:fs')
 const {root,shell}=fixture(),chrome=configureOfficeWorkspaceChrome(root,shell)
 const style=document.head.appendChild(document.createElement('style'));style.textContent=readFileSync('src/office-workspace-chrome.css','utf8')
 try{
  expect(root.classList.contains('office-ui-theme')).toBe(true)
  expect(getComputedStyle(root.querySelector('.app-bar')!).display).toBe('none')
  for(const name of ['pdf-ribbon','workbook-ribbon','slides-native-ribbon','docx-ribbon']){
   const ribbon=document.createElement('header');ribbon.className=name;shell.editor.append(ribbon)
   expect(getComputedStyle(ribbon).display).not.toBe('none')
  }
  expect(root.querySelector('[data-action=assistant]')).toBeNull()
  expect(shell.save.isConnected).toBe(true)
  chrome.dispose();expect(root.classList.contains('office-workspace-native')).toBe(false)
 }finally{style.remove()}
})
it('keeps exact source token declarations and confines theme selectors to Office UI',async()=>{
 const {readFileSync}=await import('node:fs'),{createHash}=await import('node:crypto')
 const original=readFileSync('packages/office-desktop-ui/src/theme/vendor/tokens.css')
 const metadata=JSON.parse(readFileSync('packages/office-desktop-ui/src/theme/vendor/SOURCE.json','utf8'))
 const scoped=readFileSync('packages/office-desktop-ui/src/theme/vendor/tokens.scoped.css','utf8')
 expect(createHash('sha256').update(original).digest('hex')).toBe(metadata.sha256)
 expect(scoped.match(/--[\w-]+\s*:[^;]+;/g)).toEqual(original.toString().match(/--[\w-]+\s*:[^;]+;/g))
 expect(scoped).not.toMatch(/(?:^|\n)\s*:root[\s{]/)
 expect(scoped).toContain("html[data-office-theme='dark'] :where(.office-ui-theme, #office, .office-admin-page, .editor-account-settings, body > [class*='docx-'][class*='-host'], body > [class*='pdf-'][class*='-host'], body > [class*='workbook-'][class*='-host'], body > [class*='slides-'][class*='-host'])")
})

it('themes owned body portals and settings without token self references',async()=>{
 const {readFileSync}=await import('node:fs')
 const css=readFileSync('packages/office-desktop-ui/src/theme/index.css','utf8'),source=readFileSync('packages/office-desktop-ui/src/theme/vendor/tokens.scoped.css','utf8')
 const styles=document.head.appendChild(document.createElement('style'));styles.textContent=css.replace(/@import[^;]+;/g,'')
 try {
  for(const name of ['docx-native docx-table-properties-source-host','pdf-formdesign-property-host','editor-account-settings']){
   const host=document.body.appendChild(document.createElement('div'));host.className=name
   expect(getComputedStyle(host).getPropertyValue('--office-accent')).toBe('var(--color-brand-secondary)')
   expect(source).toContain(name==='editor-account-settings'?'.editor-account-settings':`[class*='${name.startsWith('docx')?'docx':'pdf'}-'][class*='-host']`)
  }
  expect(css).not.toMatch(/(--[\w-]+)\s*:\s*var\(\1\)/)
  const unrelated=document.body.appendChild(document.createElement('div'))
  expect(getComputedStyle(unrelated).getPropertyValue('--office-accent')).toBe('')
 } finally {styles.remove()}
})
