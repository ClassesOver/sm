# XLSX 图表对象移动与八向缩放

日期：2026-11-13。固定源：`/home/junge/pros/genoffice-source-full`，提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 来源与边界

- `WorkbookVisuals.tsx` 的 marker walking、真实行列尺寸、zoom、RTL、24px 下限和八向控制点语义移植到局部模块。
- `xlsx-drawing-edit.ts` 的来源锚点 writer 分支移植为 `applyChartAnchors`，按真实 worksheet/drawing/chart 关系定位对象，校验旧锚点后仅修改目标 marker。
- `twoCellAnchor` 支持移动和缩放；`oneCellAnchor` 只支持移动并保留 `xdr:ext`；`absoluteAnchor` 按来源明确拒绝移动/缩放。界面不会给后两者显示可用的八向缩放控制点。
- 不改图表数据、样式或图表 XML。保全校验针对 ZIP entry 解压后内容字节；打包器可能重压缩，不能声称整个 ZIP 压缩字节不变。

## 交互与接线

主 canvas 以精确 chartPath 选择目标，鼠标拖动只显示临时边框，pointerup 才写入既有 operations 草稿。Escape、wheel、pointercancel、blur、视图或当前 sheet 变化取消预览；取消后的 pointerup 仍由认领手势消费，防止原生网格合成双击进入单元格编辑。

提交复用既有 `applyChartOperation`、手工草稿、File Undo/Redo、保存修订、授权下载。writer 先预检再重载，旧锚点失配不会让编辑器停在 loading 状态。保存重放根据图表末端扩展原生行列数，支持拖出初始数据网格后继续选择。

## 定向证据

证据目录：`/tmp/office-xlsx-chart-geometry-20261113`。不重复运行完整 suite。

| 日志 | 结果与范围 |
| --- | --- |
| `anchor-red.log` | 新协议未实现时的失败证据，早期 fixture 缺引用已修正 |
| `geometry-red.log` | 几何 stub 下 13 例失败 |
| `interaction-red.log` | 交互 stub 下 6 例失败、4 例通过 |
| `interaction-geometry-render-green.log` | 当时 133 例通过：anchor、geometry、interaction、renderer、selection 定向集合；不能与后续重跑累计为新增例数 |
| `python-anchor-source-green.log` | 1 例通过，真实 Python→TS bridge→ZIP/openpyxl 独立回读 |
| `main-grid-extent-red.log` / `preview-grid-extent-red.log` | 提交后网格未扩展、越初始网格预览缺失的 RED 证据 |
| `interaction-grid-final-green.log` | geometry 15 例 + interaction 当时 11 例，共 26 例通过 |
| `cancel-pointer-red.log` / `interaction-final-green.log` | 取消后释放事件回归 RED→GREEN；最后 interaction 12 例通过 |
| `main-stale-anchor-red.log` / `main-final-green.log` | writer 拒绝后 loading 锁定回归 RED→GREEN；最后主集成 5 passed / 68 skipped（共73例） |
| `engine-typecheck.log` | package 与 bridge 类型检查通过，之后 engine 源码未改 |
| `native-save-red.log` / `native-save-green.log` | 独立回读用例改走真实 `patch_office`，服务端第二层白名单缺口 RED 1 failed → GREEN 1 passed |

最后主集成 5 例覆盖：旧 palette File Undo/Redo、几何保存/越初始网格/手工 A1/UndoRedo、异步保护变化、worksheet 替换、原生插行后旧锚点拒绝且编辑器可用、草稿保留。

`frontend-typecheck.log` 是收尾前的中间检查；最终前端类型与构建由父代理统一冻结验证，不能用该旧日志宣称最后源码通过。

## 真实浏览器验收

专用脚本：

- `frontend/smoke/workbook-chart-object-geometry-smoke.mjs`
- `frontend/smoke/workbook-chart-object-geometry-verify.py`

运行要求显式提供冻结的 `PDF_SMOKE_STATIC_DIRECTORY` 与 `AGENT_REPORTING_WORKBOOK_ENGINE_DIR`。脚本不构建或修改共享 dist，启动现有受控修订宿主，核对 HTTP JS/CSS 与磁盘哈希、manifest 和 bridge 冻结前后哈希。

脚本覆盖真实图2 canvas 移动、八方向缩放、24px 后选择与移动、Escape/wheel 取消、File Undo/Redo、75% zoom、RTL、手工 A1 值与加粗、reload 草稿恢复、新修订保存、授权下载、重开。独立 verify 检查目标锚点、原图1锚点原字节、两张图 chart part 原字节、其他非允许 entry 原字节、数据及 A1 格式保留。

### 分阶段真实证据

最终通过：`/tmp/workbook-chart-geometry-browser7-20261113/summary.json`，终端日志 `/tmp/office-xlsx-chart-geometry-20261113/browser-frozen7.log`，exit 0。为遵守不重复完整测试，手势与保存按以下阶段续验，没有把跨构建证据合称为同一包首次全量执行。

1. `browser4`：87a 前端完成14条真实手势，包括移动、八向缩放、24px 后选择/移动、取消、Undo/Redo、75% 操作。`eight-handles.png` 与 `minimum24.png` 留存。该轮在 RTL 入口因 smoke 把实际属于 View 的命令放到 Page Layout 而停止。
2. `browser6`：68ce 最终前端从 `browser4` 原始来源文件和真实 localStorage 草稿恢复，完成 RTL 移动/缩放和草稿 reload；实际保存返回422，暴露 `native_office.py:_XLSX_FIELDS` 漏登记新协议。`rtl75.png`、失败 JSON 和 HTTP 422 保留。
3. 获准仅补 Python 白名单的 `applyChartAnchors: {'edits'}`，原定向测试改走真实原生入口并 RED→GREEN；未改前端和桥。
4. `browser7`：同一68ce包、修复后 Python，从 `browser6` 真实草稿仅续验 reload、保存新修订、授权下载、重开与独立回读。summary 中16条手势包含前两阶段的真实记录，`resumedFrom` 指向来源证据。没有注入伪造几何 operations。

smoke 初期坐标探针问题也保留：`browser1` 视口不足；`browser2/3` 把公式栏 canvas 的矩形与离屏100px缓存边距用于控制点换算。最终改从真实浏览器截图的蓝色原生边框/8px控制点像素定位鼠标；不调用产品几何函数计算期望或模拟提交。

### 最终身份与回读

- manifest：`68ce99975149470621d980fcf040694372b986a4c037e5463f07d85a8edf67e2`
- workbook bridge：`dd4692f17aac01165096c9e3b3e9693a9a6a5ee91626c06756510f2ce12ef1ad`
- 修复后 `native_office.py`：`79eb0bbe143a4e26db7648b46964f6e7f803ab81a96bd3833bc51e20edea001a`
- 修复前 Python 身份（以仅撤回该一行登记计算）：`c10803edca6b5f803573e798e03cb6e1bbcc54f237ef693d2c1df869eded809a`
- 最终下载：`5134476f0eb6ba7ea6526fa28801887fe1a11b2766752536410feeff29e239d7`
- 171项实际 HTTP JS/CSS 与磁盘 SHA 一致；manifest、bridge、Python 源运行前后身份一致。pageerror、console error、HTTP错误、资产错误均为空。
- 修订4→5，`revisionRegistered=true`，下载文件和重开 `/api/file` 均匹配签发身份；planner调用0次。
- 独立 openpyxl/lxml/ZIP 确认：A1 为 `Manual geometry` 且加粗，B2/B3 为10/20，仍为两图；图2锚点与最终真实草稿一致，图1锚点原字节保留，两图 chart part 原字节保留，10个其他非允许 entry 原字节一致。
- 最终锚点：from(row3,col11,rowOff66675,colOff368300)，to(row19,col20,rowOff180975,colOff254000)。
- 保存返回 `validation.ok=false`、具体原因 `native_source_review_pending`，仍成功签发/下载，不把业务验收标为通过。

已人工查看 `eight-handles.png`、`minimum24.png`、`rtl75.png` 和 `geometry-reopened.png`，边框与控制点可读，原图1保留。

### 不扩展本次验收结论

本次证明 zoom/RTL 下几何交互，不宣称视图恢复/持久化通过：既有 `applyPageSetups` 同 sheet 多条 setup（rightToLeft:false 与 zoom100）最终产物仍为 RTL=true、zoom 未写入，疑似既有 writer 多条 setup 覆盖问题，已单独通知父代理，未顺带修改。纯几何和手工数据的独立回读不受影响。
