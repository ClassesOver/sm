import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'
import { createServer } from 'vite'

const output = process.argv[2]
assert(output, '请提供隔离证据输出目录')
await mkdir(output, { recursive: true })
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5214, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage()
  const html = await server.transformIndexHtml('/contrast', `<main id="root"></main><script type="module">
    import React from 'react'; import {createRoot} from 'react-dom/client'; import {Button,ConfigProvider} from 'antd';
    import {managementTheme} from '/management/src/management/styles/tokens.ts';
    createRoot(document.getElementById('root')).render(React.createElement(ConfigProvider,{theme:managementTheme},
      React.createElement(Button,{loading:true},'刷新核验历史')))
    </script>`)
  await page.route('**/contrast', route => route.fulfill({ contentType: 'text/html', body: html }))
  await page.goto('http://127.0.0.1:5214/contrast')
  const button = page.getByRole('button', { name: '刷新核验历史' })
  await button.waitFor(); await page.waitForLoadState('networkidle'); await button.hover()
  await page.addScriptTag({ path: 'node_modules/axe-core/axe.min.js' })
  const result = await page.evaluate(async () => {
    const button = document.querySelector('button')
    return { loading: button.classList.contains('ant-btn-loading'), color: getComputedStyle(button).color,
      opacity: getComputedStyle(button).opacity,
      seriousOrCritical: (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact))
        .map(item => ({ id: item.id, nodes: item.nodes.map(node => ({ target: node.target, summary: node.failureSummary })) })) }
  })
  await page.screenshot({ path: output + '/loading-hover.png' })
  await writeFile(output + '/evidence.json', JSON.stringify(result, null, 2))
  assert(result.loading); assert.deepEqual(result.seriousOrCritical, [])
} finally { await browser.close(); await server.close() }
