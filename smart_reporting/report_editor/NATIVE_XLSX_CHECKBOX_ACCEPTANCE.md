# XLSX 源数据验证复选框对齐

固定源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，`apps/sheets/src/renderer/ribbon-actions.ts:813`，使用官方 `newDataValidation().requireCheckbox()`。源使用数字 1/0 或自定义值的数据验证复选框；这不等于新版 Excel 布尔单元格控件。

本地功能区接入官方 builder，保留现有编辑、保护和验证只读限制。普通 `1,0` 列表不会通过启发式转换为复选框。XLSX 保存仍写源兼容的 list fallback，同时以版本化 worksheet extension 显式保存本地复选框类型；读取时完整规则身份（区域、值和选项）必须匹配，实际规则和 metadata 均唯一。无效 metadata 只失去复选框投影，普通数据验证保留。append 不得将旧失配 metadata 重新授权；其他扩展保留。

复选框文件由第三方软件重新保存时，未知扩展可能被丢弃，届时保留 list fallback。本实现没有声称桌面 Excel 可点击的现代 checkbox 兼容完成。

环境重启后重新取得的当前证据：

- `npx vitest run src/workbook-checkbox-persistence.test.ts src/workbook-checkbox.test.ts`：10 项定向通过，日志 `/tmp/workbook-checkbox-resumed-targeted.log`。
- 覆盖官方 builder、原生撤销重做、身份绑定草稿、保存再读及资源投影、自定义值、普通列表隔离、fallback 区域/值/选项失配、命名空间/损坏数据、重复实际规则、append/replace/remove、旧 metadata 洗白负例。
- `smoke/workbook-checkbox-gui-smoke.mjs` 已持久保留并支持 `WORKBOOK_SMOKE_PREVIEW=1`；使用真实功能区、canvas 点击、原生复制（每次唯一 sentinel 防陈旧值误判）、撤销重做、草稿恢复、真实 Python patch、点击新修订链接重开。HTTP 身份及修订接口为 mock；不能据此声称生产 HTTP 链或桌面 Office 验收完成。
- root 最终构建就绪后，`WORKBOOK_SMOKE_PREVIEW=1 WORKBOOK_SMOKE_PORT=4201 node smoke/workbook-checkbox-gui-smoke.mjs` 首跑 exit 0，日志 `/tmp/workbook-checkbox-built-restored.log`。实际经过功能区插入、canvas 勾选/取消、Ctrl+Z/Y、草稿恢复、再次勾选、Python 保存、点击“打开新修订继续编辑”、修订 2 重开并可再次勾选/取消；`errors=[]`。
- 保存文件独立 Python/openpyxl/ZIP 检查：A2=1，B1=`keep`，A2 与普通 D1 均保留 list fallback，Protected 工作表保护和值不变，checkbox metadata 存在；ZIP entry 集合相同，仅 `xl/worksheets/sheet1.xml` 改变。openpyxl 只读检查，不经它重新保存。
- 三次加载共 204 个 workbook JS 响应均为 200 且 SHA 与磁盘静态文件匹配。`lazy-workbook-main-BjVB4Mdm.js` SHA256 `d020bd502e08fb9eebe9be6475c9f3ee34bb9444cfa459b453e2be5ff861d7cf`；`lazy-workbook-checkbox-validation-B0oUlQDP.js` SHA256 `8228abba562a87af71712db4985024805b6f01b979966a06d5d3905ef9d262ae`；`lazy-workbook-engine-Doui74Js.js` SHA256 `e302dffcdd4784c028a89fc835a348c0e689057f757ac3eb4b451462a5174580`。

引擎归属和三个相关文件身份登记于 `reporting/workbook_engine/SOURCE.md`、`UPSTREAM-PATCHES-SHA256.json`；恢复后核对均匹配。生产代码本轮接续未再修改。
