# XLSX 从右到左视图：固定源调查与真实缺口

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本记录仅调查，不宣称 RTL 已实现。

## 源行为与文件协议

`apps/sheets/src/renderer/ribbon-actions.ts:1085–1094` 的 toggle-right-to-left 按当前工作表翻转状态。`sheet-rtl-view.ts` 读取原生 `worksheet.getSheet().getConfig().rightToLeft === BooleanNumber.TRUE`。官方 `SetWorksheetRightToLeftCommand` / `SetWorksheetRightToLeftMutation` 在 Univer 0.25.1 导出但没有由插件注册，源主动注册；命令建立 undo/redo，App.tsx:3070–3088 从 mutation 记录 page-setup journal 并重算 skeleton，使原生撤销重做也更新视图和保存状态。

文件是 `sheetView/@rightToLeft`，默认 false；固定源 `packages/xlsx-gateway/src/gateway/xlsx-page-setup.ts:37,377–379` 声明 `rightToLeft?: boolean` 并 true 写 `1`、false删除属性。源 `univer-sync.ts:520` 将源文件状态加载至原生快照。本地可沿用现有 `applyPageSetups` op；Python只校验顶层setups并交bridge，通常无需新增操作kind，但仍要真实Python/ZIP回归证明。

## 视觉依赖：不能仅设置状态

固定源 `rtl-grid-mirror.ts` 共1260行，只有 `@univerjs/core`、`@univerjs/engine-render`、`@univerjs/sheets`、`@univerjs/sheets-ui` 四个官方包依赖；无其他本地模块导入。Univer stock renderer没有读取rightToLeft，源通过统一几何补丁实现：

- skeleton cell坐标、pointer命中、可见范围剔除、scroll-state往返；保持逻辑行列索引。
- gridlines、列标题、行标题、边框方向与文字位置，文字本身不反向。
- viewport锚点、RTL home右侧滚动、相对滚动、reveal选区。
- 冻结窗格右侧停靠、divider与拖动。

源 `installRtlGridMirror()` 幂等一次安装全部prototype适配，按各skeleton当前worksheet flag分流。应整体vendoring此固定源模块并登记Apache-2.0归属与hash，优先保留已存在源几何实现，不自行重造简化CSS反转。源 `apps/sheets/tests/rtl-grid-mirror.test.ts` 包含纯几何测试；同时import WorkbookVisuals的对象marker辅助函数，迁移其测试时应按模块边界拆分，不能把对象额外覆盖误当网格已验证。

本地chart-render按skeleton坐标计算anchor，需真实已有静态图/图像定位回归；该路径不是引入Plotly的理由。源WorkbookVisuals还处理RTL marker，因此不能仅凭prototype覆盖推定所有对象正确。

## 当前实际RED

持久测试 `frontend/src/workbook-right-to-left.test.ts`：

1. 真实XLSX `applyPageSetups({rightToLeft:true})` 后 `readWorkbook` 无rightToLeft字段（undefined），证明本地writer/reader尚未承载。2. model人为提供导入rightToLeft=true，经当前withWorkbookView加载真实Worksheet，其config仍0。两项失败见 `/tmp/workbook-right-to-left-red.log`。
2. 单独强制真实Worksheet config=TRUE，用原生injector创建真实SpreadsheetSkeleton；A.startX=46、B.startX=134，A仍在B左侧，RTL应A>B。准确产品断言失败见 `/tmp/workbook-right-to-left-geometry-red.log`；不是模块不存在导致的导入错误。

## 最小完整迁移方案

1. reader SheetModel可选rightToLeft（旧模型缺省false），读取first sheetView bool1/true；writer SheetPageSetupState可选boolean，复用现有setSheetViewAttr，false删除属性保留其他XML。真实ZIP验证true/false/无关编辑保留、其他parts不变、原有views/print状态不变。
2. withWorkbookView载入BooleanNumber；同既有视图差分比较current config与baseline追加applyPageSetups，草稿回放也使用相同reader。设置要来自原生command/mutation，使undo/redo差分归零，不能只维护独立bool日志。
3. 整体vendor源mirror，官方command每runtime注册并妥善释放/避免重复注册，官方command本身async必须await实际boolean；不要照搬源syncExecuteCommand(async handler)并直接报告成功。每次mutation刷新对应render，过期或非active目标不应修当前其他sheet。
4. root接View按钮、pressed、loading/saving/readonly/protection契约。源是可撤销文件视图状态；需按当前产品视图策略明确只读会话或禁用，不越过内容保护。
5. 模块纯几何、真实Worksheet+Skeleton、原生command undo/redo、真实main draft/save/reopen；浏览器验证A右侧/标题右侧、选择与键盘编辑、Home与远端定位、横向滚动、列freeze开关、LTR恢复、已有静态图位置。最终built JS200/SHA与无pageErrors。

本轮未修改main/ribbon/shared reader/page-setup，避免与root当前实现覆盖。三个RED用例是后续实现目标，不视为完成证据，未重复完整测试。

固定源文件身份：

- `rtl-grid-mirror.ts` SHA256 `0e8379603475372ac0f32e00c8d389992d39c8c9bb8d8d135da743e5bb6e1147`
- `sheet-rtl-view.ts` SHA256 `0df87726084d3ec9ae3f9c1037147366dce816ec6b8be0df85d7101028aa2879`

## 源几何迁移已实施（独立模块）

源mirror1260行已原样保存在 `frontend/src/vendor/genoffice-rtl/rtl-grid-mirror.ts`，SOURCE/LOCAL hash和LICENSE/NOTICE完整登记。32项源纯网格几何定向GREEN（`/tmp/workbook-rtl-source-geometry-green.log`）。不包含源WorkbookVisuals对象marker测试。

新增 `frontend/src/workbook-rtl.ts` API：`installWorkbookRtl(runtime) -> { set(boolean): Promise<{ sheetId, sheetName, rightToLeft }>, dispose() }`。注册官方缺失命令及mutation，多个install共享引用计数；已有外部官方命令不被release删除。监听RTL mutation，仅刷新与params unit/subunit匹配的当前active render，支持原生undo/redo。调用set时await实际async command结果，并验证实际config和来源core仍一致；不写单元格、不自行保存或markDirty。

`workbook-rtl.test.ts` 新增3个场景先因模块缺失RED，随后真实原生async RTL+undo/redo、shared lease、真实Skeleton镜像及视觉命中回logical column0/selection不变/LTR还原、外部command owner保留分别GREEN。第一次undo失败是headless fixture未focusUnit，不是命令未建历史；补显式focus后只重验受影响命令场景1项通过（`/tmp/workbook-rtl-command-green.log`），其余2项此前 `/tmp/workbook-rtl-module-green.log` 已通过。

历史真实Skeleton A46/B134的RED保持同断言，仅增加install已迁移的适配后GREEN（`/tmp/workbook-right-to-left-geometry-green.log`）；file writer/reader/hydration两项RED仍待root实现，几何GREEN不能代替文件能力。主入口、浏览器鼠标、滚动冻结和对象定位也仍待验证。未构建、未修改主入口或shared engine文件。

## 文件链实现（等待主入口）

本轮获root明确授权独占page-setup.ts/workbook-read.ts后，添加可选rightToLeft字段及同源writer分支，false删attr；reader default false，withWorkbookView只新增rightToLeft BooleanNumber投影，保留root修复的header宽46/高20。engine新增2项真实ZIP/原XML保真RED→GREEN（`/tmp/workbook-rtl-file-red.log`、`/tmp/workbook-rtl-file-green.log`）；原frontend三项RED现在全部GREEN（`/tmp/workbook-rtl-hydration-green.log`）。

Python新定向 `test_workbook_right_to_left.py` 1项通过，`/tmp/workbook-rtl-python-green.log`：patch_workbook/inspect_workbook/openpyxl真链路，default→RTL、无关cell修改保留RTL、LTR恢复删属性，原公式/标题隐藏/zoom/另sheet保护保留，首次RTL仅sheet1.xml改变，其他ZIP part逐字不变。此次使用 `/tmp/rtl-source-engine` 无dist目录将现有bridge/packages/node_modules符号链接过去，环境变量指向source链；没有偷偷替换公共dist，最终root仍需bundle并再验静态真实GUI。

`npx tsc --noEmit --pretty false` 最终exit0（`/tmp/workbook-rtl-file-typecheck2.log`）。待主入口ready的dev probe `smoke/workbook-rtl-view-gui-smoke.mjs` 已准备，明确拒绝NATIVE_GUI_PREVIEW以防当前runtime诊断模式误称built验收；后续built探针需独立真实canvas/clipboard几何证据。

## 真实浏览器暴露的刷新差异与修复

主入口接通后的GUI中，原生config与scene-space skeleton镜像都正确，toggle/undo/redo成立，但实际右侧鼠标点击预计B1选到M1。读取真实render证实viewport依然LTR（main.left134、rowheader.left0、scrollX0）；不是只依据模拟对象推测。

根因是Univer 0.25.1 `SheetSkeletonManagerService.reCalculate()` 只执行calculate，不发currentSkeleton$；官方 `HeaderFreezeRenderController` 仅active-sheet等事件调用_refreshCurrent→_updateViewport。固定源sheet-rtl-view只reCalculate在本地同版本实际宿主不足以触发迁移的viewport锚点。保持vendor镜像原字节，本地adapter改用公开 `setCurrent({sheetId,commandId:SetWorksheetActiveOperation.id})` 让官方重算、发事件并重建原生冻结viewports。新增定向RED→GREEN `/tmp/workbook-rtl-refresh-{red,green}.log`。

真实GUI5 exit0（`/tmp/workbook-rtl-view-gui5.log`）：RTL后rowheader.left1351，冻结A pane.left1263，main.left0/right135；A.scene.x2246 > B.scene.x2158。真实canvas鼠标点击B1选区正确、键盘15后三SUMIFS85；原生undo/redo、B2冻结、草稿恢复、真实Python patch/openpyxl保存方向true与freezeB2、文本/原公式保留且1edit、修订2重开均通过，pageErrors=[]。HTTP上下文/修订仍mock，未声称生产HTTP。此次FRange.getCellRect是scene-space，不能把其直接当screen坐标；先前probe这点误用已更正。

最终built探针将由原生A1红/B1绿fill截图真实像素边界检测镜像与定位鼠标，避免依赖dev runtime读值替代视觉证据；当前未在最终static验证。`/tmp/workbook-rtl-refresh-typecheck.log` tsc exit0。

## 无运行时视觉探针准备完成

`workbook-rtl-view-gui-smoke.mjs` 现支持NATIVE_GUI_PREVIEW=1；此前“明确拒绝preview”只描述当时诊断版本，已由本节取代。新fixture以原生A1红/B1绿填充提供真实截图像素边界（不是伪造计算值）；LTR像素A.x48/B.x136，RTL后A.x1265/B.x1175，实际B绿色框中心定位鼠标点击后编辑金额，原公式计算85×3。方向等待由真实功能区aria-pressed，built计算由原生Ctrl+C及每次clipboard sentinel读取，不访问runtime或dev注入。

先以dev验证像素探针完整exit0（`/tmp/workbook-rtl-view-gui-pixels2.log`），undo/redo、冻结B2、真实鼠标/键盘、draft、Python保存、rev2重开通过，pageErrors=[]。上一版像素probe临时activeWorkbook=null失败保留日志，不把失败当成功；当前日志包含每阶段实证。最终static仍待root build完成后运行一次同probe。

## 最终构建首轮启动失败（未算验收成功）

首轮built RTL未进入网格，native-main捕获初始化异常并把aria-busy设false，空editor不能因此视为ready成功。built3日志 `/tmp/workbook-rtl-view-gui-built3.log` 的真实status为 `Cannot access 'Da' before initialization`。独立同域dynamic import捕获stack：`lazy-workbook-engine-B6P5b0nC.js:58:22636` 的ne，来自 `lazy-workbook-conditional-formatting-d0mLEolX.js:2:21818` 顶层调用；root确认Da为engine内ZodNumber，CF新chunk与engine互相依赖导致TDZ。此失败与RTL几何无关，但阻挡最终交付，故不能忽略。

root负责按自然schema/serializer依赖边界修分块再build；RTL probe已加入初始化DOM/status诊断及缺少Home时明确失败，避免把软错误空界面当加载成功。等待修复最终built真实全链。

## 最终 cyclefix 静态产物验收通过

root完成schema叶子chunk拆分后，同一无runtime注入探针以 `NATIVE_GUI_PREVIEW=1` 运行最终static，exit0：`/tmp/workbook-rtl-view-gui-built-cyclefix.log`。真实LTR截图红A/绿B分别位于x47/x134，RTL后x1265/x1175；按绿色B实际像素边界点击并键盘输入15，原生clipboard三SUMIFS从80变85。冻结B2、undo/redo、draft恢复、真实Python patch/openpyxl以及修订2重开全部通过，保存内容保留A1字符串、F1及原三公式，direction=true、freeze=B2。

312个实际加载JS均HTTP200并与磁盘SHA256一致；主chunk `lazy-workbook-main-8kubb5Bf.js`、engine `lazy-workbook-engine-C_XFnbR0.js`，pageErrors=[]。本结果覆盖该fixture的网格镜像、冻结、鼠标/键盘与保存链；不扩展为所有复杂冻结/对象布局或整个XLSX/Word对齐完成。HTTP上下文和修订接口仍由probe mock，文件处理调用真实Python链。
