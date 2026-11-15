# 单元格样式预设：固定源与本地链路

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`：`apps/sheets/src/renderer/ExcelShell.tsx:4000–4023` 为14项菜单；`app-constants.ts:232–285` 给出预设；`ribbon-actions.ts:1345–1354` 按预设patch顺序调用 `univer-sync.ts:379` 的官方 facade 格式 setter。

源范围是 good、bad、neutral、input、output、calculation、warning-text、title、heading-1、heading-2、total、accent1-20、accent1-40、accent1。不是任意命名样式的导入、创建、重命名或编辑器。预设只涉及 fillColor、fontColor、bold、fontSize 和 thin all/top/bottom 边框；源 Total 明确仅提供 thin top，未实现 Excel 的 double bottom。top/bottom 对整个选区外缘生效，all 包含内边线。未指定属性保持原值；每个属性是单独官方命令，撤销也是分步，不能宣称一键原子撤销。

本地旧 `workbook-ribbon.ts` 将 cell-style 占位原因写成“尚未接入单元格样式预设的文件回写”，范围过宽。`workbook-vendor/core/style-map.ts` 的逻辑投影、`grid/sync.ts` 读回、`session-core.ts` 的 diff、engine `WorkbookStyleEdit` 及样式 copy-on-write 写入已有全部所需字段。实际缺口为固定预设菜单及 facade 接线，不需要新增 engine 协议。

最小独立实现为 `workbook-cell-style-presets.ts`：保留源14个预设值，按照源 bold→fontSize→fontColor→fillColor→border 调用顺序复用官方 facade。未知key和空选区不执行；编辑、保护、选区与现有格式预算守卫由主入口承担。模块自身不手工标dirty、不构造新样式写入协议。共享 Ribbon/main 待 root 统一集成，当前模块通过不代表用户入口完成。

定向证据（非完整suite）：

- `/tmp/workbook-cell-style-presets-red.log`：真实 good 预设调用时 helper 返回 false，明确 RED。
- `workbook-cell-style-presets.test.ts`：全部14预设均经过真实 Univer facade、四格选区、现有 snapshot/diff、engine ZIP 写入及 `readWorkbook`。保留公式、未选中值、italic、numberFormat及未覆盖的原边框；撤销一条官方属性命令会产生不同草稿差分。
- `/tmp/workbook-cell-style-presets-final-green.log`：12项通过，3个边缘预设当时测试错误地将top/bottom预期施加到内边线，未误称产品失败。
- 修正源选区外缘预期后，仅受影响 heading-1/heading-2/total 重验：`/tmp/workbook-cell-style-presets-edge-green.log`，3项通过。
- 新格式空白格依既有 diff 可能携带 null 的 value write；原公式格的缓存复原遵循生产 collectOperations，原公式格 writeValue=false。没有通过人工删空白编辑掩盖既有diff行为。

尚待：菜单与主入口守卫、草稿保存/重开入口、只读/保护状态、最终built GUI 验收。此记录不能用于宣称全量单元格样式或完整 XLSX 对齐。

独立 dev GUI 探针 `smoke/workbook-cell-style-presets-gui-smoke.mjs` 已准备（4202，语法检查通过，待主入口就绪后运行）。菜单契约为 `select[data-ribbon-control="cell-style"]`，14个固定源id与一个占位选项。代表组合为 Input、Heading1、Total、Good；通过真实菜单和键盘撤销重做，dev runtime 只用于读取观察，不调用格式应用。文件验收独立经过 Python/openpyxl，核选区外缘、保留公式/italic/font/numberFormat、草稿恢复及修订重开。此项准备记录不等于 GUI 已通过。

root已接Home原位置select[data-ribbon-control=cell-style]14项源id+placeholder和主入口编辑/保护守卫，不新增engine协议。入口定向RED→GREEN；dev代表Input/Heading1/Total/Good（包括逐属性undo中间状态）真实GUI通过。最终built /tmp/workbook-cell-style-built-final.log exit0，303 JS200/静态SHA，无runtime注入；真实菜单、undo/redo执行、draft、Python/openpyxl精确外缘边框/公式/未指定italic/font/numFmt保留、新修订重开及pageErrors=[]。built仅对最终文件验证，不声称中间undo状态由built读取；中间状态来自dev只读观察和独立真实facade定向测试。固定14预设已对齐，不代表任意named cell styles库编辑。
