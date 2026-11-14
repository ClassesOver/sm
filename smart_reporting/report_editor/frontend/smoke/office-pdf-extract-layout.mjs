import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'

// 仅观察真实提取窗口；不替换业务应答或触发额外提取。
export async function inspectExtractLayout(page, dialog, directory, phase, evidence) {
  const check = (value, label) => { if (!value) evidence.failures.push(`${phase}: ${label}`) }
  for (const [width, height] of [[1440,900],[320,640],[640,360],[390,320],[1440,360]]) {
    await page.setViewportSize({ width, height }); await page.evaluate(() => document.fonts.ready)
    const geometry = await dialog.evaluate(node => {
      const r = node.getBoundingClientRect(), header = node.querySelector('header'), footer = node.querySelector('.pdf-layout-actions')
      return { x:r.x, y:r.y, right:r.right, bottom:r.bottom, overflow:node.scrollWidth>node.clientWidth+1,
        header:!!header?.querySelector('h3'), footer:!!footer, busy:node.getAttribute('aria-busy'),
        font:getComputedStyle(node).fontFamily, themeFont:getComputedStyle(node.closest('.native-pdf-editor')).fontFamily,
        namedResults:!!node.querySelector('[aria-label="提取结果"]'), value:node.querySelector('input').value }
    })
    const prefix = `${width}x${height}`
    check(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,`${prefix}窗口边界`)
    check(geometry.header&&geometry.footer&&geometry.namedResults,`${prefix}标题及结果结构`)
    check(geometry.font===geometry.themeFont,`${prefix}主题字体`)
    check(geometry.busy===(phase==='busy'?'true':'false'),`${prefix}繁忙状态`)
    const states = []
    for (const control of await dialog.locator('input,button,a[href]').all()) {
      const disabled = await control.isDisabled(); await control.scrollIntoViewIfNeeded()
      if (!disabled) { await control.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab') }
      const state = await control.evaluate(node => {
        const r=node.getBoundingClientRect(),s=getComputedStyle(node)
        return { label:node.getAttribute('aria-label')||node.textContent, tag:node.tagName, disabled:!!node.disabled,
          focused:node===document.activeElement, height:r.height, font:s.fontFamily,
          ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,
          hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y])=>node.contains(document.elementFromPoint(x,y))) }
      })
      check(state.hit&&(disabled||state.focused&&state.ring),`${prefix} ${state.label}焦点及命中`)
      check(Math.abs(state.height-28)<1&&state.font===geometry.themeFont,`${prefix} ${state.label}紧凑字体`)
      states.push(state)
    }
    const screenshots=[]
    for (const end of ['first','last']) {
      const controls=dialog.locator('input,button,a[href]'); await (end==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded()
      const file=`extract-${phase}-${prefix}-${end}.png`; await page.screenshot({path:join(directory,file)});screenshots.push(file)
    }
    evidence.cases.push({phase,width,height,geometry,states,screenshots})
    await writeFile(join(directory,'extract-layout.json'),JSON.stringify(evidence,null,2))
    console.log(JSON.stringify({phase,width,height,controls:states.length,failures:evidence.failures.length}))
  }
  await page.setViewportSize({width:1440,height:900})
}
