# PDF 安全涂黑验收

2026-11-10。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。这是单项功能闭环，不代表 PDF Ribbon 已全部对齐。

## 固定源行为

- `apps/pdf/src/renderer/App.tsx` Annotate ▸ Draw Tools 有三个命令：涂黑（redact）、清除涂黑、应用涂黑。涂黑只标记待处理区域；应用时先另存副本（`requestRedactionCopy`），再写入。
- `apps/pdf/src/main/redaction.ts` `redactPdf`：用 PDFium 创建 Redact 批注，设置 `/OC` 黑色后执行 `ApplyRedaction`，永久移除区域内的文字、图像和路径。以下情况整体拒绝（fail-closed），不会部分写入：区域内有跨页共享的图像、区域内有表单控件、区域无效。最后以 SaveAsCopy 作为最终序列化，只写出清理后仍可达的对象。
- `save-pdf.ts` 在涂黑前删除受影响页的 `/Thumb` 和 `/PieceInfo`。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | `{kind:'redact', pageId, rect}`，坐标为 PDF user space，向内取整到 0.01pt |
| 前端 | 涂黑工具（拖出区域，草稿中显示为半透明黑块加红框，可撤销、重做、刷新后恢复）。清除涂黑：移除全部待处理标记。应用涂黑：直接保存新修订。不允许在空白草稿页涂黑，也不能与页面尺寸同批修改。区域须在含同批裁切的可见范围内，最多 500 处。 |
| 桥接 | zod 严格校验；涂黑在所有 pdf-lib 处理之后最后执行（裁切、附件、便签回复等都在它之前）。页索引换算到删除和重排后的最终页序；先删除 Thumb/PieceInfo，再调用固定引擎未修改的 `redactPdf`。输出摘要绑定预览确认。 |
| 副本语义 | 原生编辑每次保存都写入新修订，来源修订字节不变，相当于固定源的“先另存副本再涂黑”。 |

## 证据

- `reporting/pdf_engine/bridge/redaction.test.ts` 用 PDFium 回读真实引擎输出，覆盖：
  - 区域内文字被移除，同页其他文字和其他页保留，同批绘图批注保留。
  - 重排、删页后仍作用于正确的页。
  - 拒绝越界、过小、多余字段、已删除页、空白页、与页面尺寸同批，以及同批裁切后落在可见范围外的区域。
- `frontend/src/pdf-redaction.test.ts`：向内取整、排序、各类拒绝，以及 500 处上限。
- `frontend/smoke/pdf-redact-smoke.mjs` 通过 Chromium 与真实 Python→PDF 引擎链路验证，授权和修订路由用 fixture 代替。流程：
  1. 未标记时点“应用涂黑”会出现提示。
  2. 涂黑后点“清除涂黑”，草稿变为空。
  3. 重新涂黑，刷新页面后草稿恢复。
  4. 点“应用涂黑”保存出修订 2，下载的字节与保存的一致。
  5. pypdf 独立回读：第 1 页提取不到 `ACCOUNT-SECRET-4711`，“Public quarterly summary”和第 2 页文字、便签都保留，来源文件摘要不变。
  6. 重开修订 2，仍为 2 页。
  7. 渲染图在原位置显示纯黑块。

本次在开发服务器模式下运行（`PDF_REDACT_SMOKE_PRODUCTION=0`），生产镜像、真实授权和发布链路未在此验收。
