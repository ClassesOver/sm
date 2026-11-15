# CELL 文件名对齐验收（进行中）

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，`apps/sheets/src/renderer/cell-function.ts` 与 `App.tsx:2404`。本地迁移为 `frontend/src/workbook-function-cell.ts`，沿用原生引用/工作表信息及非 filename 委托；不实现另一套公式求值器。

真实引擎 RED：`/tmp/workbook-function-cell-red.log` 中 `CELL("filename")` 返回 `#N/A`，期望已保存来源目录、方括号文件名及工作表名。迁移后真实工作簿含跨表引用、MID/FIND 取表名和非 filename row 委托通过，`/tmp/workbook-function-cell-green.log`；源代表用例及取消迟到安装共10项通过 `/tmp/workbook-function-cell-final.log`。后装扩展的0ms归属反例先RED，最小owner检查后使用项目实际Vitest3的窄GREEN见 `/tmp/workbook-function-cell-owner-green-final.log`（首次同名green在仓库根误调用另版Vitest，不作为项目验收）。

来源路径由原生可信context传入file callback；报告工作簿鉴权file响应新增整段percent编码 `X-Workbook-Path`，前端恰好decode一次，支持中文、空格、百分号和Windows分隔符。真实ASGI Unicode path测试先RED缺header，后GREEN（`/tmp/workbook-cell-path-api-red.log`、`/tmp/workbook-cell-path-api-green.log`）。这不修改下载签发或发布门禁。

三覆盖统一在首轮loadWorkbookData后安装，在loading期间通过原生calculateNow重算，避免初始化覆盖首次注册；同一Univer新workbook core不重装。独立reload probe证明新path与新sheet正确、CELL(address)委托保持，`/tmp/review-function-overrides-reload.probe.log`。本地主视图初载另暴露现代函数存储前缀reader缺口，独立修复后四函数初载正确、draft为空、save0（`/tmp/workbook-functions-main-final-green.log`）。真实dev浏览器初载、键盘改A1重算、草稿刷新、Python patch保存/openpyxl和修订2重开全部通过（`/tmp/function-values-gui-first.log`）；HTTP身份/修订仍mock，dev runtime wrapper仅观测，不称最终built验收。

全量XLSX对齐未完成。文件名是本地服务已保存来源身份，不是浏览器下载后用户自行改名的磁盘路径；无来源路径时按源返回空串。非filename缺省引用沿用源限制返回#N/A，外部工作簿宿主仍独立未完成。
