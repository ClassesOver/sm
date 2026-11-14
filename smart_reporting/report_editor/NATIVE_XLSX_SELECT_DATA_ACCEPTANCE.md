# XLSX 固定源单图层 Select Data

日期：2026-11-13。固定源 `/home/junge/pros/genoffice-source-full`，实际提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 本轮边界与源行为

本轮只补已有 writer 支持的七个单 plot 家族（barChart 对应柱形/条形两种方向，以及 line/area/pie/doughnut/radar/scatter）。不新增图表或新的绘图体系，不扩展 Plotly，不改发布、授权、非阻断签发协议。原先 Ribbon 的“选择数据”会立即使用当前选区整体覆盖系列，没有可取消的系列编辑界面。

| 固定源 | 本地补齐 |
| --- | --- |
| `apps/sheets/src/renderer/ChartPanels.tsx:382–485` | 按原系列初始化名称、保留数值/分类引用为 placeholder；可分别换绑向量，名称 trim 后为空则保留原名或使用“系列 N”，名称和分类文字最多 255 字符；按源将数值无法转换项写为 0 |
| `ChartPanels.tsx:518–636` | 添加、删除、上移、下移；添加至 24 行后禁用；至少留一个系列；新系列必须有数值区域；确认一次提交完整 seriesSet，取消/Escape 不写草稿 |
| `univer-sync.ts:2486–2556` | 裸区域默认图表所在表；限定当前工作簿、跨表名称不区分大小写，支持单引号转义；只读一行或一列、最多 1000 单元格；使用实际 FRange.getRawValues 与绝对引用，不把格式化展示文字当原始值 |
| `packages/xlsx-gateway/src/domain/chart-visual.ts:374–388` | 对原系列缓存执行切换行/列，最多前 24 个分类，缺失值补 0；输出无引用的字面系列，与固定源一致，不改成旧本地的“仅连续引用矩形可切换”算法 |
| 本地必要读取前置 | 既有 writer 已写 numLit，但 reader 原先直接丢弃无 valuesRef 系列，导致转置后整个图表不可读。仅补 `ChartReadSeries.values?` 和 numLit 读取，并让原图表预览在无引用时使用这些字面值；带引用图表继续读取实时网格 |

宿主身份复核沿原 `validateChartTarget` / `applyChartOperation`：工作簿 core、工作表 core、源 bytes 和图表对象均须仍匹配，保护/只读/保存态仍拒写。公式值读取前等待 Univer 原生结果应用，再复核目标。读取期间取消/dispose 会丢弃迟到结果；实际应用期间禁用重复提交/关闭，失败保留输入及具体原因。重复打开不能替换正在应用的目标。

明确未补：固定源支持的 bar+line 组合图逐系列 plot 类型与 secondaryAxis；本地原 writer 仍明确拒绝组合图整体替换，不能把本轮单 plot 通过写成全部 Select Data 对齐。3D、外部工作簿、命名区域、超限向量不作已支持声明。

## 定向 TDD 证据

证据目录 `/dev/shm/office-next-xlsx-source-gap-20261113`。

- `select-data-host-red.log`：旧实现真实执行即时覆盖，没有新对话框，新增宿主用例失败。
- `literal-readback-red.log`：真实 writer 将 seriesSet 写成 numLit 后，原 reader 丢弃系列与图表，独立回读用例失败。
- `select-data-host-initial.log`：接线后首次一秒默认等待不足以完成原工作簿重建；没有用假 apply 替换。`select-data-host-diagnostic.log` 改为最多十秒等待真实重建后通过，未绕过写入或读回断言。
- `select-data-host-final.log`：三个定向宿主用例通过、其余八个未重复：逐系列换绑经 writer 落盘、替换工作簿身份拒写并保留人工草稿、源 literal 转置保存并重开同数据。
- `select-data-dialog-render-final.log`：13 passed / 83 skipped：dialog 八例、真实 writer literal 回读一例、已有 native renderer 的柱/条/饼/圆环 literal 预览四例。与宿主三例共 16 个独立定向用例，前序重复运行不累加。
- 仅原有 Univer `getSnapshot` 弃用 stderr；未运行完整 suite，未单独构建共享 static/dist。自身 `git diff --check`、HTTP runner `node --check`、独立 verifier `py_compile` 已通过。

## 冻结与真实 HTTP

产品写入后冻结；root 完成统一物理快照、类型检查、Vite、四桥及原体积门禁后实际运行：

- `frontend/smoke/workbook-chart-data-smoke.mjs`
- `frontend/smoke/workbook-chart-data-verify.py`

`browser-frozen-01.log` / `browser-frozen-01/evidence.json` **exit 0**，本轮首次真实 HTTP 完整链通过，只有一次保存、零 planner 调用。未 mock writer、journal、HTTP、发布或下载链。

实际完成：保留真实人工 J2 值和 bold → 取消/Escape 无图表写入 → 跨 `'O''Brien Data'` 的数值/分类向量、改名、删除、添加、重排 → 390px 点击确定并由原 writer 写入第一次完整 seriesSet → 源行列转置生成 literal 第二次 seriesSet → 刷新恢复 → 一次保存 parent 4 → revision 5 → 授权下载 → openpyxl/lxml/ZIP 独立回读 → 授权新修订重开同身份，再打开 SelectData 看到系列 A/B。

独立回读确认最终两个系列为 A/B，分类均为 Added/Renamed，值分别 `[11,5]` / `[12,8]`，OOXML 使用 numLit/strLit 且不伪造 c:f。J2 人工文字 `Manual select draft` 与 bold 正确，原 A1:D3 数据、原图表 title 保留；除 chart1、sheet1、styles 外其余 11 个包 part 原字节一致，未新增或删除 part。第一步系列检查点另确认跨表绝对引用、数值缓存、重排后的名称与原 `#123456` 颜色保持。

`save-checkpoint.json` 在保存后立即保留真实 API 响应：`revisionRegistered: true`、`validation.ok: false`、`native_source_review_pending`，且实际 XLSX 下载链接签发并成功下载。业务验收不标通过。`first-series-checkpoint.json`、`independent-checkpoint.json`、`asset-checkpoint.json` 均在最终总断言前持久保存。

四幅桌面、390px、390px 确定按钮及保存后重开截图已实际目视：无重叠或横向溢出；窄屏卡片 left=20/right=378，clientWidth=scrollWidth=356；确定按钮 x=291/y=586.75/width=60/height=36，位于 390×844 viewport，实际完成提交。浏览器 Chromium `140.0.7339.16`，canvas 字体探针通过。

173 个实际加载 JS/CSS 与冻结物理文件 SHA-256 一致；pageerror、console error、HTTP error、资源身份错误均为 0。四个后端文件实际运行 **live 工作区**，启动/结束 SHA 一致，不能称其为冻结后端副本。统一构建与门禁由 root 执行，本专项没有自行重建共享产物。

## 最终 minimal 构建零保存续验

原 `352eb5…` 完整保存链保持有效，未重复保存或签发。root 为 PDF 首次 HTTP 初始化 TDZ 仅覆盖两处 `document` 短路表达式并统一重建，最终 manifest 改为 `b8b97ee76d41a565f94e9f8c902e226031ada09ad9cd3bcf52deb886f421f04c`；本专项产品不变。该最终构建只做以下只读兼容续验，不把它称为新的完整保存验收。

`frontend/smoke/workbook-chart-data-readonly-smoke.mjs` 使用原完整链实际下载的 `selected-data.xlsx`，通过原授权导入宿主重新打开。`browser-final-readonly-01.log` / `browser-final-readonly-01/evidence.json` **exit 0**；独立输入仍为 7124 bytes、SHA-256 `93c520c470488a4f3943ea7b07392683eeb2cd23cb9df755eb55b084d74f3c22`，HTTP `/api/file` 的实际响应字节也与该文件一致。

- literal 图表实际显示 A/B 与 Added/Renamed，数值仍为 `[11,5]` / `[12,8]`。除模型回读外，从实际 canvas RGBA 中各找到两根对应颜色的连通柱体，第一色高度 245/111、第二色 267/178，比例与原数值吻合。
- 真实打开 SelectData，看到 A/B；390×844 窄屏滚到取消按钮并实际取消，`ops=[]`。`savedRevisions=0`、`plannerCalls=0`，184 个 HTTP 请求中 POST 为 0，没有再次保存或签发。
- 实际 HTTP HTML SHA-256 为 `aaa3eb21c2eb976afff3d1ae6a7ace757b75e2613a1b7272c6613cc4728a29c2`，与最终 `native.html` 原字节一致；实际模块入口为 `assets/lazy-preload-helper-BPPmGX_j.js` 与 `assets/lazy-unified-main-D3q1w4ic.js`，均唯一匹配 manifest 文件项且已实际加载。未假定 manifest 存在 `src/unified-main.ts` 或 `native.html` 键。
- 173 个实际静态资源（149 JS、24 CSS）逐项 SHA-256 匹配最终物理文件；pageerror、console error、HTTP error、资源身份错误均为空。manifest 与工作簿桥结束时身份未变，桥仍为 `fc4b32…`。
- 四个后端仍实际运行 live 工作区，起止 SHA 与下表原完整链一致，没有将其它会话的 live 修改纳入本专项；不称冻结后端副本。
- `literal-render.png`、`readonly-dialog.png`、`readonly-mobile.png` 三幅截图已实际目视，确认图表可见、桌面布局完整、窄屏单列卡片和取消/确定按钮可见。

本层只确认最终 minimal 构建对同一已下载文件的读取与对话框兼容性；原 `native_source_review_pending` 业务验收状态不变，未标记业务验收通过。

## 原完整保存链物理身份

| 对象 | SHA-256 |
| --- | --- |
| 原完整链构建 manifest | `352eb5fc3903b0d6c145c1f1e873e2ad983a2f58b7ec1e0d3567f18b3ba1a560` |
| 实际工作簿桥 | `fc4b32d351ddc2a14b336769968b2e59e689d13ef0145b28047ecc50504104ec` |
| 原 XLSX fixture | `6948895836f46a3cd747ab236d4e6fe2c361d1f66325b0513f3204aeab32955c` |
| 实际下载 XLSX（7124 bytes） | `93c520c470488a4f3943ea7b07392683eeb2cd23cb9df755eb55b084d74f3c22` |
| 新 `workbook-chart-data-dialog.ts` | `b5b2daf6f09776afd598d8afc48ced1028cd4742d3c0cbf8bff4edd1503c1eab` |
| 新 `workbook-chart-data-dialog.css` | `c8c946f02fe5dbc2149c9806af76149968390f5bc950ec8fb97fbcc669410d15` |
| `chart-read.ts` | `de677a0a16699df2acb62d59824c4d1fd92a936b2427c146f8ae8e9402037d6d` |
| `grid/chart-render.ts` | `f043a65d8ef514e442d80c04e5c333d6d71414ee520bfcaa14333524b03b1c22` |
| live `reporting/delivery/office_engine.py` | `46ebe5b4daa68ac076deaee474f491eb505dbbdeadbda62dca72b57901b1d236` |
| live `report_editor/native_office.py` | `c3ed7eb513e0aa6510294b23bb17b334642741a01ecb8e778e81cf48c68fa207` |
| live `report_editor/native.py` | `679bfa60e8b06267f77f5bae00f48c92d054d737cfc048f5f0f2c041ac7c73d6` |
| live `report_editor/native_api.py` | `1c53008a9f48a3c6a84e12e2ec3a6700f04d1f637c573e86eb600ee239196a3c` |

最终 minimal 静态目录 `/dev/shm/office-next-split-master-chart-home-20261113/source/smart_reporting/report_editor/static`；工作簿桥同快照 `source/smart_reporting/reporting/workbook_engine`。原 `352eb5…` 完整链与最终 `b8b97ee…` 零保存续验证据分别保留，不混为同一次构建。本专项产品写完后没有再变更；只补验收脚本与专项记录。不改三份总审计，不 commit/push。
