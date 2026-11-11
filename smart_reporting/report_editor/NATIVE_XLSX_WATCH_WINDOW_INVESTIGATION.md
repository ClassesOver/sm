# XLSX 监视窗口：只读调查与最小方案

2026-11-10。本轮仅调查，不修改产品、不重建、不重测已通过功能，不写共享AUDIT。
固定源 `/home/junge/pros/genoffice-source-full` HEAD
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 当前真实缺口

最新 `NATIVE_WORD_XLSX_PARITY_AUDIT.md` 末尾已记公式追踪七场景闭环，旧矩阵中
“追踪未实现”是历史状态，不能作为新工作。直接检查当前代码：

- `frontend/src/workbook-ribbon.ts:475–476` 的公式审核只给trace三入口及
  show-formulas绑定command，`watch-window`仍由无command的action构造。
- 同文件`:1240` 对无command按钮实际设置disabled及未接入原因；
  `RibbonCommand`没有watch-window，`workbook-main.ts`没有处理分支，也没有
  WatchWindow面板或状态。不是只缺样式或陈旧审计文字。
- 固定源`ExcelShell.tsx:3041–3046`真实发出watch-window；`App.tsx:4714`
  toggle watchOpen，`:6235–6243`真实挂载面板并接添加/删除/关闭。

错误检查也未接通，但源有whole-file streaming/journal分支；打印缩放依赖尚未
接入的完整打印对话框。本轮选择**监视窗口**作为单一独立缺口：源有完整可见
行为，本地确定禁用，直接复用现有Univer读取API，无文件协议扩展，能独立验收。
此选择不代表其他gap已完成或穷尽全部缺口。

## 固定源事实与身份

| 文件 | 事实 | SHA-256 |
|---|---|---|
| `apps/sheets/src/renderer/WatchWindowPanel.tsx` | WatchCell使用sheetId/row/column，watchKey稳定；非模态面板列出表名/A1地址/显示值/公式，空态、添加选区、删除项、关闭；800ms轮询，unmount clearInterval；找不到表时watch-gone | `c05cf24faa4d7e3d14ba594bd370c6478597a77ca94c9b44e5322a681098cd52` |
| `apps/sheets/src/renderer/App.tsx` | watchOpen false、watchCells空；addWatchSelection行优先去重，每次最多新增20格；resolveWatch按稳定sheetId取表，再getDisplayValue/getFormula；关闭不清列表 | `d52ad546fef9d3856046c11311bf7570e35dc203d3f0db852eb1cfe5884b0b14` |
| `apps/sheets/src/renderer/ExcelShell.tsx` | 公式审核入口真实发command | `f7ddc426f15e895a208a31ed27383c04af3de444a14b25636a5a623a8ed57f98` |
| `apps/sheets/src/renderer/styles.css:5938+` | fixed右下420px、max-height320、非模态，行表格/删除样式 | `e0faabcde838f5ad9bd2af5deb51b48cda35142f9854068cba339a6e86bfb88f` |

`App.tsx:4778–4809`是添加和解析的核心。**20是每次新增上限，不是总数上限**；
反复点击可以逐批添加余下格。表重命名因ID稳定而自然保留；删表行保留并标记
失效。源只储存坐标，不承诺插行/移格后继续跟踪原内容。没有写文件、草稿或
历史的动作。源只见初始化及增删setWatchCells，没有声称跨工作簿自动隔离。

## 实际源执行证据

`/tmp/watch-window-source-investigation.mjs`只在tmp构建源探针，不构建产品。
从固定App原文精确提取addWatchSelection/resolveWatch函数体执行，直接导入
固定源WatchWindowPanel和gateway地址格式函数。只stub locale翻译为key，不改
collector/Panel逻辑；真实React SSR渲染失效行。不是完整App/浏览器验收。

运行`NODE_PATH=<frontend>/node_modules node /tmp/watch-window-source-investigation.mjs`
exit0。证据：

- `/tmp/watch-window-source-investigation.log`
- `/tmp/watch-window-source-probe.json`
- `/tmp/watch-window-source-probe.html`
- `/tmp/watch-window-source.cjs`（临时执行bundle）

实际30格选区：首次20、第二次30、第三次仍30；稳定ID改名后解析
`{sheetName:'Renamed',value:'9',formula:'=A1+2'}`；删表返回null；SSR有
watch-gone和A1地址。800ms effect仅源码核对，SSR不执行timer，不冒称已测
浏览器轮询/焦点/显示值重算。

本地已安装Univer 0.25.1 facade类型确认`getDisplayValue()`和`getFormula()`
可用（`node_modules/@univerjs/sheets/lib/types/facade/f-range.d.ts:372,554`），
无需自己解析格式、读取原始OOXML或复制公式计算引擎。

## 最小实现方案（尚未实施）

1. 新建单一会话监视窗口模块，沿源WatchCell/watchKey、行优先20新增和解析
   契约，使用现有官方FWorkbook/FWorksheet/FRange；面板仅显示值、公式和来源
   地址，添加、删除、关闭。使用宿主DOM风格与已有样式，不迁入整个App/i18n。
   保留源800ms只在打开时刷新，关闭清timer、重新打开保留本会话列表。
2. main只接watch-window、提供真实active selection/按ID解析；Ribbon绑定
   该命令，保护/只读表可用，不经edit gate、不markDirty。加载中禁添加，
   工作簿替换/loadOperations与dispose清状态/timer；避免不同workbook重用
   sheetId时串读。删表在同工作簿显示失效行，Undo恢复后重新解析；不把整次
   宿主重新加载误认为源跨工作簿保留契约。
3. 单次新增20保持来源语义；若增加会话总量预算须明示为本地适配且反馈剩余
   数量，不能将源20误当总cap。优先保持源语义，不在调查阶段虚构新配置。
   列表按位置监视，结构编辑后读取新坐标值；明确这一点，不增加未请求的
   “跟踪原单元格实体”、跨会话持久化、导出或编辑公式能力。

独立验收需先RED→GREEN：真实Ribbon禁用→可用；源向量去重/20逐批、重命名
保ID、删表失效/Undo恢复；定时刷新只在open、close/rebind/dispose释放；真实
main snapshot/草稿/撤销/保存状态不变。新built只跑该功能：保护表选择2格→添加
并看表名/地址/格式化值/公式，切表后仍读原表，重复添加去重，关闭重开保持，
删除项；在可编辑表真正改输入并等待重算，监视值更新，真实编辑自己有Undo，
面板动作不新增Undo；rename/delete/Undo与替换隔离。核对源/下载SHA、save0
（只读阶段）、pageErrors和实际加载资产SHA。已有公式追踪等完整suite不重跑，
除非新改动直接影响其路径或新增失败提供理由。

本调查没有实现、没有最终UI结果，不登记完成。后续实现还需root协调代码
窗口、统一build/预算及独立built验收。

## 已授权实施，待统一built验收

main/Ribbon及独立watch-window模块/CSS已接通，只读与保护表可用；按工作簿核心
对象隔离，loadOperations/reset/dispose释放timer并清新会话状态，单纯关闭保留
列表。源每次20、稳定sheetId与坐标语义保留；官方显示值/公式读取，不写草稿。
本地对缩表越界/读取暂时失效显示gone，按key复用DOM只更新文字，轮询不丢
删除控件焦点。此处不是完整浏览器验收。

`/tmp/watch-window-red.log` 新模块缺失及真实main未接RED；
`/tmp/watch-window-final-tests.log` 3项GREEN（源语义/只读保护Ribbon/真实main
snapshot-draft-history-status不变）；新增焦点/越界
`/tmp/watch-window-focus-red.log`→`/tmp/watch-window-focus-green.log`，最终
watch模块3项GREEN。`/tmp/watch-window-types-final.log`窄types通过。
SOURCE.md已追加固定源SHA。等待root统一构建后运行新独立built，不重复已有
公式追踪等已通过完整测试，当前不记最终交付。
