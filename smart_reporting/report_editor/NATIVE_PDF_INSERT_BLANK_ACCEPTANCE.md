# PDF 插入空白页验收

2026-11-09。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。单项命令闭环，不代表 PDF Ribbon 全功能对齐。

## 固定源行为

- `apps/pdf/src/renderer/App.tsx` `insertBlankPage(afterOrigIdx)`：在当前页之后插入空白页，尺寸取相邻页的**显示尺寸**
  （`geomDispSize`，旋转 90°/270° 时宽高交换），无可用页面时为 A4 `595.28 × 841.89`；作为待保存修改立即可见、可移动、可撤销，保存时写入。
- `apps/pdf/src/main/save-pdf.ts` `appendBlankPages`：空白页在任何按页寻址的阶段之前追加为原始索引 `pageCount + k`，
  `pageOrder` 再把它放到目标位置。本地引擎副本已含同一实现，未新增 PDF 写入器。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | `{kind:'insertBlankPage', pageId:'blank:<uuid>', width, height}` + 一条完整 `reorderPages`；空白页只有本地草稿身份 |
| 前端状态 | `pdfPageState` 按插入顺序给空白页分配索引 `来源页数 + k`（与引擎一致）；`insertBlankPdfPage` / `deletePdfPage`（删除空白页即撤回插入，不产生 `deletePage`）/ 移动 / 反序 / 全部旋转 |
| 渲染 | 草稿空白页由前端生成最小单页 PDF（仅 MediaBox）交给 PDF.js，所有渲染/缩略图/文字层路径保持统一；页签显示“新插入的空白页，保存后写入” |
| 桥接 | `bridge/operations.ts` 校验身份格式、尺寸 1–14400pt、去重、≤200 张、排序必须完整包含保留页与空白页，转换为引擎 `blankPages`；空白页只接受旋转 |
| 边界 | 空白页保存重开前不接受裁切、标注、便签、改字（前端禁用裁切并给出原因，桥接拒绝）；全部裁切只作用于来源页 |

## 证据

- `reporting/pdf_engine/bridge/blank-pages.test.ts`（真实引擎输出字节）：两张空白页排序/尺寸/旋转、无内容流、来源页内容与批注保留、回读页数；无重排时追加到末尾且与删页组合；拒绝空白页裁切/高亮/删除、重复身份、零尺寸、非法身份、多余字段、不完整排序、未声明空白页的排序。
- `frontend/src/pdf-blank-page.test.ts`：位置与显示尺寸（含 90° 页宽高交换）、首页前插入、索引与引擎一致、移动/反序/全部旋转/删除撤回、来源绑定修改被拒、全部裁切跳过空白页、最小 PDF 的 xref 偏移正确。
- `frontend/smoke/pdf-insert-blank-smoke.mjs`（Chromium + 真实 Python→PDF 引擎链路，授权/修订路由为 fixture）：Ribbon 点击插入 → 5 页可见且第 2 页为空白页 → 空白页裁切禁用、可旋转 → 撤销/重做 → 刷新后草稿恢复 → 保存修订 2 → 下载字节与保存一致 → pypdf 独立回读 `[[612,792],[588,744,旋转90,无内容流],…]`、来源页批注仍在 → 重开修订 2 为 5 页。来源文件摘要不变。

本次在开发服务器模式运行（`PDF_BLANK_SMOKE_PRODUCTION=0`）；生产镜像、真实授权与发布链路未在此验收。
