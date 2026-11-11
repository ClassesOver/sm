# XLSX 迷你图集成定向验证

2026-11-10。真实浏览器/视觉状态由 [专项验收](NATIVE_XLSX_SPARKLINE_ACCEPTANCE.md)单独记录；本文件仅登记已执行的分层证据，不能以测试通过代替完整视觉验收。

- 引擎追加27项：`/tmp/xlsx-sparkline-append/final-green.log`；未知组子节点补充单项RED/GREEN同目录；独立ZIP/XML回读 `independent-readback.json`。
- reader最终12项：`/tmp/xlsx-sparkline-append/reader-final-green.log`；renderer跨表路径/实时来源数值变化/unit隔离3项：`render-green.log`。柱形几何是其后真实截图发现的独立缺陷，不由这三项证明。
- 前端controller初18项：`/tmp/sparkline-frontend-final-green.log`；累计200宿主保序分批及特殊表名quote分别有RED证据。source依赖新增后累计22项：`/tmp/sparkline-frontend-source-green.log`。
- root main创建/UndoRedo/保存/草稿增量1项：`/tmp/workbook-main-sparklines-restored-final.log`；readonly/protected单项在此前main运行通过；结构/rename及拒绝后stack守恒1项：`/tmp/workbook-main-sparklines-structure-stack.log`。夹具误用已关闭draft和不存在replace方法两次失败记录保留，不当作产品缺陷。
- main来源页改名后结构原子拒绝与stack守恒1项：`/tmp/workbook-main-sparklines-source-red-valid.log`（名称带red，实际为新guard落地后的GREEN）；首次夹具错误additions数组另留失败。
- Ribbon1项：`/tmp/workbook-ribbon-sparklines-final.log`；随后仅补显式command类型，完整types通过。
- Python顶层协议3项：`/tmp/native-sparkline-protocol-green.log`；真实保存/中文空格表名及ZIP独立回读1项：`/tmp/native-sparkline-real-green.log`。native_office/delivery双白名单同时登记，未改发布链/门禁。
- 受影响旧print-scale4项通过：`/tmp/sparkline-frontend-legacy-regression.log`；旧cell-shift因夹具缺官方插件初始化失败后仅修测试夹具，单文件3项通过：`/tmp/sparkline-frontend-cell-shift-fixture.log`。其它旧main测试仅新增必要resolver mock导出，未声称全部运行。
- 跨表source结构依赖4桥新增测试：`/tmp/xlsx-sparkline-cross-structure/guard-green.log`，有完整RED及桥types。原错误产物未覆盖；`guarded/execution.json`和`independent-readback.json`独立证明canonical整行列同步、canonical单格/alias结构拒绝。前端没有raw prefix元数据，对来源页结构保守拒绝，普通值/无关页允许，不能宣称完整结构同步等价。

最终冻结构建 `/tmp/workbook-sparklines-data-split-build.log` 完整types/Vite40.50s exit0，配套budget/contract exit0；main235.3KiB/data-tools14.6KiB/sparklines5.0KiB，cap仍250KiB。types先发现真实getCell含void，main统一??undefined后修；两次251.0预算失败保留，拆既有数据工具后通过。此冻结版已完成三类型真实保存，但柱形/盈亏绘制几何缺陷仍待后续版本复验，不将该构建等同最终版本。

三保存后视觉审查发现旧renderer column错误基线与winLoss全高造成越格，未把机器ok当最终验收。修复后新增18个bar几何向量先16失败（有效RED）后18通过，加3跨表回归共21通过；真实bounds诊断单项另通过。日志 `/tmp/xlsx-sparkline-bars/{red,green,bounds-diagnostic}.log`。零值无柱，极小drawable跳过，密集柱不强制1px宽，避免边界外绘制。源固定中线半高未有旧本地全高bug，本地column采用含零值域动态基线；后续真实built按saved checkpoint仅重开，不重复三保存。
