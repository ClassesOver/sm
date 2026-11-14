import assert from 'node:assert/strict'
export async function inspectDocxBodyViewport(page) {
  const editor=page.locator('.tiptap'),target=editor.getByText('目录前言',{exact:true}),scroll=page.locator('.docx-native .editor-scroll'),tools=page.locator('.docx-native .docx-tools')
  const docBefore=await editor.evaluate(node=>JSON.stringify(node.editor.getJSON()))
  await target.click()
  await page.keyboard.press('Home')
  await page.keyboard.press('Shift+ArrowRight')
  await page.waitForFunction(()=>{const e=document.querySelector('.tiptap').editor;return e.state.selection.to-e.state.selection.from===1})
  const selection=await editor.evaluate(node=>({text:window.getSelection()?.toString(),from:node.editor.state.selection.from,to:node.editor.state.selection.to,parent:node.editor.state.selection.$from.parent.textContent}))
  assert.equal(selection.text,'目');assert.equal(selection.to-selection.from,1);assert.equal(selection.parent,'目录前言')
  const targetHit=await target.evaluate(node=>{const r=node.getBoundingClientRect(),n=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return node===n||node.contains(n)})
  assert.equal(targetHit,true)
  const box=await scroll.boundingBox();assert.ok(box.height>=48)
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2)
  const beforeWheel=await scroll.evaluate(node=>node.scrollTop);await page.mouse.wheel(0,240);await page.waitForTimeout(150);const down=await scroll.evaluate(node=>node.scrollTop);assert.ok(down>beforeWheel)
  await page.mouse.wheel(0,-240);await page.waitForTimeout(150);const up=await scroll.evaluate(node=>node.scrollTop);assert.ok(up<down)
  await target.click();await page.keyboard.press('Control+End');await page.waitForTimeout(80);const end=await scroll.evaluate(node=>node.scrollTop),endPosition=await editor.evaluate(node=>node.editor.state.selection.from);await page.keyboard.press('Control+Home');await page.waitForTimeout(80);const home=await scroll.evaluate(node=>node.scrollTop),homePosition=await editor.evaluate(node=>node.editor.state.selection.from);assert.ok(endPosition>homePosition);assert.ok(end>=home)
  const references=page.locator('[data-tab-id=references]');await references.focus();const keyboard=[]
  for(let i=0;i<16;i++){
    await page.keyboard.press('Tab')
    const state=await tools.evaluate(node=>{const focused=document.activeElement;if(!node.contains(focused))return{inside:false};const r=focused.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return{inside:true,action:focused.getAttribute('data-action')??focused.getAttribute('data-note-action')??focused.getAttribute('aria-label'),hit:focused===hit||focused.contains(hit),tag:focused.tagName,scrollTop:node.scrollTop}})
    if(!state.inside)break
    assert.equal(state.hit,true,JSON.stringify(state));keyboard.push(state)
    if(state.action==='已有脚注和尾注')break
  }
  assert.ok(keyboard.some(state=>state.action==='caption-insert'));assert.ok(keyboard.some(state=>state.action==='insert-endnote'));assert.ok(keyboard.some(state=>state.action==='已有脚注和尾注'))
  const toolsScrolled=await tools.evaluate(node=>({top:node.scrollTop,overflow:node.scrollHeight>node.clientHeight}))
  if(toolsScrolled.overflow)assert.ok(toolsScrolled.top>0)
  await target.click();await page.keyboard.press('Home');await page.locator('[data-action=caption-insert]').click();const dialog=page.getByRole('dialog',{name:'插入题注',exact:true});await dialog.waitFor();assert.equal(await dialog.locator('[data-caption-confirm]').isEnabled(),true);await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'})
  assert.equal(await editor.evaluate(node=>JSON.stringify(node.editor.getJSON())),docBefore)
  return{selection,targetHit,bodyHeight:box.height,wheel:{before:beforeWheel,down,up},keyboardScroll:{end,home,endPosition,homePosition},ribbonKeyboard:keyboard,toolsScrolled,captionOpened:true,bodyUnchanged:true}
}
