/**
 * 固定源 File ▸ Export Images（renderer/export-render.tsx renderSlidesToImageBase64 + main/export-images.ts
 * buildExportImagePaths + file-actions.ts exportImages）的浏览器移植：
 * - 只导出未隐藏的页，按放映顺序；每页离屏渲染为 Konva 舞台，pixelRatio 2；
 * - PNG 直接取 toDataURL；JPG 先铺白底再按 0.92 质量编码（与固定源相同）；
 * - 文件名 `<名称>-01.png` …，页数 ≥ 100 时补零到 3 位。
 * 桌面版写入用户选择的文件夹；浏览器不能写目录，因此打包为一个 ZIP 下载（宿主等效）。
 * 渲染数据来自当前草稿的 render-tree，因此导出内容包含尚未保存的修改；不写入文件、不产生草稿。
 */
import React from 'react'
import { createRoot } from 'react-dom/client'
import type Konva from 'konva'
import { Layer, Rect, Stage } from 'react-konva'
import type { RenderSlide } from '@genoffice/pptx-render'
import { StaticNode } from './vendor/genoffice/renderer/NodeBody'
import { fillToKonva } from './vendor/genoffice/renderer/konva-adapter'

export const EXPORT_PIXEL_RATIO = 2
export type ExportImageFormat = 'png' | 'jpg'

/** 固定源 buildExportImagePaths 的文件名部分（不含目录）。 */
export function exportImageNames(baseName: string, count: number, ext: ExportImageFormat): string[] {
  const pad = count >= 100 ? 3 : 2
  return Array.from({ length: Math.max(0, count) }, (_, index) => `${baseName}-${String(index + 1).padStart(pad, '0')}.${ext}`)
}

/** 来源文件名去掉扩展名与路径；不能用作文件名的字符替换为下划线。 */
export function exportBaseName(path: string | undefined): string {
  const name = (path ?? '').split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '') ?? ''
  return name.replace(/[\u0000-\u001f<>:"/\\|?*]+/g, '_').trim() || 'slides'
}

/** 预先加载渲染树中的全部内嵌图片，保证首帧即完整（固定源由 ctx.images 提供已加载图片）。 */
async function loadImages(slides: RenderSlide[]): Promise<Map<string, HTMLImageElement>> {
  const urls = new Set<string>()
  const collect = (value: unknown) => {
    if (typeof value === 'string' && value.startsWith('data:image/')) urls.add(value)
    else if (value && typeof value === 'object') for (const child of Object.values(value)) collect(child)
  }
  collect(slides)
  const images = new Map<string, HTMLImageElement>()
  await Promise.all([...urls].map(url => new Promise<void>(resolve => {
    const image = new Image(); images.set(url, image)
    image.onload = () => resolve(); image.onerror = () => resolve(); image.src = url
  })))
  return images
}

export async function renderSlidesToImageBase64(slides: RenderSlide[], opts: { format?: ExportImageFormat; pixelRatio?: number } = {}): Promise<string[]> {
  const format = opts.format ?? 'png', pixelRatio = opts.pixelRatio ?? EXPORT_PIXEL_RATIO
  const images = await loadImages(slides)
  // 离屏容器：放在视口外（display:none 会让 Konva 画布尺寸为 0）
  const container = document.createElement('div')
  container.style.cssText = 'position:fixed;left:-100000px;top:0;pointer-events:none;'
  container.setAttribute('aria-hidden', 'true')
  document.body.append(container)
  const root = createRoot(container)
  const out: string[] = []
  try {
    for (const slide of slides) {
      const stage = await new Promise<Konva.Stage>(resolve => {
        root.render(<Stage width={slide.widthPx} height={slide.heightPx} listening={false} ref={value => { if (value) resolve(value) }}>
          <Layer listening={false}>
            <Rect width={slide.widthPx} height={slide.heightPx} {...fillToKonva(slide.background, slide.widthPx, slide.heightPx, images)} listening={false} />
            {slide.nodes.map(node => <StaticNode key={node.id} node={node} images={images} />)}
          </Layer>
        </Stage>)
      })
      // 等一帧让 Konva 完成 batchDraw 再截取
      await new Promise(resolve => requestAnimationFrame(resolve))
      if (format === 'jpg') {
        const source = stage.toCanvas({ pixelRatio })
        const flat = document.createElement('canvas'); flat.width = source.width; flat.height = source.height
        const context = flat.getContext('2d')
        if (!context) throw new Error('JPEG 导出：无法创建 2D 画布')
        context.fillStyle = '#fff'; context.fillRect(0, 0, flat.width, flat.height); context.drawImage(source, 0, 0)
        out.push(flat.toDataURL('image/jpeg', 0.92).replace(/^data:image\/jpeg;base64,/, ''))
      } else out.push(stage.toDataURL({ mimeType: 'image/png', pixelRatio }).replace(/^data:image\/png;base64,/, ''))
    }
  } finally {
    root.unmount(); container.remove()
  }
  return out
}

/** 打包为 ZIP 并触发下载；返回写入的文件名（供状态提示与测试）。 */
export async function downloadSlideImages(slides: RenderSlide[], baseName: string, format: ExportImageFormat): Promise<string[]> {
  const pages = await renderSlidesToImageBase64(slides, { format })
  const names = exportImageNames(baseName, pages.length, format)
  const { default: JSZip } = await import('jszip')
  const zip = new JSZip()
  names.forEach((name, index) => zip.file(name, pages[index]!, { base64: true }))
  const blob = await zip.generateAsync({ type: 'blob', compression: 'STORE' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob); link.download = `${baseName}-${format === 'jpg' ? 'jpg' : 'png'}.zip`
  document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(link.href), 60_000)
  return names
}
