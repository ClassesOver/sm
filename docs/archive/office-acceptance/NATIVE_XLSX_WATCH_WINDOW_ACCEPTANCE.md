# XLSX 监视窗口验收

2026-11-10。固定源GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，
源功能/实际探针/SHA见 `NATIVE_XLSX_WATCH_WINDOW_INVESTIGATION.md` 和
`frontend/src/workbook-vendor/SOURCE.md`。

监视窗口按稳定sheetId+坐标显示官方格式化值及公式，每次最多新增20格（不是
总cap），重复去重；关闭保留列表，重新加载/工作簿替换清会话。保护只读可用，
不持久化文件、草稿或历史。仅面板打开时800ms刷新，按key保留DOM和键盘焦点；
缩表越界/来源失效标gone，替换/dispose清timer。插行后仍读取原坐标，并不追随
原内容。保存后仅锁网格/AI表单，面板增删关闭和真实Ribbon重开仍可使用。

## 测试与构建

`/tmp/watch-window-red.log`有效RED：模块不存在，真实main无入口。
`/tmp/watch-window-final-tests.log`3项GREEN（源语义、保护只读Ribbon、真实main
snapshot/draft/history/status不变）；焦点/缩表
`/tmp/watch-window-focus-{red,green}.log` RED→GREEN，最终模块3项GREEN。
`/tmp/watch-window-types-final.log`窄types通过。
root保存宿主/锁范围修复定向 `/tmp/watch-saved-host-{red,green}.log`；真实main
公开facade删除+Undo监视gone恢复 `/tmp/watch-window-facade-delete2.log` GREEN，
新增表后等待其事务完成再删除，首同步过早probe失败保留。

首七case使用`/tmp/office-table-alignment-watch-final-build.log`（完整tsc、
Vite40.12s），budget/contract通过，main249.4/watch2.7KiB不升cap。
保存后宿主及导航锁修复后，新dist
`/tmp/office-alignment-watch-saved-navigation-build.log`完整tsc+Vite40.23s，
budget/contract通过；仅补受影响saved和未完成tail，不重复首七case。
不将两份build冒称同一个dist验收。

## 实际浏览器证据

| 范围 | 真实结果 | 日志/目录 |
|---|---|---|
| 首七case，旧dist | 保护表30格首加20/再加30/去重；12.5%格式值；800ms后删除键盘焦点；关闭重开/删除项/跨表不串；源下载SHA不变且草稿/history/status不变；真实输入7→公式21，Undo→6；插行后坐标空值；rename保ID | `/tmp/watch-window-built.log` / `/tmp/watch-window-built-0hjUBO`，7case即时cases.json、assets.json |
| saved，新dist | 非native独立built harness导入公开模块，真实UI输入/一次save，注册修订无editorURL；grid.inert=true、editor.inert=false，面板增删关闭，真实Ribbon再开；状态/存储/历史可用状态不变，114JS200/SHA、pageErrors=[]、save1 | `/tmp/watch-window-built-saved.log` exit0 / `/tmp/watch-window-built-Vq349V` |
| reload/revision，新dist | rename前置后reload空列表，再添加1项→revision2空列表；357JS200/SHA、pageErrors=[]、save0 | `/tmp/watch-window-built-tail-final.log` exit0 / `/tmp/watch-window-built-VNmEtL` |

saved截图：`/tmp/watch-window-built-Vq349V/saved-host-interactive.png`。
每case立即保存行文字、截图路径/SHA；每次真实JS响应立即保存HTTP状态/磁盘
SHA校验清单。总manifest `/tmp/watch-window-acceptance-manifest.json` 汇总两份
build的真实范围、截图、资产清单身份、各次独立source/download身份。
最后tail来源SHA为
`09d309db73341c1a7b460a1df6c544969cd5e870176d2a0a62ecaf1b96fdef0e`，
不与首跑生成ZIP的时间戳身份混淆。

## 限制与失败保留

浏览器UI删表没有通过。最初getByText last误中监视删除项，后限定官方
ContextMenuPanel仍位于(-9997,-9997)，关闭监视窗口后也复现；DOM证据
`/tmp/watch-window-built-mkujol/menu-diagnostic.json`，失败截图/日志保留。
role/id猜测与resize探针未解决，已停止重复，不force点击、未改产品菜单。
删表失效/Undo仅记真实main公开facade测试通过，不能写成浏览器UI删表通过。

本功能是会话只读监视，不扩展公式图、编辑器持久化或Plotly。可编辑输入和
rename/插行场景有真实编辑，未冒称零修改。HTTP授权/修订为本地夹具，XLSX
字节/下载/浏览器真实，不证明生产鉴权、桌面Excel或非native保存后端等价。
