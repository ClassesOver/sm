# XLSX 多图选择、快速布局、配色与饼图标签专项验收

日期：2026-11-13。固定源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。范围仅为已解析图表的选择与目标操作、四种快速布局、五套配色，以及 pie/doughnut 标签的读取和画布接线，不代表完整图表功能对齐。

**当前结论：限定范围的定向自动验证、统一隔离生产构建及真实浏览器保存/下载/重开已通过。最终 manifest 为 `0015c3b33b9184ffa601a0d60d3d501b498986b98865d7d41eb1e4f6accf3bfe`。桌面 Excel 与完整图表功能族未验。**

## 固定源行为依据

源目录为 `/home/junge/pros/genoffice-source-full`，以下均依据该固定 commit 的实际实现，不以能力矩阵代替源码。

| 源文件 | 本轮复用语义 |
| --- | --- |
| `apps/sheets/src/renderer/ribbon-actions.ts:295–373` | 按选中图表身份编辑；布局同时设置图例与可写标签；饼图逐点配色上限 64，其余逐系列上限 24，循环取色。 |
| `apps/sheets/src/renderer/app-constants.ts:17–36` | `office`、`blue`、`green`、`warm`、`gray` 的完整颜色序列。 |
| `apps/sheets/src/renderer/ExcelShell.tsx:2185–2212`、`i18n/app/zh.ts:684–686` | 快速布局、配色菜单及中文标签；本地对不能标注的图类不宣称会添加标签。 |
| `packages/xlsx-gateway/src/domain/chart-visual.ts:409` | bar/line/area/pie/doughnut plot 可标注；组合图含可标注 plot 时不一律禁用，保存只改第一个匹配 plot。 |
| `apps/sheets/src/renderer/WorkbookVisuals.tsx:3786–3795,4940–5130` | 饼图份额、百分比格式、内外标签及引导线；小于 0.5% 不标注，默认 9% 起内标，圆环标签位于内外半径中间。 |

源摘录保存在 `/tmp/office-xlsx-chart-presets-20261113/source-{ribbon-actions,palettes,menu,pie-labels}.txt`。

## 实际接线与接口

下列前端路径均相对 `smart_reporting/report_editor/frontend/src/`：

- `workbook-chart-geometry.ts`：`chartBounds(anchor,cellAt)` 复用锚点与 EMU 偏移；`chartAtPoint(charts,point,cellAt)` 从上层图表开始命中。renderer 与选择 controller 使用同一几何。
- `workbook-chart-selection.ts`：`installWorkbookChartSelection(root,runtime,options)` 返回 `current/select/reset/dispose`；经实际 viewport、滚动、缩放及表头变换定位图表，切表/实例替换/卸载清理选择。图表内 pointerdown/click/dblclick 拦截避免穿透到网格编辑；按 pointerId 认领起始手势，在所属 window capture 消费匹配的 pointerup/cancel（包含移出图框），blur/reset/dispose 清理；普通网格、输入框、IME、修饰键删除不接管。
- `workbook-chart-selection-state.ts`：`selectedChartPath/setSelectedChartPath` 按工作簿、工作表保存 renderer 选择状态；`workbook-vendor/grid/chart-render.ts` 绘制选中边框。
- `workbook-chart-descriptions.ts`：`open(sheetName,charts,worksheet,select)` 第四参数提供按 `chartPath` 的键盘选择按钮；同名标题不作为身份。
- `workbook-main.ts`：`chartTarget/validateChartTarget/applyChartOperation` 将已选中图表优先、单图默认、多图无选择提示统一到操作链路。删除、切换行列、替换数据、标题/图例/轴/标签/格式/类型和预设均先采集 `currentOperations()`，异步后复检实际 workbook/sheet 对象、来源、图表对象、保护与编辑状态；采集中草稿变化则拒绝覆盖。Delete 与按钮共用删除函数。`loadOperations` 先清旧选择，再在同来源、同图仍存在时重绑。
- 完整图表重放后将操作前后状态登记到现有 NativeDraft，并设置 `gridChanged=false`，使 File 撤销/恢复使用草稿历史；人工单元格修改仍先被捕获并保留。
- `workbook-chart-presets.ts`：`chartPresetEdit(command,source)` 返回可直接登记的图表改动字段或 `null`；`chartPresetMenuOptions(kind,source,editable)` 返回 `{command,label,disabled}[]`。`ChartPresetSource={isPie,canLabel,seriesCount,categoryCount}` 中 `isPie` 包含 doughnut。
- `workbook-ribbon.ts`：`chart():ChartPresetSource|null` 为目标状态，菜单使用真实 SVG 图标与中文选项；无目标、只读或保护时禁用，选择变化刷新。
- `workbook-vendor/grid/chart-pie-data-labels.ts`：`paintPieDataLabels(ctx,spec,values,worksheet,{cx,cy,radius,innerRadius},plot)` 在切片与圆环打孔后绘制，分类复用 `chartCategoryLabels`，保持缺失点索引，按 plot/series/point 层继承字体、颜色及格式。renderer 为标签预留空间并接入分类图例。
- `smart_reporting/reporting/workbook_engine/packages/xlsx-engine/src/chart-read.ts`：为 pie/doughnut 的 plot、series、point 读取 `showCategory/showPercent`，复用既有样式、主题颜色、数字格式与复杂设置识别；柱形图原有保守处理不放开。

| 命令 | 实际改动 |
| --- | --- |
| `chart-layout:1` | 右侧图例 + 标签 |
| `chart-layout:2` | 顶部图例 + 标签 |
| `chart-layout:3` | 底部图例 + 无标签 |
| `chart-layout:4` | 无图例 + 标签 |
| `chart-colors:office\|blue\|green\|warm\|gray` | 源配色；饼图/圆环图系列 0 逐点，其余逐系列，分别最多 64/24 项。 |

可标注轴图布局写 `value`，pie/doughnut 写 `category-percent`，scatter/radar 仅改图例。百分比按可见非负值的份额计算，默认整数 `0%`；只用标签显式百分比格式处理份额，不误用源单元格货币格式。

## 验证证据与复验命令

证据根目录：`/tmp/office-xlsx-chart-selection-20261113`（下称 selection）、`/tmp/office-xlsx-chart-presets-20261113`（下称 presets）。下表是各次定向验证记录，包含继承回归与交叠用例，**不得把重跑次数或各行计数相加当作独立新增 case 数**。

| 证据 | 实际结果与范围 |
| --- | --- |
| selection `main-red.log` → `main-green.log` | 多图同名目标原先缺选择入口，RED 后通过；改第二图标题、删除第二图并保存，人工 A1 修改仍在。1 项通过。 |
| selection `main-preset-guards.log` | 2 项通过：pie 连续配色/布局后保留第二图选择和人工草稿；实际工作表对象替换后，即使 sheet ID/图路径相同，拒绝旧对话框。 |
| selection `main-keyboard-guard.log` | 1 项通过：异步采集后保护复检；保护时 Delete 拒绝，解保护后同链路删除。以上 main 共 4 个独立定向用例，未运行完整 68 项。 |
| selection `root-integration-green.log` | renderer 77、selection 9、descriptions 11、ribbon-presets 2，共 99 项通过，包含既有回归。 |
| selection `input-boundaries-green.log` | 修饰键删除透传、图内双击不穿透 2 项通过，其余 9 项跳过；对应 `modifiers-red.log`、`dblclick-red.log`。 |
| selection `blank-category-red.log` → `blank-category-green.log` | 空分类不抑制饼图的单项回归 RED→GREEN；最终汇总及后续扩展覆盖以 root 后补结果为准。 |
| presets `red-behavior.log` → `green-integration.log` | 空实现 19 失败后，24 项通过：布局/图类能力/五套配色/循环和上限/菜单状态，以及 column、pie、doughnut 经真实引擎保存并独立回读、解包检查标签开关。 |
| presets `pie-read-red.log`、`pie-red.log` → `pie-green.log` | 饼图标签原先读取缺失、绘制空实现；新增读取与绘制 7 项通过。`pie-read-final.log` 的 2 项是追加逐系列/逐点覆写与 bestFit 检查后的同组复验，不另计新增 2 项。 |
| presets `pie-bar-regression.log` | 柱形标签读取、样式、主题颜色 53 项既有回归通过。 |

在仓库根目录按需要定向复验，不重复完整测试：

```bash
cd smart_reporting/report_editor/frontend
npx vitest run src/workbook-main-calculation.test.ts -t 'targets the selected same-title chart|selected pie chart|actual worksheet is replaced|rechecks protection after async chart capture'
npx vitest run src/workbook-chart-selection.test.ts src/workbook-chart-descriptions.test.ts src/workbook-chart-ribbon-presets.test.ts src/workbook-vendor/grid/chart-render.test.ts
npx vitest run src/workbook-chart-presets.test.ts src/workbook-chart-pie-label-read.test.ts src/workbook-vendor/grid/chart-pie-data-labels.test.ts
```

初次 frontend typecheck 曾发现空分类 `string|null` 与图例接口不匹配，记录在 selection `frontend-typecheck.log`；不能引用该日志作为通过证据。root 已补空分类处理；最终完整前端 typecheck 已退出0，见 `frontend-typecheck-history.log`。presets 的单模块与 pie helper 定向严格类型检查不替代最终构建。

## 最终构建与真实宿主证据

统一冻结目录 `/tmp/office-four-format-source-increment-20261113/static`，最终 manifest 如页首。`npx tsc --noEmit` 与 `npx vite build --config .vite-office-source-increment.config.ts` 均退出0，最后 Vite 43.98秒，日志 `build-history.log`。对实际隔离产物调用原 `checkBuildBudget`，`budget-history.json` 为394个JS、failures=[]，未改阈值。此前6bb及失败构建分别保留，不称零构建告警；既有模块指令、循环chunk、PURE注释、字体URL和大chunk提示仍存在。临时配置归档后移除，不覆盖共享 static/dist。

- `pointer-ownership-red.log` → `pointer-ownership-green.log`：最终选择控制器13项通过，包含移出图框/window pointerup/cancel、blur与卸载清理。早期只拦DOM dblclick不足：Univer在pointerup自行合成双击并进入单元格编辑；真实失败目录 `browser-built-frozen`/`browser-built-focus` 保留，最终浏览器双击两帧后焦点仍在图表网格。
- `blank-category-slots-green.log`：外部并发新增的2个空分类/原始数值定向用例通过；不归为本轮独占编写，不把77项历史renderer结果称为所有后补测试最终全跑。
- `main-palette-history-red.log` → `main-palette-history-source-green.log`：新增1项主集成先失败后通过；撤销恢复操作前独立读取的原始配色，重做/保存回读为绿色，人工A1=9全程保留。此前4项主图表定向在同一修复版本运行均通过，不重复完整69项。中间测试曾错误假设来源无点色及 inert 必为 false，失败日志保留；最终断言精确对照来源。
- 最终 `browser-built-history/summary.json` 为 ok=true，脚本为 `frontend/smoke/workbook-chart-selection-smoke.mjs`，复用 `workbook-ai-charts-server.py` 的真实 grant/cookie/CSRF、NativeImport/Editor/Publication、工作区文件与隔离Node writer；修订仓库是限定内存夹具，未调用AI，plannerCalls=0。
- 真实流程：人工A1加粗 → canvas双击选择第二张同名图并保持焦点 → Escape → 说明面板Enter选择第二图 → 改标题Selected → pie → 四布局及返回布局2 → green配色、Q1/Q2与33%/67%绘制 → File撤销/恢复 → reload自动恢复草稿 → 保存4→5、点击真实下载、明确重开 → 75%缩放canvas再选第二图 → Delete → 保存5→6、点击真实下载与明确重开。
- 171个实际JS/CSS响应逐SHA与冻结磁盘相同，四类错误数组均为空。两次下载与保存返回身份及新修订 `/api/file` 字节一致。两次 `validation.ok=false` 均保留具体 `native_source_review_pending`，仍提供下载；此处不替代完整发布故障注入契约。
- `workbook-chart-selection-verify.py` 使用独立 openpyxl/lxml/ZIP 回读两份真实下载：人工A1=Quarter且bold、B2=10/B3=20，编辑后第二图为Selected/pie/top/category-percent与两点375623/548235；删除后仅余第一图，第一图XML在两文件中均与原始字节相同。没有声称所有ZIP成员或桌面Excel完全等价。
- root目视 `selected-second.png`、`pie-preview.png`、`deleted-reopened.png`：蓝色选择框、18px菜单图标、75%下分类图例/33%与67%完整可读、删除后原图与A1加粗仍在。`pixel-colors.json` 独立计数截图两种实际绿色8206/16578像素，不以文字绘制调用替代截图。

完整浏览器也保留中间脚本失败：离屏canvas被误当可见画布、未切File找撤销、错误期待撤销后无点色；分别修正测试坐标/菜单路径/来源精确对照，未放宽最终图表身份或保存断言。产品双击及历史路由缺陷另有真实失败与RED/GREEN证据。

## 保留边界

- 本轮只提供对象选择，不支持拖动、resize、旋转或复杂图表格式面板，不宣称替代源桌面全部对象操作。
- line/area/combo 等可保存布局标签，不代表本地已实现这些图类的完整标签预览；组合图仅首个匹配 plot 的写入语义保持，未实现全 plot 标签视觉对齐。
- pie/doughnut 标签超过 500 点不绘制；复杂自定义文字、手动布局和其他不支持设置不伪造预览；越界、碰撞或放不下的标签省略。分类按源语义截断，数字不截成误导值。
- 爆炸偏移、非默认圆环孔径及复杂图表的读写/显示差异仍需单独验收；当前绘制使用既有 50% 圆环孔径。
- 整个 GenOffice 功能集穷举、所有图表格式无损往返及桌面 Excel 打开均未由本页关闭。本页也不替代发布/下载非阻断契约验收。


归档时发现共享源码有外部并发漂移，见`/tmp/office-four-format-source-increment-20261113/source-history-postbuild-drift.json`：包括workbook-ribbon及docx/focus-trap/pdf-object-dialog等9文件。0015的ribbon产物相对6bb除局部标识符改名外，实际新增defaultPrevented/isComposing/keyCode229键盘守卫；该外部变化被保留，不归为本批独占修复，也未单独补做该守卫专项。最终171资源与完整XLSX浏览器结论绑定实际0015静态文件；不宣称整个当前工作区已通过相同验证。`source-final-identities.json`逐文件记录当前归档SHA及与构建开始身份是否相同，不将当前副本冒称所有原始受测源码。没有为追赶并发状态反复构建或覆盖他人改动。
