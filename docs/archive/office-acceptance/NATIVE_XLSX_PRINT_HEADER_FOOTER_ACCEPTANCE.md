# XLSX 文件页眉页脚打印增量验收

固定参照：GenOffice HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮只把已有文件中的文本页眉页脚送入当前活动表打印文档，不新增编辑对话框，不代表完整打印对齐。

## 来源登记

`frontend/src/workbook-print-header-footer.ts` 直接复用下列固定源文本解析算法（仅本地 import/来源注释适配）：

- `apps/sheets/src/renderer/print-hf-codes.ts`：完整字段展开；SHA-256 `1f184d9a783db829be1084c3dcb0cdd2e2c96b0e32c8b1dbaee62323606a541b`。
- `apps/sheets/src/renderer/print-settings.ts` 的 `decodeHeaderFooter` 及 `STRIPPED_CODES`：左右中区拆分、字体控制码剥离；原文件 SHA-256 `c53b1d45df0eaef10f765649ba1c7443fa036041373a4300d8ad80f4d570e3ca`。
- `apps/sheets/src/renderer/print-html.ts` 的 `pageVariant`、`headerFooterHtml`、`renderHeaderFooterSection`：首页优先于奇偶、每页字段、9pt 文本随文档缩放、距纸边位置及安全转义；原文件 SHA-256 `eab9a0a784157e83ec4452710cb596e609478e5606356606d181adec72aee987`。

## 接口与行为

`SheetPrintSetup.headerFooter` 是可选原始文件投影，包括 odd/first/even Header/Footer 六个编码文本、differentFirst、differentOddEven 和 scaleWithDoc。渲染器内部解析编码，不改文件内容。`PrintMarginsInches` 允许 header/footer 距离，缺省 0.3in；normal/narrow 预设 0.3in、wide 预设 0.5in 与源一致。

`buildSheetPrintHtml(source, setup, { fileName, now })` 保持前两参兼容；第三参可选，文件名缺省为空、时间每次打印只获取一次。入口提供文件 basename，不渲染服务端路径。

每页 &P 是完整活动表打印计划中的页索引加一，&N 是完整计划页数，覆盖多打印区域。首页规则优先，启用 first/even 但对应 header/footer 半部缺失时保持空白，不回退 odd。未启用的变体不生效。

支持源字段 &P/&N、&P+n/&P-n、&D/&T、&F/&A、具名 &[Page]/[Pages]/[Date]/[Time]/[File]/[Tab] 等、&& 字面量。未知字段保持字面量；字体名称/大小/颜色/粗体等控制码按源剥离。原始文本和字段展开结果统一 HTML 转义，不执行脚本或字段。

## 验证

先运行 `npx vitest run src/workbook-print-header-footer.test.ts`，观察新增 7 项中 6 项因无页眉页脚失败，1 项无页眉兼容通过。实现后 7 项全部通过。

定向回归 `npx vitest run src/workbook-print-header-footer.test.ts src/workbook-print-borders.test.ts src/workbook-print.test.ts src/workbook-print-scale.test.ts`：35 项通过。未运行完整测试、未构建。读取模型和 context 接线由 root 并行完成，验证以 root 最终结果为准。

冻结构建后从 frontend 执行 `node smoke/workbook-print-header-footer-built-smoke.mjs`：该脚本经实际 native URL 的 File → Print 截获三页 XLSX 打印 HTML，断言首页/偶数/奇数内容、真实页码和总页数、左右中区、文件名/表名、转义、图片不渲染、4.5pt 缩放及 0.2in header 距离，产出截图、HTML、PDF 和 JS bundle SHA-256 对照。脚本已有阶段日志与请求超时；最终冻结构建后浏览器验收通过：Chromium 140.0.7339.16，证据目录 `/tmp/print-header-footer-built-2AO7Cg`。

- `source.xlsx`：真实三页文件输入。
- `print.html`：经真实 native URL → File → Print 截获的打印 iframe HTML。
- `native-print-entry.png`：实际入口截图。
- `print-rendering.png`：三页打印媒体截图，已查看首页、偶数页与奇数页头尾位置。
- `print.pdf`：3 页 A4，594.96 × 841.92pt，pdfinfo 确认无 JavaScript。
- `result.json`：全部断言通过，130 个加载 JS bundle SHA-256 与冻结静态文件一致，pageerror 为空。

实际内容：第一页 First 1/3 且无默认 footer；第二页 Even 2/3 且无默认 footer；第三页左 Odd 3、中 Total 3、右 Header <sheet>，页脚文件名 header-footer.xlsx 和脚本文本按字面量显示，script/img 节点为零。页眉位置 top:0.2in，50% 文档缩放后字体 4.5pt。生产文件和构建产物在此浏览器验收阶段保持冻结。

## 边界

- 页眉页脚图片 &G / &[Picture] 没有图片输入，按源缺图行为替换为空；不声称图片打印支持。
- 字体/颜色/富文本样式控制码按源剥离，保持统一字体文本。
- 文件路径 &Z 按源 decode 行为剥离；不暴露路径。日期时间使用运行浏览器 locale，与源一致。
- 当前为单活动表作业，无跨工作表作业页码；浏览器打印面板选页不重新编号，与源完整作业后筛页行为一致。
- 不新增打印范围对话框、页眉页脚编辑入口、多表打印、图表/浮动对象或跨页合并重组。
