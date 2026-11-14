# Word HTML / Markdown 导出验收

实现：`src/docx-export.ts`，复用已固定 GenOffice `f8c17004` 上游 `renderer/html-export.ts` 的 `buildStandaloneHtml` 与 `renderer/export-markdown.ts` 的 `documentToMarkdown`；对应原 `file-actions.ts` 的 `exportHtml` / `exportMarkdown`，浏览器侧用 Blob 下载替代 Electron 写盘。

- HTML：独立 `.html`，保留上游计算样式内联和编辑器装饰过滤；图片及 CSS 背景图转换为 data URL，不依赖临时 blob URL。
- Markdown：无图直接 `.md`；有图 `.zip`，包含同名 `.md` 与 `media/imageN.ext`，替换上游 `__genoffice_media__` 占位符，实际打包图片字节。
- 导出读取当前编辑器快照，先 await flush，不修改正文，不覆盖报告已发布文件。失败经 onError 告知，读取失败或上游不支持的 Markdown 图片格式不生成声称完整的文件。HTML 支持的图片类型可更广；Markdown 支持上游 PNG/JPEG/GIF/BMP/WebP/SVG/TIFF。
- 上游 Markdown 转换为受限 GFM；公式、表格、列表、修订处理及复杂对象退化遵循上游，不承诺 DOCX 全保真。HTML 为单个流式文档。本项未实现 PDF、逐页图片、OCR、批注保真或分页像素保真。

接口：

```ts
buildDocxExportArtifact({editor,format:'html'|'markdown',title})
// Promise<{fileName:string,mimeType:string,bytes:Uint8Array}>
createDocxExportControls({editor,container,title,reason?,flush?,onError})
// {run(format):Promise<boolean>, dispose():void}
// title: string | (()=>string)
// reason?: ()=>string|null|undefined
// flush?: ()=>void|Promise<void>
// onError: (error:unknown)=>void
```

实测命令（frontend 目录）：

```sh
npx vitest run src/docx-export.test.ts
FONTCONFIG_FILE=/workspace/sm/smart_reporting/report_editor/frontend/smoke/canvas-fontconfig.conf node smoke/docx-export-smoke.mjs
```

2026-11-14：5 条针对单测通过；真实 Chromium DOM + ProseMirror 生成下载的 HTML / ZIP，通过正文、文件名、相对媒体路径和媒体精确字节验收。测试先 RED（缺模块；不支持图片会静默丢失）后 GREEN。浏览器脚本自启隔离 Vite 临时端口，下载到临时目录，验收后清理。未运行重复完整套件，未修改发布门禁或构建预算。

TypeScript 检查在并行任务窗口遇到 `src/docx-theme.test.ts` 引用尚未创建 `./docx-theme`；导出模块无 TypeScript 诊断，集成完成后由主任务统一校验。
