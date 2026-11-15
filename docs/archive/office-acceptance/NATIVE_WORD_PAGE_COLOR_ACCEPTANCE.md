# Word 设计 ▸ 页面颜色验收

2026-11-12。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这一项命令闭环，不代表 Word 功能区已全部对齐。

## 固定源行为

- `apps/docs/src/renderer/components/ribbon-design-tab.tsx`：设计 ▸ 页面背景 ▸ 页面颜色，打开 `RibbonColorPalette`（主题色 10 个 + 标准色 10 个，以及“无颜色”）；选择后 `onPageColor(hex | null)`。
- `App.tsx`：页面颜色记入文档状态并标脏，编辑区纸面以 `--page-bg` 显示。
- 保存时引擎 `SaveOptions.pageColor`（`packages/docx-engine/src/patch.ts`）：
  - 设置颜色：在 `w:document` 首位写一个 `<w:background w:color="RRGGBB"/>`，并在 settings 中写 `<w:displayBackgroundShape/>`（Word 只在此开关存在时显示背景）。
  - `null`：移除背景。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | 文档级 `{kind:'setPageColor', expectedBackgroundSha256, color}`；`color` 为 6 位大写十六进制或 `null` |
| 检查 | inspect 返回 `pageColor: {color, editable, readOnlyReason, expectedBackgroundSha256}`，摘要取来源 `w:background` 原文（无则为空串）。可编辑的来源只有两种：没有背景，或单个纯色 `w:color` 背景。以下情况保持只读：主题色属性、VML 图片或渐变填充、`auto`、多个背景、文档受保护——引擎改写时会丢失原有效果。 |
| 桥接 | `bridge/docx-page-color.ts`。整批先验：至多一条、来源可编辑、摘要一致、颜色合法且与当前值不同。通过后把 `pageColor` 交给固定引擎未改动的 `saveDocx`，写后再从输出的 document.xml 与 settings.xml 独立回读核对。可与正文修改同批；与书签、题注等需单独保存的批次混用时，沿用既有的整批拒绝。 |
| 前端 | 设计 ▸ 页面颜色按钮带当前色条，色板与单元格底纹共用同一组固定源颜色，另有“无颜色”。弹层沿用固定源 `.color-palette` 的锚定定位。修改记入原生事务历史，可撤销、重做；选回来源值即撤回修改；刷新后从草稿恢复。纸面以 `--page-bg` 预览。只读来源或文档不可编辑时，按钮禁用并在提示中写明原因。 |
| Python | `reporting/delivery/docx_native.py` 的操作白名单加入 `setPageColor`。 |

## 证据

- **桥接测试** `reporting/doc_engine/bridge/tests/docx-page-color.test.ts`（4 项通过）：
  - 各类来源的分类：无背景、纯色、主题色、VML、`auto`、重复、受保护。
  - 校验：批次冲突、颜色格式、多余字段、摘要过期、与当前值相同。
  - 真实 CLI 链路依次完成设置、改色（与段落改字同批）、移除；正文 `w:body` 字节不变。
  - 只读来源、摘要过期、与题注混批都被拒绝，且不产生输出文件。
- **Python 测试** `reporting/tests/test_docx_native_page_color.py`（6 项通过）：
  - 经 Python→Node 链路设置后，用 python-docx 与 lxml 独立回读，背景与 `displayBackgroundShape` 正确。
  - 变化的部件只有 document.xml、settings.xml，以及引擎主保存路径照常更新的 `docProps/core.xml`（`cp:revision`、`dcterms:modified`）。
  - 移除后背景消失；5 类非法或过期请求被拒绝。
- **前端测试** `frontend/src/docx-page-color.test.ts`（6 项通过）：
  - 模型校验；设置、替换、撤回；能通过原生历史的筛选。
  - 只读来源与过期草稿被拒绝；恢复重放时把它当作文档级操作。
  - 功能区按固定源顺序列出 20 色加“无颜色”，回显当前值；禁用时显示原因。
- **浏览器冒烟** `frontend/smoke/docx-page-color-gui-smoke.mjs`（Chromium，开发服务器模式，真实 Python→Node 引擎；授权与修订路由为 fixture）依次验证：
  1. 来源无页面颜色，纸面为白色。
  2. 选 `FFC000` 后纸面变黄，草稿中有一条 `setPageColor`。
  3. 撤销后恢复白色且草稿为空，重做后再次变黄。
  4. 改为 `0E2841` 后纸面变深，提示显示 `#0E2841`。
  5. 选“无颜色”（即来源值）撤回修改，再设回深色。
  6. 刷新后草稿恢复。
  7. 保存为修订 2，下载字节与保存一致。
  8. 独立 ZIP/lxml 回读：背景为 `0E2841`、`displayBackgroundShape` 存在、`w:body` 逐字节相同、正文与页眉文字不变，变化部件只有上述三个。
  9. 重开修订 2，纸面为深色，草稿为空，无页面错误。
- **渲染**：LibreOffice 把下载件转成 PDF 后渲染，整页为 `#0E2841` 背景。
- **冒烟发现并已修复的两个问题**：
  - 草稿恢复重放时未把 `setPageColor` 视为文档级操作，打开时报“草稿对象不属于当前 Word 文件”。
  - 色板的绝对定位覆盖了固定源的锚定定位，导致弹层被功能区标签栏遮挡。
- **回归**：
  - Word 前端 125 个测试文件中，本次改动前后的失败集合完全相同，都是上游已有问题：`docx-ribbon` 行距用例、`docx-text-revisions-main-collector` 4 项、`docx-body-decorations` 1 项、`docx-footnote-pagination` 文件。已用暂存改动后在原代码上复跑确认。
  - 相关的书签、引用、目录 Python 测试和桥接测试通过。
  - 前端类型检查只剩上游已有的 `pdf-form-canvas.test.ts`、`slides-main.test.ts` 错误。

## 与固定源的差异

- **色板**：只提供固定源色板的主题色首行和 10 个标准色，不含主题色的明暗阶梯与“更多颜色”自定义取色。
- **深色背景上的文字**：编辑区预览不会把“自动”颜色的文字切成浅色。固定源编辑区同样只设 `--page-bg`；Word 和 LibreOffice 打开文件时会自动切换。
- **复杂背景只读**：主题色、图片、渐变或受保护来源的页面背景保持只读并说明原因。固定源会直接改写为纯色。

## 未验收范围

- 生产构建（vite preview）、真实授权、发布链路。
- 在 Microsoft Word 中打开输出文件。
- 多节文档中各节的显示差异：背景本来就是整篇文档级设置。
