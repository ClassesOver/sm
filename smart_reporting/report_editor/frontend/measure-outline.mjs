import { chromium } from 'playwright'

const URL = 'http://127.0.0.1:8020/reports/v1/editor/open/gAAAAABqt2gg6IRuii2vZdjbo26N6WH-uhwT3JusqBi7ByCUVvDMCrREEjAYllvS-pQC2xEsGrrEC2YRvIu6WlwZs-ET1iE2U32kEhBlRK-yP_EE9tZrAY9RG8OWPTTkSEZIpJk4VSKCKDmUBeRs96R0Y8R51mhblS6WNYYTpNfcjhtb5khhXZiEuDYaFlQLsgO_A3nuuP1ixcI5HdDzmHVd-Iuec-soApj2gJfCYQfp7cFlXlN-jmMdM7hhyenlBucZs6vvAMb6u3t9BSx5oJ12sf7RUnqse-uKPG29Ev2qfD44PoBAmkisx2hAdMvO_uKhzKzDzlElTSoHZ9Lwj0H0ByQ23lLYY1vyT4-6pxKFNCBvWQi3eW1zVWjIBegFusEP7GdBUF2YKOOCOFFC-irwtkvPdH-t2nZOM4yj6a4duuefTClwCU_YEpA0JUmELniD3-qiUBa'

const browser = await chromium.launch()
// 复用同一 context/cookie：先开一次拿到会话，后续复用同一 page 导航
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await ctx.newPage()
const resp = await page.goto(URL, { waitUntil: 'domcontentloaded' })
console.log('open status:', resp?.status(), '->', page.url().slice(0, 90))
try {
  await page.waitForSelector('.ProseMirror', { timeout: 30000 })
} catch {
  console.log('body:', (await page.locator('body').innerText()).slice(0, 300))
  await browser.close(); process.exit(1)
}
await page.waitForTimeout(2500)
const editorUrl = page.url()
for (const vp of [{width:1600,height:1000},{width:1440,height:900},{width:1366,height:768},{width:1280,height:800}]) {
  await page.setViewportSize(vp)
  await page.evaluate(() => window.scrollTo(0, 4000))
  await page.waitForTimeout(1200)
  const m = await page.evaluate(() => {
    const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect(); return { top: +b.top.toFixed(1), bottom: +b.bottom.toFixed(1), left: +b.left.toFixed(1), h: +b.height.toFixed(1), fontSize: getComputedStyle(el).fontSize, fontWeight: getComputedStyle(el).fontWeight, color: getComputedStyle(el).color } }
    const panel = document.querySelector('.report-outline')
    const heading = panel.querySelector('.outline-heading')
    const list = panel.querySelector('.outline-list')
    const links = Array.from(list.children)
    const active = list.querySelector('[aria-current="location"]')
    const docH1 = document.querySelector('#report-editor h1')
    return {
      panel: r(panel), heading: r(heading), list: r(list),
      first: links[0] ? { ...r(links[0]), cls: links[0].className, text: links[0].textContent.slice(0, 20) } : null,
      active: active ? { ...r(active), text: active.textContent.slice(0, 20), idx: links.indexOf(active) } : null,
      listScrollTop: list.scrollTop,
      docH1: r(docH1),
      headingOverlapsList: heading.getBoundingClientRect().bottom > list.getBoundingClientRect().top + 1,
    }
  })
  console.log(vp.width + 'x' + vp.height, JSON.stringify(m))
  await page.locator('.report-outline').screenshot({ path: `/tmp/panel-${vp.width}.png` })
}
await browser.close()
