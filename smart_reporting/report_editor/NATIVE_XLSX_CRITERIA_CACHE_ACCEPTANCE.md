# XLSX 文本条件比较缓存验收

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`：

- `apps/sheets/src/renderer/criteria-compare-cache.ts` SHA256 `786a0b05bd1c67534bce675bd9b98f3b5e423e37bb151164814460433e65b99d`
- `apps/sheets/tests/criteria-compare-cache.test.ts` SHA256 `f52320eb5978205c939cceb963aaf56719ef18b3550621f6f87815ef4b7de571`
- 源 App.tsx:2418 安装，:3861 释放。沿用现有 GenOffice Apache-2.0 LICENSE/NOTICE。

## 当前真实反例

不能直接把 `setValues(['2026-06'])` 当作导入文本：Univer 会将它自动转成日期序号46174，因此缓存键也是数字，重复 SUMIFS 结果原生正确。该 GREEN 对照在 `/tmp/criteria-cache-probe-native.log` 和 `/tmp/criteria-cache-same-pass-probe.log`。

真实导入列显式 `CellValueType.STRING` 保留月份文本 `['2026-06','2026-05','2026-06','2026-06','2026-05']`，B列为10/20/30/40/50。同一计算批次输入三个公式 `SUMIFS(B1:B5,A1:A5,"2026-06")`、相同表达式加0、相同表达式乘1，settle后原生实际 `[80,0,0]` 而非 `[80,80,80]`。trace证实 compare criteria为数值46174，缓存keys却为原字符串。临时真实引擎取证 `/tmp/criteria-cache-text-column-probe.log`；持久真实工作表回归 RED `/tmp/function-criteria-workbook-red.log`。这不是未完成计算的null或仅registry是否存在的断言。

## 最小源迁移及生命周期

本地 `frontend/src/workbook-function-criteria.ts` 保留源核心条件：只有 `operator='='`、非string且非error条件、列缓存有非错误literal的string key时临时令 `CELL_INVERTED_INDEX_CACHE.canUseCache` 返回空cache区间，委托原有 `_batchOperatorValue` 走dense比较；try/finally立即还原cache方法。其他操作符/类型继续native快路径。不自己实现SUMIFS或数值转换。

WeakMap以缓存map对象身份及size记忆是否有string key，避免每格扫描全部distinct key，map新增键后重新判断，clear替换map自然失效。

源每次调用直接覆写同一global prototype，不适合多个浏览器编辑runtime并存。本地只新增module共享patch状态与reference count。API `installCriteriaCompareCacheFix(): { dispose(): void }`：每runtime持一个lease；重复安装共享同一个wrapper，先关闭一个runtime不撤掉另一个仍用的修复；最后release且prototype仍是自己的wrapper时还原捕获original。后续第三方wrapper不被覆盖，重复dispose幂等；无timer、无provider依赖。私有method未来不存在时no-op。

root负责main/function-overrides统一安装/释放与manifest，建议与其他数值覆盖同生命周期：每个实际runtime安装一次，dispose先于univer释放。本批不改共享main/registry/vite/static。

## 定向证据

- 真实工作表反例RED→GREEN `/tmp/function-criteria-workbook-green.log`：三个SUMIFS均80。
- 只新增边界5项通过 `/tmp/function-criteria-edges-green.log`：真实SUMIF/COUNTIF/COUNTIFS/AVERAGEIFS/MINIFS/MAXIFS重复计算、双owner释放其一后的实际runtime计算、第三方prototype owner保留、私有方法消失、native compare异常时cache方法finally恢复。
- 新增缓存边界1项通过 `/tmp/function-criteria-cache-edges-green.log`：数字/同类型string继续native缓存，错误literal边界、缓存map新增string key时memo失效。

未重复完整测试、未构建或改写static、未commit/push。浏览器主入口/保存重开尚需root集成后单独验收，不能把模块GREEN当最终产物已通过。

## 边界

这是同一JS realm内同步prototype适配，依赖固定版本私有 `_batchOperatorValue` 与同步比较执行模型。临时替换canUseCache期间的同步嵌套比较会一起使用dense路径，finally恢复；不是跨worker自动安装。若第三方owner替换自身wrapper，后续lease尊重该owner，不强制夺回。源按map.size失效假设缓存只增key、clear替换map；不宣称可识别外部强行删加同size的map变异。源码中定义的文字转数值比较语义保持，不扩大为任意Excel条件公式完全等价。

最终测试类型修订将fixture统一为 ICellData 矩阵（运行时文本身份不变），仅重验受影响3项真实计算例均通过（`/tmp/function-criteria-cell-type-green.log`）。最终 `tsc --noEmit` 无 criteria 文件错误；该次全项目检查仍被并行开发中的 `docx-style-majority.test.ts:39` 和 `workbook-checkbox.test.ts:31` 类型错误阻挡（`/tmp/function-criteria-typecheck-final.log`），不声明全项目类型检查通过。

## 真实浏览器主入口

新增独立 `frontend/smoke/workbook-function-criteria-gui-smoke.mjs` 首跑 exit0（`/tmp/function-criteria-gui-first.log`）：openpyxl生成真实文本月份 XLSX，导入后重复SUMIFS为 `[80,80,80]`；Ribbon定位B1后真实键盘输入15，三者变 `[85,85,85]`；草稿刷新恢复；真实 Python patch_office 保存，经 openpyxl 回读月份字符串身份 `data_type='s'`、三条原公式和F1文本均保留，恰一条单元格编辑；修订2重开三者仍 `[85,85,85]`，pageErrors=[]。dev宿主仅捕获实际runtime以读取数值，未替换公式计算或伪造结果；尚未声明最终static产物已验收。未重跑旧数值全流程。


## 最终静态浏览器验收（重启恢复后）

2026-11-10：环境重启后旧 /tmp 日志不可读取，未把历史日志当作当前可复核证据。`NATIVE_GUI_PREVIEW=1 node smoke/workbook-function-criteria-gui-smoke.mjs` 本次 exit0，日志 `/tmp/function-criteria-gui-built-restored.log`。直接使用最终 static 的 vite preview，没有开发运行时注入；通过真实功能区“定位”、原生 Ctrl+C 和逐次唯一 clipboard sentinel 读取 D1:D3，依次得到 `80\n80\n80`、键盘 B1=15 后 `85\n85\n85`、草稿刷新 `85\n85\n85`、修订2重开 `85\n85\n85`。

真实 Python patch_office + openpyxl 回读验证 A1='2026-06' 且 data_type='s'、B1=15、三条原 SUMIFS 公式及 F1='keep' 保留，恰一条单元格编辑。HTTP context/save/revision 宿主是 mock，文件修改与公式计算是真实链路；没有生产 HTTP 或桌面 Excel 验收声明。291个实际JS响应均HTTP200并与磁盘SHA256一致，pageErrors=[]。

- `lazy-workbook-main-BjVB4Mdm.js` SHA256 `d020bd502e08fb9eebe9be6475c9f3ee34bb9444cfa459b453e2be5ff861d7cf`
- `lazy-workbook-engine-Doui74Js.js` SHA256 `e302dffcdd4784c028a89fc835a348c0e689057f757ac3eb4b451462a5174580`
- `lazy-workbook-insert-function-FBE3MIvK.js` SHA256 `300983f4055f527f5eb6e1447c044fb846ba7b08c6324ae8d8a5e1fe44676462`
- `lazy-workbook-insert-function-DWmYSuqM.js` SHA256 `e940ce28f7859bbbe3500bf47711247c8b5ff634a0da7c8c207000ac336226ce`

此次 `npx tsc --noEmit --pretty false` exit0（`/tmp/criteria-headings-typecheck.log`）；上一段旧类型阻挡仅是历史状态，不代表当前仍失败。完整数值套件未重复执行。
