import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

export async function runPivotControlFieldRenameSmoke({page,base,ready,command,goto,draft,evidence}){
 const names=['OrderDate','Area','Revenue','Qty','ShippedDate']
 const edit=async(ref,value)=>{await goto(ref);await page.keyboard.type(value);await page.keyboard.press('Enter');await delay(700)}
 const copy=async ref=>{
  await goto(ref);await delay(250);const sentinel='copy-'+Date.now();await page.evaluate(value=>navigator.clipboard.writeText(value),sentinel);await page.keyboard.press('Control+c')
  for(let i=0;i<40;i++){const value=await page.evaluate(()=>navigator.clipboard.readText());if(value!==sentinel)return value.trimEnd();await delay(100)}throw Error('复制网格超时: '+ref)
 }
 const check=async(label,expected)=>{
  assert.equal(await copy('Data!A1:E1'),expected.join('\t'))
  await goto('Pivot!A1');await command('Insert','slicer-open')
  const dialog=page.getByRole('dialog',{name:'透视表筛选',exact:true})
  const chooser=dialog.getByLabel('筛选字段',{exact:true});await chooser.selectOption(expected[1])
  assert.equal(await dialog.locator('[data-native-control]').isChecked(),true)
  await dialog.locator('[data-action="cancel"]').click()
  await page.locator('[data-pivot-control="Slicer_P1_F1"]').waitFor({state:'visible'})
  assert.equal(await page.locator('[data-pivot-control]').count(),3)
  assert.equal(await page.locator('[data-pivot-control="Slicer_P1_F1"]').getByLabel('West',{exact:true}).isChecked(),false)
  for(const name of ['Timeline_P1_F0','Timeline_P1_F4'])assert.equal(await page.locator(`[data-pivot-control="${name}"]`).getByLabel('结束日期',{exact:true}).inputValue(),'2026-01-31')
  await page.screenshot({path:join(evidence,label+'.png'),fullPage:true})
 }
 await page.goto(`${base}/reports/v1/native/pivot-protection/1`);await ready()
 const original=['Date','Region','Amount','Qty','Delivery']
 await check('initial-fields',original)
 await edit('Data!G1','manual rename draft')
 await edit('Data!B1','Area');await check('renamed-slicer',[original[0],'Area',...original.slice(2)])
 await command('File','undo');await check('undo-slicer',original)
 await command('File','redo');await edit('Data!A1','OrderDate');await edit('Data!E1','ShippedDate');await edit('Data!C1','Revenue');await check('renamed-timelines',names)
 await edit('Data!A1','FinalOrderDate');await check('consecutive-field',['FinalOrderDate',...names.slice(1)])
 await command('File','undo');await check('undo-consecutive',names)
 const history=await draft();await page.reload();await ready();assert.deepEqual(await draft(),history);assert.equal(await copy('Data!G1'),'manual rename draft');await check('draft-reloaded',names)
 await command('Data','refresh-all');await page.waitForFunction(()=>document.querySelector('.workbook-feedback')?.textContent?.includes('已刷新 1 个透视表'),null,{timeout:60000});await check('refreshed',names)
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent?.includes('已保存修订 2'),null,{timeout:60000})
 const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);await writeFile(join(evidence,'downloaded.xlsx'),await readFile(await download.path()))
 await page.goto(`${base}/reports/v1/native/pivot-protection/2`);await ready();await check('reopened-fields',names)
 return {fields:names,slicer:true,timelines:2,undoRedo:true,consecutiveRename:true,draftReload:true,refresh:true,download:true,reopened:true}
}
