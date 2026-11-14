// @vitest-environment node
import { beforeEach, expect, it, vi } from 'vitest'
const copy = vi.hoisted(() => ({ cp: vi.fn(), mkdir: vi.fn() }))
vi.mock('node:fs/promises', () => copy)
import config from '../vite.config'

beforeEach(() => vi.clearAllMocks())

it('将 PDF 运行资源和许可证写入实际构建输出目录', async () => {
  const plugin = (config.plugins as unknown as Array<{ name: string; writeBundle(options: { dir: string }): Promise<void> }>)
    .find(item => item.name === 'native-pdf-runtime-assets')!
  const directory = '/tmp/native-editor-isolated-assets'
  await plugin.writeBundle({ dir: directory })
  expect(copy.mkdir.mock.calls.map(([path]) => String(path))).toEqual([`${directory}/licenses`])
  expect(copy.cp.mock.calls.map(([, path]) => String(path))).toEqual([
    `${directory}/licenses/pdfjs-LICENSE`,
    `${directory}/licenses/genoffice-docs-LICENSE`,
    `${directory}/licenses/genoffice-docs-NOTICE`,
    `${directory}/licenses/genoffice-sheets-format-LICENSE`,
    `${directory}/licenses/genoffice-sheets-format-NOTICE`,
    `${directory}/pdfjs/cmaps`,
    `${directory}/pdfjs/standard_fonts`,
    `${directory}/pdfjs/wasm`,
  ])
})
