import { chromium } from 'playwright'

const URL = 'http://127.0.0.1:8020/reports/v1/editor/open/gAAAAABqt2gg6IRuii2vZdjbo26N6WH-uhwT3JusqBi7ByCUVvDMCrREEjAYllvS-pQC2xEsGrrEC2YRvIu6WlwZs-ET1iE2U32kEhBlRK-yP_EE9tZrAY9RG8OWPTTkSEZIpJk4VSKCKDmUBeRs96R0Y8R51mhblS6WNYYTpNfcjhtb5khhXZiEuDYaFlQLsgO_A3nuuP1ixcI5HdDzmHVd-Iuec-soApj2gJfCYQfp7cFlXlN-jmMdM7hhyenlBucZs6vvAMb6u3t9BSx5oJ12sf7RUnqse-uKPG29Ev2qfD44PoBAmkisx2hAdMvO_uKhzKzDzlElTSoHZ9Lwj0H0ByQ23lLYY1vyT4-6pxKFNCBvWQi3eW1zVWjIBegFusEP7GdBUF2YKOOCOFFC-irwtkvPdH-t2nZOM4yj6a4duuefTClwCU_YEpA0JUmELniD3L-qiUBa'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const resp = await page.goto(URL, { waitUntil: 'domcontentloaded' }).catch(e => null)
console.log('status:', resp?.status(), 'url:', page.url())
await page.waitForTimeout(3000)
const hasEditor = await page.locator('.ProseMirror').count()
console.log('editor loaded:', hasEditor > 0)
if (hasEditor > 0) {
  await page.waitForTimeout(2000)
  const info = await page.evaluate(() => {
    const panel = document.querySelector('.report-outline')
    if (!panel) return { error: 'no .report-outline' }
    const dump = (el) => ({
      tag: el.tagName, cls: el.className,
      text: (el.textContent || '').slice(0, 40),
      font: el.tagName === 'BUTTON' ? getComputedStyle(el).fontSize + '/' + getComputedStyle(el).fontWeight : undefined,
      pad: getComputedStyle(el).paddingLeft,
    })
    const kids = Array.from(panel.children).map(dump)
    const list = panel.querySelector('.outline-list')
    const links = list ? Array.from(list.children).slice(0, 6).map(dump) : []
    return { panelClass: panel.className, kids, links, html: panel.innerHTML.slice(0, 600) }
  })
  console.log(JSON.stringify(info, null, 1))
  await page.screenshot({ path: '/tmp/outline-live.png' })
}
await browser.close()
