import {expect,it} from 'vitest'
import {scopeDocxStyleRules} from './docx-style-scope'
it('gives source document rules the same host scope as static rules without changing font-face or media semantics',()=>{
 const style=document.createElement('style')
 style.textContent="@font-face {font-family:'Fixture';src:url(data:font/woff2;base64,AAAA)} .doc-page p, .doc-page :is(h1,h2) {margin-bottom:10pt} @media screen {.page-dark .doc-page p {color:red}}"
 document.head.append(style)
 try{
  const fontRule=style.sheet!.cssRules[0].cssText
  scopeDocxStyleRules(style.sheet!)
  const rules=[...style.sheet!.cssRules]
  expect((rules[1] as CSSStyleRule).selectorText).toBe('.docx-native .doc-page p, .docx-native .doc-page :is(h1, h2)')
  expect((rules[2] as CSSMediaRule).conditionText).toBe('screen')
  expect(((rules[2] as CSSMediaRule).cssRules[0] as CSSStyleRule).selectorText).toBe('.page-dark .docx-native .doc-page p')
  expect(rules[0].cssText).toBe(fontRule)
 }finally{style.remove()}
})
