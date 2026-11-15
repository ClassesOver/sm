# XLSX 默认页眉页脚编辑增量验收

固定参照 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/sheets/src/renderer/HeaderFooterDialog.tsx`（六区域、字段原样传递、null 清空）和 `edit-journal.ts` 的 HeaderFooterParts。本轮模块使用本地结构接口，不新增 @sheets-web 引用或依赖。

本轮新增六区域文本编辑器，操作现有引擎 `SheetPageSetupState.header/footer` 协议，不修改首页/偶数页页眉页脚及其开关，不新增格式化或图片编辑。

## 模块接口

`frontend/src/workbook-header-footer-editor.ts`：

- `headerFooterEditorState(file, patch?)` 从原始 oddHeader/oddFooter 生成 `values.header/footer.left/center/right`，叠加日志中已编辑的半部；保留字段、字体、字号、颜色、图片、未知字段等原始控制代码。
- `headerFooterEditorPatch(state, values)` 仅返回变化的 `header` 或 `footer`；未变化返回 undefined；整半部清空返回 null。
- `createHeaderFooterDialog(root, apply)` 提供 `open(state, {book,sheet,sheetId})` 和 `dispose()`。apply 回调接收 `(patch,target)`，宿主负责只读与过期目标检查、日志提交和保存。
- 六个 textarea 的选择器是 `[data-header-footer-field=header-left]`、header-center、header-right、footer-left、footer-center、footer-right。按钮为 `[data-header-footer-apply]` 与 `[data-header-footer-cancel]`，dialog label 为“页眉页脚”。

编辑器不能使用打印 decoder 初始化：打印 decoder 按固定源有意剥离格式控制码。此处以小型扫描器仅拆左右中标记，保留原始代码，识别 `&&` 与带引号字体声明中的 `&L/&C/&R`。字段内未转义的区域标记会被拒绝，提示使用 `&&L` 等字面量形式，防止保存后区域发生移动。

## 定向测试

`npx vitest run src/workbook-header-footer-editor.test.ts`：新增模块前 6 项失败，实现后 6 项通过；review 新增未配对尾 & 和未闭合字体声明用例，先 RED 后修复为 7 项通过。覆盖保留字体/图片/未知码与转义区域标记、日志叠加、清空半部、拒绝区域重定向与不完整字段、六域可访问标签、只提交变化半部、重复提交不再写、取消/Escape/无变化确认无写入，以及宿主拒绝过期目标时保留输入。

不写入用户文本到 innerHTML，文本域通过 value 初始化；用户的 HTML 按文本显示。宿主提交抛错时弹窗保持打开，成功后关闭并借助共享 modal 恢复焦点。

## 边界

- 编辑的是默认/奇数页六区域。首页、偶数页及 flags 保留现状；弹窗提示已经启用的变体。
- 用户可直接编辑代码。未修改的整半部从 patch 省略，由现有引擎保持原 XML；修改的半部通过现有 writer 以左右中顺序序列化，保留各区域内控制代码，但不声称保持该半部 XML 的字节形式。
- 图片代码和不支持的字体/样式代码保留在文件中；现有打印链仍按前轮边界处理，图片不显示。
- 不新增 native Undo。取消/无变化不写日志，宿主现有页面设置保存链负责持久化。
- 主入口/ribbon、保存/重开/下载和最终真实浏览器验收由 root 集成核对。此模块没有修改这些文件，没有运行完整测试或最终构建。


## 冻结构建真实浏览器证据

Chromium 140.0.7339.16 验收通过，证据目录 `/tmp/header-footer-editor-built-gIj1K8`。实际 Insert → 页眉和页脚入口验证取消不写草稿、编辑后 reload 恢复草稿、保存下载修订 2、重新打开后清空页眉、再保存下载修订 3 并重开。保存请求只包含 applyPageSetups，第一次只写 header（footer 省略），第二次 header=null。

下载 XML 确认页眉新中区为 Edited &P/&N，右区图片/未知码 &G &Q 保留；未编辑 footer、firstHeader、evenFooter、differentFirst/differentOddEven、工作表其他 XML 和其余 ZIP 部件哈希均保持一致。两次下载文件 SHA 与保存响应的实际字节一致，浏览器 errors 为空，加载 bundle SHA 与最终冻结静态文件一致。

证据文件：`result.json`（全部断言与请求）、`assets.json`、`revision-2.xlsx`、`revision-3.xlsx`、`downloaded-revision-2.xlsx`、`downloaded-revision-3.xlsx`、`cleared-reopened.png`（已查看）。此阶段没有修改生产文件或冻结构建产物。

最终局部布局补验通过：`HEADER_FOOTER_LAYOUT_ONLY=1 node smoke/workbook-header-footer-editor-built-smoke.mjs`，证据 `/tmp/header-footer-editor-built-oLghfd/layout-verified.png`、`layout-result.json`、`assets.json`。两组文本域均为同高左中右三列，宽约122px，截图已查看，浏览器 errors 为空，资源身份与最终布局构建一致。本次只做打开/布局截图和资源身份补验，没有重复完整保存 smoke。

最终服务端bridge重建后追加窄验证：使用先前revision-2和实际header=null保存操作调用Python patch_office，确认页眉清除、first/even/footer/flags保留及其他ZIP部件逐字节一致；证据/tmp/xlsx-hf-current-bridge-check.json。未重复完整浏览器流程。后续透视引擎修复导致资源身份变化，完整保存证据与最终布局证据按各自构建分层记录，不宣称早期130个JS与最终文件全部相同。
