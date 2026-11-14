// 旧用例的数据夹具仍可用简短CSV字面量；通过真实表格控件录入，不触碰产品模型。
export async function fillPdfRadioRows(panel,fixture) {
  const values=fixture.split(/\r?\n/).filter(line=>line.trim()).map(line=>line.split(',').map(value=>value.trim()))
  const rows=panel.locator('table[aria-label="单选选项"] tbody tr')
  while(await rows.count()<values.length)await panel.locator('[data-pdf-radio-row-add]').click()
  while(await rows.count()>values.length)await rows.last().locator('[data-radio-remove]').click()
  await panel.locator('[data-pdf-radio-selection-clear]').click()
  for(const[index,[value,x,y,width,height,checked]]of values.entries()){
    const row=rows.nth(index);await row.locator('[data-radio-value]').fill(value)
    for(const [index,value]of [x,y,width,height].entries())await row.locator(`[data-radio-coordinate="${index}"]`).fill(value)
    if(checked==='true')await row.locator('input[type=radio]').check()
  }
}
