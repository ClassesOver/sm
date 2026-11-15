import {expect,it} from 'vitest'
import {readFileSync,readdirSync,statSync,existsSync} from 'node:fs'
import {join,resolve,relative} from 'node:path'
const root='packages/office-desktop-ui'
it('ships independent desktop UI entries without importing host business code',()=>{
 const pkg=JSON.parse(readFileSync(join(root,'package.json'),'utf8'))
 expect(pkg.name).toBe('@smart-reporting/office-desktop-ui')
 for(const app of ['theme','docs','sheets','slides','pdf'])expect(existsSync(join(root,pkg.exports[`./${app}.css`]))).toBe(true)
 function inspect(directory:string){for(const name of readdirSync(directory)){
  const file=join(directory,name)
  if(statSync(file).isDirectory())inspect(file)
  else if(/\.(ts|tsx)$/.test(name)&&!file.includes('/vendor/')&&!/\.test\.tsx?$/.test(name)){
   const source=readFileSync(file,'utf8')
   expect(source).not.toMatch(/(?:from\s*|import\s*\()['"](?:electron|.*native-api|.*native-draft|.*report_editor)/)
   for(const match of source.matchAll(/(?:from\s*|import\s*\()['"]([^'"]+)/g)){
    if(match[1].startsWith('.'))expect(relative(resolve(root),resolve(directory,match[1])).startsWith('..')).toBe(false)
   }
  }
 }}
 inspect(join(root,'src'))
})

it('uses the host theme preference for desktop app accent switches',()=>{
 const previous=document.documentElement.getAttribute('data-office-theme')
 const style=document.head.appendChild(document.createElement('style'))
 style.textContent=readFileSync(join(root,'src/docs/ribbon.css'),'utf8')+'\n'+readFileSync(join(root,'src/theme/app-accents.css'),'utf8')
 const host=document.body.appendChild(document.createElement('section'))
 host.className='office-ui-theme';host.innerHTML='<div class="docx-native"><div class="docx-ribbon"></div></div><div class="pdf-ribbon"></div><div class="slides-native-ribbon"></div><div class="workbook-ribbon"></div>'
 try {
  document.documentElement.setAttribute('data-office-theme','dark')
  expect(getComputedStyle(host.querySelector('.docx-ribbon')!).getPropertyValue('--word-blue')).toBe('#4a9eff')
  expect(getComputedStyle(host.querySelector('.pdf-ribbon')!).getPropertyValue('--accent')).toBe('#e8663f')
  expect(getComputedStyle(host.querySelector('.workbook-ribbon')!).getPropertyValue('--accent')).toBe('#34a853')
  document.documentElement.setAttribute('data-office-theme','light')
  expect(getComputedStyle(host.querySelector('.docx-ribbon')!).getPropertyValue('--word-blue')).toBe('#185abd')
  expect(getComputedStyle(host.querySelector('.pdf-ribbon')!).getPropertyValue('--accent')).toBe('#c43e1c')
  expect(style.textContent).not.toMatch(/\[data-theme=/)
 } finally {style.remove();host.remove();if(previous===null)document.documentElement.removeAttribute('data-office-theme');else document.documentElement.setAttribute('data-office-theme',previous)}
})
