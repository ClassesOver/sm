import fontAssets from './assets/docx-cjk/metrics.json'
import {setBrowserFontMetrics} from './vendor/genoffice-docs/apps/docs/src/renderer/font-resolve'

/** 只向来源解析器登记浏览器实际加载成功的内置字体；文档嵌入字体仍按来源规则优先。 */
export async function loadDocxBundledFonts(): Promise<void> {
  const loaded = await Promise.all(Object.entries(fontAssets).map(async ([family, asset]) => {
    try {
      const faces = await document.fonts?.load(`16px "${family}"`, '中文ABC')
      return faces?.length ? {family, metrics: asset.metrics, eastAsian: true} : null
    } catch {
      return null
    }
  }))
  setBrowserFontMetrics(loaded.filter((face): face is NonNullable<typeof face> => face !== null))
}
