# XLSX 组合图 Select Data 专项验收

日期：2026-11-13。

## 本次范围

固定参考源 `/home/junge/pros/genoffice-source-full`，实际 HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。补齐原手工 Select Data 的柱形/折线组合图逐系列 `plot` 与 `secondaryAxis`，沿用原生 `applyChartEdits.seriesSet` 和现有草稿、撤销重做、保存、修订与下载链。

实现包括逐系列类型及次轴控件、添加/删除/重排标签保留、行列切换的来源默认、真实 plot/axId 读回，以及画布按实际类型与独立主次轴数值尺度绘制。写入器按类型与轴组分组，保留全局 `idx/order`，保留原主轴并按需保留、合成或移除次轴。只剩同一类型但仍有次轴的图仍按组合图读回。

读回继续保留 XML 文档中的系列顺序，以兼容已有 AI `seriesData.index` 的文档位置协议；不更改 AI 来源 DSL、Python 链路或非组合图类型转换。横向条形与折线的复杂混合、3D 及其它多 plot 组合不列为本次完成范围。

## 修改文件

- `reporting/workbook_engine/packages/xlsx-engine/src/chart-edit.ts`
- `reporting/workbook_engine/packages/xlsx-engine/src/chart-read.ts`
- `report_editor/frontend/src/workbook-vendor/core/session-core.ts`
- `report_editor/frontend/src/workbook-chart-data-dialog.ts`
- `report_editor/frontend/src/workbook-chart-data-dialog.css`
- `report_editor/frontend/src/workbook-main.ts`
- `report_editor/frontend/src/workbook-vendor/grid/chart-render.ts`

相关定向测试为 `chart-combo-series.test.ts`、`workbook-chart-data-dialog.test.ts`、`chart-render.test.ts`、`workbook-main-sparklines.test.ts`。新增实际 HTTP 脚本 `frontend/smoke/workbook-combo-smoke.mjs` 及独立验证器 `workbook-combo-verify.py`。

## 已执行的定向证据

证据根目录：`/dev/shm/office-next-xlsx-combo-20261113`。

- 写入器及原有 chart-edit 回归：22 通过；随后增加的“同一类型保留次轴”专项 1 通过，未重复此前已成功的完整组。
- Select Data 对话框：11 通过。
- 图表画布：88 通过。
- 宿主组合图专项：1 通过，覆盖取消、人工单元格草稿、逐系列类型/次轴、实际 Ribbon Undo/Redo、同身份 NativeDraft 重开和一次真实引擎保存。
- 前端和引擎 TypeScript 类型检查均 exit 0；目标文件 `git diff --check` 通过。
- 固定源迁入的 9 个写入器函数除本地类型别名替换外逐函数完全一致，记录于 `source-writer-parity.json`。

保留了真实 RED 与中间失败日志。早期宿主测试的隐藏旧对话框选择器、原生撤销重建等待和按行自动选系列夹具问题均只修正测试；最终成功记录为 `host-green-final.log`。不得把早期超时当作明确的产品行为 RED；明确的旧组合图拒绝记录为 `host-rejection-red.log`。

## 原生文件独立回读

`native-roundtrip` 使用 openpyxl 创建真实组合图来源，经过实际 TypeScript writer，再由独立 openpyxl、lxml 和 ZIP 校验器读取。此项属于直接原生写入链验证，不能冒称 HTTP 保存验收。

`verify.log` 返回 `ok: true`：

- 人工 `J2 = Manual combo draft` 与 bold 均保留。
- Added 主轴柱形、North 主轴折线、South 次轴柱形、Rate 次轴折线形成四组，数值、类别、全局 `idx/order` 与轴引用均正确。
- 原主轴与标题 C14N 精确一致；所有非目标 ZIP 部件字节相同。
- 输出 6,899 字节，SHA-256 `746c36bf3b3eaa480d24faad0381f776530ee9afe34acd8ae4e2c4a4e71e0391`。

## 统一冻结 HTTP 验收

统一冻结根为 `/dev/shm/office-next-dropcap-combo-merge-master-elements-20261113`。8 项构建检查均 exit 0，静态 manifest SHA-256 为 `615163c4c3ded620bb13234122204fc6f4002f03c2c8079a1d1c444da6373650`，工作簿桥为 `58fdf64603c6d7f1ad52ed54e506315d4a0dcbaee4968ceded54549efdf3b5da`。

`browser-frozen-01` 在服务和 fixture 启动前发现 104 份 live 后端基线中的两处差异，0 次保存，保留前置失败记录。后续按主代理明确要求保留原冻结基线并单独报告差异，使用实际 live 后端执行；不得称后端完全隔离或与冻结基线完全相同。

`browser-frozen-02` 为唯一完整 HTTP 保存运行，exit 0。运行前已复制实际 runner、独立验证器、服务和辅助脚本并登记 SHA；实际 runner SHA-256 为 `99d7d9e3b27bda46e0c878bd3799f1e52c64f7c82d1bf109a86cc8f5300181d4`。

- 人工 bold 草稿、取消/Escape、逐系列类型/次轴、添加和重排、390px 提交、Ribbon Undo/Redo、刷新恢复、保存下载、新修订重开全部通过。
- 174 份 JS/CSS 响应与冻结磁盘文件逐一 SHA 相同；浏览器错误、console error、HTTP error 和资源身份错误均为空。
- 390px 对话框边界为 x=20 至 378，内容宽度 356 与可见宽度相同；提交按钮完全位于视口内。已目视检查桌面四行六列控件及移动端滚动提交截图，无横向溢出或按钮遮挡。
- `r4 → r5`，`savedRevisions = 1`，`plannerCalls = 0`。`validation.ok = false` 且明确返回 `native_source_review_pending`，下载仍正常签发。
- 下载输出 6,900 字节，SHA-256 为 `b15466d01595cb2bdf528bf4b12142ec3603e3da6208d9e9fa809cee9d6bc249`。独立 openpyxl/lxml/ZIP 回读 `ok: true`，四组类型/轴/数据、人工 bold、原主轴与标题及非目标 ZIP 部件均保持预期。
- 本次实际 live 后端的 104 份文件起止身份完全相同。相对于原冻结基线，`render_preparation.py` 从 `82bb692e…` 变为 `3dabe2d4…`、`service.py` 从 `057713d3…` 变为 `8a54ea38…`，完整身份位于 `backend-start-identities.json`、`backend-end-identities.json` 和 `backend-baseline-mismatches.json`。

## 本地适配登记调和

两份 live `LOCAL-ADAPTATIONS-SHA256.json` 已更新本轮 4 个受管文件：引擎 `chart-edit.ts`、`chart-read.ts` 及 vendor `session-core.ts`、`chart-render.ts`。其余 3 个宿主/对话框文件属于本地产品代码，由统一源快照和专项 `after-identities.json` 登记，不扩张 vendor 原始来源声明。

统一冻结时这 4 项 LOCAL 登记仍是旧值。主代理冻结根下 `LOCAL-ADAPTATIONS-RECONCILIATION.json` 逐项列出旧登记、实际冻结源 SHA 和最新 live 登记，4 项均验证一致。未改物理冻结源码或原始 SOURCE 清单，未因此重新构建或重复保存。
