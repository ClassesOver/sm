# XLSX 打印百分比缩放：只读调查

2026-11-10。固定完整源 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮仅新增本文件及 `/tmp/xlsx-print-scale-investigation/`；未改生产、构建产品、跑旧专项或复跑Error Checking。

## 结论与真实入口

打印百分比scale是真实可保存的源能力，本地缺用户入口；不能把它误认作仅打印会话，也不能把既有fitToPage重复当作新增。固定源Page Layout的“调整为合适大小”仅有宽/高fit页数，**没有独立百分比输入**；File→Print经App.tsx:5491调用openPrintPreviewHost，ExcelShell.tsx:1422挂PrintDialog。PrintDialog.tsx:390的缩放选择有none/sheet/columns/rows/custom，以及仅源fitToPage时出现的fit-file；custom显示10–400数值input。none=100，sheet=1×1，columns=1×0，rows=0×1，fit-file沿文件页数，不覆盖为某个假定值。

控件change通过setScaling→update立即调用host.applySetting(`scale:N`或`fit:w,h`)，并不是点击Print才写。host.applySetting在page-layout-actions.ts:545委托handlePageLayoutCommand；scale分支:164校验10–400整数，构造set_page_setup操作交共享runOps。op-executor.ts:759记录scale并令fitToPage=false；其余已有fit维度可保留，但不生效。PrintDialog关闭/取消只onClose，无撤销这些已记录设置的代码；因此不能设计“取消打印对话框恢复原打印设置”的假契约。preview自有settings会给buildJob传overrides，copies/printer/page-range等为打印会话状态，与可保存page setup需区别。

保存链确实存在：edit-journal.ts:384的toSavePageSetupStates导出非删除表journal；save-actions.ts:500收集，:754/:812提交pageSetupStates；gateway/xlsx-gateway.ts:1553逐表调用applyPageSetupState。该writer在xlsx-page-setup.ts:418写scale，100删除默认属性，fitToPage=false删除该默认false属性。不要仅因为XML没有显式scale=100或fitToPage=0就误判未保存。

## 实际源执行证据

目录 `/tmp/xlsx-print-scale-investigation/`：`build.mjs`用TypeScript AST按函数名从固定源提取initialSettings、fitFor、overridesFor、handlePageLayoutCommand原函数，临时esbuild仅构建调查探针；XML writer与fitToPageScale直接import固定源完整模块。没有复制这些业务实现；消息翻译、runOps共享executor边界及工作簿/表身份为明确stub。`probe.mjs`执行20项，`run.log` exit0，`results.json` ok=true。

实际结果：

- 85/100、fit1×1/1×0/0×1/2×3初始化分别custom/none/sheet/columns/rows/fit-file；fit-file overrides不伪造scale或页数；百分比初始化沿source setup。
- scale85/100/10/400各提交一条真实函数构造的set_page_setup；9/401/12.5/NaN拒绝，无operation；fit1,0单独提交。runOps stub只捕获ops并返回ok，不冒充真实executor/journal/undo执行；源原journal保持原90作为边界证明。
- 直接执行真实applyPageSetupState，85/100/10/400四个XML仅改目标打印属性，100移除scale，fitToPage移除true，原fitToWidth2/fitToHeight3、copies2、orientation与A1内容保持。`scale-N.xml`保留输出。
- `package-readback.py`把这些真实source writer输出替换进实际openpyxl XLSX，仅作为包级回读，不冒充源完整save coordinator。四份scale-N.xlsx经openpyxl重开有效比例正确（100原属性None代表默认100）、fitToPage原属性None代表默认false、fit维度2×3保留、A1=42。所有非worksheet ZIP部件逐字节相等，`package-readback.json/.log` exit0。
- `render-scale-probe.mjs`按固定源print-html.ts实际scale表达式与真实clamp函数、print-scale.ts常量执行；10→0.1、85→0.85、100→1、200→2、300/400→2。**源UI/保存允许400%，源打印renderer实际上限200%**（MAX_PRINT_SCALE=2），是源真实边界/不一致，不能声称400%预览与文件语义一致。这只执行scale表达式，不冒充完整打印HTML、浏览器像素、打印机或PDF输出。

最初包回读曾错误断言openpyxl fitToPage必须是字面False，源删除默认false属性后实际为None；改为核验有效false并记录raw，不改source/放宽业务语义。没有把该探针断言误差描述为产品bug。

## 本地已有能力与最小缺口

workbook-ribbon.ts:244明确记录scale仅在源PrintDialog；:452现有“缩放比例”action无command，:580原因“固定源经打印对话框设置打印缩放；打印对话框尚未接入”，实际disabled。不能因菜单标签存在声称功能完成。

本地已经有page-fit width/height（workbook-main.ts:1028），按整数0–1000、另一轴默认0、两轴均0关闭fit；不是本轮缺口。已有pageSetupJournal和applyPageSetups落盘协议：main.ts:1898已把scale与fitToPage一并纳入差分；源文件scale能读入currentModel，workbook-print.ts:355按scale10–400用于现有分页，fitToPage开启时使用fit结果。故本地缺“用户输入scale并与fit互斥”的入口/host接线，不缺新的文件格式、百分比字段或通用打印引擎。

但mergedPageSetup(main.ts:666)目前给Ribbon摘要只提供fit页数，不提供scale和fitToPage；若新增百分比控件，需从可信pageSetupJournal/基线读取当前值，不能从当前默认100臆测。主流程已有真实模型、草稿回放和保存差分，应复用；不要另建scale journal或另一套XLSX XML writer，不要为百分比功能引入完整打印机选择/多份/页段/图表体系。

最小后续可选：按用户认可的入口提供独立打印百分比设置，明确与源不同是源PrintDialog子功能的本地最小入口；必须10–400整数、scale设置同时fitToPage=false，切回fit沿既有width/height路径。另一个选项是实现完整源PrintDialog，范围显著更大，本调查没有授权实施。不要把normal-view zoom当打印scale，也不要顺手重复实现fitToPage。源200% renderer上限应明确记录；若本地维持已有400%打印能力，属于已知源差异，不能为照抄源bug而截断合法保存比例。

## 后续必要窄验收与边界

新增UI初值来自source scale/fit状态、85/100及10/400、非法/小数拒绝、当前同值不dirty、取消不写、设置scale关闭fit但不抹掉无关页设置；切回fit后比例字段保留但不生效；同表rename/delete/切表/stale身份与protected/readonly遵循现有page setup。这里只读确认源PrintDialog的修改即时记录，未来独立本地确认式dialog可有自己的明确交互契约，不能把它冒称源PrintDialog完全等价。

collector/draft/save必须只产applyPageSetups并保其它view/cell/print设置；实际XLSX patch/download SHA/ZIP与明确重开、真实分页比例变化需窄built证明，特别100默认属性清除与fit关闭。不重跑已通过fitToPage、打印区域/标题等完整专项。当前未执行完整源runOps/save coordinator、UI React事件、真实print host buildJob或本地新增UI，亦未对生产HTTP授权、桌面Excel、打印机/PDF视觉作等价结论。

## 固定源身份

| 文件 | SHA256 |
| --- | --- |
| PrintDialog.tsx | f248aa1730b867caf8d87aaf1cd581b8e4e20ee4c3ad8614d0a6cfb9df89196d |
| page-layout-actions.ts | 777ded405e77dad44bc3fdaae353aea113c65fccc254b70ab3f0747c615f1803 |
| op-executor.ts | 2d82c88141fb8ad8cd2e5dae08c78e1106b1921017d69221a317f1e2860f5d10 |
| print-scale.ts | 6d37a1c1b7d836e754caa4680aa3db9f409d0aa80c9de175be817abc7742297b |
| save-actions.ts | aecb8ae993f99b94889ddfd11ab3f2ea2d95526275fc12d611fcfbbbc463ca2e |
| xlsx-page-setup.ts | 10da528114e67f8a801bc823c327cfdd4527517a23e356daffadbb860fb41a79 |
