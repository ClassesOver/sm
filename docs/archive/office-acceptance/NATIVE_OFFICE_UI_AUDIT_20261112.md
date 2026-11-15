# 四格式 UI 核查与局部修复

日期：2026-11-12（工作跨午夜，部分证据目录沿用 20261111）。
初始基线：`code` 分支 `4cfaac23`；后续提交、远端连接结果与冻结构建分别记在各续批，历史基线不代表当前工作区或远端最新状态。
改动保留在工作区，未提交或推送。

## 范围与统计口径

目标仍是逐项核查 XLSX、PDF、DOCX、PPTX 功能组件及 UI。本记录只说明本轮覆盖，不能据此标记整体完成。
最新用户方向：UI 尽可能贴近 PC。后续以桌面 Office 的紧凑工具栏、清晰分组、左标签右字段和合理宽弹窗为主，
窄屏仅做必要的换行与滚动适配。组件夹具的六视口检查继续保留，但不以移动端卡片外观作为设计主导。
功能范围继续以 `smart_reporting/report_editor/NATIVE_GENOFFICE_FOUR_FORMAT_SCOPE.md` 和
`docs/parity/2026-11-10-explicit-ribbon-gaps-inventory.md` 为参照。
固定参考源是 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

新增 TypeScript AST 清单工具 `scripts/office-ui-inventory.mjs`，沿原生入口本地导入闭包枚举
初期732个模块、4452个 UI 声明点（初轮725模块4368点，其后4390/4420/4449点）；当前计数随组件新增持续刷新，以同目录 `NATIVE_OFFICE_UI_INVENTORY_20261112.md` 及末尾续批为准。
这些数字不是功能数量、验收通过数或完成率；不包含外部 npm/引擎包、计算式动态入口和桌面原生菜单。

## 实际修改

- PPTX 自定义尺寸弹窗复用已有表格弹窗外观，补中文无障碍名称、操作区和主按钮样式。
  保留原尺寸换算与未修改坐标精度。
- XLSX 函数弹窗复用 Office 主题字体、颜色和焦点环；修正短屏浮窗溢出，窄屏参数标签独占一行。
  缩放等确认按钮沿用主操作颜色。
- PDF 设置和 PPTX 表格/尺寸弹窗增加局部字体、滚动与焦点样式；PDF 提取按钮放进右对齐操作区。
- DOCX 真实列表按钮暴露了空本地标记误判问题：节点转换会丢弃目标 schema 未声明的空属性。
  `docx-operations.ts` 只归一 `nativeCoverPage/nativeRibbonStyle/nativeRulerIndent/nativeTabStops` 的 null/undefined，
  保留非空意图校验和来源身份检查。新增真实编辑器扩展下的项目符号、编号及非空边界回归。
- 修正最新基线中阻止 TypeScript 构建的两处测试类型错误：重复对象字段和泛型 request mock。
- 更新两处过期验收方式：段落行距弹窗已接入，不再断言禁用；DOCX 字体回读分别核验西文槽和 `w:eastAsia` 中文槽。
  Microsoft YaHei 写入中文槽，不能用仅读取西文槽的 `python-docx r.font.name` 判断其丢失。

## 验证结果

### 构建与定向单元测试

- `npm run build`：通过，包含 TypeScript 检查与 Vite 构建。
  日志 `/tmp/office-ui-build-20261112.log`。
- `npm run check:budget`：通过。PPTX 主模块约 249.9 KiB、DOCX 主模块约 249.6 KiB，接近 250 KiB 上限。
  日志 `/tmp/office-ui-budget-20261112.log`。构建仍有依赖包注释、静态/动态混合导入和大 chunk 提示。
- UI 清单解析器 2 项测试通过。
- DOCX 本轮分批定向覆盖 9 个测试文件、166 个用例，最终均通过：
  operations、notes、ruler-indent、style-majority、tab-stops、ribbon、line-spacing、list-ribbon、font-slots。
  初次回归的旧行距禁用断言失败，修正后重跑 ribbon/line-spacing 共 57 项通过。
  日志 `/tmp/office-ui-docx-regression-20261112.log`（保留初次失败）、
  `/tmp/office-ui-docx-spacing-regression-20261112.log`、
  `/tmp/office-ui-docx-list-green-20261112.log`、`/tmp/office-ui-docx-font-slots-20261112.log`。
- 前一阶段 PPTX/PDF 定向测试 3 文件 31 项通过；另外 6 文件 103 项中 102 项默认限时通过。
  剩余一项 `does not create an undo step when Enter repeats an absolute paragraph value`
  连续执行 501 次界面刷新，默认 5 秒超时；仅该用例使用 CLI `--testTimeout=240000` 后通过，耗时约 158.6 秒。
  未放宽全局超时、删减断言或优化无关代码，不能表述为默认套件全部通过。
  日志 `/tmp/office-ui-regression-20261111.log` 和 `/tmp/office-ui-noop-longcase-20261111.log`。
- 未运行全仓库完整测试，也未重复完整测试。

### 弹窗与功能区视觉覆盖

`smoke/office-dialog-layout-smoke.mjs` 使用实际产品组件构造器及产品 CSS，覆盖
DOCX 注释、XLSX 缩放、XLSX 函数参数、PDF 提取、PPTX 尺寸这 5 种组件。
每种覆盖 1440×900、768×1024、390×844、320×640、640×360、390×320，共 30 个场景通过。
检查边界、字段横向溢出、主题字体/主色、参数输入宽度、Tab 焦点环、Esc 关闭和入口焦点恢复。
证据 `/tmp/office-dialog-layout-20261111/evidence.json`，同目录 30 张截图。
夹具替换必要上下文，不代表生产授权或真实文件保存已验收。

`smoke/office-desktop-layout.mjs` 现记录逐标签可见控件元数据和 1280/768/390 宽度截图。
四视口外壳及当前可见标签布局检查均无 failures：

| 格式 | 当前可见标签状态 | 可见控件记录条数 | 证据目录 |
| --- | ---: | ---: | --- |
| XLSX | 9 | 231 | `/tmp/office-ui-ribbon-20261111` |
| PPTX | 11 | 135 | `/tmp/office-ui-ribbon-20261111` |
| DOCX | 11 | 205 | `/tmp/office-ui-ribbon-20261112` |
| PDF | 6 | 131 | `/tmp/office-ui-ribbon-20261112` |

总计 37 个标签状态、702 条可见控件记录；重复/共享入口没有去重，不能用作独立功能数量。
没有 SVG 的控件另行登记：DOCX 10 个（含 B/I/U、数字/加减字形和文字按钮），PDF 1 个“文本字段属性”。
该启发式不判定其全部为图标缺陷，也不因此宣称图标全通过。部分功能区横向滚动和文档画布裁切是现有布局行为。

### 真实文件操作与回读

以下浏览器场景使用实际构建和文件引擎；除 PDF 提取隔离服务场景外，授权/上下文/修订登记通过夹具模拟。
不代表生产服务全链路或真实 AI 模型已验收。

| 场景 | 结果与边界 | 日志 |
| --- | --- | --- |
| PPTX 自定义尺寸 | 通过；9000000×7200000 EMU、撤销重做、保存下载、独立回读及重开 | `/tmp/office-ui-pptx-save-20261111.log` |
| XLSX 格式与自动求和 | 通过；真实文件回读格式和 SUM；未验证桌面 Excel | `/tmp/office-ui-xlsx-save-20261112.log` |
| XLSX 函数弹窗 | 通过；分类检索、引擎预览、草稿恢复、公式保存/重开、物理 fx 取消和 Shift+F3；本次 preview 模式未执行 range pick | `/tmp/office-ui-xlsx-function-20261112.log` |
| PDF 提取 | 通过；隔离服务、实际提取、下载回读，2 页、38 个静态资源 | `/tmp/office-ui-pdf-extract-20261111.log` |
| PDF 页面布局 | 通过；实际构建、页面操作保存与 PDF 回读 | `/tmp/office-ui-pdf-layout-20261112.log` |
| DOCX 常规保存 | 最终通过；项目符号/编号、插删段落、格式/间距/对齐/缩进、下载哈希和重开；原件不变，模拟验收失败仍保留 Word 下载 | `/tmp/office-ui-docx-save-final-20261112.log` |

## 复现命令

从 `smart_reporting/report_editor/frontend/` 运行；浏览器脚本需要允许本地端口与 Chromium：

```bash
node scripts/office-ui-inventory.mjs --output-dir /tmp/office-ui-inventory
node -e "import('./scripts/office-ui-inventory.test.mjs')"
node smoke/office-dialog-layout-smoke.mjs
NATIVE_GUI_PREVIEW=1 DOCX_SMOKE_PORT=4291 OFFICE_VISUAL_DIR=/tmp/office-ui-ribbon node smoke/docx-native-save-smoke.mjs
NATIVE_GUI_PREVIEW=1 PPTX_SMOKE_MODE=slide-size-custom PPTX_SMOKE_PORT=4290 OFFICE_VISUAL_DIR=/tmp/office-ui-ribbon node smoke/pptx-native-save-smoke.mjs
WORKBOOK_SMOKE_BUILD_DIR=../static WORKBOOK_SMOKE_PORT=4292 OFFICE_VISUAL_DIR=/tmp/office-ui-ribbon node smoke/workbook-native-save-smoke.mjs
OFFICE_VISUAL_DIR=/tmp/office-ui-ribbon PDF_LAYOUT_SMOKE_PORT=4293 node smoke/pdf-layout-smoke.mjs
NATIVE_GUI_PREVIEW=1 node smoke/workbook-insert-function-gui-smoke.mjs
```

## 尚未穷尽

菜单展开及嵌套弹窗、所有表格/图像/图表/表单等上下文选区、禁用条件组合、外部依赖 UI、全部行为的保存回读、
真实 AI 模型与生产授权链路未覆盖完。继续根据声明点定位并建立逐项映射，不能仅凭静态源码或按钮存在标记通过。
上述 SVG 检查候选和 PPTX 501 次刷新用例的默认超时/性能情况也仍需单独核查。

## 后续弹窗批次：表格属性、数据设置与原生图表（2026-11-12）

### 新增覆盖及实改

扩大现有真实组件夹具，加入下列 21 种弹窗/模式，每种仍检查六种视口，共新增 126 个场景：

| 格式 | 新增组件/模式 |
| --- | --- |
| DOCX | 行跨页、列宽、行高、整表对齐、拆分单元格、标题/说明、自动换行 |
| XLSX | 创建表格、分类汇总、合并计算 |
| PDF | 密码保护、Markdown 导出、插入外部页面、替换外部页面、插入文字 |
| PPTX | 对象超链接、图表数据/类型/元素/配色与样式/单点配色五种模式 |

这些是产品构造器与产品 CSS 的组件检查；只替换必要上下文，不执行夹具的保存回调。
累计组件夹具覆盖 26 种模式、156 个不同视口场景，不能作为完整功能族验收分母。

根据失败证据修正：

- PPTX 图表数据使用内部横向滚动区，标题与底部按钮不再被表格横向推走；图表类型网格自适应窄屏，
  样式与配色去除 280/300px 硬最小宽度。点配色行与颜色预览可换行。
- 图表与对象链接使用现有 Office 弹窗字体、边框、字段、焦点环及操作区。保留当前图表数据/类型/样式操作协议。
- 图表弹窗在 Escape、取消、确认关闭后恢复仍连接的入口焦点，保留一次关闭回调。
  先新增 3 项 RED 回归，修复后通过。
- PDF 保护/导出/外部页面/插字共四个构造器复用现有右对齐操作区，主操作明确着色。
  通用输入框规则曾使 checkbox 被拉伸至 34px 高；局部修正为 16px，并让复选框与标签同行。
- 七个 Word 表格属性弹窗使用单独 `docx-table-property-dialog` 类，统一字段分行、标签间距、字体和底部操作排列。
  只影响设置界面；不改变文档纸面或表格数据。
- Word 设置弹窗及 Excel 格式弹窗补齐 select/textarea 的清晰焦点环。

检查器也做了两项口径修正：识别现有主题渐变主按钮，避免把渐变背景色为透明误判为无主色；
允许弹窗内部有真实且可到达末端的横向滚动容器，不把表格正常滚动误判为整体溢出。
容器本身仍必须在弹窗边界内，弹窗自身横向溢出仍失败。新增 checkbox 尺寸守卫。

### 失败与最终证据

- `/tmp/office-dialog-expanded-baseline-20261112/evidence.json`：126 场景、201 条失败检查。
  含上述真实问题，也含旧检查器对合法渐变的误报，不能把 201 全称为产品缺陷。
- `/tmp/office-dialog-expanded-fixed-20261112/evidence.json`：126 场景，剩图表配色在 320×640 的一条溢出。
- `/tmp/office-chart-design-final-20261112/evidence.json`：去除遗留 300px 最小宽度后，仅复核该模式六场景，全部通过。
- `/tmp/office-pdf-checkbox-red-20261112/evidence.json`：12 场景复现 checkbox 被拉伸，每场景均失败。
- `/tmp/office-settings-controls-final-20261112/evidence.json`：七个 Word 表格弹窗及两个 PDF checkbox 弹窗共 54 场景全部通过。
  已人工查看最终 Word 短屏、PDF 保护、PPTX 图表数据/类型/配色截图。

按受影响组件组合上述结果关闭本批问题，没有将它们说成一次最终统一构建上重新跑完的 156 场景。

### 定向回归与实际构建

- 图表与链接 2 文件 23 项通过：`/tmp/office-chart-link-green-20261112.log`。
- PDF 4 文件 40 项通过：`/tmp/office-pdf-dialog-regression-20261112.log`。
- Word 表格设置 7 文件 50 项通过：`/tmp/office-docx-table-settings-20261112.log`。
- 本批合计 13 文件 113 项定向回归通过，没有运行或重复完整项目 suite。
- 最新 `npm run build`（TypeScript + Vite）通过，Vite 44.38 秒；`npm run check:budget` 通过。
  日志 `/tmp/office-ui-settings-final-build-20261112.log`、`/tmp/office-ui-settings-final-budget-20261112.log`。
  最新 manifest SHA256 为 `4c80aa71c24da6b5f3efb82e2bc08084019b6b6a21b5c33b6e06f4d09276b280`。

### 真实保存与独立回读

- PPTX：`/tmp/office-chart-built-expanded-final-20261112/evidence.json` 为 ok:true。
  实际构建、真实 Python/OOXML 引擎，图表数据/类型/元素/行列交换/配色预设/单点颜色，
  取消不提交、UndoRedo、草稿恢复、保存下载、独立 python-pptx/ZIP 回读及修订 2 重开通过；
  121 个实际 JavaScript 资源，page/console/route/HTTP 错误数组为空。
  授权和修订登记为明确 route fixture，未验证生产授权。
- 首次 PPTX 检查在旧本地桥包缺失 `chartStyle` 时失败；源码返回该字段，但运行的 `dist/edit-pptx.mjs` 未更新。
  确认运行目录后执行项目已有 `npm run bundle:bridges`，重建四个 ignored 桥包，再复核成功。
  没有用空对象 fallback 掩盖来源样式缺失，也没有为此修改引擎业务逻辑。
- PDF：`/tmp/office-pdf-static-expanded-final-20261112/summary.json` 为 ok:true。
  真实本地服务的 grant/cookie/CSRF、引擎预览、确认、发布下载、pypdf 独立回读与修订重开通过；
  插入文字可搜索、原正文和页框保留、无新增批注/表单、来源 SHA 保持。
  首次失败为旧脚本只期望左对齐；当前源码与引擎契约已支持左/中/右。
  脚本改为精确检查三个选项及默认 left，原保存与身份断言全部保留。

两条完整文件链路均绑定当时冻结 manifest `b751bf3af553b26dee05b9df74a39bfd00980d571478f04ef7a58922561e7e6e`。
之后只追加 Word 表格设置类/样式及 PDF checkbox 样式，再完成最终统一构建。
完整链路不冒充在新 manifest 上重跑；最终局部 UI 由上述 54 个真实组件场景核验。
`/tmp/office-ui-settings-build-continuity-20261112.json` 另按唯一模块/chunk 身份比较实际字节：
PPTX 121 个资源中 118 个、PDF 38 个中 33 个与最终构建 SHA 相同；其余 3/5 个字节不同，
没有原始旧脚本文本可供全文归一比较，因此不推断其等价。该记录不能替代新构建上的完整文件链路验收。

### 下一批未覆盖清单

- Word：默认/覆盖单元格边距、段落/缩进/题注、正文修订列表、链接等其余弹窗与菜单，以及各类对象上下文组合。
- Excel：数字格式/完整单元格格式、排序/高级筛选、名称/定位、序列/模拟运算/单变量求解、透视筛选、页眉页脚/打印等其余组件。
- PDF：转换与图片导出、既有图片属性，以及正文中的裁切、图章、链接、签名、便签等内联构造弹窗。
- PPTX：查找替换、表格与页眉页脚、放映设置、图库和上下文浮层。
- 共享：AI/历史/冲突/导出等可达共享界面仍需逐项映射；完整菜单展开、嵌套弹窗及禁用/繁忙/错误/长文本状态未穷尽。

以上仍是未完成项，不因存在按钮、静态源码或本批通过而关闭。未提交、推送或部署。
收尾时工作区另出现应用/工作流/发布等后端文件的并行修改；它们不属于本批 UI 改动，也不纳入上述验收结论。


## 2026-11-12 续批：Excel 设置、分类与运行状态

上一轮属于实际进展：已有生产修改、RED/GREEN、截图与文件回读证据。本轮继续原目标，未将验收范围缩小为已覆盖的默认弹窗。

### 当前分支与工作区

- 本地仍为 `code`，HEAD 为 `4cfaac23`；本地保存的 `origin/code` 也在该提交。
- 本次 `git fetch origin code` 明确以 GitHub 443 连接失败退出；一次 40 秒有界重试也超时。
  因此本次不能确认远端最新提交，不能把本地跟踪引用的 0/0 当成本次远端更新成功。
- 既有 UI 修改、后端并行改动全部保留；本轮未提交、推送或部署。

### 真实问题与局部修复

- 数字格式分类的 `hidden` 标签被通用 `display:grid` 覆盖，导致常规分类也显示货币、日期、分数等无关字段。
  在 Excel 设置表单范围内恢复原生隐藏语义；未改格式分类、代码构建或应用逻辑。
- 排序的 checkbox 被网格拉宽并与文字分行；三层排序缺少稳定的字段布局。修正 checkbox 为 16px 同行控件，
  桌面三列、窄屏标签单行配两列字段。
- 高级筛选长列名使 grid 的最小内容宽度撑出弹窗。修正字段容器的 `min-width:0` 及输入/选择框宽度，保留完整选项文本。
- Excel 设置字段、次级按钮沿用已有字体、边框、36px 最小高度及禁用态；数字格式分类有明确选中态和示例区。
- 允许编辑区域分组增加局部边框和间距，删除按钮与所属区域同组。
- 图表设计和迷你图原有表单接入现有设置表单、错误提示与右对齐操作区。只补样式类，不改图表协议或新增绘图功能。

### 新增模式与状态

新增 30 个组件模式：排序、高级筛选（默认/校验错误）、单变量求解、模拟运算、允许编辑区域（默认/只读）、
全部 11 个数字格式分类、表格范围调整、迷你图、图表标题/分类轴/数值轴/数据标签/分组与网格线/图例六模式，
以及求解和模拟运算的长错误、未完成繁忙四状态。

繁忙夹具使用产品构造器及真实 UI 禁用逻辑，只替换运算回调为可释放的 Promise；先检查全部控件禁用及 Escape 不关闭，
再释放为长错误并检查重试界面与关闭。它不证明真实求解器或后端任务通过。

### RED/GREEN 与边界

- 初始 12 个新增模式、72 场景：`/tmp/office-xlsx-dialog-baseline-20261112/evidence.json`，42 条失败检查。
- 增强字段主题、checkbox 同行和 `hidden` 检查后：`/tmp/office-xlsx-field-red-20261112/evidence.json`，18 场景、51 条失败检查。
- 图表/迷你图接入前：`/tmp/office-xlsx-object-red-20261112/evidence.json`，18 场景、38 条失败检查。
  这些数量是重复视口上的失败断言，不是独立产品缺陷数。
- 首批修复后 15 模式、90 场景通过：`/tmp/office-xlsx-dialog-fixed-20261112/evidence.json`。
- 扩展 33 模式、198 场景通过：`/tmp/office-xlsx-dialog-final-20261112/evidence.json`。
  包括上述 30 个新增模式及受样式影响的创建表格、分类汇总、合并计算三个既有模式。
  逐一检查全部 11 分类的可见字段集合与分类选中态，不以 `hidden` 属性存在代替真实渲染显隐。
- 后补短屏滚动检查，仅复核数字格式数值、编辑区域、求解繁忙、模拟运算繁忙、图表分组五模式、30 场景：
  `/tmp/office-xlsx-scroll-final-20261112/evidence.json`，均通过。验证主操作滚动可达，并保存 `-actions.png`；
  繁忙态另存 `-pending.png`。
- 已人工查看排序、高级筛选、数字格式、迷你图、允许编辑区域及短屏长错误/繁忙截图。

### 定向回归与构建版本

- 12 文件 30 项定向回归通过：`/tmp/office-xlsx-dialog-regression-20261112.log`。
- 透视配置与筛选的 2 文件 6 项定向回归通过：`/tmp/office-xlsx-pivot-regression-20261112.log`。
- `npm run build` 通过（Vite 45.80 秒），`npm run check:budget` 通过；
  日志 `/tmp/office-xlsx-ui-build-20261112.log`、`/tmp/office-xlsx-ui-budget-20261112.log`。
- manifest SHA256：`249cd70b1bf2aa7dd4f36e06d80004a4532681cd563d57d0b9bd45241dfd2e8c`。
  PPTX 主模块 249.7KiB、DOCX 249.6KiB、XLSX 190.4KiB。既有 Rollup 注释、混合导入与大 chunk 告警仍在。
- 源码枚举重新生成于 `/tmp/office-ui-inventory-xlsx-final-20261112/`：722 模块、4373 UI 声明点，解析器 2 项测试通过。
  源码模块 SHA 已刷新；声明点仍不作为功能完成率。
- 本轮没有重复完整项目 suite，没有把 Vite 组件夹具称为最终构建上的完整文件保存验证。
  前述 PPTX/PDF/DOCX/XLSX 文件链路仍只支持各自已记录的旧构建版本。

### 仍需继续

数字格式分类和上述 Excel 组件已增加可视验收；完整单元格格式的其余面板、名称/定位、序列、打印/页眉页脚、
嵌套菜单及其它上下文仍待核对。前述 Word、PDF、PPTX 和共享界面清单仍未关闭，目标保持 active。


## 用户追加方向：尽可能贴近 PC

本条适用于完整四格式目标，后续批次继续沿用。当前先落在 Excel 设置界面：

- 桌面宽度 769px 以上使用左标签右字段，输入/选择框和操作按钮压至 32px 最小高度；窄窗口保留纵向字段和 36px 控件。
- 排序维持紧凑的关键字/列/次序三列设置。
- 透视配置原有 780px 宽度被较晚加载的基础格式弹窗 480px 样式覆盖。
  使用对应两类组成的局部选择器恢复原宽度；桌面 1000px 以上将字段分组排成两列。
- 透视 fieldset 使用真实 grid 间距，避免字段选择与添加按钮贴合。
- PC 样式前先跑字段布局 RED：`/tmp/office-xlsx-pc-label-red-20261112/evidence.json`，6 场景中桌面布局失败。
- 透视宽度/间距 RED：`/tmp/office-xlsx-pivot-width-red-20261112/evidence.json`，6 场景、7 条失败检查。

透视新增空白配置、已配置字段、切片器、时间线及两种保存原生控件的模式，共 6 种。
夹具使用真实 `createBlankWorkbook/applyCellEdits/createPivotPlan/applyWorkbookOperations/readWorkbookPivots` 构造并读取文件，
然后打开产品组件；没有将产物保存回调或生产授权冒充为已验证。
初次夹具新增时相对导入路径写错，加载超时且没有执行任何产品场景；已纠正路径。
修正后的 `/tmp/office-xlsx-pivot-layout-final-20261112/evidence.json` 为 36 场景通过；
当时尚未加入 PC 宽度与间距检查，不能用其替代后续 PC 终轮结果。


### PC 终轮验收

- `/tmp/office-xlsx-pc-final-20261112/evidence.json`：39 模式、234 场景，failures/pageErrors 均为空。
  这是当前 PC 样式下本批已纳入的 33 个 Excel 设置模式与 6 个透视模式复核；其它共用样式的界面仍待逐项检查。
- 包含桌面标签与字段同行、原生宽弹窗、字段分组间距、分类真实显隐与选中态、checkbox 尺寸和同行、
  主题、横向边界与内部滚动、短屏主操作可达、繁忙禁用/拒绝关闭、释放后长错误及关闭焦点恢复。
- 已人工查看 PC 排序/高级筛选/数字格式及透视配置两列、滚动末端、切片器截图。
- 新增组件夹具累计 36 种模式，本批与此前合计 62 模式、372 个不同视口场景。
  该累计来自分批证据组合，不是最终统一构建上四格式一次全跑，更不代表整个功能范围已穷尽。
- PC 样式最终构建 `npm run build` 成功（Vite 47.10 秒）、包体预算检查成功。
  日志 `/tmp/office-xlsx-pc-build-20261112.log`、`/tmp/office-xlsx-pc-budget-20261112.log`。
  最终 manifest：`12b15b0c9a0ec9fc239b572ee1dc377a6a6d6fa79da7784701df954c38bf1bf4`。
  前述 `249cd70...` 为 PC 布局追加前的构建，不能混用。
- 最终源码枚举位于 `/tmp/office-ui-inventory-pc-final-20261112/`，722 模块、4373 声明点。
  PC 追加仅改两个 CSS；上述 14 文件 36 项业务组件定向回归对应的 TypeScript 内容仍一致，未重复全量项目测试。
- `node --check` 两个组件 smoke 文件、`git diff --check -- smart_reporting/report_editor` 通过。

当前只关闭本批具体问题。PC 优先要求继续用于后续 Word/PDF/PPTX/共享组件、菜单、上下文和各类运行状态的逐项核查。
原目标保持 active，未提交、推送或部署。


## 2026-11-12 续批：Word 设置与修订列表的 PC 布局

延续已确定的 PC 优先方向，本批关闭下列具体问题，未将四格式完整功能范围标记为完成。

### 实际修改

- 行距、特殊缩进、默认/覆盖单元格边距、题注接入现有设置样式；与已有七种表格属性弹窗共用字段和操作区规则。
  769px 以上采用左标签右字段、对齐字段起点和紧凑操作按钮；窄窗口保留纵向布局和内部滚动。
  表单显式保留原生 `hidden` 语义，避免桌面 grid 优先级将隐藏字段重新显示。
- 题注使用现有主按钮组件及右对齐操作区；禁用原因、选区校验和 SEQ 插入协议保持原逻辑。
- 正文修订列表在桌面使用 760px 宽弹窗，批量操作分组，长作者身份和正文在区域内换行。
  既有修订定位、接受/拒绝、批量决策与 AI 入口协议不变。
- 单元格边距转入行跨页/整表对齐时先关闭原弹窗并交回外部入口焦点，再打开二级设置。
  打开失败则恢复原表单和草稿，显示错误；成功关闭后可回到仍连接的外部入口。
- 核对真实调用发现表格属性通过 `docx-tables.ts` 挂载在 `document.body`，不能只测 `.docx-native` 内的夹具。
  新增两种直接挂载 body 的产品构造器场景，并为设置类本身补上键盘焦点环。
  原 `.docx-native .modal-card` 规则保留；补充范围仅限上述 Word 设置类。

### 定向回归与失败证据

- 新增 `docx-table-property-focus.test.ts`，两种二级设置的焦点交接在修改前失败；打开失败保留草稿用例同时通过。
  RED 日志 `/tmp/office-docx-focus-red-20261112.log`。
- 修改后 8 文件 107 项通过，覆盖焦点、题注、行距、缩进、两类边距、修订和缩放：
  `/tmp/office-docx-settings-green-20261112.log`。没有运行或重复完整项目测试。
- 原控件 RED：`/tmp/office-docx-controls-red-20261112/evidence.json`，30 场景、39 条失败检查。
  首次修复仍有一条桌面隐藏字段失败：`/tmp/office-docx-controls-fixed-20261112/evidence.json`；随后修正选择器优先级。
- 外层挂载 RED：`/tmp/office-docx-portal-focus-red-20261112/evidence.json`，12 场景、30 条字段焦点环失败检查。
- 原 24 模式基线在缩放错误夹具超时：浏览器原生 max 约束阻止 requestSubmit，应用校验未触发。
  夹具改用显式 submit 事件检查应用错误分支；生产浏览器约束和校验代码未改。

### 分批视觉与交互结果

- `/tmp/office-docx-pc-final-20261112/evidence.json` 跑完 32 模式、192 场景。
  剩余 12 条失败仅来自题注选区/锁定态的检查器误报：禁用主按钮原本就应采用主题禁用色。
  没有将该整轮说成零失败；检查器现分别校验可用主色及真实 disabled 状态下的主题禁用色。
- `/tmp/office-docx-portal-and-locked-final-20261112/evidence.json`：两个 body 挂载模式及上述两个题注模式，24 场景通过。
- 以后一批替换相同模式，保留前批其余 180 个场景，组合为 **34 模式、204 个不重复视口场景**；
  索引 `/tmp/office-docx-pc-combined-20261112.json` 明确记录每个场景的来源，合并后的失败/pageErrors 为空。
  这是分批组件证据，不是最终构建上四格式一次全跑，也不代表生产授权与全部功能已验收。
- 六视口仍为 1440×900、768×1024、390×844、320×640、640×360、390×320。
  覆盖字段/按钮主题、桌面标签对齐、隐藏字段、长文本和短屏操作可达、Escape 与关闭焦点恢复。
  新增同一行距弹窗中固定值/最小值/倍数切换，以及字符缩进切换为悬挂/无/首行、再恢复字符单位的显隐/禁用检查。
- 已人工查看桌面行距、默认边距、题注和正文修订列表，以及短屏错误末端、锁定题注和外层整表对齐截图。

### 最终构建与真实文件回读

- 最终 `npm run build` 成功（Vite 45.07 秒），`npm run check:budget` 成功：
  `/tmp/office-docx-pc-final-build-20261112.log`、`/tmp/office-docx-pc-final-budget-20261112.log`。
  DOCX 主模块 249.9KiB，PPTX 249.7KiB，仍接近现有 250KiB 预算；既有依赖注释、混合导入与大 chunk 提示保留。
- 最终 manifest SHA256：`159b461ea32e9407c85e0a8e7cba005d84791af6f2fc1bf948041b09f7f1779e`。
  前一构建 `13c26f...` 属于补充 body 挂载焦点样式之前，不能混用。
- 最终构建上的 DOCX 文件链路通过：`/tmp/office-docx-pc-final-save-20261112.log`。
  真实文件引擎、编辑/保存/下载、独立 Python/OOXML 回读、修订 2 重开、源 SHA 不变及模拟验收失败仍保留下载均通过；
  四视口外壳检查 failures 为空，截图与控件记录位于 `/tmp/office-docx-pc-final-save-20261112/`。
  授权和修订登记仍是明确 route fixture，未将其称为生产服务全链路验收。
- 最终源码枚举 `/tmp/office-ui-inventory-docx-pc-final-20261112/`：722 模块、4373 声明点；
  声明点数量不作为功能完成率。两个组件 smoke 的 node 语法检查及编辑器范围 `git diff --check` 通过。

本次再次执行 25 秒有界 `git fetch --no-tags origin code`，退出 124 且没有成功结果，
不能确认远端最新状态；本地仍为 `code` / `4cfaac23`。既有管理端、后端与其它 UI 并行改动保留，未提交、推送或部署。
仍待逐项检查的 Word 链接/菜单、Excel 其余面板及 PDF/PPTX/共享界面，继续适用 PC 优先方向。

## PDF PC 设置续批（2026-11-12）

本批延续 PC 优先方向，覆盖转换、页面图片导出、已有图像属性及原生宿主内联弹窗；四格式总目标仍未完成。

### 实际修改与边界

- PDF 转换、图片 ZIP 导出和已有图像属性复用右对齐操作区与主题主按钮。
  转换/导出的状态、错误和结果链接置于操作区之前，长错误在短屏滚动末端也能访问主操作。
- 签名、印章、裁切、纸型、链接、测量、便签正文、待保存绘图移动/图像缩放接入现有 PDF 设置主题，
  统一字体、字段、按钮和键盘焦点环；便签正文补无障碍名称。
- 桌面字段采用左标签右字段。印章弹窗宽 760px，修复旧高优先级样式将其限制为 560px 的问题；
  窄屏转单列，复选框保持 16px。裁切桌面宽 840px，左预览右参数，1440×900 无需滚动即可看到全部设置；
  窄屏保留单列和窗口内部滚动。签名切换保留原生 hidden 语义。
- 转换和页面图片导出等待时仅剩关闭按钮可用，将 Tab / Shift+Tab 留在该按钮，继续允许关闭。
  未引入 Excel 忙碌状态禁止关闭的契约；原有 generation、过期结果丢弃、缓存和文件身份校验保留。
- 未改发布门禁/验收契约、服务端转换引擎、PDF 纸面内容和其他业务修改。

### 夹具可靠性与 RED 证据

- 新增 `smoke/office-pdf-host-fixture.mjs`，使用真实 PDF 引擎检查两页 PDF 来源后挂载产品宿主；
  file/preview 为明确夹具，preview 仅接受空操作，不声称其覆盖生产授权或服务端预览。
  导出结果夹具提供真实 ZIP 容器和 SHA256，仅用于结果 UI，不代表已执行生产转换。
- 修复夹具使用不存在的 addNote 类型、未等待工具栏 Promise 回调的问题；后者会导致键入签名仍停在手写状态、
  待保存绘图列表尚未打开即继续点击。当前明确断言签名标签 aria-pressed 与画布/输入区显隐，
  链接和测量通过 Playwright 真鼠标拖动创建区域。
- 早期 `/tmp/office-pdf-dialog-baseline-20261112/` 只完成 56 场景后超时；执行期间修改共享夹具会触发 HMR，
  不将其称为完整基线。后续每批执行期间冻结产品源码和共享夹具。
- 可靠 RED：独立字段 `/tmp/office-pdf-field-red-20261112/`（18 场景、38 条失败）；
  链接/测量 `/tmp/office-pdf-region-red-20261112/`；
  异步夹具修复后的签名/绘图 `/tmp/office-pdf-drawing-red-fixed-20261112/`（18 场景、61 条失败）。
- 补充桌面 RED `/tmp/office-pdf-desktop-width-red-20261112/`（12 场景），分别发现印章宽度覆盖和裁切纵向滚动。
- 两个新增等待焦点单测先失败，再由产品修复通过：
  `/tmp/office-pdf-pending-focus-red-20261112.log`、`/tmp/office-pdf-image-pending-focus-red-20261112.log`。

### 分批 UI 与定向测试

- 初批宿主 `/tmp/office-pdf-host-pc-green-20261112/`：12 模式、72 场景通过。
- 初批独立/既有设置 `/tmp/office-pdf-fields-pc-green-20261112/`：19 模式、114 场景跑完；
  有 8 条失败，来自长错误后的主操作和转换等待焦点。该原始批次未宣称全通过。
- 修复后 `/tmp/office-pdf-pc-followup-green-20261112/`：8 模式、48 场景通过，包含新增桌面宽度/裁切完整可见及等待时双向 Tab 检查。
- 最终常规状态 `/tmp/office-pdf-pc-normal-final-20261112/`：5 模式、30 场景通过。
- 以较晚批次替换相同模式，组合为 **31 模式、186 个不重复视口场景**，failures/pageErrors 为空；
  `/tmp/office-pdf-pc-combined-20261112.json` 为每个场景保留来源。属于分批组件证据，不是四格式一次全跑或生产服务全链路验收。
  六视口为 1440×900、768×1024、390×844、320×640、640×360、390×320。
- 人工查看桌面键入签名、印章、裁切、页面图片导出、转换等待，以及窄/短屏印章、裁切和长错误末端截图。
- 首次修复定向单测 12 文件、73 项通过：`/tmp/office-pdf-pc-green-unit-20261112.log`。
  后续只复测受补丁影响的转换、图片导出、裁切弹窗和裁切画布 4 文件，42 项通过：
  `/tmp/office-pdf-pc-followup-unit-20261112.log`。包含两个新增等待焦点回归和 22 项裁切画布测试；
  与前批按文件替换后的不重复覆盖为 13 文件、97 项，非同一次套件执行。未运行完整项目测试。

### 最终构建与真实 PDF 回读

- 最终 `npm run build` 成功（Vite 47.08 秒），`npm run check:budget` 成功：
  `/tmp/office-pdf-pc-final-build-20261112.log`、`/tmp/office-pdf-pc-final-budget-20261112.log`。
  PDF 主模块 216.5KiB；DOCX 249.9KiB、PPTX 249.7KiB，均保留现有预算。
  构建仍有既有依赖注释、混合导入和大 chunk 提示。
- 最终 manifest SHA256：`c3e5c0402424793e280346e6b8ebdc7bb9808f0fd4838aa8b292bba378144d4e`。
  前一构建未包含后续裁切分栏及等待焦点修复，不混用其身份。
- `smoke/pdf-layout-smoke.mjs` 在最终生产构建上通过：
  `/tmp/office-pdf-pc-final-layout-20261112.log`；实际 PDF 引擎、页面合并/拆分、保存下载、独立 pypdf 回读、
  来源 SHA 不变、修订 2 重开通过，产物 `/tmp/office-pdf-pc-final-layout-20261112.pdf`。
- `smoke/pdf-crop-handles-smoke.mjs` 首次因默认 `/usr/bin/chromium` 不存在而未启动浏览器，未把它算作产品失败或通过；
  显式指定已安装的 Playwright Chromium 后通过：`/tmp/office-pdf-pc-final-crop-handles-retry-20261112/summary.json`。
  summary 记录上述同一 manifest；覆盖 0/90/180/270 度、八控制柄、真实拖动、窄屏、数字边距、实际预览与保存字节一致、
  下载及独立 pypdf CropBox 回读；errors 为空。授权与修订路由仍为替代夹具，未称为生产 HTTP/auth 验收。
- 最终源码枚举 `/tmp/office-ui-inventory-pdf-pc-final-20261112/`：722 模块、4376 声明点；
  已刷新清单，声明点不作为功能完成率。组件 smoke node 语法检查及本批编辑器文件 `git diff --check` 通过。

改动保留在现有工作树，未提交、推送或部署；既有管理端/后端并行修改未覆盖。
后续仍需逐项核查 Word 链接/菜单、Excel 其余面板，以及 PDF/PPTX/共享界面的剩余组件，继续按 PC 优先实施。

## Excel PC 设置续批（2026-11-12）

本批继续按桌面 Office 的紧凑控件、清晰分组及合理弹窗宽度处理 Excel 设置；四格式穷举目标仍在进行中。

### 修改范围与 RED

- 名称管理器接入既有设置主题，桌面宽 720px；原生 size 列表明确保持 160px 高度，修复被 ribbon 高度压成单行的问题。
  复用现有作用域、创建/更新/删除行为，统一字段、错误及主操作样式。
- 定位名称列表限定 240px 内部滚动，长名称和引用可换行，不再撑宽整窗；成功导航和关闭焦点合同保留。
- 序列桌面宽 600px，三个选项组并列；窄屏保留单列。未改日期单位、预测趋势、步长解析或禁用逻辑。
- 页眉页脚桌面宽 780px，保留页眉/页脚各自左、中、右三栏；700px 以下转单列。
  删除仅用于旧布局的 inline 样式，六个 textarea 统一主题并保持 80px 初始高度；未改字段代码解析或首页/偶数页保留逻辑。
- 打印比例接入设置主题，百分号与输入框保持同行；打印预览宽 980px，统一范围字段、分页工具栏、错误和主按钮。
  预览保持原来的实际打印 HTML、缩放和页码算法；静态 sandbox iframe 移出 Tab 顺序，修复等待/错误时 Tab 进入 iframe 后 Esc 不能关闭外层弹窗。
- 批注复用桌面左标签右字段及禁用主题；查询连接统一按钮字体、尺寸、焦点环和长文案换行。
  查询仍只读，未启用执行或刷新。未触碰发布门禁、下载签发、服务端业务或 Plotly。
- 新增 `smoke/office-workbook-settings-fixture.mjs`：39 种状态，覆盖空/有值/错误/等待/只读等。
  使用产品构造器、真实打印 job 和真实 XLSX 查询元数据读取；运算/宿主回调为明确替代夹具，不能称为生产服务端到端验收。
- 初始 `/tmp/office-xlsx-settings-baseline-20261112/` 完成 38 模式、228 场景，记录 223 条 UI 失败、无 pageErrors；
  最后函数目录选中场景因误点隐藏的原生 category option 超时，因此该基线不是完整 39 模式执行。
  已改为精确点击 `.fn-list [role=option]`，保留原始失败记录。
- 补充 `/tmp/office-xlsx-settings-guard-red-20261112/` 完成 4 模式、24 场景，37 条失败、无 pageErrors；
  包含名称列表至少 120px、定位列表限定高度的 RED，以及修正后函数目录选中和行高 span 标签检查。
  新增打印预览键盘回归单测先失败于 iframe 默认 tabIndex=0：`/tmp/office-xlsx-preview-focus-red-20261112.log`。

### 定向单测与既有集成失败

- `/tmp/office-xlsx-settings-pc-unit-20261112.log`：9 文件、99 项，91 通过、8 失败，另有 2 个范围越界未处理错误。
  其中页眉页脚、打印比例、打印预览、查询、定位焦点、批注及名称作用域 7 文件共 48 项全部通过。
  新增预览 Tab 顺序、Escape 后丢弃延迟结果用例包含在内。
- 失败位于 `workbook-main-defined-names.test.ts`（7 项名称草稿/移位同步）与 `workbook-main-fill-goto.test.ts`（1 项表格 header/totals 范围）。
  为判断归因，在 `/tmp/office-xlsx-settings-original-source-20261112/` 保存 HEAD 原始 UI 模块，通过临时 Vite load 插件按原路径加载，
  保留当前其它源码和依赖，未回退或覆盖运行中的产品文件。
  `/tmp/office-xlsx-settings-original-source-control-20261112.log` 复现名称 CRUD、表格范围失败及 2 个相同越界错误；
  `/tmp/office-xlsx-settings-original-source-names-control-20261112.log` 复现其余 6 项名称失败。
  不将上述 8 项视为通过，也未为 UI 任务修改这些业务路径或放宽断言。
- 初始定向基线还发现 `workbook-format.test.ts` ribbon tabs 断言仍停留在 8 项，产品现有 `Chart Design` 为第 9 项；
  仅修正预期 tabs/tabIndex，单例通过记录 `/tmp/office-xlsx-settings-ribbon-expectation-20261112.log`。
  未重复运行完整项目测试。

### 分批组件验证及脚本修正

- `/tmp/office-xlsx-settings-pc-green-20261112/` 完成新增 39 模式、234 场景，无 pageErrors；
  仅 320×640 的打印预览错误/等待状态有两条焦点环失败，未将这次原始执行称为全通过。
  原因是 Chromium 自动将窄屏可滚动 pane 纳入 Tab 顺序，但该区域仅有浏览器默认 1px 黑色焦点环。
- 预览滚动区补显式 tabindex、region 无障碍名称和 2px 主题焦点环，静态 iframe 继续排除于 Tab 顺序；
  对应单测先 RED `/tmp/office-xlsx-preview-pane-red-20261112.log`，后 6 项通过 `/tmp/office-xlsx-preview-pane-green-20261112.log`。
  桌面序列组补 align-content:start，避免只有两个选项的方向组被垂直拉开。
- `/tmp/office-xlsx-settings-pc-followup-20261112/`：仅复测受补丁影响的打印预览与序列 7 模式、42 场景，全部通过，无 pageErrors。
- 旧设置代表复测初批 `/tmp/office-xlsx-settings-pc-regression-20261112/`：排序、长错误高级筛选 12 场景通过；
  求解 busy 场景因脚本只检查第一个 status 节点、漏看后面的非空 alert 而超时，未作产品失败或整批通过。
  将脚本等待条件改为任一非空 status/alert 后，`/tmp/office-xlsx-settings-pc-regression-fixed-20261112/` 的
  求解 busy、自定义数字格式、迷你图、已配置透视表 4 模式、24 场景全部通过。
- 较晚执行替换同名同视口结果，组合证据 `/tmp/office-xlsx-settings-pc-combined-20261112.json`：
  **新增设置 39 模式、234 场景，加旧设置代表 6 模式、36 场景，共 45 模式、270 个不重复视口场景，failures/pageErrors 为空。**
  每条保留原始来源，组合不掩盖先前批次失败，也不等同于全部四格式验收完成。
  六视口为 1440×900、768×1024、390×844、320×640、640×360、390×320。
- 人工查看桌面名称管理器、长名称定位、日期序列、打印预览、只读批注、实际文件页眉页脚，以及窄屏页眉页脚、查询、预览等待焦点截图。

### 实际文件与脚本兼容性

- 首次生产构建与预算通过：`/tmp/office-xlsx-settings-pc-build-20261112.log`（Vite 47.28 秒）、
  `/tmp/office-xlsx-settings-pc-budget-20261112.log`；manifest SHA256 `45143854fba31715decac9056366e466fd29fe1091b4952e7deb22d36056b957`。
  此构建早于预览滚动区和序列对齐的小补丁，不能把它冒称最终构建。
- 页眉页脚完整保存验证 `/tmp/office-xlsx-settings-pc-header-footer-save-20261112.log` 成功，证据 `/tmp/header-footer-editor-built-n7OFZx/`：
  真实文件引擎、取消不写草稿、刷新恢复、修订 2 保存下载/哈希、OOXML/openpyxl 回读、清空后修订 3 重开，
  首页/偶数页、图片/未知字段及其它包部件保持，无浏览器错误。
- 打印缩放首次脚本仍等待旧的直接打印行为，在 `scale-10` 超时；当前 File Print 已有预览面板。
  更新 smoke 显式等待预览并点击产品打印按钮后，`/tmp/office-xlsx-settings-pc-print-scale-save-fixed-20261112.log` 成功，
  证据 `/tmp/print-scale-built-WrTJAa/`：10%/100%/400% 分别保存下载和重开，行高为 3/30/120pt，400% 实际 8 页。
  检查取消、非法输入、过期目标、草稿恢复、同值不写、重命名/撤销及非目标部件不变，3 次真实文件保存，无浏览器错误。
- 定位 scroll smoke 首次等待旧 AI 状态区“可见”，但原生 Office 外壳有意隐藏它；产品已完成导航，脚本超时。
  改为等待导航结果文本并继续验证真实画布后，`/tmp/office-xlsx-settings-pc-goto-built-fixed-20261112.log` 成功，
  证据 `/tmp/goto-scroll-built-LuoLct/`：普通、冻结、150% 缩放、RTL、远端大表 5 类远距离定位及实际交叉高亮像素/恢复通过；
  只读保护、偏好刷新恢复、草稿/历史/保存状态、源与下载 SHA 不变，保存请求 0、pageErrors 为空。
- 上述 HTTP/auth/revision 登记仍是明确替代夹具；实际 XLSX 文件引擎、下载、回读和画布为真实执行，未称为生产授权服务全链路验收。

### 最终构建与剩余范围

- 预览滚动区与序列对齐补丁后的 `npm run build` 退出 0（Vite 46.41 秒），`npm run check:budget` 退出 0：
  `/tmp/office-xlsx-settings-pc-final-build-20261112.log`、`/tmp/office-xlsx-settings-pc-final-budget-20261112.log`。
  DOCX 249.9KiB、PPTX 249.7KiB、PDF 216.5KiB、Workbook 190.5KiB；未提升既有预算。
  构建仍有既有依赖注释、混合导入和大 chunk 提示。
- 最终 manifest SHA256：`65068a85d1741223d3eb334346f4bf4067417b947e1cf030afa1900e8d81f3c7`。
  组合组件证据同步记录该构建身份和最终源码清单位置。
- 最终生产构建上只复核最严格的 400% 场景：`/tmp/office-xlsx-settings-pc-final-print-scale-400-20261112.log` 退出 0，
  证据 `/tmp/print-scale-built-DiX5m7/`。实际预览/打印 8 页、120pt 行高、修订 21 保存下载哈希/独立文件回读/重开一致，
  非法输入、取消、过期工作表、重命名/撤销和草稿恢复继续通过，浏览器 errors 为空；加载的实际 JS 均 200 且与磁盘 SHA 匹配。
  未将此前 10%/100% 或页眉页脚的较早构建证据混标成最终 manifest，也未再次运行整套项目测试。
- 最终源码清单 `/tmp/office-ui-inventory-xlsx-settings-pc-final-20261112/`：722 模块、4376 声明点；
  已刷新清单文档。声明点数量不是功能完成率。组件/真实文件 smoke 的 node 语法检查、编辑器范围 `git diff --check` 通过。

本地仍为 `code` / `4cfaac23`，未提交、推送或部署。上一批远端 fetch 超时的问题未冒称已解决。
保留既有管理端、后端和其它 UI 工作树修改。
四格式穷举目标继续 active：仍需检查 Word 链接/菜单，Univer npm 中完整单元格格式、条件格式、数据验证和框架菜单，
以及 PDF/PPTX/共享 AI、历史、冲突、导出等剩余界面。本批自有设置构造器和源码声明枚举不能替代这些范围的验收。

## Word 超链接、书签与交叉引用 PC 续批（2026-11-12）

本批只处理超链接设置和书签/交叉引用两类非模态面板；四格式 UI 穷举目标仍在进行中。

### RED 与修改范围

- 新增 `smoke/office-docx-reference-fixture.mjs` 和 `office-docx-reference-smoke.mjs`，使用产品 `DocxInsertSource`、真实 Tiptap 及产品书签/交叉引用构造器。
  8 种状态为链接、链接非法 URL、打开后切只读、空书签、长书签列表、只读书签、长交叉引用列表和只读交叉引用。
  来源模型为显式构造，布局夹具不代表真实文件写回或生产授权。
- `/tmp/office-docx-reference-red-20261112/evidence.json`：8 模式、48 个场景完成，114 条失败，无 pageErrors。
  实际复现了字段字体/高度、PC 标签位置、长列表溢出，以及超链接 Tab 离开弹窗、Esc 不能关闭的问题。
- 新增 `src/docx-link-dialog.test.tsx`，通过真实 React 插入区与真实 Tiptap 验证来源选区。
  `/tmp/office-docx-link-unit-red-20261112.log`：4 项中 2 项失败，分别是 Esc 不能关闭和宿主只读后仍能用表单提交改写正文。
- 超链接复用现有 `createModal` 和按钮/设置主题，620px 桌面宽度、左标签右输入、窄屏换行。
  保留 `Link`/`Link URL` 无障碍名称和原 `data-command`；错误显示在窗口内，输入使用 value/textContent，不插入外部 HTML。
  模态框支持焦点陷阱、Esc/取消/关闭、组件卸载清理；提交时同时核验宿主编辑状态和既有 `applyDocxLink` 来源快照/安全 URL 校验。
  保留移除链接的原有路径与外层错误处理；未改源段落写回协议。
- 书签和交叉引用采用局部主题，32px 控件、明确的禁用与焦点状态，长名称和只读原因可换行，列表内部滚动上限220px。
  原生 hidden、来源/范围验证、独立保存和 UndoRedo 不变；未改其它批注面板的共享 CSS。
- 初次截图发现 PC 面板纵向堆叠浪费宽度；新增列表与字段区并列守卫。
  `/tmp/office-docx-reference-columns-red-20261112/evidence.json`：2 模式、12 场景完成，2 条桌面并列布局失败，无 pageErrors。
  随后将字段区和列表分为两个原生容器，PC 双栏、窄屏单列；关闭后 hidden 不被 display:grid 覆盖。
- DOCX 超链接界面独立为小 chunk，沿用现有拆包方式；未提高任何构建预算。

### 定向与组件验证

- `/tmp/office-docx-reference-unit-green-20261112.log`：5 文件38项通过，含新增4项、链接3项、书签5项、交叉引用5项、Ribbon21项。
  验证非法 URL 保留正文、纠正后按 UTF16 精确来源选区应用、宿主只读拒绝提交、来源过期拒绝提交及卸载清理。
- `/tmp/office-docx-reference-green-20261112/evidence.json`：首轮8模式48场景通过、无 pageErrors；此时PC面板仍为纵向布局，不能代替最终双栏证据。
- `/tmp/office-docx-reference-columns-unit-20261112.log`：仅重跑受双栏容器变动影响的书签/交叉引用2文件10项，全部通过。
- `/tmp/office-docx-reference-columns-green-20261112/evidence.json`：5面板模式30场景通过、无 pageErrors；含PC并列、长列表内部滚动、末项完整访问及关闭后的隐藏验证。
- 六视口为1440×900、768×1024、390×844、320×640、640×360、390×320；人工查看桌面链接、窄屏非法URL、书签双栏及长列表截图。
- 每轮浏览器检查期间冻结产品源码和共享夹具；未执行完整项目测试。未触碰发布门禁、下载签发、服务端业务或 Plotly。
- 超链接真实文件 smoke 增加可选冻结生产构建模式：必须核对指定 manifest SHA256、浏览器实际加载 JS 与磁盘 SHA，并在结束时再核对 manifest；原开发模式继续可用。

本批源码清单：`/tmp/office-ui-inventory-docx-reference-20261112/`，723可达模块、4372声明点；不等同于功能完成率，也不包含npm完整界面。

### 最终组件证据与生产构建

- `/tmp/office-docx-reference-link-focus-20261112/evidence.json`：链接3模式18场景通过，另检查Tab循环后的2px键盘焦点环。
- 与最终双栏面板30场景合并为 `/tmp/office-docx-reference-final-combined-20261112.json`：8模式48个不重复视口场景，failures/pageErrors均为空，每条保留来源。
  分批证据不代表一次全跑，也不代表所有Word菜单或四格式UI已穷尽。
- 最终 `npm run build` 退出0：`/tmp/office-docx-reference-final-build-20261112.log`（Vite45.03秒）。
  `npm run check:budget` 退出0：`/tmp/office-docx-reference-final-budget-20261112.log`。
  DOCX249.8KiB、PPTX249.7KiB、PDF216.5KiB、Workbook190.5KiB，链接设置独立chunk1.2KiB，预算阈值未变。
  构建仍报告现有vendor注释/循环chunk/体积提示；不将退出0描述为无任何warning。
- 冻结构建manifest SHA256：`c7c17fac5e23f11413a8a5d461c4728f2780035d421fc22b27122f8df7bc326c`。
  较早首次构建 `/tmp/office-docx-reference-build-20261112.log` 在双栏调整之前，不作为最终双栏产物证据。
- 书签真实Python/Node桥验证：`/tmp/office-docx-reference-bookmarks-built-20261112/evidence.json`，日志同名`.log`位于`/tmp/`。
  创建/精确定位/UndoRedo/草稿刷新/修订2保存下载/重开/删除/修订3保存下载全部通过；仅document.xml变化，XML均有效，errors为空。
- 交叉引用真实桥验证：`/tmp/office-docx-reference-cross-built-20261112/evidence.json`，日志同名`.log`位于`/tmp/`。
  插入、UndoRedo、保存下载和重开通过；仅document.xml变化，保留书签和粗体，REF域指令及缓存文本经独立读取核对，errors为空。
  两项均核对浏览器JS与磁盘SHA及前后manifest；授权/修订存储为路由替身，不冒充生产鉴权验证。
- 超链接初次生产构建测试 `/tmp/office-docx-reference-link-built-20261112.log` 在第一次保存/重开后编辑入口disabled处超时，未将该次标为通过。
  加入选区诊断后，`/tmp/office-docx-reference-link-diagnostic-20261112/evidence.json` 完成新增/修改/移除三个修订保存下载和重开，未修改产品代码。
  诊断中的native与PM选区均为4–13、同一目标文字，链接标记与按钮正常；首轮脚本此前只验证浏览器高亮，没有等待异步selectionchange进入PM。
  因此脚本补明确的PM选区同步等待，并把失败时的选区/按钮状态和截图留存；不以固定sleep或强制点击绕过disabled。
- 最终超链接脚本 `/tmp/office-docx-reference-link-final-20261112/evidence.json` 及同名`.log`通过；使用上述同一冻结manifest，实际加载133个JS文件的身份核对通过。
  新增https、修改mailto、移除链接分别保存为修订2/3/4并下载独立回读、重开；混合粗体/斜体、其它段落和未目标链接的tooltip/样式保持。
  原件SHA不变，草稿刷新和真实键盘UndoRedo通过；模拟验收失败仍有Word下载并显示失败原因。
  该证据的路由仍是显式fixture，真实DOCX解析/修补/下载读取不是模拟。
- 最后 `node --check` 三个新增/修改smoke、`git diff --check`通过，manifest未变化。

本批改动仍在原工作树，未提交、推送或部署。Word导航/页码和其它嵌套菜单、Excel框架自带条件格式/数据验证完整面板，以及PDF/PPTX/共享AI与历史导出等剩余上下文仍需继续核查，目标保持进行中。

## 2026-11-12：Excel 框架条件格式与数据验证面板（续批）

范围：通过真实 Ribbon 的 `dv-open` / `cf-open` 入口检查 Univer 完整侧栏；自有“单元格格式”弹窗不重复计为框架面板。保留框架编辑、范围选择、规则预览、保护和落盘守卫。

基线与中途失败保留：
- `/tmp/office-workbook-panels-discovery-20261112/`：列表2场景；`/tmp/office-workbook-panel-detail-discovery-20261112/`：详情3场景；`/tmp/office-workbook-panel-branches-discovery-20261112/`：类型菜单/高级设置/新建4场景。早期守卫尚不完整，不作最终验收。
- `/tmp/office-workbook-panels-red-20261112/` 仅完成19场景；新建规则产生dirty后，脚本dismiss beforeunload导致下一次导航ERR_ABORTED。修复为接受离开，并清理夹具本地草稿；没有将中断冒充全量执行。
- `/tmp/office-workbook-panels-branches-red-20261112/` 原计划48场景，实际完成26场景；已有主题、尺寸、CF侧栏裁切失败，随后切换到列表规则发生真实pageError中断。诊断复现保存在 `/tmp/office-workbook-list-diagnosis-20261112/`。
- 堆栈定位到 `installDataValidationNames` 将框架“切换类型时公式尚未设置”的状态传给 `resolveTableListSource`，后者调用undefined.match。新增回归先红（`/tmp/office-workbook-list-unit-red-20261112.log`），只在名称扩展入口保留非字符串原值并交回官方validator，再绿（`/tmp/office-workbook-list-unit-green-20261112.log`，2项通过）。没有吞掉异常或放宽文件校验。
- 首轮样式检查 `/tmp/office-workbook-panels-style-green-20261112/` 实际9场景仍有2个CF窄屏失败，不因目录名称含green标为通过。补充守卫后的 `/tmp/office-workbook-panels-detail-green-20261112/` 实际18场景，暴露6px高工作区导致短屏不可访问、CF内部grid最小宽度和菜单越界；还捕获快速重载时的既有Univer已释放Injector异步回调异常。最终布局脚本改成每视口独立页面，避免把上个宿主卸载与下个视口测试混在同一页面事件流；此变化不代表修复了框架卸载竞态。
- `/tmp/office-workbook-panels-fit-green-20261112/`：补充修复后8场景通过，failures/pageErrors均为空，截图已人工检查320px侧栏、短屏滚到底及类型菜单。

局部产品修改：`workbook.css` 使用现有Office token设置侧栏和XLSX限定portal菜单的主题；输入字体继承，关闭按钮32px及焦点环；侧栏最大宽度受视口约束、内部grid允许收缩、管理栏换行。高度≤480px时侧栏在顶栏下方覆盖工作区并内部滚动，保持底部状态栏；普通PC仍用框架原生侧栏宽度及调整行为。不覆盖条件格式实际预览色、色阶、图标或源单元格样式。

测试夹具：新增 `office-workbook-panel-smoke.mjs` 使用openpyxl生成真实空白/已配置XLSX和真实浏览器宿主；鉴权/修订接口明确为route fixture。覆盖9种DV、6种CF、空白/列表/新建/编辑/高级/提示/菜单状态；字段边界、主题、关闭焦点、Esc、滚动可达及PC键盘调整宽度均有检查。布局脚本save接口刻意返回500，因此布局通过本身不代表保存通过。

本批已完成的构建/文件证据：
- 修改前相关4文件27项单测通过：`/tmp/office-workbook-panels-unit-20261112.log`；名称空公式新增回归后的2项通过见上述green日志，未重复完整项目测试。
- `npm run build` 退出0（Vite44.76秒）：`/tmp/office-workbook-panels-build-20261112.log`；`npm run check:budget` 退出0：`/tmp/office-workbook-panels-budget-20261112.log`。主模块DOCX249.8KiB、PPTX249.7KiB、PDF216.5KiB、Workbook190.5KiB；预算阈值未改。仍有既有vendor注释/循环chunk/大chunk构建提示。
- 本次冻结生产manifest SHA256：`e8a01a5619943f474a2e55343115b294ee7568fd6802849390cb223bf2cfb50b`。
- `workbook-native-save-smoke.mjs` 新增 `rules` 专项，真实UI将DV上限100改150、CF阈值100改175，真实Python `patch_office`桥保存、下载并用openpyxl独立回读，随后原生编辑器重开两个规则列表均通过。
  `/tmp/office-workbook-rules-save-built-20261112/evidence.json`：同一冻结manifest，operations仅两个规则替换，文件单元格20/200、SUM公式、0.00数字格式和红色填充可读回；`zip-integrity.json`确认仅styles.xml和sheet1.xml变化、所有XML有效、无重复ZIP成员。鉴权/修订存储仍是显式路由替身，不代表生产授权验证。
- 保存专项初轮dev检查 `/tmp/office-workbook-rules-save-dev-20261112.log` 失败原因是独立读取断言把OOXML默认between当成必须显式operator、只读取fgColor忽略CF差异样式的bgColor；按实际XML语义调整检查，再由上述生产专项通过。未为此改动产品序列化。
- 同时记录未在本批修复的框架行为：CF样式编辑组件在来源没有显式文字颜色时以`#2f56ef`初始化并通过effect写入编辑状态，确认阈值时会随之产生显式文字颜色；真实保存operations已如实保留该字段。本批只证明公式、范围、数值、填充及新阈值，并不宣称编辑既有CF时所有未指定的样式槽均逐字节保留。该行为与快速卸载的异步回调竞态应另行处理，不能因布局验收通过而关闭。
- 源码清单已刷新到 `/tmp/office-ui-inventory-workbook-panels-20261112/`，仓库清单同步；仍723模块、4372声明点，外部框架面板此次以真实宿主补证，不把声明点当完成率。

最终六视口结果与限制：
- `/tmp/office-workbook-panels-final-built-20261112/evidence.json`：同一生产构建，27模式×6视口共162场景全部执行完，布局/字段边界/主题/关闭焦点/滚动/菜单/Esc等 `failures=[]`；PC键盘resize384→404→384。截图已人工核对PC列表/详情/高级/提示，以及窄屏规则分支与短屏滚动。
- **整轮脚本退出1**：`pageErrors`保留2条`dv-add`的Univer已释放Injector异步resize回调异常，不能将162场景描述为整轮无错误通过。独立页面减少事件串扰但没有消除此竞态，也不能假称已修复。
- 随后仅对`dv-add`和此前出现过同类回调的`cf-edit`，增加视口/阶段诊断并复查六视口：`/tmp/office-workbook-panels-teardown-diagnostic-20261112/evidence.json`，12场景、failures/pageErrors均为空、脚本退出0。期间没有产品源码改动；这是间歇性问题未复现，不是对前轮失败的撤销。不重复整轮162场景，不忽略异常，不放宽断言。
- 生产manifest前后未变化。单元回归、构建、体积预算、真实规则保存/下载/独立回读/重开均各自通过；这些独立证据不能消除上述异步框架异常。
- 最后仅整理smoke缩进，`node --check`和`git diff --check`通过；没有修改产品或覆盖构建。

本续批样式及最小空公式修复保留在原工作树，未提交、推送或部署。四格式逐项UI核查目标继续进行：框架异步释放竞态、CF隐式文字颜色行为，以及Word导航/其它嵌套菜单、PDF/PPTX与共享AI/历史导出仍需后续核查；不将本批布局覆盖当作整体完成。

## 2026-11-12：Word 导航、页面缩略图与页码格式（续批）

按用户“UI尽可能贴近PC”要求，保留Ribbon和真实编辑器结构，局部统一导航窗格与页码弹窗；不更改正文、源缩略图的字体/颜色或文件写回协议。

产品修改：
- `docx-navigation.css`：沿用Office主题token和字体，PC窗格宽280px，统一标题、标签、输入、按钮、焦点、禁用状态。宽度≤768px时在工作区内覆盖，短屏在顶栏/状态栏之间覆盖并内部滚动，避免原32vw将320px屏幕窗格压到约100px。标题区sticky，长结果及页面列表可滚动。
- `docx-navigation.ts`：打开后聚焦搜索/页面标签；仅在关闭时焦点仍位于窗格内才恢复入口，避免从已返回正文的用户手中抢走焦点。
- `docx-page-number-dialog.tsx`、`docx.css`：复用现有按钮、设置弹窗和focus trap；PC宽560px、窄屏单列，增加关闭按钮、初始焦点、Esc和焦点恢复。非法起始号有可见alert及aria-invalid，输入时清除错误；原0/续前节及节格式写回语义保留。
- `vite.config.ts`：页码弹窗独立chunk，预算阈值未提高。

基线、中途失败和组件证据：
- `/tmp/office-docx-navigation-red-20261112/`：夹具缺少一个右花括号，启动超时，实际0场景；修复夹具后 `/tmp/office-docx-navigation-baseline-20261112/` 执行24场景，旧产品主题、窄宽、焦点及错误提示守卫失败，pageErrors为空。
- 新页码单测先红3项：`/tmp/office-docx-page-number-unit-red-20261112.log`；导航焦点先红1项、原9项通过：`/tmp/office-docx-navigation-focus-red-20261112.log`。
- 修改后 `/tmp/office-docx-navigation-unit-green-20261112.log`：实际5文件55项通过（navigation-pages、navigation、navigation-search、page-number-dialog、layout-source）。命令中另列不存在的insert-source测试文件，不计入通过文件数。
- `/tmp/office-docx-navigation-green-20261112/` 执行8模式×6视口48场景；其中pages/pages-unsupported的12场景被“隐藏搜索框宽0”守卫误判，另外36场景通过，pageErrors为空。守卫仅对可见宽度>0输入检查；只复查这12场景，`/tmp/office-docx-navigation-pages-green-20261112/evidence.json`全部通过。
- `/tmp/office-docx-navigation-final-combined-20261112.json`保留36+12的48个不重复场景和各自来源，failures/pageErrors为空；这是分批组合，不能描述成一次整轮全绿。覆盖标题/空状态/搜索/无结果/页面/页面不可用/页码/错误页码，六视口包括1440×900、768×1024、390×844、320×640、640×360、390×320。
- `office-docx-navigation-fixture.mjs`使用真实产品组件和Tiptap，显式36标题及显式分页模型；其页面布局不冒充真实文件分页。PC/窄屏/短屏截图已抽查，后续又人工检查PC错误页码、320px页码与真实页面缩略图。

首次生产构建：`/tmp/office-docx-navigation-build-20261112.log`退出0，Vite45.49秒；`/tmp/office-docx-navigation-budget-20261112.log`退出0。DOCX248.5KiB、PPTX249.7KiB、PDF216.5KiB、Workbook190.5KiB、页码chunk2.5KiB；既有vendor/循环chunk/大chunk警告仍在。冻结manifest：`3c2383639fe11703013329b1a6d85efea45d4a091dbe18a1fd670126e09a5fa9`。

该构建真实DOCX验证均退出0，并核对浏览器实际加载的134个JS与磁盘SHA及manifest前后一致：
- `/tmp/office-docx-navigation-headings-built-20261112/evidence.json`：编辑/只读、空/继承/编号/重复标题、折叠/键盘/跳转、保留草稿和实时标题更新；errors为空，PC窗格280px且正文边界正常。
- `/tmp/office-docx-navigation-search-built-20261112/evidence.json`：编辑/只读、表格、跨run/非BMP/全半角、字面字符及原查找高亮保持；errors为空。
- `/tmp/office-docx-navigation-pages-built-20261112/evidence.json`：真实三页分隔解析、正文缩略图、跳转、150%缩放、大纲切换、inert焦点保护；编辑/只读均保持正文/存储，errors为空。
- `/tmp/office-docx-page-number-built-20261112.json`：Layout入口，两节upperRoman/0与lowerLetter/5，草稿刷新、真实修订2保存下载独立回读和重开；第一节改decimal/续前节后修订3保存重开，页眉页脚part保持；ok=true、pageErrors为空。
- `/tmp/office-docx-page-number-insert-built-20261112.json`：Insert菜单“设置页码格式…”实际入口，多节页眉页脚边界操作和upperRoman/12经真实修订保存、下载、独立回读及重开；ok=true、pageErrors为空。脚本为`hf-insert-edge-multi`，不是仅布局夹具。
- 上述路由/鉴权/修订存储为显式fixture，不代表生产鉴权测试；实际DOCX生成、解析、修改、下载及独立读取是真实执行。

真实窄屏宿主追加检查发现入口焦点缺陷：`/tmp/office-docx-navigation-narrow-built-20261112.log`在320×640关闭导航后断言失败；没有最终evidence，不计六场景通过。根因是Ribbon视图命令统一preventDefault(mousedown)保留正文选区，使导航捕获的activeElement不是入口。`docx-ribbon.test.ts`新增入口捕获断言，先红见`/tmp/office-docx-navigation-ribbon-focus-red-20261112.log`。仅在导航命令click调用前focus当前按钮，保留其它视图命令和正文选区行为；`/tmp/office-docx-navigation-ribbon-focus-green-20261112.log`两文件31项通过。后续构建及窄屏定向复查结果另列如下。

源码清单已更新：`/tmp/office-ui-inventory-docx-navigation-20261112/`，仓库`NATIVE_OFFICE_UI_INVENTORY_20261112.md`同步，723模块、4377声明点；不将声明点当功能总数或完成率。Excel异步释放竞态及CF隐式文字颜色问题仍沿用上一批未修复记录，不能因Word验收通过关闭。

入口焦点修复后的最终定向证据：
- `/tmp/office-docx-navigation-focus-build-20261112.log`退出0（Vite44.81秒）；`/tmp/office-docx-navigation-focus-budget-20261112.log`退出0，保留既有构建警告和原预算。
- 最新冻结manifest为`a4d5b9a5be648859e3b5a1f8d4507ca665b433f2ea0605e573b1c0f42edb7cf7`。上述`3c238...`下的文件操作与完整导航功能证据保留其原身份，不冒充在最新构建重跑；两构建间产品差异仅为Ribbon导航入口聚焦。
- `/tmp/office-docx-navigation-narrow-focus-built-20261112/evidence.json`：320×640、390×320、640×360各编辑/只读共6场景，退出0、ok=true、errors为空。真实宿主窗格宽280px、搜索框221px，无横向溢出，关闭按钮和末项可命中，关闭后恢复Ribbon入口，正文/本地存储不变；实际134个浏览器JS身份、源DOCX、manifest、引擎bridge前后均核对。
- `/tmp/office-docx-navigation-desktop-focus-built-20261112/evidence.json`：1440×900编辑/只读2场景，退出0、ok=true、errors为空，同样核对134个JS和文件/构建身份，关闭焦点及正文/存储守卫通过。人工查看该PC截图，以及320px和390×320只读截图，确认PC侧栏/白纸布局与短屏内部滚动。
- 最后四个新增/修改导航与插入smoke的`node --check`及`git diff --check`退出0；未重复完整项目测试。

本批在原工作区完成局部修改，未提交、推送或部署。四格式UI穷举仍在进行，剩余嵌套菜单、共享AI、历史/导出以及前述框架问题继续保留；不将本批通过标为整体完成。

## 2026-11-12：PPTX 查找替换与演讲者备注 PC 续批

前一目标轮为实际进展（Word导航/页码产品修改、文件回读及焦点修复），本轮继续原四格式目标。源码核查确认`slides-find-replace.ts`原生dialog没有专用样式，备注使用独立sans-serif字体与硬编码色值。本批沿用用户已确认的PC Office方向，不改变查找范围、字面替换、只读边界、备注规范化/IME或文件协议。

新增基线及回归：
- `office-pptx-text-panels-fixture.mjs`直接调用真实产品查找/备注构造器，显式来源文字及回调；不冒充实际文件、引擎、授权或保存。涵盖查找初始/匹配/无结果/提交错误/锁定5种，以及备注正常/只读/提交错误/折叠4种。
- `/tmp/office-pptx-text-panels-red-20261112/evidence.json`：3视口×9模式=27场景、96条失败检查、pageErrors为空。包含真实字段排布、紧凑尺寸、备注字体/键盘焦点问题；原生dialog未补齐cancel/焦点管理，Tab及关闭检查也失败，不能将96条逐一等同独立产品缺陷。
- `slides-find-replace.test.ts`新增底部关闭/Esc/cancel/dispose入口焦点回归，`/tmp/office-pptx-find-focus-red-20261112.log`4项红、原9项绿。

局部修改：
- `slides-find-replace.ts`复用现有`installFocusTrap`和`buttonClasses`，增加标题关闭按钮、移除内联label布局，统一幂等dispose清理与入口焦点恢复，处理原生cancel事件；原查找/替换算法及反馈文本保留。
- `slides.css`为查找组件添加560px PC宽度、左标签右字段、主题输入框/复选框/焦点环、右对齐操作区，窄屏单列，短屏内部滚动。演讲者备注改用Office字体与色值token、28px标题操作、焦点环及长错误换行，空提示不占行；不更改画布或放映内容。
- `/tmp/office-pptx-text-panels-unit-green-20261112.log`：查找13项、备注11项共24项通过。随后为新标题关闭按钮补一条路径，仅定向5条关闭回归通过：`/tmp/office-pptx-find-close-green-20261112.log`（5通过/9跳过）；这两份证据有重叠，不累计成29项独立用例。
- `/tmp/office-pptx-text-panels-green-20261112/evidence.json`：9模式×6视口54场景通过，failures/pageErrors为空。涵盖1440×900、768×1024、390×844、320×640、640×360、390×320，检查字体、字段对齐/边界、尺寸、Tab、Esc、关闭焦点、只读/错误及来源/提交不变。
- 增加底部按钮滚动命中守卫后，只复查5种查找状态×2种短屏：`/tmp/office-pptx-find-scroll-green-20261112/evidence.json`10场景通过。人工查看PC匹配弹窗、390×320错误弹窗顶部/底部，以及320px备注错误截图，确认短屏长提示后仍可滚到按钮。该10场景为补充守卫，不冒充54场景的整轮复跑。

构建中途失败如实保留：`/tmp/office-pptx-text-panels-build-20261112.log`TypeScript/Vite通过（45.00秒），但`/tmp/office-pptx-text-panels-budget-20261112.log`退出1，PPTX主模块250.3KiB超过250KiB。该manifest`0ababf08d8191c589341687b277ea37929a23e7675f989272d7c71bbc16e1a79`不作为最终验收。按组件边界在`vite.config.ts`将查找替换单列chunk，预算阈值未改。

真实宿主验证脚本`pptx-notes-smoke.mjs`新增可选`PPTX_TEXT_PANEL_VIEWPORTS`分支，在实际构建上从Ribbon进入查找、核对字段/边界/滚动/焦点/不生成草稿，再检查原有备注可达和主题；之后继续原有真实备注修改、撤销/重做、草稿恢复、两次修订保存、下载独立回读与重开流程。完整文件结果待下述终态证据确认。

源码清单刷新至`/tmp/office-ui-inventory-pptx-text-20261112/`，仓库清单已同步：723模块、4378声明点，仍不作为完成率。PPTX表格/页眉页脚/新增节、放映/图库/其它侧栏和共享界面仍有未完成核查；Excel框架异步释放与CF隐式文字颜色问题保留，不因本批通过关闭。

拆包后的构建与真实文件证据：
- `/tmp/office-pptx-text-panels-final-build-20261112.log`及`/tmp/office-pptx-text-panels-final-budget-20261112.log`均退出0，manifest为`d411f76439c465d455f6a500c0d2f177907fc3242c62a253d797a158ccf579b4`；DOCX248.6KiB、PPTX245.6KiB、PDF216.5KiB、Workbook190.6KiB，独立查找模块4.8KiB。保留既有构建warning，未提高预算。
- `/tmp/office-pptx-find-save-built-20261112/evidence.json`：ok=true、修订2、123个实际JS响应身份核对，page/console/route/HTTP错误均为空。真实来源图片插入/替换、图表修改与查找替换组合，查找不产生草稿、字面替换与一次UndoRedo、刷新恢复、实际Python保存、下载SHA/大小、独立python-pptx/ZIP回读及修订2重开通过。route/CSRF/登记仍为显式fixture，不代表生产鉴权，辅助PDF为有效占位附件。

真实宿主暴露的备注遮挡问题及回归：
- `/tmp/office-pptx-text-notes-built-20261112.log`退出1：首个1440×900真实宿主中，备注字体/80px高度正确，但输入中心命中失败；尚未执行备注修改/保存。没有最终evidence，不能据此称备注文件链已通过。
- 仅补采位置/命中元素/滚动数据，再在单PC视口诊断：`/tmp/office-pptx-text-notes-diagnostic-built-20261112.log`同样失败，记录备注y770～850，命中元素为904×678px的Konva canvas；stage高665、scrollHeight696。`failure.png`人工确认画布实际盖住备注，而不是延迟或字体问题；错误数组为空不能掩盖此UI失败。
- 根因是stage仅定义`minmax(0,1fr) auto`，新增备注成为隐式第三行，而第一行固定像素Konva画布溢出到备注行。局部修复仅针对含`data-notes-panel`的PPTX宿主，显式第三行并让第一行画布自身`min-height:0/overflow:auto/align-self:stretch`，不改PPTX坐标或画布内容。
- 追加`notes-host`夹具，使用真实stage/CSS、真实备注组件和显式900px高canvas结构，不冒充文件渲染。`/tmp/office-pptx-notes-host-red-20261112/evidence.json`首个PC已记录输入遮挡/网格重叠/按钮不可命中，随后真实点击被canvas拦截超时，完成场景0（原计划2）；保留此失败。
- 修复后只跑该宿主模式六视口：`/tmp/office-pptx-notes-host-green-20261112/evidence.json`6场景通过、failures/pageErrors为空，人工检查PC备注与画布分离截图。此前54普通组件场景没有伪装成再次执行；原10条短屏查找滚动补证也保留自身来源。
- 两条真实脚本均已终态后才写产品CSS、重新构建；没有在它们运行时覆盖static或引擎。此后仅CSS变化，沿用前次TypeScript检查并运行`npx vite build`及预算，结果与备注链终态另列。

画布/备注分区修复的构建：`/tmp/office-pptx-text-panels-host-build-20261112.log`退出0（Vite44.64秒），`/tmp/office-pptx-text-panels-host-budget-20261112.log`退出0；manifest为`b1b851db9e667b288805158b13e67a5d93be1b4f462e623e5f76c2ceafca67da`，上述五个主/查找模块的预算数值不变。

截图检查额外保留边界：该构建的真实宿主四视口查找/备注基本命中守卫通过，人工查看1440×900备注截图确认真实画布不再覆盖下方备注；但390×320实际截图受高Ribbon与很矮工作区影响，仅露出备注局部。当前基本守卫仅证明输入中心可命中，不证明标题、输入、折叠按钮可同时完整显示；此短屏宿主布局仍需后续修复，不能用显式高画布夹具六视口通过来覆盖该问题。四格式整体目标继续进行。

最终真实备注链已终态：`/tmp/office-pptx-text-notes-final-built-20261112/evidence.json`，脚本退出0、ok=true、修订3、2次保存、123个实际JS响应与磁盘身份核对，page/console/route/HTTP错误均为空，前后manifest一致。四个真实宿主视口记录查找尺寸/主题/底部操作/焦点恢复与不产生草稿，以及备注中心命中；实际1440×900备注仍位于y770～850，但命中从canvas变为textarea，stage scrollHeight由696恢复665，确认遮挡修复。随后真实编辑两页备注、直接切页、UndoRedo、刷新恢复、第三页重排、修订2保存/下载/独立python-pptx与ZIP部件保留/重开，以及清空备注后修订3立即保存、独立读取、重开均通过。源Unicode/空行/字面实体和未修改源部件由原脚本继续检查。路由鉴权/CSRF/登记为显式fixture，辅助PDF是有效占位附件；不代表生产鉴权或真实PDF转换。

查找完整组合文件链保留在`d411...`构建；最新`b1b...`比它只追加画布/备注分区CSS，其上真实查找进入/查找/关闭由备注专项补验，不冒充再次执行图片/图表/替换组合保存全流程。最后三个新增/修改smoke的`node --check`与`git diff --check`通过。没有重复完整项目测试；未提交、推送或部署。短屏备注全窗可用性、其它PPTX设置/菜单与四格式剩余组件继续核查，目标保持active。

## PPTX 短屏备注的完整编辑区

延续上批390×320真实宿主截图暴露的问题，普通PC仍使用底部停靠备注；只有视口高度不超过480px且可见、展开的备注面板持有焦点时，改用视口内的固定编辑区，焦点离开后回到停靠位置。窄屏顶部保留82px、宽屏顶部保留48px，底部保留28px。仅修改`slides.css`，不重建textarea，不更改备注提交、IME或保存协议。

组件证据：`/tmp/office-pptx-short-notes-red-20261112/evidence.json`为普通/只读/长错误三模式×两个短屏共6场景，6条完整编辑区失败、pageErrors为空。修复后`/tmp/office-pptx-short-notes-green-20261112/evidence.json`为三模式×六视口18场景，failures/pageErrors均为空。守卫检查面板与标题操作/输入框完整处于视口内、实际命中、升高视口后恢复停靠、同一textarea与焦点/文本保留、移走焦点恢复停靠。人工检查390×320普通与长错误focused截图，标题、收起和输入区完整可见，错误区可滚动。

本批CSS构建`/tmp/office-pptx-short-notes-build-20261112.log`退出0（Vite44.05秒）；构建终态后的`/tmp/office-pptx-short-notes-budget-20261112.log`退出0，manifest为`e841905352a2bb2829f35a16942d36626b8371e714964cd36888c6dd8aacff0f`。未改预算，保留既有warning；只改CSS，沿用上批TypeScript证据，不重复完整项目测试。注意构建仍运行时曾检查一次旧static预算，该次不作为新构建证据，最终预算命令在构建退出0后重新执行。

实际宿主回归在`pptx-notes-smoke.mjs`中增加可选`PPTX_TEXT_PANEL_LAYOUT_ONLY=1`，沿用真实Python来源inspect/render与构建JS身份核对，明确不执行patch/save。旧static上`/tmp/office-pptx-short-notes-red-built-20261112.log`退出1，捕获position仍为static及标题操作无法完整命中，未进入保存。

新构建第一次补验`/tmp/office-pptx-short-notes-final-built-20261112.log`退出1：短屏完整边界/命中守卫已通过，但新增测试错误地期待“收起”后仍可点面板内的“展开备注”，真实宿主既有onVisibleChange会隐藏整个面板；脚本因此等待隐藏按钮超时。此失败不记为新的产品缺陷，也不宣称该轮通过。仅修正smoke使用“视图→备注”重新打开，并将离开焦点目标改为始终可见的“开始”标签；产品CSS及static保持不变。失败日志与截图保留，后续终态另记。

实际宿主最终证据：`/tmp/office-pptx-short-notes-green-built-20261112/evidence.json`及同目录截图，脚本退出0、ok=true、layoutOnly=true，manifest与上述`e841...`一致，123个运行JS身份核对，page/console/route/HTTP错误数组为空。1440×900、320×640、640×360、390×320、1440×360五视口通过查找边界/焦点恢复/不产生草稿及备注可达检查；三个短屏额外通过完整编辑区与标题操作实际命中、点击收起、从Ribbon重开、移走焦点恢复停靠、内容与草稿不变。实际390×320备注边界x12～378/y82～292，1440×360边界x12～1428/y48～332，标题操作和textarea均在面板内。已人工查看这两张实际截图。仍为修订1、saves为空，明确不冒充新构建执行了上批两次保存回读；本批纯CSS，真实保存链证据保留在上批各自manifest下。

三个相关smoke脚本`node --check`及`git diff --check`通过。本轮没有修改PPTX业务、发布或导出链路；没有完整项目测试、提交、推送或部署。PPTX内联设置弹窗仅继续调查了现有源码，尚未增加新改动/验收；四格式剩余组件、Excel异步释放错误与CF隐式文字色问题继续保留，整体目标保持active。

## PPTX 插入表格、页眉页脚和新增节弹窗

上个goal turn分类为progress：短屏备注CSS及真实构建证据已落地；本批继续用户要求的PC桌面Office方向，保持三个弹窗原字段和业务提交逻辑，仅调整排布与关闭/焦点行为。

真实基线使用`e841...`构建，从实际Ribbon打开原有内联弹窗，没有复制产品HTML或为测试抽取业务构造器。新增`smoke/office-pptx-settings-layout.mjs`作为实际宿主检查器，`pptx-notes-smoke.mjs`通过可选`PPTX_SETTINGS_PANEL_VIEWPORTS`调用。`/tmp/office-pptx-settings-red-built-20261112/settings-evidence.json`完成三弹窗×三视口9场景，记录24条未满足检查：PC宽度/左标签右字段、标题关闭缺失、Tab从最后操作离开弹窗、页眉页脚checkbox尺寸。所有实际错误数组为空，但整轮退出1，不能以错误数组为空称UI通过。人工查看PC页眉页脚基线截图，确认原360px竖排布局。

先增加三弹窗×取消/原生cancel/标题关闭九条回归，`/tmp/office-pptx-settings-unit-red-20261112.log`九条失败、其余12条未跑，失败分别是关闭后焦点丢失、原生cancel未移除和缺少标题关闭。此处jsdom的原生dialog行为为显式mock，不单凭它推断浏览器默认焦点行为；实际Tab问题来自上述真实基线。

局部改动：
- 新增`src/slides-settings-dialog.ts`，三个内联弹窗复用已有`buttonClasses`和`installFocusTrap`；提供标题关闭、原生cancel转close、关闭后移除/释放键盘监听并恢复入口焦点，初始焦点落到首字段。该辅助函数不读取或提交业务字段。
- `slides-main.ts`仅将三个弹窗的show/close清理接入上述辅助函数，为表格和新增节增加局部类；表格1–75校验、节名称校验/数量限制、页眉页脚日期及保存字段原逻辑保留。
- `slides.css`限定`.slides-settings-dialog`：表格420px、节480px、页眉页脚520px，左标签右字段、30px输入/操作、16pxcheckbox，标题28px关闭按钮；窄屏保留字段排布并缩小标签列，空警告不占位。共享尺寸/链接/图表弹窗未套用这组局部新样式。

`/tmp/office-pptx-settings-unit-green-20261112.log`21项通过，包含九条关闭路径、本批表格4×3与节名称trim后的保存payload检查，以及原有固定/自动日期、几何/结构保存、只读锁定、AI历史等已有用例。`/tmp/office-pptx-settings-typecheck-20261112.log`TypeScript退出0；`/tmp/office-pptx-settings-build-20261112.log`Vite退出0（45.62秒）；`/tmp/office-pptx-settings-budget-20261112.log`预算退出0。manifest为`e1580fe864b709947ed52926f743467af97a2f01c95167827980b81104f01b4c`，既有warning保留、预算未放宽。

新构建实际UI：`/tmp/office-pptx-settings-green-built-20261112/evidence.json`及`settings-evidence.json`，脚本退出0、ok=true、layoutOnly=true，三个弹窗×六视口18场景，failures为空，123个实际JS身份核对，page/console/route/HTTP错误均为空。检查PC精确宽度与同排标签、字段最小宽度/字体/控件边界、空节名与无效表格尺寸原错误提示、长页脚本地输入、底部操作命中、Tab和Shift+Tab循环、Esc与标题关闭焦点恢复、重新打开后原始字段及草稿不变。PC输入宽分别266/326/366px。人工查看PC页眉页脚、390×320表格错误截图，确认排布和底部操作可见。仍为修订1且saves为空，不冒充真实保存测试。

同一冻结构建另跑原有`pptx-native-save-smoke.mjs`的`new-slide`组合文件链，首次`/tmp/office-pptx-settings-save-built-20261112.log`退出1，尚未进入本批三个设置提交：脚本在指定版式新页名称处仍期待英文“Title Slide”，当前来源本地化映射已显示“标题幻灯片”。核对`slides-native-ribbon-locales.ts`的现有映射后，仅修正这条UI文字断言；内部版式path与独立python-pptx的`Title Slide`检查不变。失败保留，未修改产品或降低文件断言。续跑终态另记。

源码清单已刷新到`/tmp/office-ui-inventory-pptx-settings-20261112/`并同步仓库清单：724模块4379声明点，仍不是功能数或完成率。四格式整体目标保持active。

组合文件链第二次失败保留：`/tmp/office-pptx-settings-save-final-built-20261112.log`退出1，已经操作到表格插入之后，但尚未保存。旧夹具的正文文本框没有显式简单轮廓，当前已有`slides-shape-format-pane`按来源能力将轮廓修改禁用，脚本在`shapeOutlineWidth`等待启用超时。源码核对`pptx-brush-source.ts`与格式面板确认这是已有的安全子集契约，不能通过强制启用、跳过或修改产品来通过。本次仅为`new-slide`正向组合夹具新增显式1磅黑色RGB实线，加入真实inspect能力前置断言，保留其他模式来源；继承缺省的只读规则不变，原保存payload与下载文件独立断言保留。新运行使用独立`save-verified-built`证据目录，不覆盖两次失败记录。三弹窗18场景通过结果仍属于同一未改动的`e158...`产品构建。

组合文件链最终终态：`/tmp/office-pptx-settings-save-verified-built-20261112/evidence.json`，脚本退出0、ok=true、mode=new-slide、修订2。沿用原有真实Python inspect/patch、草稿刷新恢复、下载SHA/大小以及独立python-pptx/ZIP检查；三个设置实际提交，表格4×3、第二部分节、页脚“智能报告 · 内部”及幻灯片编号均通过，组合中的新建/复制/删除/重排、图形/图表/SmartArt等原断言未删减。首次进入UI的来源能力前置断言已通过；两次失败均在各自目录/日志保留。脚本的route/CSRF/登记仍是显式fixture，不代表生产授权；辅助PDF是旧预览stub，不作为PDF转换证据。

终态后再次独立读取落盘文件与浏览器资源，结果写入同目录`independent-settings-check.json`：当前manifest仍为`e158...`，123个实际JS逐一与磁盘SHA匹配；源SHA为`d7480dfc1528fe1b0f3f298a4a2845a133bdc81cdad26ad270064bc70360afc8`，下载SHA为`f77f92efe1668a4bdb5dfc8500858afe9bef6d00b69a7fc9bed488b84d580304`，下载52237字节。python-pptx确认四页及目标页原2×2/新4×3表格；直接解析ZIP中的presentation.xml确认`Default Section`和`第二部分`，逐个slide XML确认四页页脚文字与四个编号占位符。实际UI十八场景与文件链使用同一冻结构建，运行期间未覆盖产品源码、static或共享夹具。

人工补看PC新增节错误、390×320页眉页脚底部滚动状态和组合编辑后的PC截图；短屏页眉页脚通过内部滚动到达底部操作，截图中的标题随内容滚动，不将其表述为固定标题栏。最终三个相关smoke的`node --check`、`git diff --check`通过。没有完整项目测试、提交、推送或部署；四格式剩余组件与前述未修复问题仍保留，整体目标保持active。

## PDF 便签、绘图移动及图像缩放窗口

上一批为progress；本批继续贴近PC Office的窗口外观与键盘行为。新增`src/pdf-object-dialog.ts`，仅供便签正文、待保存绘图移动和图像缩放三个动态弹窗使用：可见标题、28px标题关闭、初始字段焦点、Tab循环、原生cancel转close以及返回产品入口焦点。替换窗口时，旧窗口延迟close不得把焦点移出新窗口。业务提交、草稿身份与过期引用检查仍由原宿主管理。局部CSS采用560px桌面宽度、固定标题和表单内部滚动；高度不超过480px时，PDF宿主内部滚动且工作区保底160px，避免被Ribbon压为零高。既有坐标、比例、只读及提交规则未改。

RED证据保留：`/tmp/office-pdf-object-chrome-unit-red-20261112.log`九项失败、十一项跳过，分别捕获缺少标题关闭、取消后焦点丢失和原生cancel未清理。组件首轮`/tmp/office-pdf-object-chrome-red-20261112/evidence.json`只完成三个便签视口的测量（九条失败），随后390×320真实入口被footer遮挡而退出，不能称完成九场景。独立`/tmp/office-pdf-object-entry-diagnostic-20261112/evidence.json`记录工作区零高、按钮中心命中footer；绘图另外两模式的RED在`/tmp/office-pdf-object-drawing-red-20261112/evidence.json`，六场景二十二条失败。均保留失败结果，未强制点击或降低守卫。

GREEN：`/tmp/office-pdf-object-chrome-unit-green-20261112.log`三个定向文件48项通过；`/tmp/office-pdf-object-chrome-green-20261112/evidence.json`三个模式×六视口18组件场景通过，failures/pageErrors为空。390×320便签入口命中恢复、工作区高160px。组件夹具使用真实宿主组件和CSS，但额外测试入口影响body位置，不能替代以下native.html真实构建验证；此前31模式186组件场景没有重跑，也不记入本批数量。

构建检查：`/tmp/office-pdf-object-chrome-typecheck-20261112.log`、`/tmp/office-pdf-object-chrome-build-20261112.log`（44.22秒）、`/tmp/office-pdf-object-chrome-budget-20261112.log`均退出0，预算未放宽。冻结manifest为`93b3310c721d9b953b6dc6ba1e8937cc8a8f35cc9898ec83e725634761ecd653`。源码清单刷新至`/tmp/office-ui-inventory-pdf-object-20261112/`并同步仓库：725模块4382声明点，不是功能数或完成率。

三个真实脚本复用`smoke/pdf-object-dialog-checks.mjs`，从产品入口打开弹窗，不复制HTML；分别检查1440×900、320×640、640×360、390×320、1440×360五视口的标题、首字段、内部滚动后操作实际命中、Tab/ShiftTab、标题关闭、入口焦点及草稿不变。各脚本原取消、过期引用、UndoRedo、刷新、只读、旋转重排、预览/保存/下载/重开断言保留。脚本默认使用已安装的Playwright Chromium，仍支持环境指定可执行文件。

- 图像缩放：`/tmp/office-pdf-object-resize-built-20261112/evidence.json`退出0、ok=true，五视口通过、39个运行JS身份核对；实际下载12941字节、三页，独立pypdf核对两张图像印章坐标、像素SHA/纵横比、原文字与表单、旋转及重排；替换弹窗后新比例字段仍持有焦点。
- 绘图移动：`/tmp/office-pdf-object-move-built-20261112/evidence.json`退出0、ok=true，同样五视口和39个JS；实际下载12158字节、三页，独立pypdf确认剩余矩形为`[96,288,172,357]`及文字/字段/旋转重排保留。
- 便签首轮`/tmp/office-pdf-object-notes-built-20261112.log`退出1：旧`getByLabel('编辑便签正文')`在新增标题关闭后匹配dialog、关闭按钮及textarea，未到保存。仅把正文定位限定为exact textbox，产品/static未改。最终`/tmp/office-pdf-object-notes-verified-built-20261112/evidence.json`退出0、ok=true，五视口和39个JS通过，真实保存修订2/下载/重开、便签取消/UndoRedo/刷新及原身份守卫通过。实际下载12991字节；另用pypdf独立读取落盘两页，正文依次为`rotated pending`以及`keep note`、`待保存修改 金额 750 ✓`。

三组终态后再次逐一核对全部运行JS与磁盘SHA，manifest保持不变，并读取实际落盘PDF；结果分别写在各目录`independent-object-check.json`。人工查看真实构建PC图像缩放、390×320绘图移动/便签和1440×360图像缩放/便签截图，确认标题固定、操作可达与PC字段行。鉴权/CSRF/修订路由仍为显式fixture，使用真实Python引擎/PDF.js和文件，不代表生产授权验收或桌面拖拽等价；便签未声称字节一致预览。三个脚本运行期间未修改产品/static或它们的共享检查器，待全部终态后才修正便签测试定位。

本批仅定向检查，没有重复完整项目测试、提交、推送或部署。PDF待保存对象侧栏仍有原生按钮外观待后续处理；Excel异步Injector释放错误及CF缺省文字色问题继续保留。四格式整体目标保持active。

## PDF 对象列表与便签操作区

上一goal turn分类为progress：三个动态弹窗及实际文件验证已完成。本批继续同一PC方向，核查待保存绘图列表和页内待保存/已保存便签操作。修改限定`pdf-main.ts`与`pdf.css`：复用`buttonClasses`，30px按钮、13px标签、选中行边框/背景、独立可换行操作组及删除危险色；待保存绘图使用标题/说明层次、面板自身滚动和不超过256px/45dvh的高度，避免短屏按钮遮挡。不改变坐标、过期引用、只读或提交规则。

额外发现并修复键盘选择焦点丢失：选择绘图会重建列表，原按钮已脱离文档；仅当触发选择的按钮实际持有焦点时，将焦点恢复到新列表中相同操作索引，不抢夺其它入口焦点。新宿主单测最初`/tmp/office-pdf-object-panel-unit-red-20261112.log`因未等待异步Ribbon入口而遇到null，不能作为产品缺陷证据；补齐等待后`/tmp/office-pdf-object-panel-unit-red-verified-20261112.log`准确捕获activeElement不是所选新按钮，一失败二十跳过。修复后`/tmp/office-pdf-object-panel-unit-green-20261112.log`三个定向文件49项通过，含原弹窗、来源身份/能力及对象草稿守卫。

新增`smoke/pdf-object-panel-checks.mjs`，两个既有真实文件smoke通过可选`PDF_OBJECT_PANEL_VIEWPORTS`调用。从实际产品列表读取样式/边界与命中，不复制HTML；分别覆盖1440×900、320×640、640×360、390×320、1440×360。每个按钮滚动到可见后检查实际命中及完整视口边界，检查尺寸/圆角/字体、键盘模式下焦点环、操作分组、横向溢出和草稿不变；绘图另以Space重新选择，核验焦点保留。便签覆盖待保存、只读及修订2保存后状态，未强制点击或放松身份/保存断言。

真实基线：`/tmp/office-pdf-object-panel-move-red-built-20261112/object-panel-drawings-evidence.json`五场景十六条失败；`/tmp/office-pdf-object-panel-notes-red-built-20261112/object-panel-pending-notes-evidence.json`五场景十二条失败，涉及原生按钮、焦点环及操作分组，绘图390×320还有遮挡。两脚本均退出1，未进入保存；已人工查看PC原生按钮基线。初轮构建`accf89f98fc9edcbf296f2524cbd4999936ae9f1aadb909ff04975c8e14ecfb9`上，`/tmp/office-pdf-object-panel-{drawings,notes}-green-built-20261112/evidence.json`均退出0，共20面板场景及两条原文件链通过。

人工查看该轮截图后发现便签删除颜色仍被既有`.pdf-tool`覆盖，不能把尺寸/命中通过称为视觉全部符合。追加颜色守卫后，`/tmp/office-pdf-object-panel-notes-color-red-built-20261112/object-panel-pending-notes-evidence.json`两视口两失败、脚本退出1。仅增加便签内危险按钮的局部颜色/边框规则，禁用按钮不套用危险色；其它共享按钮、文档内容及业务代码不变。

构建记录：TypeScript日志`/tmp/office-pdf-object-panel-typecheck-20261112.log`退出0；初轮Vite日志`/tmp/office-pdf-object-panel-build-20261112.log`退出0（44.59秒）及预算退出0。补颜色后只改CSS，沿用同一TypeScript证据；`/tmp/office-pdf-object-panel-color-build-20261112.log`退出0（45.12秒），`/tmp/office-pdf-object-panel-color-budget-20261112.log`退出0。最终manifest为`65e6b35ee1ff58d4e94c60ebe6d5e450e627bd59ed8c9025b4a7946d2b566857`，预算未放宽，既有构建warning保留。清单`/tmp/office-ui-inventory-pdf-object-panel-20261112/`725模块4382声明点，已同步仓库，仍非独立功能总数或完成率。

最终同一冻结构建：
- `/tmp/office-pdf-object-panel-drawings-final-built-20261112/evidence.json`退出0、ok=true，绘图五视口、弹窗PC/390×320两视口及原实际预览/保存/下载/重开链通过，包含双胞绘图精确选择、移动/删除、过期面板/弹窗、UndoRedo、刷新、旋转重排和只读拒绝；39个实际JS逐一核对。下载12158字节、三页。
- `/tmp/office-pdf-object-panel-notes-final-built-20261112/evidence.json`退出0、ok=true，待保存/只读/保存后便签三状态×五视口15场景、弹窗两视口及原取消/过期按钮/UndoRedo/刷新/页删除重排/保存下载重开通过；39个实际JS逐一核对。下载12991字节、两页；只读五视口全部操作保持disabled。

两脚本终态后，独立读取落盘PDF与全部运行JS，结果存各目录`independent-object-panel-check.json`，manifest仍65e6...。补充核验第一次误将Square注释`/Rect`当作实际路径矩形而断言失败；直接检查落盘AP确认路径为`96 288 76 69 re S`，注释外接框`[92,284,176,361]`包含2pt线宽周围的边距。修正独立核验的对象定义后同时验证路径、外接框和线宽，未改变产品、文件或原smoke断言。便签独立pypdf正文核验仍为首行`rotated pending`，次页`keep note`与`待保存修改 金额 750 ✓`。所有按钮实际高30px，20场景命中、焦点环、危险色与操作分组检查通过；此前的20场景初轮证据保留为其自身manifest，不混算。

人工检查最终PC待保存便签、390×320保存后便签，以及初轮PC/390×320绘图、PC只读便签截图。PC列表压缩并保留选中整行，短屏通过面板/文档滚动逐项访问，不声称所有记录与说明能同时出现在小视口。仍为显式授权/CSRF/修订路由fixture、真实Python引擎/PDF.js/下载文件，不代表生产授权或桌面拖拽等价。每轮真实脚本运行时冻结产品/static及共享检查器；终态后才进行下一次修正/构建。

本批没有完整项目测试、提交、推送或部署。已保存绘图面板、批注线程/附件等其它侧栏尚需继续核查；Excel异步Injector释放与CF隐式文字色问题仍保留。四格式总体目标继续active，未宣称穷尽或完成率。

## PDF 批注线程、附件侧栏与已保存绘图

继续用户“UI尽可能贴近PC”的方向。本批限定PDF宿主和局部CSS：批注/附件侧栏13px正文、30px操作按钮、28px标题关闭、固定标题、焦点环、附件操作组及删除危险色；已保存绘图复用上一批列表层次和操作组。保留既有侧栏宽度、拖动和持久化clamp规则，未改纸面字体。关闭侧栏后，入口可见则返回入口，否则返回当前Ribbon标签。长批注完整保留并允许行内滚动；普通行最高180px，短屏96px。仅在行自身溢出且无修饰键时处理Home/End，组合键保留原行为。

RED证据：`/tmp/office-pdf-sidebar-unit-red-20261112.log`两失败二十一跳过，`/tmp/office-pdf-sidebar-unit-red-complete-20261112.log`四失败二十一跳过，捕获关闭后焦点丢失。原65e6...构建上三个真实脚本均退出1：`/tmp/office-pdf-sidebar-saved-red-built-20261112/object-panel-saved-drawings-evidence.json`两场景六失败；comments/attachments对应red-built目录的threads/loaded证据各两场景二十八/二十六失败，共六场景六十条失败，未到完整保存验收。

首轮GREEN构建manifest为`695a51ac14f1e40c4f5728e7c4e3ccd67f3b6b9943a7d851c4707a23d17e1e62`；`/tmp/office-pdf-sidebar-unit-green-20261112.log`五文件四十项通过，TypeScript/build/budget对应日志退出0（构建44.73秒）。附件green-built三十场景及文件链通过；comments-green在只读短屏有三条裁切失败，完整日期使线程行146.5px高而工作区只有160px。随后限制行高并保留内部滚动，没有删正文或日期。

saved-green失败于旧smoke期待只读存在禁用删除按钮。`/tmp/office-pdf-sidebar-saved-diagnostic-built-20261112/readonly-page-state.json`确认当前确为来源页0；既有宿主明确仅在editingEnabled时请求引擎编辑metadata，只读模型没有绘图编辑信息。因此保留只读读取规则，将空提示改为“当前只读修订未加载绘图编辑信息；可查看页面内容或下载原件”，修正旧smoke预期，不强行请求metadata或开放删除。只读单测`readonly-unit-red`一失败二十五跳过，`readonly-unit-green`二十六项通过（文件均为`/tmp/office-pdf-sidebar-...-20261112.log`）。

第二构建manifest为`ed41a1911ed99b002014f20fa09f6a8c1808cce3f28bed3659bc10d930aef516`，final-typecheck/build/budget均退出0（45.10秒）；saved-final十五场景、attachments-final三十场景及原文件链通过。comments-final仍失败于真实长回复按Home未回到开头。`/tmp/office-pdf-sidebar-comments-text-diagnostic-built-20261112/text-scroll-diagnostic.json/png`记录焦点仍在行内，但scrollTop2430、clientHeight178、scrollHeight2608，Home后仍在末尾；不以独立Chromium按钮探针替代实际宿主失败。增加局部无修饰键Home/End处理，`/tmp/office-pdf-sidebar-text-scroll-unit-red-20261112.log`一失败二十六跳过，GREEN同名日志二十七项通过。不是一次全套四十二项通过。

最终冻结构建manifest：`9960e58a10046cc47d3625be5e934066c8836fa6f05ddaa644287af71519d675`。`/tmp/office-pdf-sidebar-text-scroll-typecheck-20261112.log`、build同名日志（45.20秒）及budget同名日志退出0，预算未放宽，既有chunk warning保留。

新增`smoke/pdf-sidebar-checks.mjs`，通过可选PDF_SIDEBAR_VIEWPORTS从实际产品DOM逐一滚动/聚焦button、input和summary，检查命中、边界、焦点环、紧凑样式、固定标题关闭及草稿不变。溢出正文真实按End到末尾、Home回开头；关闭再打开验证焦点恢复。三条原smoke继续真实Python引擎、PDF.js、预览/保存/下载/重开，读取实际运行JS身份；没有复制UI HTML。comments旧正文定位改为exact textbox，长回复仅扩充既有Bob正文，不增加线程。五视口为1440×900、320×640、640×360、390×320、1440×360。

最终三脚本全部退出0，evidence.ok=true，同一manifest，各39个实际JS：
- `/tmp/office-pdf-sidebar-saved-verified-built-20261112/`：已保存绘图/暂存删除/只读三状态十五场景；原双胞绘图精确身份、取消删除、UndoRedo、刷新及实际预览保存下载通过。下载12447字节、三页。
- `/tmp/office-pdf-sidebar-comments-verified-built-20261112/`：读取失败、线程、回复筛选、只读四状态二十场景；worker故障/重试/缓存、作者筛选、定位、编辑删除、UndoRedo、重排删页、实际预览和只读重开通过。下载18330字节、两页。
- `/tmp/office-pdf-sidebar-attachments-verified-built-20261112/`：目录失败、内容失败、已加载、待保存、只读、空附件六状态三十场景；四种真实附件下载、过期下载/读取拒绝、碰撞、增删、UndoRedo、刷新和实际预览保存下载通过。下载90917字节、三页。

终态后用pypdf独立读取实际落盘文件，各目录生成`independent-sidebar-check.json`：三个manifest仍一致，39个运行JS逐一与磁盘SHA/字节数相符，共六十五布局场景，逐phase failures为空。绘图Line从两条减至一条，原文字、表单和便签保留；批注输出来源顺序[1,0]，四条正文精确核对，包括完整913字符Bob长回复、keep note、edited through sidebar与pending updated，八条真实行内End到底证据及脚本Home回首等待通过。附件逐字节比较保留empty.bin零字节、folderB/same.txt十七字节、报告.bin76800字节，删除folderA/same.txt，新增zz-new.bin六字节[0,1,2,255,128,10]；原文字/表单保留，新增便签精确匹配。

人工查看最终PC附件/批注/长回复/绘图、390×320长回复和只读批注/绘图截图。短屏通过侧栏与正文内部滚动逐项访问，不声称全文同时显示。侧栏沿用既有默认150px及clamp，窄栏操作可换行。鉴权、CSRF和修订路由仍是显式fixture，不代表生产授权、桌面拖拽或四格式全量验收。每轮真实脚本运行期间冻结产品/static/共享检查器，全终态后才改动下一轮。

源码清单同步自`/tmp/office-ui-inventory-pdf-sidebars-20261112/inventory.md`，725模块4382声明点，不是独立功能数或完成率。本批没有完整项目测试、提交、推送或部署；其它复杂侧栏/AI及四格式剩余组件仍待处理，Excel异步Injector释放错误和CF缺省文字色问题未修复，整体goal保持active。

## PDF 缩略图、目录大纲与文档属性

上一goal turn为progress，本批继续PC方向：导航侧栏增加固定标题、28px标题关闭和入口/当前Ribbon标签焦点恢复；缩略图与目录以来源pageId同步选中态。保留侧栏宽度与clamp、拖动、缩略图实际栅格尺寸、按需渲染/缓存释放以及来源页跳转逻辑。目录13px、圆角选中行、缩进上限为栏宽30%，长标题完整保留并允许行内滚动；行高普通上限180px、短屏96px，仅无修饰键Home/End处理正文首尾。属性继续为来源文档只读信息，增加标题关闭与aria-expanded，标签/值对齐、长值换行、最高300px/45dvh内部滚动，不改PDF纸面内容。

基线证据：`/tmp/office-pdf-navigation-unit-red-20261112.log`七失败二十七跳过，其中四条导航关闭与当前页标记共五条可靠捕获缺陷；两条属性关闭测试最初未等待已有Promise事件，不能把这两条失败视为产品证据，补齐等待后继续验证。`/tmp/office-pdf-navigation-red-built-20261112/navigation-editable-evidence.json`在9960...构建上六场景116条失败，涉及原生字体、缺少标题/关闭、当前页标记、深层长目录的溢出/不可达。真实脚本退出1，未到原侧栏生命周期验收；已查看PC长目录基线截图。

首轮`/tmp/office-pdf-navigation-unit-verified-20261112.log`实际两文件37项通过，命令中额外指定的不存在pdf-sidebar.test.ts未产生覆盖，不计入文件数。typecheck/build/budget同前缀日志退出0，构建44.63秒；manifest为`1e8a11fadc6d8785f7b3891d77fc9290b233fdf0fc1a63c10d6f24dcea9ad208`。真实`green-built`十五场景已通过样式/焦点/边界检查，但五个缩略图场景捕获选中pageId和纸面边框不一致。源码确认旧缩略图点击仅更新activeId与控件，没有同步纸面is-active，随后在既有updateControls统一同步纸面选中类，不改选中身份规则。

人工查看属性截图还发现真实文件显示0 bytes：PDF.js将传入缓冲区转移至worker，旧代码在转移后读取file.byteLength。现于加载前保留实际字节数，摘要校验照旧。新双页选择与缓冲区转移测试先因jsdom缺少scrollIntoView而混入一条未捕获异常；补齐测试页面的滚动stub后，`/tmp/office-pdf-navigation-selection-size-red-verified-20261112.log`准确两失败三十五跳过，分别为纸面仍在page0而选择page1、0 bytes而实际2 bytes，无未捕获错误。`final-unit`两文件39项通过，final-typecheck/build/budget退出0（44.86秒），manifest为`d4e36a813fd4df68175b47aa67c5085ab8893673755ff24d146f97feb1fb0ac8`。

新增`smoke/pdf-navigation-checks.mjs`并扩展已有真实`pdf-sidebar-smoke.mjs`，通过可选PDF_NAVIGATION_VIEWPORTS使用30页真实PDF、14个含深层长标题的目录和完整长属性值；从实际DOM逐项滚动/键盘聚焦，检查命中/边界、焦点环、28px关闭、横向溢出、完整来源标题及实际文件大小、Home/End、pageId与纸面一致和草稿不变。五视口1440×900、320×640、640×360、390×320、1440×360；可编辑/只读各十五场景，1440×360另验证切换Ribbon后关闭返回当前标签。首个final-built三十场景退出0；截图发现smooth跳转尚未结束便取图，随后增加目标纸面实际进入视区的等待。`/tmp/office-pdf-navigation-verified-built-20261112/evidence.json`同d4e...构建三十场景通过，包含78条行内滚动首尾检查、39个运行JS；原拖动/取消/键盘边界、窄屏clamp不持久化、缓存隔离/位图释放、真实预览/原件下载及销毁样式恢复断言均保留。不将这两次相同场景相加计数。

补跑既有`pdf-reading-state-smoke.mjs`发现卸载后阅读位置被覆盖，三次失败分别保留于`/tmp/office-pdf-navigation-reading-built-20261112/`、`reading-verified-built`和`reading-diagnostic-built`同前缀目录。第一次失败后增加普通open等待宿主aria-busy=false和首次滚动实际位置断言；仍在原延迟恢复断言失败，未删减或跳过。诊断trace确认beforeunload/pagehide时scrollTop1029、记录第2页均正确；随后第二次存储写入时scrollTop归零并覆盖为第1页。源码确认pdfAIDock.dispose会将layout移出workspace，旧宿主却在该布局移动之后才调用saveReading。现将保存阅读位置移到宿主dispose第一步，停靠区和画布清理API原样保留。

`/tmp/office-pdf-navigation-dispose-red-20261112.log`一失败三十七跳过，用双页几何和浏览器重挂载归零行为捕获保存成page1/frac0而不是page2/frac0.25。修复后`/tmp/office-pdf-navigation-dispose-green-20261112.log`四文件49项通过：宿主38、阅读状态7、目录2、AI停靠区2。dispose-typecheck/build/budget同前缀日志均退出0（45.12秒），预算未放宽、既有构建warning保留。该轮manifest为`3cc4ac2d527e670d66ba5bd46e990aedeab74858f8cd590189ef6cd206b0d704`；两条真实脚本在该冻结构建上的终态与独立回读续记如下。

3cc4...构建上`/tmp/office-pdf-navigation-dispose-verified-built-20261112/evidence.json`退出0、三十场景及原侧栏生命周期通过；`/tmp/office-pdf-navigation-reading-dispose-verified-built-20261112/`仍退出1，但卸载的两次保存均正确保留第2页，失败推进至重载后实际位置恢复等待。trace显示新文档载入完成后scrollTop再次归零；源码确认初次await refresh已恢复位置，随后mountPdfTaskDock才将layout挂进workspace。现把首次解锁/refresh移到停靠区挂载之后，避免已恢复的滚动节点再次重挂载。没有增加延迟、清空阅读记录或取消恢复断言。

`/tmp/office-pdf-navigation-mount-red-20261112.log`一失败三十八跳过，带实际来源阅读状态和双页DOM几何，模拟重挂载归零，捕获初始打开后scrollTop0而不是600。`/tmp/office-pdf-navigation-mount-green-20261112.log`四文件50项通过（宿主39、阅读状态7、目录2、AI停靠区2）；mount-typecheck/build/budget同前缀日志退出0（45.07秒）。最终冻结manifest为`58454024a02a55b351800dd4c2b5f355a9e204ae89f42de7096d9767dbfd3eac`。

最终两个真实脚本均已确认终态退出0，evidence.ok=true，各39个运行JS身份相符，运行期间冻结产品/static与共享检查器：
- `/tmp/office-pdf-navigation-mount-verified-built-20261112/evidence.json`：可编辑/只读三组件×五视口共三十场景，两个phase的failures均为空，78条真实长目录End到底/Home回首等待通过，关闭焦点与纸面/导航选择身份一致。原真实鼠标拖动、不在拖动中重新栅格化、Escape/pointercancel/blur/切换取消、分隔符键盘边界、窄屏宽度记忆、位图离屏/删除释放、实际预览与只读/损坏及拒绝存储、销毁恢复cursor/userSelect全部通过。
- `/tmp/office-pdf-navigation-reading-mount-verified-built-20261112/evidence.json`：原缩放及页内比例、重载自适应重算、逆序页投影、实际预览返回原稿、pagehide立即保存、延迟恢复不覆盖、用户导航优先、用户/修订隔离、损坏记录/拒绝存储及只读浏览全部通过；新增核验刷新后缩略图和纸面均保留所选来源page1。保留53条生命周期trace，没有将此前三次旧位置覆盖和一次挂载归零失败改写为通过。

两脚本终态后，使用pypdf独立读取落盘文件并逐一核对运行JS磁盘SHA/大小，结果写入各目录`independent-navigation-check.json`。manifest仍5845...；导航来源/原件下载20731字节、30页且逐字节相同，实际预览21790字节、29页，删除最后来源页，文字和表单保留、14条完整目录标题保留、原keep note与新增sidebar preview note精确匹配。属性长标题与实际20731 bytes相符。阅读回归来源/原件下载11603字节、三页且逐字节相同，实际预览12628字节、三页，来源顺序[2,1,0]、文字/表单以及原便签与reading-state preview note保留。这些是实际预览和原件下载证据，不冒充本批生成新保存修订。

人工查看最终PC目录/缩略图、只读PC完整长属性，以及390×320只读长目录与属性末端截图；标题关闭可达、页边框与导航选择一致，长值/长标题靠内部滚动完整访问。短屏初次打开属性可需滚动宿主再查看正文，不声称所有字段和Ribbon能同时显示。鉴权/CSRF/修订路由仍为显式fixture，真实Python引擎和PDF.js，不代表生产授权、桌面拖拽等价或四格式全量验收。

源码清单已刷新至`/tmp/office-ui-inventory-pdf-navigation-final-20261112/`并同步仓库：725模块4382声明点，非功能分母/完成率；三个相关smoke/helper的node语法、git diff --check及清单cmp均通过。本批没有完整项目测试、提交、推送或部署。PDF复杂回复/AI与其它格式剩余组件继续核查；Excel异步Injector释放和CF缺省文字色问题仍未修复，整体goal保持active。

## PPTX 调整表格行列窗口

本批继续已授权的桌面Office方向，局部处理原先没有主题的“调整表格行列”弹窗：复用slides-table-dialog和slides-settings-dialog，PC宽520px、28px标题关闭、30px字段与按钮，增加可见参考行/列标签及原生fieldset/legend行列分组。新增行列和删除行列仍为原六种即时暂存操作，删除用危险色文字，取消在右下方；不增加确认或额外操作。保留原说明并关联aria-describedby，窄屏分组内按钮换行、短屏在窗口内滚动。共享设置helper仅将初始字段选择从input扩展到input/select，沿用原焦点陷阱、Escape和返回入口行为。

来源Sha、草稿快照、当前来源对象、代际、保存/销毁/过期窗口守卫以及1–75行列范围均保留；未改变结构修改的保存、Undo/Redo、刷新恢复、单元格/版式冲突锁定或来源表格渲染方式。新增四条宿主回归覆盖首字段焦点/可见标签和分组，以及取消、Escape、标题关闭后的入口焦点、选择重置和草稿不变。

基线证据：`/tmp/office-pptx-structure-unit-red-20261112.log`两失败、两通过、26跳过，准确捕获初始焦点缺失和没有标题关闭。`/tmp/office-pptx-structure-red-built-20261112/structure-layout-evidence.json`在58454024...构建上一个PC场景14条失败，涉及原生字体、标签/分组、宽度/焦点环和标题关闭；脚本终态退出1，未到后续保存断言。人工查看原生平铺窗口截图。

`/tmp/office-pptx-structure-unit-green-20261112.log`三文件52项通过（结构30、共享宿主21、焦点陷阱1），保留六操作、1/75边界、过期/篡改/保存中拒绝及冲突草稿等原断言。`/tmp/office-pptx-structure-build-20261112.log`包含TypeScript检查与Vite构建，终态退出0、构建45.27秒；`/tmp/office-pptx-structure-budget-20261112.log`预算检查退出0，未放宽预算。原有循环chunk、注解和大chunk警告仍保留。最终冻结manifest为`dc6dcff0ef41d8e5ed288a6861269c344f9865dd4284f6ff183550a4752be4d3`。

首个green-built脚本五视口产生40条焦点环误报：逐项证据显示全部控件hit=true/focused=true，但脚本在鼠标选择后用程序focus检查键盘focus-visible。按输入方式区分后，改用真实Tab逐项遍历并核验每项焦点/命中/2px环；没有修改产品CSS或放宽断言。该失败目录保留，不计为产品修复或成功保存证据。所有先前脚本终态后才修改检查器，并在同一冻结构建复核。

最终两个真实脚本均已确认终态退出0：
- `/tmp/office-pptx-structure-verified-built-20261112/evidence.json`：1440×900、320×640、640×360、390×320、1440×360五场景、50项真实键盘可达/命中/焦点环检查全部通过；检查完整字段标签、分组、字体、PC宽度/左右表单、窗口和控件边界、Tab/Shift+Tab循环、Escape/标题/取消关闭回入口、重开参考行列重置且草稿不变。随后保留原插入行、Undo/Redo、刷新锁定、真实保存/下载逐字节核对和修订2重开九单元格断言。123个实际运行JS与磁盘身份相符，pageErrors/failedResponses为空。
- `/tmp/office-pptx-structure-settings-built-20261112/evidence.json`：原插入表格、新增节、页眉页脚三个设置窗口×相同五视口共15场景通过，包含无效输入、长页脚、字段重置、关闭和焦点循环；123个实际JS身份匹配，pageErrors/consoleErrors/routeErrors/failedResponses为空。该脚本显式layoutOnly=true、零保存请求，不冒充本批另一次保存验收。

终态后运行`/tmp/verify-office-pptx-structure-20261112.py`，生成最终结构目录的`independent-structure-check.json`：manifest与123个JS的SHA/大小逐一核对，来源28539字节、下载40989字节；实际PPTX为3行3列，原两行文字/粗体保留，新第三行全部留空，表格高3英寸且宽/位置不变，旁侧原文本框XML及theme1.xml逐字节保留，ZIP完整。下载SHA为`1b26e1f91e9bb8b4e13e2b167fa9d491a20434f94e5ea04e9787056a27da1874`。另独立核对设置回归的123个JS、15场景和零保存请求，写入`independent-settings-check.json`。

人工查看最终PC结构窗口、320×640窗口、390×320滚动末端，以及原页眉页脚PC截图。短屏依赖窗口内部滚动逐项访问，不声称所有分组和标题同时显示。真实Python/Node引擎及下载文件回读，授权、CSRF、修订路由仍为显式fixture，preview.pdf占位不代表PDF转换验收。六种操作本批均有宿主回归，真实新修订文件验证的是向下插入一行，不把它扩称六种操作均经过真实文件保存。

源码清单同步自`/tmp/office-ui-inventory-pptx-structure-20261112/`：725模块4387声明点，非功能数或完成率。没有完整项目测试、提交、推送或部署。四格式仍有未逐项验收组件；Excel异步Injector释放和CF缺省文字色仍未修复，整体goal保持active。

## PPTX 动画窗格

本批承接上一批有效进展，继续桌面Office方向：动画窗格增加28px标题关闭、关闭后恢复当前可见入口焦点（动画入口已随切换Ribbon隐藏时，返回当前标签）；保留原aria-pressed入口状态。列表最高min(420px,48dvh)内部滚动，选择及计时重绘保留同页列表scrollTop，跨来源页重置。行标题30–80px、完整对象名按需换行/行内滚动，tooltip同时保留完整行名及计时；无修饰键Home/End访问行内首尾。24px排序/删除按钮和原计时提示保留。中屏下窗格占满对象栏的网格列。

选择/取消选择后把焦点还给重建后的同一行；移动后跟随同一动画，继续移动按钮可用时保留按钮焦点，到边界则落在该动画的选择按钮；删除后落到邻近存活行，删除最后一条后落到标题关闭。没有改写动画序列、触发、计时、来源引用、只读预设计时、段落目标或动作路径规则；保存锁与过期事件的捕获守卫继续生效。

基线：`/tmp/office-pptx-animation-unit-red-verified-20261112.log`11条失败中10条准确捕获关闭/焦点/滚动/提示缺陷，另1条最初错误要求保存中可选择动画，不能作为产品缺陷证据；检查既有root捕获锁后改为验证保存中拒绝过期选择/删除事件。最早未纠正readonly参数的`unit-red`日志也保留，不将其当作只读验收。`/tmp/office-pptx-animation-long-row-red-20261112.log`另1失败、11跳过，捕获Home/End缺失。`/tmp/office-pptx-animation-red-built-20261112/animation-layout-evidence.json`在dc6dcff0...构建上1个PC场景11条失败，其中3条键盘焦点探针后来证实调用方式错误，不作为产品缺陷；其余关闭、长列表、完整提示及选择/移动/删除焦点问题有独立证据。脚本退出1，未到保存阶段，原平铺长列表截图已人工查看。

首个`/tmp/office-pptx-animation-unit-green-20261112.log`三文件37通过、1失败，唯一失败仍为上述保存中可选择的错误期望；没有为通过测试放开保存锁。修正后`/tmp/office-pptx-animation-pane-unit-verified-20261112.log`13项窗格宿主测试全部通过；同一产品代码下动画序列4项和共享宿主21项在前一日志已通过，合计38个不同测试，不把重复执行的窗格测试相加。覆盖普通/边界移动、首尾删除、空列表、长名、Home/End及组合键、选中态、列表滚动、计时字段不抢焦点、关闭切换标签回退、保存中拒绝过期事件。

`/tmp/office-pptx-animation-build-20261112.log`包含TypeScript检查和Vite构建，终态退出0、构建45.10秒；`/tmp/office-pptx-animation-budget-20261112.log`预算退出0，未放宽。原有chunk循环、注解和大chunk警告保留。冻结manifest为`45fc5aa12f64d2590e6c2e2fb4aa3934182e0ffa6cdea6350e154e36f2658f9a`。

首个green-built五场景15条键盘探针失败，逐项证据均为focused=false/ring=false：检查器使用locator.press('Shift+Tab')，会在按键前重新聚焦该locator，不能与前一Tab组成往返。改用page.keyboard的连续真实按键，并让滚动几何检查显式将目标移至可视区域；没有修改产品或弱化命中/焦点环断言。短屏另需宿主和列表滚动，不能从一次滚动尚未稳定的截图判断整个控件已显示。该失败目录保留，未冒充保存成功证据。所有真实脚本终态后才修改检查器，重跑同一冻结构建，同时增加删除最终来源动画的空状态检查。

最终`/tmp/office-pptx-animation-verified-built-20261112/evidence.json`脚本终态退出0、ok=true：
- 真实Ribbon添加24条临时动画，连同2条来源动画形成26条列表；1440×900、320×640、640×360、390×320、1440×360五视口检查字体、横向边界、78个行操作按钮尺寸和内部列表滚动。每视口采样首条/第15条/末条，共15条真实键盘焦点环/命中/选择与取消选择检查，并验证每条长名称Home/End完整访问。
- 各视口检查上移至边界、删除末条后的焦点、Undo精确恢复原草稿、关闭入口状态/焦点、28px标题关闭键盘焦点与命中。移动和删除各5次；行选择与关闭不改草稿。24条临时新增全部撤销后，另删除2条来源动画至空列表，验证空提示和标题关闭焦点，再完整撤销回原来源内容。
- 保留原真实保存链的“无”删除原淡入、按段飞入、锯齿路径、重排、修改缩放计时、删除/Undo/Redo、保存/下载逐字节核对、修订2重开及生产inspect回读断言。最终保存3条动画，不把临时26条布局夹具说成全部保存验收。脚本原pageErrors/failedResponses断言通过，123个实际运行JS有响应身份记录。

终态后运行`/tmp/verify-office-pptx-animation-20261112.py`并写入`independent-animation-check.json`：当前manifest与123个JS的SHA/大小逐一核对；来源41513字节、下载41754字节、ZIP完整。直接用lxml读取实际下载的p:timing，确认缩放为shape3/withEffect/1200ms；自左飞入为shape2/clickEffect/500ms/第0段，x插值从0-#ppt_w/2开始；锯齿动作路径为shape3/clickEffect/2000ms及完整路径。整个来源p:spTree与theme1.xml原样保留，正文两段、旁侧Untouched object及粗体保留。下载SHA为`5f7fcc196bdce3960563527cf95c1df84d72ff26613ba21c29570b92ee7d1e03`。

人工查看PC列表开头/末端、390×320末端和1440×360空状态截图。390×320受既有应用栏/Ribbon占高影响，仅少量正文同时可见，依赖宿主、列表和长行内部滚动逐项访问；不宣称标题、所有行及整个Ribbon能同时显示，也不将15行抽样扩称26行全量键盘遍历。实际浏览器、Python/Node引擎和ZIP/XML回读，授权、CSRF和修订路由仍为显式fixture；preview.pdf仍为占位，非PDF转换验收。保存期间整个编辑区保持既有锁定，未声称支持保存中浏览动画。

源码清单同步自`/tmp/office-ui-inventory-pptx-animation-20261112/`：725模块4388声明点，非功能数/完成率。相关smoke与检查器node语法、清单cmp和git diff --check通过。本批没有完整项目测试、提交、推送或部署。四格式剩余组件继续核查；Excel异步Injector释放和CF缺省文字色问题仍未修复，整体goal保持active。

## PPTX 经典批注窗格

本批继续按尽可能贴近PC Office的方向，局部调整经典批注窗格：统一主题字体、细边框和小圆角、28px标题关闭、30px操作按钮及焦点环；列表与长正文分别滚动，正文最高180px，短屏96px；作者名保留完整tooltip，日期和正文可换行。中屏窗格跨满网格列并保留最小高度，标题清除继承自属性栏的负边距；正常高度标题吸顶，400px及以下高度改为普通流以便宿主滚动访问关闭按钮。没有修改共享Ribbon、来源身份、发布/撤回、UndoRedo、只读原因及保存锁规则。

同来源页重绘保留列表和窗格scrollTop，输入焦点、选择范围/方向及textarea内部滚动位置；卡片按来源authorId/idx或新增clientId恢复焦点，删除后落到邻近存活卡片。发布/取消后返回新增入口，关闭后返回可见批注入口，入口随切换Ribbon隐藏时返回当前标签。只读正文可Tab聚焦，Home/End访问长文首尾，组合键交给默认行为；输入框增加aria-describedby及aria-invalid，IME composing期间Ctrl/Meta+Enter不触发发布。

失败先行：`/tmp/office-pptx-comments-unit-red-20261112.log`6失败、9跳过，捕获关闭/取消/发布/删除焦点丢失、重绘丢失编辑状态、只读长文不可键盘聚焦及IME误发布。实现后`/tmp/office-pptx-comments-unit-green-20261112.log`3文件38项全部通过：经典批注宿主15项、批注数据10项、动画窗格13项；本批不把重复运行累计为新测试数。原来源重排、同idx不同作者、刷新、未失焦保存flush、AI与Undo、非法文本及来源页删除保护继续通过。

旧构建45fc5aa1...上的`/tmp/office-pptx-comments-red-built-20261112/`基线终态退出1：完成PC的4个阶段截图，640×360重开窗格超时。实际截图显示中屏侧栏被放进首个网格列且正文无可用高度；该检查器当时尚未逐场景checkpoint，没有完整布局JSON，不声称基线完成全部视口。未保存，无浏览器或路由错误。增加长作者和32段来源长批注的真实PPTX夹具，verify改为逐字段精确对比来源保留记录，不再依赖旧短文本常量。

首个新构建manifest为538f66a7...，`comments-build`和`comments-budget`退出0。其真实经典检查`/tmp/office-pptx-comments-green-built-20261112/`20场景报告8条失败，只读`/tmp/office-pptx-comments-boundaries-built-20261112/`在modern的5场景报告2条失败，均在布局断言退出1、未保存：640px标题继承.inspector-heading的-14px边距而横向溢出；640/390短屏部分标题关闭中心被宿主遮挡。没有放宽断言。两脚本终态后才局部清除标题margin，并在短屏取消标题吸顶；检查器补记控件rect和实际命中元素用于诊断。

最终`/tmp/office-pptx-comments-build-verified-20261112.log`TypeScript/Vite退出0，Vite44.90秒；`/tmp/office-pptx-comments-budget-verified-20261112.log`预算退出0，未放宽。既有chunk循环、注解和大chunk警告保留。冻结manifest为`8a53b35f39898db94bcdef68cda67936195e6c3ae60f6915133946fcae0741d3`。构建及真实脚本运行期间没有修改产品源码、静态产物或共用检查器。

最终两个真实浏览器脚本均终态退出0、ok=true：
- `/tmp/office-pptx-comments-verified-built-20261112/evidence.json`：1440×900、320×640、640×360、390×320、1440×360五视口，每视口来源/编辑器/临时新增/删除至空四阶段，共20布局场景、120次控件Tab往返/中心命中/焦点环检查。长正文Home/End、完整作者提示、字体/尺寸/横向边界、非法超限输入、关闭重开保留输入、取消与发布焦点、撤回及Undo精确恢复来源均通过。临时布局批注全部撤回，不将这些临时内容称为保存验收。
- 同一脚本保留原真实链：来源同idx不同作者、页面重排定位、取消、发布/撤回、来源删除、UndoRedo、刷新恢复、输入未失焦直接保存；实际仅一次保存，4条commentEdits（删2条来源、新增2条用户批注），validation.ok=false仍有下载并显示具体复核警告。下载后重开修订2，保留Bob，Alice来源批注已删，两条新增存在，第二页为空。
- `/tmp/office-pptx-comments-boundaries-verified-built-20261112/evidence.json`：现代/未知批注来源、authorId损坏两种只读变体各5视口，共10布局场景、20次正文/关闭键盘与命中检查；原因可见，新增/删除保持禁用，无草稿写入、无保存请求。
- 两脚本分别核对123个实际运行JS的响应SHA与磁盘文件，pageErrors/consoleErrors/failedResponses/routeErrors均为空；记录manifest、Node桥及夹具身份。Node桥SHA为0814aee6...，夹具SHA为191234df...。

终态后`/tmp/verify-office-pptx-comments-20261112.py`独立核对最终manifest及两组123个JS的SHA/大小，读取实际下载ZIP/lxml，结果为经典目录的`independent-comments-check.json`。第一次过严地断言不得增加任何ZIP entry，实际新增的14条均为空目录；确认is_dir且file_size=0后修正为禁止新增文件部件，没有改产品/放宽正文保存断言。最终退出0：来源30978字节、下载43289字节，下载SHA为`28619d1103ad277fd3d2b2f2ba0bb0b4c46f18165a58132cf15856534ec727f2`；全部XML有效，长Bob作者/正文逐字精确保留，两条新增归属“用户”，第二页最后批注的part/relationship/content-type均移除，两页正文及所有无关部件逐字节不变。唯一变化为内容类型、第二页comments关系、作者表及两页comments部件。

人工查看最终PC编辑器、PC只读、320×640编辑器、640×360只读和保存警告/下载截图。极矮窗口仍受应用栏和Ribbon占高限制，需滚动逐项访问；中心命中通过不等于所有控件边缘、标题、列表与Ribbon能同时完整显示，不将其标记为短屏一屏展示。实际浏览器、生产Python/Node引擎及ZIP/XML验收，授权/CSRF/修订路由仍为显式fixture；preview.pdf占位，非PDF转换或生产权限验收。夹具自带的notes_edit_relationships_invalid提示仍可见，非本批修复内容。

源码清单同步自`/tmp/office-ui-inventory-pptx-comments-20261112/`：725模块4388声明点，非功能数或完成率。检查器node语法、清单cmp和git diff --check通过。本批没有完整项目测试、提交、推送或部署；四格式其余组件继续逐项核查，整体goal保持active。Excel异步Injector释放与CF缺省文字色问题仍未处理。

## 四格式共享助手停靠与浮动窗口

本批继续尽可能贴近PC Office，局部调整Word/XLSX/PPTX的office-task-dock及PDF的pdf-ai-dock共享窗口：继承Office主题字体，标题按钮固定尺寸，模式栏改为平面标签/底部选中线，窗口、输入区、预设和证据区域统一主题小圆角与细边框，移除默认装饰阴影；保留输入聚焦提示，补充按钮、选择器、折叠提示及结果区的键盘焦点环。只读XLSX/PPTX分支没有加载工作簿/幻灯片主题，原先Office token缺失，改由四格式共用floating模块显式加载既有office-theme，不另造主题。

窄屏或高度不超过480px时，窗口与结果区分别滚动，结果区保留至少64px。极矮停靠窗口改为距离视口边缘8px的覆盖式窗口，修复Word在390×320下高度为0、按钮被状态栏截获的问题；正常桌面仍使用原停靠布局。结果区增加tabindex=0、region及原有阅读标签；只有结果区自身、无修饰键且非IME组合状态的Home/End才直接滚动首尾，子输入控件和组合键保持原行为，dispose移除监听。没有重建任务控制器或改变取消、采纳、授权来源身份及编辑草稿逻辑。

失败先行：`/tmp/office-assistant-window-unit-red-20261112.log`1失败、3跳过，捕获结果区不可聚焦；`/tmp/office-assistant-window-home-unit-red-20261112.log`1失败、4跳过，捕获缺少显式Home/End处理。首轮green单位测试8文件37项通过，wiring另3文件9项通过；最终新增首尾滚动测试后panel文件5项通过，合计47个不同定向测试，不累计重复panel运行。其中其余42项在最后Home/End监听变更之前通过，最后5项覆盖该变更及组合键、IME、子输入框和释放监听。日志分别为`office-assistant-window-unit-green`、`office-assistant-window-wiring`、`office-assistant-window-home-unit-green`，均在`/tmp/`、后缀`-20261112.log`。

旧manifest 8a53b35f...上的基线目录`/tmp/office-assistant-window-red-20261112/`记录XLSX/PPTX各4个场景、Word3个场景后短屏点击超时，字体、圆角、焦点环和Word零高度问题有证据；另`word-red`目录完成Word4场景并执行真实阅读，仍有样式缺陷。PDF初版脚本误用`--output-dir`而非`--directory`，且等待已退出server导致exit13；此`pdf-red`目录是检查器失败，不计产品缺陷。后续`pdf-word-red`中PDF完成4场景，但查找不存在的`data-pdf-ai=summarize`超时；纠正为实际Ribbon命令后才继续，不用这些失败冒充完成阅读验收。

首个新构建manifest ace9ff06...的`/tmp/office-assistant-window-green-20261112/`完成XLSX7场景后，在第8个极矮浮窗发现End成功而Home未回到开头。独立`other-diagnostic`中Word/PDF/PPTX各4场景，唯一失败仍为PDF极矮浮窗Home：afterEnd与afterHome均top386、height112、scrollHeight499且focused=true。仅靠重跑时偶然通过的`home-diagnostic`及`xlsx-sequence-diagnostic`不能视为修复；据此补充上述显式键盘监听及失败先行测试。以上真实脚本全部终态后才编辑产品或共用检查器。最终检查器还将resultScrolledByKeyboard改为从实际首尾位置和焦点计算，并将聚合审计阶段显式命名final-audit，未削弱失败断言。

最终`/tmp/office-assistant-window-build-verified-20261112.log`包含TypeScript检查与Vite构建，终态退出0、Vite44.95秒；`/tmp/office-assistant-window-budget-verified-20261112.log`预算退出0且未放宽。既有chunk循环、注解及大chunk警告保留。冻结manifest为`c9b4ba7df601a475e9396e64a71a01ea89e66f18e0637f22f2f4055971419bc1`。构建和最终真实浏览器运行期间没有修改产品、静态资源或共用smoke助手。

最终`/tmp/office-assistant-window-verified-20261112/evidence.json`脚本确认终态退出0、ok=true：

- XLSX/PPTX/DOCX/PDF各在1440×900、320×640、640×360、390×320、1440×360下检查停靠和浮动，共40场景、516次控件Tab往返/中心命中/焦点环检查，全部通过；40个结果区全部验证真实End到末尾及Home回开头且焦点仍在结果区。逐格式layout JSON保留几何和键盘滚动位置。
- 桌面非PDF停靠分隔条ArrowLeft加宽20px、ArrowRight复原；浮窗拖动柄ArrowLeft/ArrowUp操作后检查边界，切回停靠保留待提交输入；关闭恢复原入口焦点，重开保留原输入。窗口操作前后草稿相同，没有额外启动AI任务。
- 每格式先通过真实grant/cookie/router和实际Agno执行器完成一次阅读，检查completed、answer、issues为空、sourceSha匹配，再以真实完成结果检查窗口。每格式最终job仍为1，没有编辑、保存、导出或发布POST；原来源与工作区来源逐字节相同。148个实际运行JS的响应SHA/大小与磁盘匹配，pageErrors、consoleErrors及HTTP错误均为空。

终态后运行`/tmp/verify-office-assistant-window-20261112.py`，生成该目录`independent-window-check.json`，退出0。独立核对40场景、516项控件状态、40组首尾滚动、manifest及148个JS身份、各格式单任务与请求范围；直接读取来源与工作区副本，SHA/字节全部一致。用openpyxl核对经营表收入42/费用12；python-pptx核对两文本框与未被读取的讲者备注原样保留；python-docx核对两段及净收益30的表格；pypdf核对两页文本、400×350页框、批注和书签。来源大小依次4871、33079、36863、2271字节，没有用仅UI状态替代实际文件回读。

人工查看四格式最终PC停靠、390×320浮窗内容截图，以及XLSX/Word/PDF窄屏截图。小屏依赖窗口和结果区内部滚动，标题与输入不必同时出现在一屏；不将中心命中检查称为所有控件/标题一屏完整显示。XLSX/PPTX此夹具是原件阅读分支，无编辑网格/幻灯片引擎；Word/PDF为只读宿主。模型为实际Agno中的ScriptedModel，修订查询为显式fixture，不代表真实provider，也不扩称编辑、审阅、表单等全部任务模式已验收。本批没有保存/导出需求或保存链改动，未重复运行完整项目测试。

源码清单最终同步自`/tmp/office-ui-inventory-assistant-window-final-20261112/`：725模块4388声明点，仍非功能数或完成率。两个新增smoke检查器node语法、清单cmp与git diff --check通过。没有提交、推送或部署；四格式其余组件仍需逐项验收，整体goal保持active。Excel异步Injector释放与CF缺省文字色问题仍未处理。

## Excel 监视窗口 PC 续批

上一goal turn为progress：共享助手窗口已有实际修改及四格式验收。本批继续PC Office方向，局部调整workbook-watch-window：复用Office主题字体/小圆角/细边框，640px桌面宽度，44px浅色标题栏、28px标题关闭和单行操作按钮；表格固定布局，表头吸顶并保留列语义，普通行紧凑显示，长值/公式换行且保留完整title。窗口以视口高度限制，480px以下底边16px，表格独立横纵滚动，修复原窗口在390×320时标题关闭超出视口的问题。保留非模态窗口，不添加阻断底稿操作的遮罩或Tab陷阱。

打开聚焦首个可用按钮；关闭及Escape返回原入口，原入口随Ribbon重建/隐藏时返回当前标签，输入法组合期间Escape不关闭；dispose/reset不抢夺外部焦点。删除持有焦点的监视项后返回相邻存活项，删除末项回到可用标题操作；无选区时避开禁用添加按钮。表格区域可Tab聚焦并用无修饰键Home/End阅读首尾，不接管组合键。轮询继续保留已有DOM节点及焦点，原每次20格/去重、sheetId与坐标监视、800ms更新、来源失效及会话隔离契约未改，没有增加文件保存协议。

失败先行：`/tmp/office-watch-window-unit-red-20261112.log`4失败3通过，捕获初始/关闭/删除焦点与表格键盘阅读缺陷；另`disabled-unit-red`1失败7跳过，捕获禁用添加时初始焦点丢失。首轮green仍有1条测试错误要求整个jsdom环境定时器为0。`timer-ticks-diagnostic`打印剩余3个回调均为jsdom自身fireAnEvent("selectionchange")，产品clearInterval已调用；据此改为关闭后推进800ms并断言没有再次读取工作簿，未修改产品清理逻辑或忽略真实轮询。最终窗口文件8项全部通过，见`/tmp/office-watch-window-unit-final-20261112.log`。

同一日志中的旧宿主测试4项失败于缺失SheetsFilterService，导致载入失败并连带保存锁断言失败。对照当前advanced-filter/protection测试，确认公式追踪测试的真实Univer测试启动器漏注册现有筛选插件；仅在该测试启动器补齐UniverSheetsFilterPlugin，未绕过产品依赖或修改断言。`/tmp/office-watch-window-host-unit-20261112.log`4项随后全部通过，含只读监视不改snapshot/draft/history/status、非native保存锁外仍可监视、真实facade删表失效/Undo恢复及公式追踪回归。合计12个不同定向测试，不累计重复执行；既有getSnapshot弃用警告保留。早期命令带不存在的workbook-main-watch.test.ts实际只运行窗口文件7项，未将它算成宿主覆盖。

旧manifest c9b4ba7d...上的`/tmp/office-watch-window-red-built-20261112/`记录空列表5场景、30项列表3场景及190条检查失败，随后390×320标题关闭在视口外而真实点击超时，脚本终态退出1；这些是重复场景检查记录数，不是190个独立缺陷。基线PC截图确认旧蓝色标题与原生小按钮。该基线没有完成余下视口/行为链，不冒充保存验收。

第一次构建52c57857...（Vite44.86秒）先于禁用焦点补齐；第二次eadc1495...（44.74秒）完成禁用焦点修复，两个构建及预算均退出0。后者`/tmp/office-watch-window-green-built-20261112/`实际10场景及原9行为场景、保存后fixture分支均退出0，但人工PC截图发现删除文字纵向折行，150个删除按钮实际宽36px、高46px；`/tmp/office-watch-window-compact-controls-red-20261112.log`独立读取这些真实几何后准确失败。因此不把首个green当作最终视觉验收。全部真实脚本终态后，将操作列56px加宽到76px，按钮禁止文字折行，并给检查器增加宽至少44px、高不超过36px的严格断言。

同时纠正横向键盘探针：初版检查从删除按钮遗留的最右滚动位置按ArrowRight，只要求大于0，不能证明按键产生移动。最终先以instant回到0，按真实ArrowRight，等待位置变化并稳定后记录，再instant回左侧；不使用旧位置冒充键盘移动。另增加切换到Home标签后标题关闭的实际焦点检查及真实Enter删除后邻近项焦点检查。检查器改动均在构建/真实脚本终态后完成，运行期间冻结产品、static及共享smoke。

最终`/tmp/office-watch-window-build-verified-20261112.log`含TypeScript/Vite，终态退出0、Vite45.18秒；`/tmp/office-watch-window-budget-verified-20261112.log`预算退出0、未放宽。既有循环chunk、注解及大chunk警告保留。最终manifest为`64d01be2d1de4193945d0dd4d0ce80dd9dd99dbf4014ec3accbe87abe4a69968`，12项定向测试的产品TS与最终相同，之后仅修正本窗口CSS及检查器，没有重跑完整项目测试。

最终两个浏览器脚本均确认终态退出0、ok=true：

- `/tmp/office-watch-window-verified-built-20261112/evidence.json`：空/30项长内容两状态×1440×900、320×640、640×360、390×320、1440×360共10场景、180次控件Tab往返/中心命中/焦点环检查通过。150个删除按钮全部单行46×28px；5组Home/End及4组真正从0开始的横向键盘滚动通过；两状态切换Ribbon后关闭均返回Home，Escape返回监视入口，重开聚焦可用添加按钮。布局操作前后localStorage不变。
- 同脚本继续原9行为场景：保护表按20/30新增及去重、12.5%显示值与公式、轮询保留焦点、关闭重开与键盘删除/相邻焦点、跨表身份稳定、阅读前后draft/history/status和真实下载字节不变；随后实际改值触发公式重算、Undo、插行按原坐标监视、重命名跟随sheetId，reload及修订2清空监视会话。后半段有明确的底稿编辑，不冒充全程零修改；全程saveCount=0。
- `/tmp/office-watch-window-saved-final-built-20261112/evidence.json`：单独非native实际构建宿主，通过真实UI改值并接收fixture保存登记后，网格inert而监视窗口仍可增删、关闭和从Ribbon重开，状态与内容快照不变。该分支saveCount=1，但应答/修订为fixture，不代表实际生成了新XLSX或通过保存/导出引擎验收。
- 两脚本pageErrors、consoleErrors、failedResponses均为空。主脚本记录441次实际JS响应、147个唯一文件；保存后分支140次/140个唯一文件，响应SHA/大小均与冻结磁盘资源匹配。

终态后`/tmp/verify-office-watch-window-20261112.py`独立回读来源、下载、几何、键盘证据和全部JS，生成主目录`independent-watch-check.json`，退出0。两来源XLSX的ZIP完整，openpyxl核对三张表、Protected保护标记、A1/B1值与公式、C1百分比格式；主夹具另逐字核对三表D5长值及F5长公式。主来源6782字节、SHA`469a64e95b5711945e006eadafec9c09dfdd6fbc79538170cf5ad0e6089e30e0`，阅读前后两次实际下载与来源逐字节相同。另核对10布局、180控件、5组首尾/4组横向、两个切换标签关闭证据与manifest不变。

人工查看最终PC空/30项列表、320×640、390×320开头及长公式末端。窄屏需横向滚动访问右侧公式/操作列，长值依赖表格纵向滚动，不宣称五列与所有正文同时一屏展示。真实浏览器/工作簿引擎，授权/修订/保存应答为显式fixture，不代表生产授权、桌面拖动定位或真实保存回写。删表UI仍未冒充通过，其facade删除/Undo只有上述宿主定向证据。

源码清单同步自`/tmp/office-ui-inventory-watch-window-20261112/`，725模块4388声明点，非功能总数或完成率。两个smoke的node语法、清单cmp和git diff --check通过。本批未提交、推送或部署；四格式剩余组件仍需逐项覆盖，整体goal保持active。既有Excel异步Injector释放与CF缺省文字色问题没有在本批宣称修复。

## PPTX 静态放映 PC 控制条续批

本批继续尽可能贴近PC Office的方向，仅调整现有静态放映控制条：继承Office主题字体和小圆角，按钮30px高、12px字、单行文字，页码使用等宽数字，控制间距8px，保留深色放映背景和原幻灯片内容。使用100dvh及不收缩的控制条/说明区域，让320px窄屏仍保持按钮单行、390×320小高度仍可访问说明。增加控制组语义、悬停与2px主题焦点环；没有扩展动画、转场、音视频或演讲者视图。

修复全局Space错误接管工具栏原生按钮激活：按钮上的Space只隔离编辑器快捷键，不取消浏览器默认动作。首尾页切换导致当前导航按钮禁用时，将焦点转移到可用导航按钮；输入法组合期间不处理导航或关闭。保留原正文Space、方向键、Home/End/Escape、退出返回入口，以及只读快照契约。

失败先行：`/tmp/office-pptx-show-unit-red-20261112.log`记录新增3失败、原5通过；IME用例拆为逐键断言后，`/tmp/office-pptx-show-ime-unit-red-20261112.log`准确记录组合态ArrowRight错误翻页的1失败、7跳过。测试中外部键盘监听在断言前清理，避免RED失败泄漏。最终`/tmp/office-pptx-show-unit-green-20261112.log`两文件44项通过（放映8、原生Ribbon36），之后没有改变产品TS。旧构建基线`/tmp/office-pptx-show-red-built-20261112/`完成10布局场景，记录42条重复场景检查失败，反映按钮尺寸/字体、320px折行、Space激活及禁用焦点问题；该数不是42个独立缺陷。

`/tmp/office-pptx-show-build-20261112.log`含TypeScript及Vite，终态退出0、Vite44.97秒；资源预算日志`/tmp/office-pptx-show-budget-20261112.log`退出0，没有放宽预算。既有循环chunk、注解及大chunk警告保留。冻结manifest为`d1bfd51d01dbaa0a44a83a884b9c5f6878e92582a7daa8ae6f22ae0943f8d5b3`。布局检查器的最终键盘证据字段在构建终态后、浏览器运行前补齐；构建和浏览器期间保持产品、static及共享smoke冻结。

最终真实浏览器脚本确认终态退出0：`/tmp/office-pptx-show-verified-built-20261112/evidence.json`的ok=true、revision=3，pageErrors、consoleErrors、routeErrors、failedResponses均为空。1440×900、320×640、640×360、390×320、1440×360各首/末页，共10场景；20个可用控件的真实Tab/Shift+Tab往返、中心命中、主题字体、紧凑尺寸、焦点环及视口边界通过。5组原生Space依次激活下一页、上一页、退出，页码与可用导航焦点准确，退出返回入口，重开后草稿不变。人工查看PC、320×640及390×320首末页截图，控制条单行，画布4:3，静态能力说明可见。所有实际记录fullscreen=false，属于真实普通dialog回退路径，不宣称浏览器接受全屏；既有全屏变更单测仅为模拟事件。

该脚本保留原真实链：对来源三个对象组合、Undo/Redo、刷新，调用Python引擎保存、下载、独立回读并重开修订2；取消组合、刷新，再实际保存/下载/重开修订3；然后设置`Unsaved slideshow snapshot`待保存文字进行只读放映及从当前页放映。总共恰好2次保存，放映不产生新保存且保留待保存草稿。授权、CSRF、修订登记由明确fixture提供；PDF仅为辅助占位，不代表PPTX转PDF或生产授权验收。

终态后`.venv/bin/python /tmp/verify-office-pptx-show-20261112.py`退出0，生成`independent-show-check.json`：独立核对manifest与浏览器124个唯一JS文件的磁盘SHA/大小，10布局、20控件及5组原生Space记录。用python-pptx和ZIP核对三个实际文件各2页：来源29671字节、SHA`abf29d2013e16a8a58ad06efbe9a1b1e7732057d2f66bd2936fb9d9d986af765`；修订2为42528字节、SHA`ef22621ecd13b063058bbb3a8e2893f7966fee717af61b800cf63a679418a7a8`；修订3为42353字节、SHA`3a020b51778fe209546dba5fe391ffa58476d18bd750f669a638708339039bc6`。组合子对象及取消组合后的对象ID、名称、文本、几何、图片SHA和裁剪与来源一致，前后对象不变；除slide1.xml外其余ZIP文件部件字节相同，未保存放映文字不在修订3中。保存收据身份匹配实际文件。

本批实测夹具为2页4:3，不能外推到所有比例、空文档或超大页数。清单同步自`/tmp/office-ui-inventory-pptx-show-20261112/`，725模块4388声明点；全部725份来源SHA核对一致，canonical Markdown逐字节相同，声明点仍非功能总数或完成率。两份smoke通过node语法检查；没有重复完整项目测试、提交、推送或部署。四格式其余组件继续逐项覆盖，整体goal保持active；此前Excel异步Injector释放与CF缺省文字色问题仍未处理。

## PPTX 大小与位置窗格及短屏工作区 PC 续批

上一goal turn已完成静态放映修改与验收，分类为progress。本批继续现有PC Office方向，局部调整`slides-geometry-pane`：使用原生fieldset/legend区分尺寸、缩放、位置，保留左标签右字段、厘米/百分比、步进和参考点；统一主题字体、28px字段、小圆角、数值右对齐及等宽数字、2px焦点环、错误边框和禁用状态。没有改变厘米换算、来源96dpi坐标、精度、锁比例、图片原始尺寸、来源身份和保存协议。

比例复选框、位置参考点及输入Escape会重建控件，原来丢失键盘焦点。本批仅在这些当前窗格内操作后恢复对应控件焦点；外部update/setLocked不主动恢复焦点。组合输入中的Enter/Escape不再提交或撤回值。`/tmp/office-pptx-geometry-unit-red-20261112.log`先记录4失败6通过，准确捕获三条焦点路径及组合态Enter提前提交。最终`/tmp/office-pptx-geometry-unit-green-20261112.log`四文件40项通过：pane10、scale4、original5、宿主21。覆盖既有非法值/边界/重试、百分比基准、原图异步失效、来源锁定与宿主保存等；之后产品TS没有再修改，初次与最终清单中的该TS SHA相同，没有重复完整项目测试。

旧冻结构建`d1bfd51d...`上的`/tmp/office-pptx-geometry-red-built-20261112/`完成两类对象×五视口共10场景，记录255条重复检查失败，反映分组、字段尺寸、焦点环及三条交互焦点问题；不是255个独立缺陷。初次构建`75ceb550...`（44.75秒）后两个脚本均退出0并实际保存/独立回读，但早期检查只有中心命中，且直接截取超过短屏滚动区的整个pane，产生部分空白/裁切截图。因此`first-built`及`viewport-first-built`只保留为阶段证据，不能用它们宣称字段完整可见。

补充真实首尾字段视口截图及四角内侧3px命中检查后，`/tmp/office-pptx-geometry-edges-red-built-20261112/`在390×320的两类对象记录42条失败，实测工作区只有22px，28px输入框底边被裁切。定位为固定高度宿主与三行功能区争用空间：仅在高度不超过480px时把PPTX功能区内容区限制到80px并允许内部纵向滚动，保留原命令、分组和三行排列，常规PC高度布局不变。随后`a5ac1ca0...`构建（45.18秒）的`ribbon-red-built`显示工作区恢复92px、字段边缘通过，但助手大按钮高于可视区域，剩1条失败；补为短屏56px高按钮。

扩大到常规标签及形状/图片上下文后，`57a522ab...`构建（45.05秒）的`/tmp/office-pptx-geometry-inspector-red-built-20261112/`记录36标签状态414条控件检查通过，但640×360两类对象仍有40条字段边缘失败。定位为601–900px双行工作区使用`minmax(0,180px)`允许对象窗格收缩到零；只把该行下限改为120px。最终五视口中对象窗格高度分别为665、240、120、240、171px，保留宿主与窗格的现有滚动，不声称全部字段同时一屏显示。

最终`/tmp/office-pptx-geometry-inspector-build-20261112.log`包含TypeScript与Vite，终态退出0、Vite45.08秒；同前缀budget日志退出0，未放宽预算。最终manifest为`7b5d702ef317368d5c26e9c9db523fef00298332b5769c16e5d603db46ac98a8`。所有构建/浏览器运行期间冻结产品、static和共享smoke，先确认前一脚本终态才修改检查器或产品。既有循环chunk、注解及大chunk警告保留。

最终`/tmp/office-pptx-geometry-verified-built-20261112/evidence.json`确认脚本终态退出0、ok=true、revision=2：

- 文本框/图片两种真实来源对象，各在1440×900、320×640、640×360、390×320、1440×360检查，共10场景、215个可用控件的真实Tab/Shift+Tab往返、主题字体、28px字段、焦点环、中心及四角命中通过，工作区与对象窗格均至少90px。10组比例切换、参考点selectOption和Escape均保留焦点、草稿不变；参考点使用浏览器selectOption触发change，不冒充物理选择框按键。20张首尾字段视口截图通过可见性核对，另保留PC完整pane截图。
- 三个短屏中，file/home/insert/draw/design/transitions/animations/slideShow/review/view、shapeFormat及pictureFormat，共36标签状态414条控件记录，无裁切失败。包含禁用控件的显示检查；可用控件通过宿主DOM focus及滚动访问，不是414次命令激活，也不是完整功能或唯一控件数量。标签切换和阅读前后草稿不变；未展开所有菜单，也未覆盖表格、图表、3D上下文。
- 随后在真实宿主将源文本框宽度改为5.08cm并锁比例联动高度，Undo恢复空草稿、Redo恢复修改；图片相对120×80原始像素设宽200%、高150%，水平位置改为5.08cm。刷新恢复两条几何修改，再调用真实Python引擎保存、下载、独立回读并重开修订2。保存恰好1次，重开图片宽6.35cm、高3.18cm、水平位置5.08cm。pageErrors、consoleErrors、routeErrors、failedResponses均为空。

终态后`.venv/bin/python /tmp/verify-office-pptx-geometry-20261112.py`退出0，生成`independent-geometry-check.json`。独立核对10布局、215控件、20截图、10组交互和36标签414条记录，以及manifest与浏览器123个唯一JS的磁盘SHA/大小。python-pptx和ZIP核对实际来源29671字节、SHA`a009ab38a3e11e8f5ed5886c683fc9c744ccb4ab3523e03f0739a1d8890759ce`；修订2为42519字节、SHA`770bb49eddeeeac3cf12c352e83b410c9c29991b65dd0715ed7347c7047f2614`。两份各2页，保存收据身份匹配下载；仅Group A与Group image的指定几何变化，文字、对象ID/名称、图片SHA及裁剪不变，第二页不变，除slide1.xml外其余ZIP文件部件逐字节相同。预期几何由固定源尺寸和手算换算独立生成，不直接用待保存payload作期望值。

人工查看最终PC完整pane与编辑器、320×640图片、640×360及390×320首尾字段截图和保存重开截图。夹具为2页4:3及两类对象；授权/CSRF/修订登记为明确路由fixture，辅助PDF仅占位，未测试生产授权或PDF转换。短屏功能区需内部滚动访问其余行和列，字段需窗格滚动；不等价于桌面PowerPoint、全比例/全对象/全错误状态验收。

清单同步自`/tmp/office-ui-inventory-pptx-geometry-inspector-20261112/`，725模块4390声明点；全部来源SHA一致、canonical Markdown逐字节相同。两份新增smoke的node语法及git diff --check通过。复现：在frontend目录执行`PPTX_EXPECTED_MANIFEST_SHA256=7b5d702ef317368d5c26e9c9db523fef00298332b5769c16e5d603db46ac98a8 PPTX_SMOKE_EVIDENCE_DIR=/tmp/office-pptx-geometry-repeat node smoke/pptx-geometry-pane-smoke.mjs`。本批没有提交、推送或部署，四格式整体goal保持active；既有Excel异步Injector释放与CF缺省文字色问题仍未处理。


## DOCX 查找与替换 PC 续批

沿用用户“UI 尽可能贴近 PC”的方向，本批只调整 `docx-find-replace.ts` 和 `docx.css` 的查找面板局部：保留宿主内非模态区域，补原生关联的可见字段标签、查找/替换 tablist 与选中状态、28px 紧凑字段和按钮、主题字体、小圆角、2px 焦点环及禁用状态。查找结果按宽度换行，结果区保持自身高度并滚动；不再因继承的 flex 收缩被压到4px，窄屏不再由旧360px固定结果宽度导致横向溢出。字段、匹配规则、替换预检、来源锚点、守卫、草稿协议及原有关闭返回编辑器行为不改。

修复结果列表重建后的焦点丢失，仅在焦点原来位于结果列表内时恢复当前结果；查询框、外部命令不主动抢焦点。标签支持左右方向键及 Home/End，只有选中标签进入 Tab 顺序。组合输入中的 Enter/Escape 和 Ctrl/Cmd+F/H 不再触发面板导航或关闭。此处组合输入验证来自单测构造的 isComposing 事件，不冒充真实中文输入法端到端测试。

初始单测 `/tmp/office-docx-find-unit-red-20261112.log` 为4失败20通过，对应结果焦点、两种组合键及标签语义；旧冻结构建 `7b5d702e...` 的 `/tmp/office-docx-find-red-built-20261112/` 完成可编辑10组合并记录218条重复检查失败，不是218个独立缺陷。首版构建 `42dc7da8...` 的10个可编辑布局已通过；脚本随后误定位不存在的 Undo 按钮，修为编辑器的真实 Control+z / Control+Shift+z。下轮真实保存后核对暴露 core.xml 的正常 revision/modified 更新，检查器改为独立验证这两项元数据，其他核心属性仍严格比较。ZIP新增的7个目录条目不作为文件部件，文件集合仍一致。

首版最终浏览器 `/tmp/office-docx-find-final-built-20261112/evidence.json` 已完成20组合、保存、下载及重开，但人工截图发现输入框 Enter 导航后列表仍可能停在末端，当前匹配落在列表内部可视区外。因此补 `/tmp/office-docx-find-scroll-unit-red-20261112.log` 的真实失败（scrollTop=0，24通过1失败；前一轮测试缺 vi 导入已先修正，不计作产品RED），仅在 navigate 后调整结果容器 scrollTop，不移动输入焦点或主动滚动整个面板。该问题修后重新构建和验证，首版证据不冒充最终版。

最终单测 `/tmp/office-docx-find-unit-final-scroll-20261112.log`：3文件56项通过（find25、ribbon21、navigation10），包含原有大小写/全半角/通配符/正则、来源身份、混合格式、Unicode、保存锁和原子撤销等回归。没有运行或重复完整项目测试。`/tmp/office-docx-find-scroll-build-20261112.log` TypeScript + Vite终态退出0，Vite44.24秒；同前缀budget日志终态退出0，未放宽预算。已有循环chunk、注解和大chunk警告保留。最终 manifest `11fecafd31b2715225b3b195bd5c307adffb1f28e9ec7111d2109e2c0f3292a8`。

最终 `/tmp/office-docx-find-scroll-final-built-20261112/evidence.json` 脚本终态退出0：

- 可编辑/只读 × 查找/替换 × 1440×900、320×640、640×360、390×320、1440×360，共20组合。455个可用且进入Tab顺序的控件实际 Tab/Shift+Tab 往返、焦点环、中心与内侧四角命中通过；不含禁用控件和非选中模式标签。普通文字字段和按钮28px，原生复选框保留浏览器外观；复选框自身无文字，其CSS默认字体不当作标签字体。80次真实方向/Home/End标签切换、20次结果激活焦点保持、20组输入框 Enter/Shift+Enter 后焦点与结果列表内部可视范围检查通过。
- 只读替换字段和两种替换按钮均禁用，查找仍正常；20组合前后正文JSON、Undo/Redo可用性和 native-editor-draft 存储相同。40张布局视口截图另加重开截图。短屏/窄屏需面板、结果区及现有宿主滚动，不宣称字段、全部结果和功能区同时一屏显示；长匹配上下文仍沿用已有摘要截取，并非全文检索阅读器。
- 对真实来源中的标题、混合粗体段、8个普通段及2个表格单元格共13处 cat→dog，原子替换映射为12条来源操作；真实键盘 Undo 恢复13匹配、Redo归零；刷新恢复草稿后恰好保存1次。应答明确模拟验收失败且保留 Word 链接，浏览器实际下载并写入 `downloaded-revision-2.docx`，与 `revision-2.docx` 逐字节相同；重开修订2查 dog 得到13处。没有生产鉴权、修订登记或生产签发链验收之意。
- 实际JS/CSS响应SHA和大小与冻结磁盘146个唯一资源一致；page/console/HTTP和route错误为空，manifest及DOCX bridge身份前后不变。所有构建与浏览器运行期间冻结产品、static及共享smoke，确认终态后才修改。

终态后 `.venv/bin/python /tmp/verify-office-docx-find-20261112.py /tmp/office-docx-find-scroll-final-built-20261112` 退出0，生成 `independent-find-check.json`。独立核对20组合、455控件、80标签键、40布局截图、146资源、来源/保存/下载SHA和尺寸；python-docx逐段逐run核对cat→dog、段落样式、粗体/斜体/下划线、表格结构。ZIP完整且文件集合相同；除document.xml与core.xml外所有文件字节相同；document.xml仅13处文本替换及相应 w:t 增加 xml:space="preserve"，其余XML经规范化严格一致。core.xml仅revision由1变2及合法modified时间更新，其余属性经规范化一致。

来源 36957 字节 SHA `a9d9865e93091eea6b2df42180a20f8cfa5678c0f1074c855890a0074eef86c4`，修订2及实际下载 37642 字节 SHA `6e865e619cf54edfc42ca32e19f3d9cf36fb39599d1cc609bdbb6351194ff98c`。授权、CSRF与修订登记为明确fixture，DOCX解析、替换、保存、下载及重新加载是真实浏览器/引擎链。人工查看最终PC替换、320×640只读、640×360与390×320末端结果及重开修订2截图；界面不等价于桌面Word，也没有覆盖全部文档结构及错误状态。

清单同步自 `/tmp/office-ui-inventory-docx-find-final-20261112/`，725模块4390声明点；全部来源SHA一致，声明点不是功能总数或完成率。新增smoke的node语法、清单cmp及git diff --check通过。复现：frontend目录执行 `DOCX_EXPECTED_MANIFEST_SHA256=11fecafd31b2715225b3b195bd5c307adffb1f28e9ec7111d2109e2c0f3292a8 DOCX_TEST_OUTPUT=/tmp/office-docx-find-repeat node smoke/docx-find-replace-smoke.mjs`。本批未提交、推送或部署；四格式整体goal仍active，既有Excel Injector释放与CF缺省文字色问题未处理。


## PPTX 填充与轮廓窗格及共享颜色图库 PC 续批

上一goal turn已完成DOCX查找替换，分类为progress。本批继续用户已确认的PC Office方向，仅修改 `slides-shape-format-pane.tsx/.css` 与共享 `SlidesFormatColorWell` 的局部交互。原有填充/轮廓section标题改为原生fieldset/legend，左标签右控件，28px字段与按钮、主题字体、数值右对齐及等宽数字、2px焦点环、禁用态与非法粗细边框；保留现有radio、70色图库、原生更多颜色输入、来源预检、200ms合并、历史与保存协议。复杂填充、虚线及继承缺省轮廓的能力限制不放宽。

新增回归先复现：键盘选择色块后portal移除导致焦点落到body；粗细组合输入的Enter提前flush、Escape提前撤回；Escape只清除widthDraft但pending与定时器仍保留旧宽度，随后会提交。颜色选择仅在焦点原在图库内部时返回对应入口，外部关闭不抢焦点；粗细保存编辑开始值，Escape通过既有候选规划恢复宽度并保留同批填充/轮廓颜色，避免旧定时器提交和空历史。非法值加aria-invalid；组合keydown忽略isComposing，未改变既有防抖规则，不宣称完整真实输入法测试。

`/tmp/office-pptx-shape-format-unit-red-fields-20261112.log`为6失败13通过：分组、字段错误状态、组合键两项、Escape宽度及色块焦点。修后 `/tmp/office-pptx-shape-format-unit-green-20261112.log` 三文件34项通过（shape12、chart7、parallel-host15），再补单独宽度Escape不产生空历史的边界验证，`/tmp/office-pptx-shape-format-cancel-green-20261112.log` shape13项通过。当前三文件共35个不同用例，不把重复执行的shape用例累加；宿主回归涵盖合并样式、刷新、撤销重做、保存前flush、图表/图片等原有并行修改。没有运行或重复完整项目测试。

旧冻结构建 `11fecafd...` 的 `/tmp/office-pptx-shape-format-red-built-20261112/` 完成三种来源×五视口15场景及15色板，记录100条重复检查失败，不是100个独立缺陷：原生分组、焦点环、紧凑主题按钮与字段错误状态。1050次色板方向键原先已可用，没有为了展示改动重写固定源图库。初版正向夹具曾让右侧文字重叠，仅将夹具中的After文本框下移；产品不变。

`/tmp/office-pptx-shape-format-build-20261112.log` TypeScript + Vite终态退出0，Vite44.99秒；同前缀budget日志终态退出0，未改预算。最终manifest `e1d5d472b6bc51c75fd718c04f00bb79c44f2a708c76e332c85bc24571a80a13`。保留已有循环chunk、注解及大chunk警告。产品、static与共享smoke在构建/浏览器期间冻结，确认终态后才修改检查器。

`/tmp/office-pptx-shape-format-first-built-20261112/` 已完成15布局、所有样式操作并保存，但新增检查器误要求保存后继续inert而退出1。源码 `save.finally` 明确解除root.inert以便链接可访问，并保留字段disabled及写入守卫；只修正断言为九个字段/按钮均disabled，不改产品锁定规则。最终 `/tmp/office-pptx-shape-format-verified-built-20261112/evidence.json` 使用同一未再修改的产品构建完整复跑，脚本终态退出0，ok=true、revision=2：

- 来源明确RGB填充/实线、无填充且继承轮廓的文本框、渐变填充/虚线三类；各在1440×900、320×640、640×360、390×320、1440×360检查。15场景135条控件记录；50条可用控件焦点检查，其中35条真实Tab/Shift+Tab往返、15条未选中radio直接DOM聚焦；85条禁用控件检查可滚动完整命中。全部中心/内侧四角命中与可用控件2px焦点环通过。非radio控件26–32px范围实际为28px且使用主题字体，原生radio14px。
- 15次可用色板，在每次打开后真实连续按ArrowRight遍历70个不同色块并回绕，共1050步；每个色块焦点环及四角命中通过。Escape关闭色板并返回入口。共30张窗格首尾视口截图、15张色板截图，另有重开截图。五组非法宽度和正常宽度Escape后等待定时器，草稿保持不变。短屏依靠现有窗格/功能区滚动，不宣称全部设置同时一屏显示；未实际打开操作系统原生更多颜色对话框，该input持续挂载由单测覆盖。
- 随后真实键盘选Red填充与标准Blue轮廓，入口焦点恢复；宽度设3.5磅。Undo仅撤回宽度、Redo恢复；分别恢复填充/轮廓来源并Undo，分别Space切无填充/无线条并Undo。刷新恢复最终shapeStyles，恰好保存1次。保存后root.inert=false，九个窗格控件均disabled；浏览器实际点击“下载PPTX”，文件字节和大小与签发收据匹配，写入revision-2.pptx，重开显示红色填充、蓝色轮廓及3.5磅。
- 实际123个JS和12个CSS，共135个唯一资源的SHA/大小与冻结磁盘一致（继承证据字段名runtimeJavaScript，实际包含CSS）。page/console/HTTP/route错误均为空。授权/CSRF/修订登记由明确路由fixture提供；实际PPTX解析、渲染、patch、下载与重开运行真实引擎，辅助PDF仅为占位，不代表PPTX转PDF或生产授权链验证。

终态后 `.venv/bin/python /tmp/verify-office-pptx-shape-format-20261112.py /tmp/office-pptx-shape-format-verified-built-20261112`退出0，生成independent-shape-format-check.json。独立核对15布局/15图库/1050方向键/135控件、30布局截图、135资源及收据文件身份；python-pptx检查固定预期FF0000填充、0070C0轮廓、3.5磅，所有对象ID/名字、文本与run粗体/斜体/字号、几何、图片bytes及裁剪不变。ZIP完整，文件集合相同，除slide1.xml外所有文件部件逐字节相同，第二页不变。

完整XML比较首次捕获目标形状新增a16:creationId；核对引擎patchedElementXml/ensureCreationId确认这是现有“仅修改的外来对象补持久身份”行为，不是本批改动。独立验证器严格检查只有目标cNvPr新增一个指定uri扩展、单个合法GUID creationId；仅规范化该扩展及目标的填充/轮廓子树后，全页XML完全一致，没有泛化忽略全部扩展或所有形状属性。来源 29952 字节SHA `4e429a8090d5a753fe372686bdee33e0823742142d4efde3aeba85a707766184`，下载修订2 42760 字节SHA `a52a4715ae536db1c0bd1eabe107e772efb66ca36e68ca9b1306d685910b88d3`。画布仍使用原渲染器，未宣称桌面PowerPoint像素一致或覆盖全部字体/比例。

人工查看PC完整设置、320×640继承来源、640×360复杂来源、390×320图库和末端字段及重开修订2截图。清单同步自 `/tmp/office-ui-inventory-pptx-shape-format-20261112/`，725模块4390声明点，所有来源SHA一致，非功能总数或完成率；canonical Markdown逐字节相同。新增smoke的node语法、清单cmp及git diff --check通过。复现：frontend目录 `PPTX_EXPECTED_MANIFEST_SHA256=e1d5d472b6bc51c75fd718c04f00bb79c44f2a708c76e332c85bc24571a80a13 PPTX_SMOKE_EVIDENCE_DIR=/tmp/office-pptx-shape-format-repeat node smoke/pptx-shape-format-smoke.mjs`。本批无提交、推送或部署，四格式整体goal保持active；Excel Injector释放与CF缺省文字色问题仍未处理。

## PDF 字段设计列表 PC 续批

本批延续用户“UI 尽可能贴近 PC”的方向，仅调整 `src/pdf-form-design.ts` 的面板结构/焦点与 `src/pdf.css` 的字段设计局部规则。新增固定标题栏、28px主题按钮、字段名/页码及控件ID/限制原因的分层列表、长名称列内换行、细分隔线、48dvh且不超过360px的面板滚动边界、2px键盘焦点环。保留原有删除身份、单控件及单选组限制、独立保存、实际预览确认和原修订保留规则；没有修改引擎或发布/签发链。

打开聚焦安全的关闭按钮，关闭或Escape返回仍连接且未hidden/inert/disabled的入口；组合输入的Escape不关闭（单测构造isComposing，不代表真实输入法全流程）。列表重建后按widgetIdentity恢复原操作焦点，目标变成禁用/消失则回到关闭按钮；异步刷新时若焦点已移出列表则不抢回。unavailable原因同时禁用操作；每个操作的无障碍名称含字段名、页码和widgetId。现有两份删除smoke改用稳定data选择器，适配新增无障碍名称，其业务断言不变。

`/tmp/office-pdf-form-design-unit-red-20261112.log`为4失败6通过，复现标题/入口焦点、Escape、刷新焦点及操作身份名称；修后 `/tmp/office-pdf-form-design-unit-green-20261112.log`三文件27项通过（design10、host15、radio-removal2）。覆盖来源/控件身份校验、只读/保存锁、预览确认、复核告警保留修改与单选删除现有回归；没有运行或重复完整项目测试。

旧冻结manifest `e1d5d472...` 的 `/tmp/office-pdf-form-design-red-built-20261112/`完成五视口并记录面板无专用标题/滚动边界、215字符名称横向溢出、原因未分层、焦点环/Escape/入口焦点问题。最初检查器错误要求字体名必须含Segoe/Aptos，误报15次；改为与现有PDF宿主主题字体完全一致，不为通过脚本改变中文字体。本批仅一次产品构建，`/tmp/office-pdf-form-design-build-20261112.log` TypeScript/Vite终态退出0，Vite45.55秒；`/tmp/office-pdf-form-design-budget-20261112.log`终态退出0，未放宽预算。既有循环chunk、注解及大chunk警告保留。最终manifest `07fbed2ccfbd011dc1699328c75d61399eec9440b015044ef74923511ca3fbeb`。

浏览器检查器调试记录：`final-built`完成布局后在刷新时误读304响应正文退出；只对200响应取bytes，并立即记录异步资源检查错误。`verified-built`误在已恢复的独占删除草稿上点击禁用入口；`final-verified-built`误在Redo触发异步refresh未完成时立即断言按钮状态；改为等待真实禁用状态。`confirmed-built`已完成保存、实际下载及初步文件检查，但重开时仍误点击“剩余全只读字段”的禁用删除入口；改为检查真实preview模型中的保留字段及入口禁用。这些为夹具/等待断言修正，没有修改产品保护规则或重建产品。独立检查器最初误算字段长度为200（实际215），继而捕获现有pdf-lib的资源/内容规范化；收窄为精确验证该已知变化，未放宽为忽略正文或资源。

最终 `/tmp/office-pdf-form-design-final-proof-built-20261112/summary.json`终态退出0、ok=true：1440×900、320×640、640×360、390×320、1440×360五视口，15条按钮记录（10个可用控件实际Tab/Shift+Tab往返与2px焦点环，5个禁用按钮检查），中心/内侧四角命中、五次Escape及入口焦点、长字段无横向溢出、原因可滚动显示通过；10张布局视口图。布局前后草稿存储完全相同。短屏依靠现有宿主和面板滚动，不宣称功能区、全部长名称及PDF画布一屏显示。

真实来源由`office-pdf-form-design-server.py`复用已有FastAPI路由和存储夹具生成，两个字段分别为可删除remove_me和215字符的只读keep字段；仓储为内存，非生产部署鉴权验收。浏览器真实点击删除、Undo/Redo、刷新恢复草稿，恰好POST保存一次（修订4→5），实际点击下载链接取得download事件并读取下载文件，重开真实修订5。PDF.js、packed PDF引擎、grant/cookie/CSRF路由及下载处理真实执行，没有HTTP业务替代。重开真实preview模型仅有只读keep字段，删除入口按已有规则禁用。39个JS及9个CSS共48个唯一200响应资源SHA与磁盘一致，304复用先前资源，不取不存在的正文；page/console/HTTP/asset错误均为空，manifest前后不变。

终态后 `.venv/bin/python /tmp/verify-office-pdf-form-design-20261112.py /tmp/office-pdf-form-design-final-proof-built-20261112`退出0，生成`independent-desktop-check.json`及source/output独立渲染图。pypdf确认仅目标字段及对应Widget退出字段树/Annots，保留只读字段完整属性、原值、控件字典及外观流；页面几何、字体资源及文字不变。现有`form-design.ts`的普通removeAnnot调用PDFPageLeaf.normalize，输出资源仅增加空XObject/ExtGState两项，正文流仅精确增加q/Q包裹，已分别严格比较，不能声称PDF所有未删除对象字节原样。PyMuPDF以2倍分辨率独立渲染，目标矩形外扩2pt范围外像素逐点相同，目标内有真实变化。来源7190字节SHA `ae4f7aaa66122719aafa9dc675faebd5af56e8adea6d07849a65026dafcd1257`；下载7089字节SHA `4afb0dff719f78a34ad1170d6245fd5552265bbcbec2ba7eb1a1a6d49183cb05`，身份与签发收据及重开context一致。

人工检查PC完整列表、320×640长名称、390×320末端原因与重开修订5截图。清单更新自`/tmp/office-ui-inventory-pdf-form-design-20261112/`：725模块4394声明点，全部来源SHA一致，非功能总数或完成率；canonical清单cmp、48资源独立哈希、10布局截图数量、新增/受影响smoke的node语法及git diff --check通过。构建和浏览器运行时冻结产品/static/共享smoke，确认各次进程终态后才修检查器。本批未提交、推送或部署；四格式整体goal保持active；其他PDF创建/文本属性/单选扩展设置区、以及既有Excel Injector释放与CF缺省文字色问题不在本批覆盖范围。复现：frontend目录执行 `PDF_EXPECTED_MANIFEST_SHA256=07fbed2ccfbd011dc1699328c75d61399eec9440b015044ef74923511ca3fbeb PDF_FORM_DESIGN_SMOKE_DIRECTORY=/tmp/office-pdf-form-design-repeat node smoke/office-pdf-form-design-smoke.mjs`。
## PDF 表单创建、文本属性与单选扩展 PC 续批

本批延续“UI 尽可能贴近 PC”的方向，覆盖创建文字/复选框/日期/下拉/单选组、字段属性、对齐排列、文本属性、追加单选项共9个功能区入口。三个设置面板共用局部标题栏与焦点生命周期：原生 fieldset/legend 分组、28px 主题控件、桌面双列属性布局、数值右对齐及等宽数字、2px 焦点环、禁用状态、受限高度内部滚动；窄屏转单列。打开聚焦关闭按钮，Escape 关闭并返回可用入口；组合输入中的 Escape 不关闭，单测构造事件不代表真实输入法端到端验证。控件重建按无障碍名称和 widgetIdentity 恢复面板内原焦点，外部焦点不抢回。

单选组创建由产品 CSV 文本框改为原生可编辑表格，逐行设置选项值、X/Y/宽/高和初始选中项，支持添加/删除及清空初始选择。保留2–64项限制，原生单选组保证互斥，窄屏通过可聚焦的内部横向滚动区访问。仍直接生成原协议 radioWidgets，不保留产品隐藏 CSV 解析兜底。最终测试发现并修复本批引入的“删中间行再添加时默认 Option3 重名”，默认名称按现有值避重。文本/单选扩展/创建验证错误保留已输入值及焦点；暂存成功后的默认值重建仍沿用原行为，不宣称待保存值始终显示在表单中。来源身份、权限、能力、预览确认、草稿和保存协议未修改。

测试记录：`/tmp/office-pdf-form-settings-unit-red-20261112.log` 初始11失败捕获预期界面差异。首次 green 命令误从仓库根运行，Vitest 5.1.0 缺 frontend jsdom 配置并拾取 .worktrees 同名文件，47失败是运行目录错误，不计产品 RED/GREEN；未修改依赖与锁文件。纠正 cwd 后5文件29项通过。宿主相关5文件23通过2失败来自旧 `.closest('div')` 结构选择器；改为稳定 `[data-pdf-form-widget]` 后业务断言通过。滚动区语义 RED 为1失败13通过，修后14通过；默认名称 RED 为1失败14通过，最终15项界面测试通过。跨11文件共59个不同相关测试通过（UI15、create6、textProperties4、next4、extended4、host15、widgetName3、choiceOptions3、radioRequired2、radioName2、buildChunks1），不累加重复运行。未运行完整项目测试。

旧冻结构建 `/tmp/office-pdf-form-settings-red-built-20261112/` 完成45场景515条控件记录，1321条重复检查失败反映焦点环/字体/尺寸/标题结构/Escape/单选行及溢出问题，不是1321个独立缺陷。首构建45.24秒后实际浏览器已通过45场景和3次保存；滚动区语义补强后第二构建45.56秒，再补默认名称修复后第三次最终构建45.30秒。三个构建及预算检查均终态退出0，预算未放宽；既有循环 chunk、注解和大 chunk 警告保留。最终日志 `/tmp/office-pdf-form-settings-confirmed-build-20261112.log` 与 `confirmed-budget`，manifest SHA256 `48c0fba53436acae8843c6f1f8895af79da80952d39a692bd7fb55540b473241`。各构建/浏览器运行期间冻结产品、static 和共享 smoke，确认进程终态后才修改；最终记录时均已结束。

最终 `/tmp/office-pdf-form-settings-confirmed-built-20261112/evidence.json` 的实际浏览器终态退出0、ok=true：

- 9入口 × 1440×900、320×640、640×360、390×320、1440×360，共45布局场景590条控件记录。580个可用控件中575次真实 Tab/Shift+Tab 往返，5个未选中单选框直接 DOM focus；另10个禁用删除按钮显示检查。主题字体、28px普通控件、14px原生开关、焦点环、中心及内侧四角命中、45次 Escape 和入口恢复通过。90张首尾布局截图，布局前后草稿存储相同。5组真实单选框方向键互斥、5组滚动区焦点、3个窄视口真实 ArrowRight 横向滚动通过。短屏依靠宿主及面板滚动，不宣称全部控件和画布同时一屏可见。
- 真实新增 Yes/No/Maybe 单选组，包含删中间行再添加默认值避重、选择 Maybe、非法名称输入保留、Undo/Redo、刷新恢复、预览确认，保存修订4→5并实际下载重开。文本 maxLen=4 拒绝时保留字号18，改32、Courier-Bold、居中，Undo/Redo后保存5→6并下载重开。原 consent 追加重复 Yes 拒绝时保留坐标，再追加 Maybe，Undo/Redo后保存6→7、下载重开，原 Yes 仍选中。总计恰好3次保存，实际 download 事件读取文件，SHA/大小匹配收据。
- 49个实际200响应资源（40 JS/mjs、9 CSS）SHA/大小均独立匹配冻结磁盘；304复用先前资源而不读取不存在的正文。page/console/HTTP/assets 错误全部为空，manifest 前后相同。FastAPI、PDF.js、真实 PDF 引擎、cookie/grant/CSRF 路由实际执行，仓储/修订登记为明确内存夹具，不等同生产部署鉴权验收。五份既有单选 smoke 改用测试侧 CSV fixture→真实表格输入 helper，未逐份重新执行浏览器，语法检查通过。

终态后 `.venv/bin/python /tmp/verify-office-pdf-form-settings-20261112.py /tmp/office-pdf-form-settings-confirmed-built-20261112` 退出0，生成 `independent-settings-check.json` 和独立渲染图。pypdf 使用固定预期核对字段值、选中状态、矩形、字体字号、MaxLen、Q 和外观资源/内容；保留字段字典、引用及解码外观流不变，原 consent 前两个控件与选中状态不变。三页几何/文字/资源保持，现有 pdf-lib 创建和追加各在第一页内容流精确增加一层 q/Q，文本属性内容流与前一版相同，第二三页内容流逐字节相同；不能宣称全部 PDF 字节不变。PyMuPDF 2倍渲染确认目标内实际变化，目标矩形外扩2pt之外像素完全一致，其他页完全一致。

实际来源9279字节，SHA `14cd2ca28e6015343586d746862a13efb4b7187b6342d41e8971bce4e878dd44`；单选保存14757字节，SHA `fd51fa1492c7477bf933fdbc763f1f77c0d0636ca6311ceb1b3001b41c7cf3a8`；文本属性保存15277字节，SHA `4872b30958b0e5d4688b4c9d572d29dc502053610706d2d4a8c4b234369b8c9c`；追加保存17160字节，SHA `afce8102b5364d7fc278feda7e708aa83ec09dd0ebf2b9eb17247d43d01cf145`。身份均与实际下载、收据和重开来源匹配。

人工查看桌面属性分组、文字属性、单选表格和320px内部滚动截图。清单同步自 `/tmp/office-ui-inventory-pdf-form-settings-20261112/`：727模块4401声明点，全部模块来源SHA、canonical Markdown字节、49运行资源、最终manifest及90布局截图独立核对一致；声明点不是功能总数或完成率。新增/迁移 smoke 的 node 语法及 git diff --check 通过。没有提交、推送或部署，四格式整体 goal 仍 active；其余未覆盖组件以及既有 Excel Injector 释放与 CF 缺省文字色问题继续保留。最终证据为本机三页固定 PDF 夹具，不能外推所有文件、所有错误状态和生产环境。


## PDF 原位改字、整对象与选区文字样式 PC 续批

上一 goal turn 完成表单设置与审计，分类为 progress。本批继续既定 PC Office 方向，局部调整 `pdf-main.ts` 的原位改字面板，以及 `pdf-replace-text-style.ts`、`pdf-text-selection.ts` 和 `pdf.css`。增加标题、原生“文字内容”分组及两个关联可见标签；原文预览成为可聚焦、可滚动的命名 region。整对象与选区样式在桌面并列，内部采用左标签右字段的紧凑属性布局；窄屏逐列排列。普通控件28px、原生复选框14px、主题字体、数字右对齐/等宽、2px焦点环、禁用状态和独立操作栏。保留字体/粗斜体/颜色/对齐/行距、UTF-16选区、继承及混合状态、4000字符、草稿、预览确认和保存协议；没有修改 PDF 引擎或发布签发链。

旧冻结 manifest `48c0fba5...` 上的 `/tmp/office-pdf-text-settings-red-built-20261112/` 完成五视口×无选区/已选区10场景190控件记录，460条重复检查失败，主要为尺寸186、焦点环160、字体90、标题10、标签10和命中4；不是460个独立缺陷。该初版标签检查器使用所有直系fieldset下的label，后续新界面误报10次，已收窄到真实 `.pdf-text-content label`；旧界面确实缺少这两个内容标签，但不以错误选择器计修复数量。

首构建45.25秒、manifest `2f71438b...` 后，标题、字体、尺寸与焦点环已改善，但仍有14次窄/短屏边缘遮挡。中间目录 `hover-red-built` 实际使用尚未扩展的检查器，24失败为标签误报10+命中14；随后 `edges-red-built` 的扩展检查器确认标签通过，24失败为命中14+主按钮悬停对比度10次失败，实测1.0866。命中数据记录实际 elementFromPoint，确认多数为悬停标题遮挡。将标题改为独立固定区域、属性使用内部滚动body，修复主按钮悬停背景。第二构建44.57秒、manifest `3c87cd67...` 后，新增颜色启用状态共15场景，只剩8次“已有选区的textarea按Shift+Tab返回后仍在屏外”。不把该阶段记录当最终验收。

单独真实宿主诊断 `/tmp/office-pdf-text-focus-debug-20261112/debug.json`：正常、关闭滚动锚定、克隆移除textarea业务监听器、等待双requestAnimationFrame、显式preventScroll五种对照均复现；Tab滚到下一字段后，Shift+Tab虽恢复textarea焦点和[2,4)选区，却不恢复可见位置。390×320诊断中textarea top从230变62，属性区scrollTop从126变294。`focus-nearest-debug` 对照只增加获得焦点时scrollIntoView(nearest)，返回top=215、scrollTop=141，文字与选区保持。产品仅给替换框增加一条带现有abort signal的focus监听，不改按键默认行为、选区或业务数据；最终实际Tab回归覆盖该问题，不以诊断注入替代产品验证。

三次构建均含TypeScript和Vite、均终态退出0，预算均通过且未放宽；第三次最终 `/tmp/office-pdf-text-settings-focus-build-20261112.log` Vite44.97秒，`focus-budget`退出0。最终manifest SHA `496ccbbe562ea3209edc29af3f9dc13ea1a54b91ee51f75aeae4357106b3ceec`。既有循环chunk、注解及大chunk警告保留。产品/static/共享smoke在各构建及浏览器进程运行期间冻结，确认终态后才修改；最终所有进程已结束。

相关单测最终 `/tmp/office-pdf-text-settings-unit-focus-20261112.log`：6文件31项通过（replacement2、selection2、selection-controls4、shortcuts14、static-text-host8、build-chunks1）。覆盖整对象改动清理相应选区覆盖、混合/继承、清除与方向/焦点保持、UTF-16边界、Ctrl/Cmd+Enter及组合输入/禁用/外部事件、真实宿主现有插入预览守卫。组合输入来自构造事件，不代表真实输入法全流程。阶段目录 `unit-frontend` 与 `unit-scroll` 同31项在各次结构变更后通过，不累加为93项；一次误在仓库根执行npm因缺package.json退出，另一次准备smoke脚本时相对路径错误，均为命令目录错误而非产品RED，未改依赖/锁文件。未运行完整项目测试。

最终 `/tmp/office-pdf-text-settings-focus-final-built-20261112/summary.json` 浏览器终态退出0、ok=true：

- 1440×900、320×640、640×360、390×320、1440×360 × 无选区/已选区/两种颜色控件启用，共15场景285条控件记录；255个可用控件真实Tab/Shift+Tab往返、30个禁用控件显示检查。另15组原文预览region真实Tab往返和焦点环。字体、尺寸、中心/内侧四角命中、滚动边界、内容标签及选区应用保持通过。35次可用按钮真实hover检查，最低文字对比度4.623。30张首尾视口截图，布局前后草稿存储相同。短屏仍需要属性区和现有宿主滚动，不宣称全部字段、说明和画布一屏显示；未覆盖所有字体/缩放/超长原文或手动拉高textarea组合。
- 真实选择源 `source page one` 改为AABBCC，整对象Courier12左对齐，BB配置Times18、粗斜体和红色。选区字号5拒绝时保留输入、范围且不暂存；验证混合选区、分别修改整对象属性只清除相应选区覆盖、清除/重新应用后焦点和选区保持。实际Undo/Redo、刷新恢复同一草稿，真实引擎预览applied=[0]、skipped=[]，确认digest后恰好保存一次修订4→5。实际点击链接取得浏览器download事件，读取下载文件而非仅请求URL，SHA/大小匹配收据；重开修订5并看到真实AA文字层，来源SHA与下载相同。
- 49个实际200响应资源（39 JS、1 mjs、9 CSS）SHA/大小与冻结磁盘一致，304不读取不存在的正文；page/console/HTTP/asset错误均为空，manifest前后相同。复用已有 `pdf-static-text-server.py` 真实FastAPI、PDF.js、PDF引擎、grant/cookie/CSRF与下载路由，仓储/修订登记为内存夹具，不代表生产部署授权验收。新增两个smoke文件通过node语法检查。

终态后 `.venv/bin/python /tmp/verify-office-pdf-text-settings-20261112.py /tmp/office-pdf-text-settings-focus-final-built-20261112` 退出0，生成 `independent-desktop-check.json` 与独立渲染图。独立核对15场景、285控件、30布局截图、49资源、manifest、保存/下载/重开身份。pypdf固定预期核对AA/CC的LiberationMono12、BB的LiberationSerif-BoldItalic18、嵌入字体、红色绘制和350pt基线及水平位置（0.05pt容差）；第一页面文字只剩AABBCC，三页几何、旋转及第二三页原文保持，未新增批注或表单。PyMuPDF以2倍渲染确认第一页面固定源行限定区域（PDF x20–152、y328–374）内有实际变化，区域外像素完全一致，第二三页像素完全一致。不声称整份PDF字节或全部资源字典不变。

实际来源2234字节、SHA `4069ea2736d7a2492bb772b0cf8e6bfcea1f7d2892df6334ea6ff775725771ab`；下载12030字节、SHA `58933e8b36179e12fbaef1a44ded9daecd5b09a2473d95c3b5516104ec4ffdb4`。人工检查桌面内容/并列属性、320px颜色启用末端、390×320选区和最终重开截图。清单同步自 `/tmp/office-ui-inventory-pdf-text-settings-20261112/`：727模块4406声明点，全部来源SHA及canonical Markdown字节核对一致；声明点不是功能总数或完成率。最终node语法及git diff --check通过。未提交、推送或部署，四格式整体goal仍active；其他未验证组件、既有Excel Injector释放与CF缺省文字色问题保留。复现：frontend目录执行 `PDF_TEXT_SETTINGS_OUTPUT=/tmp/office-pdf-text-settings-repeat PDF_EXPECTED_MANIFEST_SHA256=496ccbbe562ea3209edc29af3f9dc13ea1a54b91ee51f75aeae4357106b3ceec node smoke/office-pdf-text-settings-smoke.mjs`。


## PPTX 图表数据点格式窗格 PC 续批

延续“UI 尽可能贴近 PC”的既定方向，本批仅调整 `src/slides-chart-format-pane.tsx/.css` 的窗格结构和局部视觉规则：独立标题及滚动内容区域、原生 fieldset/legend 系列分组（单系列也显示来源名称，空名称回退“系列 N”）、系列和类别长名称完整换行、28px主题字体颜色入口/恢复按钮、行分隔与2px键盘焦点环。错误区域使用alert。保留现有共享颜色图库、200ms配色合并、目标代次守卫、锁定、null恢复、历史与保存协议；未改图表引擎、发布或签发链。此前已有的键盘选色返回入口修复及其测试保留，不计作本批新增功能。

冻结旧构建manifest `496ccbbe562ea3209edc29af3f9dc13ea1a54b91ee51f75aeae4357106b3ceec` 上，`/tmp/office-pptx-chart-format-baseline-built-20261112/` 终态退出0，15布局场景完成、10色板共700次方向键可用，草稿不变且未保存；210条重复检查失败分别为120尺寸/字体、70可用按钮焦点/命中、10系列分组、10类别换行，不是210个独立缺陷。最初red-built检查器误用不存在的#slides-app主题根导致异常，修正为真实.slides-embedded后取得上述有效基线；该设置错误不计产品RED。夹具首次直接执行缺PYTHONPATH、首次npm在仓库根缺package.json，同属命令准备错误，未改依赖或锁文件。

新增原生系列分组单测先RED：`/tmp/office-pptx-chart-format-unit-red-frontend-20261112.log` 1失败7通过。GREEN `/tmp/office-pptx-chart-format-unit-green-20261112.log` 四文件54项通过（chart-pane8、shape-pane13、slides-parallel-edit15、slides-native-chart-edit18），50.94秒。涵盖多点合并、恢复、切换目标、锁定、颜色浮层与焦点、撤销重做、草稿和保存请求。未重复运行完整项目测试。

`/tmp/office-pptx-chart-format-build-20261112.log` 的TypeScript/Vite构建终态退出0，Vite45.61秒；对应budget命令退出0，未放宽预算。保留既有循环chunk、注解及大chunk警告。最终manifest SHA `de10319a4bb55a139d028a58504cad3425d8810857122558e8e040efe917e0d2`。构建和浏览器进程运行期间，产品/static/共享smoke冻结；确认原会话终态后才更新文档，未因等待而重启测试。

最终真实浏览器 `/tmp/office-pptx-chart-format-final-built-20261112/evidence.json` 终态退出0、ok=true：

- 四页真实PPTX夹具，前三页为柱状图、饼图、散点图，第四页为保留文本。三种来源×1440×900、320×640、640×360、390×320、1440×360，共15布局场景、120按钮记录；系列分组、主题字体、长类别换行、28px高度、横向边界、中心及四个内侧角命中均通过，可用按钮逐个真实Tab/Shift+Tab往返及焦点环通过。散点图保留“不支持数据点配色”的既有原因与控件守卫。布局前后草稿相同。
- 柱状图/饼图各五次色板，共10次打开与700次真实ArrowRight，逐次遍历70个不同色块并回绕，焦点环和四角命中通过，Escape关闭并恢复入口；30张首尾布局截图、10张色板截图。短屏依赖属性区和宿主滚动，不宣称所有内容一屏显示；未实际打开操作系统原生更多颜色对话框。
- 实际键盘把0:1设Blue（#0070C0）、1:2设Red（#FF0000），恢复来源0:0覆盖为null；检查精确合并patch、恢复按钮禁用、Undo/Redo及刷新恢复。恰好保存一次修订1→2，保存后当前窗格按钮均禁用；点击实际下载链接取得浏览器download事件并读取文件，SHA/大小匹配收据。重开修订2，草稿为空、来源身份更新，蓝色入口和真实画布颜色存在。
- 135个实际200响应JS/mjs/CSS资源的SHA与大小匹配冻结磁盘（证据沿用runtimeJavaScript字段名，实际含CSS）；page/console/route/HTTP错误均为空，manifest前后相同。授权/CSRF/修订登记由显式路由夹具提供，PPTX解析、渲染、patch及下载重开运行真实引擎；辅助PDF明确为占位，不代表PPTX转PDF或生产授权链验收。

终态后 `.venv/bin/python /tmp/verify-office-pptx-chart-format-20261112.py /tmp/office-pptx-chart-format-final-built-20261112` 独立验证退出0，生成 `independent-chart-format-check.json`。核对15布局、120控件、10色板/700方向键、40截图、135资源及实际文件收据身份；ZIP健康、部件集合相同，仅 `ppt/charts/chart1.xml` 变化。精确验证两个目标dPt分别为series0/index1/0070C0与series1/index2/FF0000，来源index0覆盖已移除；仅移除dPt后图表XML canonical字节相同。嵌入工作簿、其余所有ZIP部件逐字节相同；四页对象ID/名称/几何及文本不变。

独立检查器首轮错误假定dPt只有idx和spPr两个子项，实际来源及保存文件均带既有 `bubble3D val="0"`。直接检查两份实际XML后，改为严格限定idx、bubble3D、spPr三项顺序及bubble3D值，并保留其余精确检查；未改产品或重新构建/重跑整套浏览器来适配验证器。来源58896字节SHA `0f785bb5b93494a298087cb0737dec03e5d49544c22e22688ee09d4f5d685576`，下载58905字节SHA `b7a112ae0930a4d8a1e56ddb9ab120bdad1a7aa096482101b15bfd597f2ed0dc`。

人工查看桌面长名称、390×320末端、短屏色板及重开截图。画布长横轴标签仍沿用原渲染器，未宣称本批修复其裁切或达到桌面PowerPoint像素一致。清单刷新自 `/tmp/office-ui-inventory-pptx-chart-format-20261112/`：727模块4408声明点，所有来源SHA及canonical Markdown字节核对一致；声明点不是功能总数或完成率。新增两个smoke的node语法及git diff --check通过。本批未提交、推送或部署；四格式整体goal继续active，其他未验证组件、既有Excel Injector释放与CF缺省文字色问题保留。复现（仓库根）：`PPTX_SMOKE_EVIDENCE_DIR=/tmp/office-pptx-chart-format-repeat PPTX_EXPECTED_MANIFEST_SHA256=de10319a4bb55a139d028a58504cad3425d8810857122558e8e040efe917e0d2 node smart_reporting/report_editor/frontend/smoke/pptx-chart-format-smoke.mjs`。


## PDF 提取页面窗口 PC 续批

上一 goal turn 完成PPTX图表格式窗格及真实文件核对，分类为progress。本批继续“UI 尽可能贴近 PC”方向，局部调整 `src/pdf-extract-dialog.ts` 与 `pdf.css`：固定标题栏和可用的标题关闭按钮、内部说明/字段/结果滚动区、底部独立操作栏、28px主题控件及链接入口、清晰的命名结果区域与错误颜色、繁忙状态和2px焦点环。打开聚焦页码，标题/底部关闭及原生Escape返回仍连接、可用且不在hidden/inert区域的入口；另一个原生dialog已打开时不强制抢回焦点。现有提取页序、页码验证、requestId复用、缓存结果、关闭后异步完成不绘制及同源链接过滤保留，没有改提取引擎或发布签发链。

旧冻结manifest `de10319a4bb55a139d028a58504cad3425d8810857122558e8e040efe917e0d2` 的 `/tmp/office-pdf-extract-baseline-built-20261112/summary.json` 终态退出0。真实三页来源上，打开/非法页码/请求等待/验收警告四状态×五视口共20场景、70控件记录；110条重复失败为20标题/结果结构、20缺少aria-busy状态及70控件高度检查，不是110个独立缺陷。原34px输入/按钮与普通文本式链接均为本批PC标准化对象。基线原有焦点、命中、提取、警告下下载及重开通过，不宣称本批修复这些原已正确的业务能力。

新增四项窗口回归先RED：`/tmp/office-pdf-extract-unit-red-20261112.log` 4失败6通过。修改后 `unit-green` 10项通过（1文件）；命令最初也传入一个不存在的pdf-extract-host.test.ts过滤项，Vitest实际只执行dialog文件，未将不存在的文件计作通过。随后真实 `pdf-extract-entry.test.ts` 和 `native-pdf-extract-api.test.ts` 在 `/tmp/office-pdf-extract-entry-api-20261112.log` 2文件3项通过，合计3文件13项，未重复完整项目suite。覆盖原始/重复/越界页码、来源身份、readonly/saving/unsaved守卫、晚到结果与销毁、外域/脚本链接，以及新增标题/底部关闭焦点、结果警告与缓存、等待时关闭及重开、请求异常保留输入与requestId重试。

`/tmp/office-pdf-extract-build-20261112.log` TypeScript/Vite构建终态退出0，Vite46.69秒；budget命令退出0，未放宽预算。既有循环chunk、注解和大chunk警告保留。最终manifest SHA `6f02daa73238db444d109cab6e7a4bea5afb260b42530eb91c0e85e638c8ed01`。构建/浏览器活跃期间冻结产品、static及共享smoke，按原会话确认终态，没有因观察超时重启。

最终 `/tmp/office-pdf-extract-final-built-20261112/summary.json` 真实浏览器终态退出0、ok=true：

- 四状态×1440×900、320×640、640×360、390×320、1440×360，共20场景90控件记录。80个可用控件实际Tab/Shift+Tab往返，10个等待期间禁用控件显示检查；主题字体、28px高度、焦点环、中心及四个内侧角命中、窗口水平/垂直边界、标题与结果结构、aria-busy均通过。40张首尾截图。说明和结果可内部滚动，短屏不宣称所有说明同时一屏显示。未覆盖所有字体、浏览器缩放和任意超长业务原因。
- 输入0时拒绝且未发送提取请求；真实标题关闭和Escape后回到Ribbon入口，重开仍聚焦页码。将实际extract-pages请求暂留在浏览器路由以稳定观察等待状态，检查页码/生成禁用而关闭可用，随后原请求原样放行至真实服务，没有替换业务响应。该等待状态验证不等同真实网络性能测量。
- 真实请求pages=[3,1]、expectedSha256匹配已保存来源，生成独立文档修订1、parentRevision=null、revisionRegistered=true。服务返回validation.ok=false及具体native_validation_pending原因，窗口明确显示验收未通过，同时保留“下载提取 PDF”和“打开独立文档”。关闭重开保留输入及缓存链接，没有再次提取；原来源SHA和localStorage草稿不变。
- 实际点击下载链接取得浏览器download事件并读取文件，SHA/大小匹配签发收据，而非仅请求链接；pypdf读出source page three、source page one。实际导航打开独立文档，PDF.js显示两页，context为derived且来源身份匹配下载。服务状态核对parentDocumentId/parentRevision/parentSha256关联。总计只有一次extract-pages POST，没有save/export POST。
- 49个实际200响应资源（39 JS、1 mjs、9 CSS）SHA/大小与冻结磁盘一致，manifest前后相同；page/console/HTTP错误数组为空。复用真实FastAPI/grant/cookie/CSRF/router、PDF引擎、发布与下载，文档、grant和artifact仓储为内存夹具；不扩称生产环境和真实provider验收。本批未修改或放宽非阻断发布契约。

终态后 `.venv/bin/python /tmp/verify-office-pdf-extract-20261112.py /tmp/office-pdf-extract-final-built-20261112` 退出0，生成 `independent-extract-check.json` 及两页独立渲染图。再次核对20场景/90控件/80焦点往返/40截图/49资源、manifest及实际文件身份、一次提取和验收失败状态。精确检查新文档页面顺序[3,1]，两页300×400的mediabox/cropbox/旋转与相应来源页一致，解码页面内容流逐字节一致，无新增表单/批注或加密；PyMuPDF两倍渲染逐页像素与对应来源页完全相同。该检查针对固定纯文本来源，不宣称所有图像/字体/保护PDF和任意复杂页面均已覆盖。

实际来源2234字节SHA `5d2a2e2c3ec4f0a1c724520707ef7fccb3839b47aa661312d1c55221dcfb79f6`；下载1805字节SHA `ef56194a2d839a83d1c029a1bb6e27bd357faa768af081757d75861a136178ad`。人工查看桌面结果、390×320结果末端和320×640等待截图，标题及底部操作完整、链接可见。清单同步自 `/tmp/office-ui-inventory-pdf-extract-20261112/`：727模块4412声明点，全部来源SHA及canonical Markdown字节一致，声明点不是功能总数或完成率。新增/修改smoke通过node语法检查，git diff --check通过。未提交、推送或部署；整体四格式goal保持active，未验收菜单/上下文/错误状态与既有Excel Injector释放、CF缺省文字色问题仍保留。

复现（仓库根）：`PDF_EXTRACT_LAYOUT=1 PDF_EXTRACT_SMOKE_DIRECTORY=/tmp/office-pdf-extract-repeat PDF_EXPECTED_MANIFEST_SHA256=6f02daa73238db444d109cab6e7a4bea5afb260b42530eb91c0e85e638c8ed01 node smart_reporting/report_editor/frontend/smoke/pdf-extract-smoke.mjs`。


## DOCX 新建批注编辑与草稿列表 PC 续批

上一goal turn完成PDF提取窗口和真实文件验证，分类为progress。本批继续“UI 尽可能贴近 PC”，仅调整 `src/docx-comment-create.ts` 与 `docx.css` 的新建批注面板及对应构建分包。保留原停靠位置，新增固定标题、复用取消语义的“取消并关闭新建批注”入口、编辑/草稿双列分区（窄屏单列）、28px按钮、主题字体与焦点环；所选文字是命名且可聚焦的滚动region，草稿列表分离作者/原始ISO时间/多行内容，空列表有明确说明。面板内部滚动，草稿列表和选区预览有各自高度边界；没有更改正文纸面样式。

保留来源模型与UTF16范围校验、光标词语捕获、独立保存、pending snapshot、晚到/过期输入保留、65536字符限制、原批注、作者设置、撤销重做及保存前自动flush。标题关闭与原“取消新建”一样丢弃当前未提交输入，保留已加入草稿的批注，名称明确包含取消；未新增Escape丢弃输入的行为。列表在Undo后变空时，仅原焦点在列表内才落到可用输入/取消入口，外部焦点不会被refresh抢走。

旧冻结manifest `6f02daa73238db444d109cab6e7a4bea5afb260b42530eb91c0e85e638c8ed01` 的首版 `/tmp/office-docx-comment-create-baseline-built-20261112/` 终态退出0，但113条检查失败包含15个空UL/空blockquote的零高度区域误报。记录实际height=0后，把检查器限定到非空选区及有li的列表；修正后的 `baseline-corrected-built` 再次终态退出0，15场景60控件、98条重复检查失败（15结构/命名、53焦点/命中、30按钮尺寸/字体），不是98个独立缺陷。两次基线均沿用完整真实保存/下载/独立XML回读/重开断言，未将错误检查器的113条作为修复数量。

初始新增5个用例先RED：`/tmp/office-docx-comment-create-unit-red-20261112.log` 5失败3通过；结构修改后unit-green为8通过。首次GREEN命令同时给了两个不存在的测试过滤路径，实际仅执行docx-comment-create.test.ts一文件，未计不存在的文件。随后真实 `docx-recovery.test.tsx -t 'main new comment captures exact text'` 1项通过、61项未选，覆盖真实宿主Ribbon两入口、取消、UTF16来源范围、未失焦flush、历史、恢复及验收失败保存；不称62项全部执行。

第一次构建Vite46.90秒、TypeScript与构建终态通过，但资源预算失败：Word主包250.7 KiB超过原250 KiB。未放宽预算，按已有explicit manualChunks方式为 `docx-comment-create.ts` 增加单独模块边界 `native-docx-comment-creation`，不修改运行时保存API或加载时序。第二次构建45.86秒及预算通过，Word主包242.5 KiB、批注组件8.4 KiB，manifest `7f1d880b...`。这不是最终验收构建。

第二构建上的首次新UI浏览器 `final-built` 在5个编辑场景后停止：标题/命名/尺寸/字体已通过，但640×360、390×320、1440×360有3次textarea焦点返回后的边缘遮挡；随后取消焦点断言失败，没有继续保存。局部真实宿主诊断 `/tmp/office-docx-comment-create-focus-debug-20261112/focus-debug.json` 确认：Ribbon的mousedown preventDefault保留正文选区，activeElement仍是“审阅”标签，而不是被点击的新建批注按钮。取消实际focus到该标签。给openNew接收原生/React点击事件的currentTarget，在同一同步调用内记住实际入口，未改Ribbon的选区保护或移除preventDefault。

同一诊断的390×320长文本框，经真实Tab/Shift+Tab返回后top=183、bottom=271，body scrollTop=136，顶部两角命中标题/关闭按钮而非textarea；只调用该textarea.scrollIntoView(nearest)后top=211、bottom=299、scrollTop=108，四角均命中，文字与[160,160]选区不变。产品为textarea增加局部focus可见性恢复，不重写默认Tab或编辑协议。两项新增回归先RED（focus-unit-red：2失败8通过），修后最终focus-unit-green为10通过；最终focus-recovery指定宿主回归1项通过、61未选。最终合计2文件11项实际执行通过，不把各阶段重复次数累加为测试数量。未运行完整项目suite。

最终 `/tmp/office-docx-comment-create-focus-build-20261112.log` TypeScript/Vite终态退出0，Vite44.77秒；focus-budget退出0，Word主包242.5 KiB、批注组件8.5 KiB，原预算未改。最终manifest SHA `c88f2fef268319459971820a1da49df378d47221cf806952d3a4e78d8b1ece9a`。现有循环chunk、注解及大chunk警告保留。构建/浏览器运行期间产品、static与共享smoke冻结，确认原会话终态后才改，未因观察等待重启。

最终 `/tmp/office-docx-comment-create-focus-final-built-20261112/evidence.json` 浏览器终态退出0、ok=true：

- 编辑长多行输入/已有草稿/保存后锁定三状态×1440×900、320×640、640×360、390×320、1440×360，共15场景75控件记录。65个可用控件真实Tab/Shift+Tab往返，10个锁定输入/提交控件显示检查；主题字体、28px按钮、原生区域命名、焦点环、横向边界、中心及四个内侧角命中均通过。30张截图定位标题入口或末端操作，不能称为所有列表行和正文同时一屏显示。布局前后草稿与输入字节保持。
- 实际鼠标从审阅入口打开，底部取消及标题取消均回到实际“新建批注”按钮，未加入草稿；插入入口再添加第一条，Undo/Redo及刷新恢复同一草稿。随后第二条在textarea未失焦时触发保存，宿主自动flush，保存请求精确为两条createComment，均锚定from=2、to=8、text=chor t。恰好保存一次修订1→2，保存后输入/提交禁用且取消入口仍可用。
- 显式fixture返回validation.ok=false及“新批注版式验收待复核”，界面保留真实Word下载入口。实际点击“下载 Word”取得浏览器download事件，读取下载文件，SHA/尺寸与应答及真实patch文件匹配。重开修订2，原批注列表读取第二条新增批注文字；旧来源操作在新修订上被实际引擎拒绝，原始修订1文件SHA不变。
- 实际147个200响应资源（136 JS、11 CSS）SHA/尺寸与冻结磁盘一致，包含新增批注chunk，manifest前后相同；page/console/HTTP错误数组为空。实际Python薄桥及Node文档引擎运行；授权、CSRF/context/修订登记和下载路由为显式fixture，不代表生产授权/发布门禁验收。Node桥SHA `870bf8460d5cac896e2a25c59c35c4714361fd3783bf768cb54bb3967d363844` 与最终磁盘一致，未重建或改写桥包。

终态后 `.venv/bin/python /tmp/verify-office-docx-comment-create-20261112.py /tmp/office-docx-comment-create-focus-final-built-20261112` 退出0，生成 `independent-comment-create-check.json`。独立核对15场景/75控件/65焦点往返/30截图/147资源、实际文件身份及一次保存。ZIP健康、部件集合相同，只有word/document.xml和word/comments.xml变化。原批注用exclusive canonical XML逐节点一致，新批注精确匹配两条请求的作者/日期/文字与唯一ID。正文目标段落严格核对所有子节点顺序：原id=1锚点、An/chor t/ext三个纯文本run、两个新批注的start/end/reference及原reference；只有预期xml:space与分割，替换回已核验原段落后整份document.xml canonical字节相同。python-docx确认正文仍为Anchor text，节、表格状态保持；其他所有ZIP部件逐字节相同。不扩称复杂批注锚点、所有故事和全部字体版式已验收。

实际来源36893字节SHA `4ef498ec529da187e8abc4dc50447207fc72f1ec260b0f1c92175460965705f2`；下载37114字节SHA `b7d5d7d9e571bef6e1a9751264f75a34f2ec8bf8b7aa937b0a9b729c054b56dc`。人工查看桌面编辑/草稿双区、390×320编辑末端和锁定状态。清单同步自 `/tmp/office-ui-inventory-docx-comment-create-final-20261112/`：727模块4416声明点，全部来源SHA及canonical Markdown字节核对一致，声明点不是功能总数或完成率。

smoke语法检查通过；本批路径的git diff --check通过。全工作区检查另在management/business_documents_api.py、business_evidence_api.py、report_issue_reviews_api.py报告其他后端修改的行尾空白，未改这些不相关文件，也未将全工作区检查标为通过。未提交、推送或部署，四格式整体goal继续active；其余批注面板/上下文、未验收组件及既有Excel Injector释放与CF缺省文字色问题保留。

复现（仓库根）：`DOCX_COMMENT_CREATE_LAYOUT=1 DOCX_COMMENT_CREATE_EVIDENCE=/tmp/office-docx-comment-create-repeat DOCX_EXPECTED_MANIFEST_SHA256=c88f2fef268319459971820a1da49df378d47221cf806952d3a4e78d8b1ece9a node smart_reporting/report_editor/frontend/smoke/docx-comment-create-smoke.mjs`。

## DOCX 已有批注编辑面板 PC 续批

范围：`src/docx-comment-controls.ts`、`docx.css`中的`.docx-comment-editor`局部规则及Ribbon入口事件类型；既有新建面板和回复面板不受该规则影响。原停靠位置保留，采用固定标题、紧凑编辑区和操作分组；宽屏左右分区，窄屏纵向换行，正文区内部滚动。28px常规按钮/select、主题字体/边框、焦点环，长重载按钮允许换行。标题关闭明确命名“应用并关闭已有批注”，沿用已有先flush语义，失败不关闭/不丢输入；成功返回实际点击入口，无可信target时标题关闭仍可聚焦。输入重新获得焦点时滚入内部视口。可信来源/dirty快照/独立保存/撤销重做/线程删除原生确认/AI根目标约束均保留。

先补3条失败测试：标题关闭缺失、空来源焦点缺失、textarea重获焦点不滚动；原9条通过。执行脚本首用`python`失败（环境无该命令），随后使用项目`.venv/bin/python`完成原定局部写入，未重复应用CSS。最终组件12/12通过（`/tmp/office-docx-comment-editor-green-20261112.log`）；宿主定向执行2条只读/重新载入（60跳过）及1条未失焦保存（61跳过），共15条实际执行，不冒充62条全跑。

旧生产构建manifest `c88f2fef268319459971820a1da49df378d47221cf806952d3a4e78d8b1ece9a`的基线退出1：原smoke打开后等待textarea完整进入视口超时，截图确认普通大标题/长表单把输入裁在屏幕底部；未进入新增15场景检查，不宣称收集了完整旧版矩阵。日志 `/tmp/office-docx-comment-editor-baseline-20261112.log`，截图同名目录`failure.png`。

生产构建退出0（Vite44.21s），预算退出0，Word主chunk243.4KiB，未调高预算；日志`/tmp/office-docx-comment-editor-build-20261112.log`和`...-budget-20261112.log`。最终manifest `765f99f0fe067b5fec044a977166b43fdeafac1133637271bf3d4bdae026f2e0`。构建及browser原handle终态前冻结产品/static/smoke，未因轮询返回running重启。

实际浏览器证据 `/tmp/office-docx-comment-editor-built-20261112/result.json`：原文/已应用/保存锁定3状态×1440×900、320×640、640×360、390×320、1440×360=15场景，120控件记录、80次可用控件Tab/Shift+Tab往返、30截图。结构命名、横向边界、主题字体、紧凑高度、焦点环与中心/四角命中通过，布局前后localStorage草稿和textarea原值保持。未验证长多行内容、脏输入时重载按钮全部几何或AI provider实际调用，不外推这些状态。人工查看1440桌面及390×320锁定末端，短屏允许内部滚动。

真实Python/Node桥恰好保存一次修订1→2，验证撤销重做、刷新恢复、未失焦输入由宿主自动flush。fixture返回validation.ok=false且“批注版式验收待复核”，下载入口保留；真实点击并接收browser download事件，下载后重开读取精确文字，旧来源操作在新修订上被拒绝。147个实际资源响应（136JS/11CSS）SHA与冻结磁盘一致；manifest前后相同，page/console错误为空。授权/CSRF/context/修订登记/下载路由为显式fixture，不冒充生产鉴权及发布门禁验收。

独立脚本`/tmp/verify-office-docx-comment-editor-20261112.py`退出0：下载36946字节SHA `32706eb280588ef69d892e16bc786258952a2fcd55c7444d01f0eb136dbb145f`，来源36893字节SHA `3ac8e05b329b868ba9c605cbf74260db1d7d2f8c1e74d17046b85c1f1196cd80`。ZIP部件集合及健康核对通过；仅word/comments.xml变化，仅目标w:t文字及xml:space变化，恢复该节点后canonical XML与原件相同；作者/ID、正文与其余所有部件字节不变。Node桥SHA仍为`870bf8460d5cac896e2a25c59c35c4714361fd3783bf768cb54bb3967d363844`。

增强smoke的checkpoint恢复分支随后在复制证据目录`/tmp/office-docx-comment-editor-resume-20261112`验证退出0：不重复成功保存、使用HTTP读取已生成文件，明确actualBrowserDownload=false；原始成功矩阵及真实点击下载证据保留在built目录。恢复验证不算新增15场景或新增保存。

清单同步自`/tmp/office-ui-inventory-docx-comment-editor-20261112`，727模块4416声明点，全部来源SHA及canonical Markdown字节核对一致。声明点不是功能数量或完成率。本批目标继续active，未提交/推送/部署。

复现：`DOCX_COMMENT_EDITOR_LAYOUT=1 DOCX_COMMENT_SMOKE_DIR=/tmp/office-docx-comment-editor-repeat DOCX_COMMENT_ENGINE_DIR=/home/junge/pros/smart_reporting/smart_reporting/reporting/doc_engine DOCX_EXPECTED_MANIFEST_SHA256=765f99f0fe067b5fec044a977166b43fdeafac1133637271bf3d4bdae026f2e0 node smart_reporting/report_editor/frontend/smoke/docx-comment-gui-smoke.mjs`。

### 按更新目标补充的专家检查维度

各批组件除视觉层级/Office主题/紧凑密度，还检查：开启、输入、应用、错误、只读及保存锁定等实际状态；Tab顺序/焦点可见及返回入口；短屏、窄屏和长内容；原有来源身份及业务保护；真实生成文件的保存、下载、重开和部件最小变化；源码清单和可复现证据。逐批记录已检查与未检查状态，不把模块声明数或截图数当整体完成率。不新增无依据的业务功能，也不把某一面板通过推广为四格式全部通过。

## DOCX 根批注回复面板 PC 续批与专家细节检查

范围：`src/docx-comment-reply.ts`的控件构造/刷新和`docx.css`的`.docx-comment-reply`局部样式；来源模型、根线程验证、批次协议、保存和日期/作者逻辑未改。原停靠位置保留，固定紧凑标题；PC编辑与草稿双区，窄屏纵向；28px按钮、88px默认textarea、主题焦点环/边框、预览及草稿列表内部滚动。根批注预览和草稿列表具备名称及键盘入口；列表行显示作者、回复对象、时间和保留换行的正文，空状态明确。新增标题取消与原取消相同，只丢本地待提交输入，保留已加入文档历史的回复；正常可用入口获焦返回；不增设Esc丢弃。列表经undo变空时仅在列表原本获焦时恢复输入/取消焦点，外部焦点不被抢走；输入重新聚焦时滚入可见范围。切换到另一根时非空输入原有保护保留。

新增3条测试先失败（标题取消缺失、预览无键盘区域/草稿无明细、input聚焦无内部滚动），原7条通过；改动后10/10通过（`/tmp/office-docx-comment-reply-green-20261112.log`）。宿主定向`main binds existing comment reply`执行1条通过、61条跳过，覆盖原取消、undo/redo、恢复及未失焦保存（`/tmp/office-docx-comment-reply-host-20261112.log`）。本续批实际11条，不扩称62条全跑，也未重复全仓完整测试。

基线及环境诊断如实保留：最初两次默认/tmp Chromium出现renderer crash，第三次普通来源得到`ERR_INSUFFICIENT_RESOURCES`和CSS预载失败，均未进矩阵/未保存，不能算UI结果。现场根盘曾仅18MiB可用，进程退出后空间回升。仅将TMPDIR改为/dev/shm、不改产品/断言后，同一长来源旧构建完成5视口baseline，记录35项结构/键盘/紧凑尺寸缺陷并预期退出1：`/tmp/office-docx-comment-reply-baseline-shm-20261112/comment-reply-layout.json`。旧manifest为`765f99f0fe067b5fec044a977166b43fdeafac1133637271bf3d4bdae026f2e0`。相同来源移临时目录即可正常运行，支持临时存储资源压力判断，不将此前崩溃冒称应用功能故障。

首生产构建TypeScript通过，Vite在复制pdfjs标准字体时ENOSPC退出1，产物不完整，不用于验收（`/tmp/office-docx-comment-reply-build-20261112.log`）。TMPDIR=/dev/shm重试完整构建退出0，Vite43.54s（`...-build-shm-20261112.log`）；预算退出0，Word主模块244.7KiB，未提高阈值。最终manifest `e7cdf62ef52b8906eab1dc53d1fbf136331d563bce10cd8bdf44bdb25bce726d`。所有原始build/browser handle终态后才开始下一写入；未删除他人缓存、证据或源码。

真实浏览器最终证据：`/tmp/office-docx-comment-reply-built-20261112/evidence.json`，TMPDIR=/dev/shm。来源根批注追加100次英文长内容，输入态100行中文/emoji长回复；编辑长输入/已有草稿/保存锁定3状态×1440×900、320×640、640×360、390×320、1440×360=15场景85控件记录，75次可用控件真实Tab/Shift+Tab往返、30张截图。区域命名、横向边界、主题字体、28px按钮、焦点环和中心/四角命中通过；布局前后原草稿及输入不变。实际标题取消丢本地长输入后返回“回复此批注”入口，草稿仍空。未宣称所有内容/两个停靠面板/功能区始终同时一屏，允许页面与面板内部滚动；人工检查1440长输入及390×320末端截图，草稿列表几何由同一矩阵逐控件检查。

生产Python/Node桥完成一次修订1→2的保存，两条replyComment精确文本为“历史恢复的回复😀”“未失焦保存的回复😀”，均绑定原根target；验证undo/redo、刷新恢复和第二条未失焦保存自动flush。fixture返回validation.ok=false和“批注回复版式验收待复核”，保留Word链接，真实点击取得browser download事件并写入downloaded.docx。重开修订2读取新回复并显示父批注#1，新回复不能当根回复；旧来源操作重放实际被引擎拒绝。实际147资源（136JS/11CSS）响应SHA/尺寸与冻结磁盘一致，manifest前后相同；page/console/HTTP错误为空。鉴权、CSRF/context、修订登记和下载路由为fixture，不冒充真实生产HTTP发布验收。

独立脚本`/tmp/verify-office-docx-comment-reply-20261112.py`退出0并生成`independent-check.json`。来源37734字节SHA `b25d425a1a33837793d84c5b47a1c767322cdc376d23038ea5cd54527cc9f449`；下载37896字节SHA `058224f7db2a727b118ac65290b3d92d80857cf08c66a7ad0c566faeb255091f`，与实际patch文件逐字节相同。ZIP健康、部件集合及所有XML有效；仅document.xml/comments.xml/commentsExtended.xml变化。原批注节点exclusive canonical XML保持，新回复作者/日期/文字与两条请求一致，两个commentsEx父paraId精确为AA000001；删除两条新增commentsEx后原树canonical一致。正文仅每条新ID各一组start/end/reference；reference所在run无其他属性/节点，移除这些新标记后整个document.xml canonical与原件相同；其他ZIP部件逐字节不变。Node桥SHA仍为`870bf8460d5cac896e2a25c59c35c4714361fd3783bf768cb54bb3967d363844`。

另定向根切换浏览器补验`/tmp/office-docx-comment-reply-switch-built-20261112/evidence.json`退出0：空输入可从第一根切到第二根，回复只登记第二根；undo/redo保留实际target；非空切换被拒后第一根文字和输入不丢；取消保留已登记操作。0保存/0导出，不重复成功保存或完整套件。来源/manifest/资源身份核验、错误数组均通过。

最终清单同步`/tmp/office-ui-inventory-docx-comment-reply-20261112`：727模块4420声明点，全部来源SHA及canonical Markdown字节核对一致；声明点不是功能分母/通过率。先前批次的manifest是当时证据版本，不冒充这次final构建。源码/smoke/审计局部diff及语法检查见最终工具输出。当前四格式整体目标继续active；回复面板已改，仍有其他面板、上下文、引擎扩展和既有Excel Injector释放/CF缺省文字色问题待逐项核对。未提交、推送或部署。

复现：`TMPDIR=/dev/shm DOCX_COMMENT_REPLY_LAYOUT=1 DOCX_COMMENT_REPLY_LONG_PARENT=1 DOCX_COMMENT_REPLY_EVIDENCE=/tmp/office-docx-comment-reply-repeat DOCX_EXPECTED_MANIFEST_SHA256=e7cdf62ef52b8906eab1dc53d1fbf136331d563bce10cd8bdf44bdb25bce726d node smart_reporting/report_editor/frontend/smoke/docx-comment-reply-smoke.mjs`。

## XLSX 透视切片器与时间线筛选窗口 PC 续批

范围：`workbook-pivot-filters-dialog.ts`及新增局部CSS。桌面窗口改为820px上限、筛选条件与Excel原生控件双列、左标签右字段、28px输入/按钮；标题和底部操作固定，长成员与主体分别滚动，700px以下单列。成员列表和展开的兼容说明有名称及键盘入口，保留原控件字段、原生复选框和原业务判断；异步读取/应用暴露aria-busy与礼貌状态，失败保留已选成员和窗口。未改透视模型、日期语义、来源身份及实际引擎算法。

专家额外检查落实到本批：长中文成员换行、短屏/窄屏操作可达、真实Tab/Shift+Tab焦点和回到开启入口、异步失败不丢输入、日期倒序错误、undo/redo及刷新恢复，以及真实XLSX的保存/下载/重开和原数据公式保持。没有新增推测性业务功能，也不把截图数量当整体完成率。

定向测试：新增成员分组/键盘区域/应用失败保留选择用例先红，原3条通过；修改后dialog4条及pivot-filters5条共9条通过。日志`/tmp/office-xlsx-pivot-filter-red-20261112.log`、`...-green-20261112.log`。旧生产构建5视口baseline记录21项分组、键盘命名或命中缺陷，预期退出1，未保存：`/tmp/office-xlsx-pivot-filter-baseline-20261112/`。首新构建实际15布局场景通过后，检查脚本错误要求undo删除localStorage键，实际产品保留operations为空的草稿；只改为空操作断言，布局过程仍逐字节比较完整草稿，未弱化输入保持检查。该次saved=false，证据`/tmp/office-xlsx-pivot-filter-built-20261112/`。

第二次完成20场景及一次真实修订1→2保存后，提示文本精确匹配失败。调查确认两件事：提示节点附带新修订链接，不应使用整节点exact文本；产品原生模式初始化feedback.hidden=true且保存后未恢复，导致真实验收原因隐藏。不是XLSX已生成文件丢失。新增宿主回归断言验收原因可见、下载和重开链接保留，先在旧mock恢复套件遇到既存Injector缺失（非本功能失败），迁移到现有真实Univer的protection宿主夹具；实际红为hidden=true，`/tmp/office-xlsx-pivot-feedback-red-real-20261112.log`。产品仅在保存finally增加`feedback.hidden=false`一行，不改变保存协议或门禁。定向新用例1条通过，9条跳过（不是整个宿主套件通过），日志`...-green-20261112.log`。本批实际绿色定向测试10条；未运行或重复全仓完整测试。

首透视筛选生产构建退出0、预算通过，manifest `e9935d9f819d0536a1ec171bf3f1248ee749b05cd315fdb0eb8fe79574879b1c`，20场景及唯一实际文件生成均使用此版。反馈修复后TypeScript+Vite再次退出0，Vite43.08s，预算明确退出0（`/tmp/office-xlsx-pivot-feedback-build-20261112.log`、`...-budget-confirmed-20261112.log`），不调整阈值。最终manifest `fe3f584a2192b078da2b137e26b5e5545dd602ed21a737ac332f002b5df10752`，workbook-main190.7KiB、筛选chunk10.3KiB。构建仍有依赖注释/混合导入/大chunk提示，不冒称无警告。所有build/browser句柄终态后才改相关源码、静态资源或共享smoke，TMPDIR=/dev/shm。

保留已成功生成的revision-1.xlsx/revision-2.xlsx/request.json，smoke增加显式RESUME：恢复原请求身份和操作，fixture仅回放同一保存应答，断言请求逐字段相同，不再次调用patch或新建修订。恢复运行`/tmp/office-xlsx-pivot-filter-recovery-built-20261112.log`退出0；真实浏览器验证最终构建中验收原因可见并实际点击下载取得download事件，随后重开revision2读取PC_Slicer、不可取消已有控件的复选框及首成员未选状态，新增5视口场景。故25场景是首构建20+最终构建5，不说全部场景在最终构建重跑。原失败failure.json和日志保留，不冒充一次无失败运行。

最终证据`/tmp/office-xlsx-pivot-filter-final-built-20261112/evidence.json`：slicer/timeline-error/native-slicer（展开兼容说明）/native-timeline/reopened-slicer五状态×1440×900、768×720、320×640、640×360、390×320。25场景655控件记录，620次可用控件Tab/Shift+Tab往返，50张入口/末端截图，边界、无横向溢出、主题字体、控件密度、焦点环、中心及四内角命中通过。布局前后输入和草稿保持；允许内部滚动，不宣称所有成员/正文同时可见。实际取消回到Ribbon入口，日期倒序失败无草稿，slicer应用后undo/redo及刷新恢复相同操作。人工查看桌面展开说明、390×320末端和重开桌面截图。

当前最终构建172个实际200响应资源（148JS、24CSS）的SHA和尺寸与冻结磁盘一致，manifest前后相同，page/console/HTTP错误数组为空。鉴权、CSRF/context、修订登记/保存应答为显式fixture；文件由实际Python native_office薄桥及Node workbook引擎生成，下载为真实HTTP附件传输；此结果不代表生产授权、真实PC Excel程序或完整HTTP发布门禁验收。

独立`.venv/bin/python /tmp/verify-office-xlsx-pivot-filter-20261112.py`退出0，生成`independent-check.json`。来源10795字节SHA `1a658c5168b10d3859a4c6945f505c5e1adae1427dc2027b6a971f033f7e93d2`；保存/浏览器下载均14709字节，逐字节一致，SHA `7f72a8c6cf8946199db4fcf50f363c002c14f0e49b8471d806d51d99e54d817b`。原18行日期/长Region/金额全部精确匹配；Preserved!A1文字、B1公式=SUM(1,2)保持。透视来源Data!A1:C19、字段/汇总保持；Region第一成员隐藏，Jan16–18隐藏。原生PC_Slicer标题/Region/锚点AZ2/240×260、PC_Timeline字段Date/Jan1–15/锚点AZ18/480×160与保存请求一致。实际Node读取，不以截图替代控件校验。

ZIP健康，所有XML/rels可解析，无部件删除；只修改7个透视/工作簿/关系/内容类型部件，新增5个drawing/slicer/timeline缓存和控件部件，其余10个原部件逐字节保持，含Data和Preserved工作表及styles.xml。openpyxl只读检查发出不支持slicer/扩展警告，未用其保存文件，原生控件另由真实引擎回读验证，不宣称openpyxl支持原生控件。实际workbook CLI SHA `b5c5146aaefe5bfac152fca9ccd24e7e3e6118d4f69dc6b61d22a77fed7d7488`，本批未改动桥包。

清单同步`/tmp/office-ui-inventory-xlsx-pivot-filter-20261112/`：728模块4420声明点，全部来源SHA及canonical Markdown字节核对一致。局部diff/语法检查通过；四格式整体目标仍active，未提交、推送或部署。首批复现需新证据目录：`TMPDIR=/dev/shm OFFICE_PIVOT_FILTER_OUTPUT=/tmp/office-xlsx-pivot-filter-repeat WORKBOOK_EXPECTED_MANIFEST_SHA256=fe3f584a2192b078da2b137e26b5e5545dd602ed21a737ac332f002b5df10752 node smart_reporting/report_editor/frontend/smoke/office-xlsx-pivot-filter-smoke.mjs`；RESUME=1仅用于已有revision文件及原request的应答回放，不能算第二次真实保存。

## PDF 水印与页眉页脚窗口 PC 续批

上一目标回合为progress：完成XLSX透视筛选局部改动及真实保存/下载/重开证据。当前继续完整四格式UI目标，不把此前专项或728模块4420声明点当整体完成。本批核对源码与审计后选中PDF Stamp窗口：已有760px桌面宽度与双列表单，真实缺口是水印/页眉页脚未分成独立语义组、range当前数值不可见、缺少标题关闭及固定操作区，不能把所有原布局都说成未美化。

产品只改`pdf-main.ts`的Stamp构造、数值同步/关闭回焦及`pdf.css`局部选择器。820px桌面上限，水印和页眉页脚各有fieldset/legend，左标签右字段；三条原生range旁显示度数/百分比，并同步aria-valuetext，保持原min/max/数值换算。固定标题与底部说明/操作，主体滚动；700px以下单列，窄屏按钮可换行但保持紧凑。说明有名称及键盘入口，错误不占空白，主题焦点环。新增标题关闭与原取消语义相同，原生close后回到实际Ribbon入口（若入口所在标签已隐藏则回当前标签）；打开仍聚焦水印文字，重开从草稿或默认值同步。未改buildStamps、原生写入引擎、页面结构限制、草稿历史、保存协议或发布门禁。

专家额外检查在本批体现为：真实键盘调整range时数值与无障碍值一致；长中文输入及极短屏仍能访问取消/确定；取消不提交，清除Stamp保留已有旋转操作；undo/redo与reload恢复同一PNG及配置；实际预览/保存/浏览器下载/新修订重开；独立核对PDF原文字、页面几何及九个图像的像素/位置/透明度。不增加无依据的新业务能力。

旧构建manifest `fe3f584a2192b078da2b137e26b5e5545dd602ed21a737ac332f002b5df10752`下，`/tmp/office-pdf-stamp-baseline-20261112/baseline.json`记录5视口13项结构/滑块数值/窄屏按钮尺寸问题，savedRevisions=0、errors=[]，baseline脚本按记录模式正常退出，不冒称UI通过。新增2条宿主测试初红：缺fieldset及标题关闭；初次修改后1通过、1在异步Ribbon action执行前读取重开值而失败，按宿主实际Promise调度补等待dialog.open，不改产品语义或放宽值断言。最终定向watermark2条通过、39条跳过，`/tmp/office-pdf-stamp-green-final-20261112.log`；另原stamps操作2条通过（覆盖crop偏移、共享位图、页结构保护及覆盖范围），`...-operation-20261112.log`。本批4条不同绿色定向测试，不称整个41条宿主套件通过，未运行/重复全仓完整测试。

TypeScript+Vite构建退出0，Vite43.41s，`/tmp/office-pdf-stamp-build-20261112.log`；预算退出0，`...-budget-20261112.log`，PDF主chunk222.3KiB，未改预算阈值。保留既有依赖注释、混合导入和大chunk提示。最终manifest `fca75c9515a160fb1eb4d90a9b5e11f379524c7150c101d5d7765d62fcfd2079`。build/browser原句柄确认终态后才改产品/静态资源/共享smoke，TMPDIR=/dev/shm。

第一次新构建浏览器`/tmp/office-pdf-stamp-built-20261112/`已有20布局场景通过并生成实际PDF预览，随后脚本错误套用原位改字的必选确认框要求而超时，0保存。根因由PDF_REVIEW_KINDS及prepareSave源码核实：无reviewIssue的rotatePage+setStamps显示实际PDF预览，但原契约不展示确认面板，也不提交confirmedPreviewDigest。仅修正smoke：等待真实pdfPreview状态、明确断言确认面板hidden、保存请求不含该digest；不改产品确认门槛。保留原失败日志/截图。原handle终态后在新证据目录复验，未重复任何成功保存。

最终`/tmp/office-pdf-stamp-final-built-20261112/evidence.json`及日志退出0。initial/error/long-input/recovered四状态×1440×900、768×720、320×640、640×360、390×320，共20场景360控件记录、345次可用控件Tab/Shift+Tab往返、40张入口/末端截图；窗口边界、无横向溢出、分组、滑块显示/aria值、字体、28px紧凑控件、焦点环、中心与四内角命中通过，布局前后所有字段值及完整草稿记录保持。初始水印文字获焦；错误输入不入草稿；长输入取消和Esc回到原Ribbon；实际Home/ArrowRight把三条range调到-30°/45%/12%。保留旋转后加入setStamps，undo/redo/reload精确恢复；清除仅移除setStamps，旋转仍在，再undo回相同操作。长输入态保留此前错误文本直到取消/应用，为原行为，不表述为即时校验清空。

实际独立保存一次修订4→5；完整源数据及同一草稿通过真实grant/cookie/CSRF路由、preview/preview.pdf、打包PDF引擎、发布与下载服务。隔离测试身份/内存修订仓储仍为fixture，不等同生产数据库/真实用户或完整生产授权验收。真实保存返回validation.ok=false、native_source_review_pending及具体“文件已保存；原生编辑内容尚未重新核验业务事实与完整版式”告警，正常签发PDF并实际点击取得download事件；未标验收通过。实际下载180868字节与服务签发SHA/尺寸一致；重开修订5原文件可读。Stamp沿用原合同写成页面位图，已保存文件重开设置窗口默认为空；不声称保存后仍可读回或编辑旧Stamp配置。配置的完整恢复只针对尚未保存的草稿。

最终49个实际200响应资源（40JS/worker、9CSS）SHA/尺寸与冻结磁盘一致，允许浏览器后续合法304；manifest前后相同，page/console/HTTP及资源错误为空。人工查看桌面双分组、640×360固定标题/操作、390×320错误与长输入末端、实际预览及修订5第一页截图；其它页面内容和全部九个图像另由独立文件检查，不宣称截图中所有懒加载页面已同时完成渲染。

独立`.venv/bin/python /tmp/verify-office-pdf-stamp-20261112.py`退出0，`independent-check.json`：原2234字节SHA `d22ee52f109b515075881fcc0f7511930192e4b94807ad1e158192dd53babc30`；下载180868字节SHA `c94401f3740bf6eda540eedee26fc484e21836464c123dd57adb94681b9c301c`。三页原文字精确相同，源ContentStream所有操作完整连续保留、MediaBox/CropBox相同；只第一页按原请求旋转90°。每页恰有水印/页眉/页脚3幅图，总9幅；独立提取图像与请求PNG合成白底后逐像素相同，所有Do绘制矩阵与请求rect在0.001内一致，水印ExtGState不透明度0.45。无新增批注/表单。参数精确为机密Confidential/-30°/45%/页宽12%、页眉年度经营报告、起始页码3、页脚{page}/{total}，原页码替换规则保持。实际PDF CLI SHA `1b1cec12eb0d22057fe713fa415bc858055ca317a4c5cd0fdd221539960fb667`，本批未改引擎。

清单同步`/tmp/office-ui-inventory-pdf-stamp-20261112/`：728模块4420声明点，全部来源SHA及canonical Markdown字节核对一致；此清单未把包装函数内部新增HTML控件当成独立功能总量，声明点仍不是功能数/通过率。源码/smoke局部语法及diff检查通过。四格式完整目标继续active，未提交、推送或部署。复现使用新目录：`TMPDIR=/dev/shm PDF_STAMP_OUTPUT=/tmp/office-pdf-stamp-repeat PDF_EXPECTED_MANIFEST_SHA256=fca75c9515a160fb1eb4d90a9b5e11f379524c7150c101d5d7765d62fcfd2079 node smart_reporting/report_editor/frontend/smoke/office-pdf-stamp-smoke.mjs`。

## DOCX 插入题注窗口 PC 续批

本批仅修改`src/docx-caption-dialog.ts`、`docx.css`的题注局部规则及一条组件回归，另新增两份窄范围browser smoke。沿用现有真实SEQ域、来源编号、只读/过期选区/插入位置保护与独立保存规则。640px桌面窗口，固定标题和底部操作区，中间表单滚动；左标签右字段，预览独立fieldset并可键盘进入；长说明/预览/状态有名称及内部滚动。新增底部取消，按钮沿用共享组件与Office主题圆角；窄屏标签缩窄，取消/插入仍能访问。未改题注引擎、编号算法、保存或发布协议。

专家额外核对落实为：长中文/特殊字符按纯文本预览，图/表/公式即时同步；键盘焦点与五点实际命中；取消/Esc/标题关闭不产生草稿操作；重开清描述而保留原标签选择；不可插入位置明确禁用并说明；undo/redo及刷新恢复；一次实际保存、浏览器下载、新修订重开；独立核对真实域代码、缓存编号和原文/节设置保真。未新增无依据的业务功能。

旧生产构建manifest `fca75c9515a160fb1eb4d90a9b5e11f379524c7150c101d5d7765d62fcfd2079`，`/tmp/office-docx-caption-baseline-20261112/baseline.json`记录5视口15项结构/字体/尺寸缺陷，saved=false。baseline为缺陷记录模式退出0，不算UI通过。新增组件用例先因预览缺少region失败，原2条通过；布局修改后`docx-caption-dialog.test.ts`3条、`docx-caption.test.ts`3条共6条实际通过，日志`/tmp/office-docx-caption-green-20261112.log`。无完整仓库测试或重复全套。

首新构建`a4389dae34ac1a283307d7b1d3bb92c5c3e7cb381ded370d291ae9df01301342`的browser在long矩阵发现关闭及底部按钮四角内侧命中失败，0保存。核实共享ui-button的8px圆角，题注局部改用现有Office圆角。下一构建`95f5f0831d6c55561c3425262aa5a5d02b4a004ab01e1c5b453efbc61c11fde5`的5个long场景全部通过，随后真实取消未返回题注入口，仍0保存。根因是Ribbon的mousedown.preventDefault保留正文光标，使modal记录到此前活动元素。局部open接收现有click事件并先聚焦实际currentTarget，再记录原选区和打开；不改共享modal或其它命令。加强原新增测试，用正文焦点模拟实际入口，红灯复现取消焦点错误，再定向1条通过、2条跳过（`...-focus-red-20261112.log`、`...-focus-green-20261112.log`），原文及选区保持；此为同一条用例复验，不算第7条不同测试。三份失败证据保留，不冒充一次成功运行。

最终TypeScript+Vite构建退出0，Vite43.87s，`/tmp/office-docx-caption-final2-build-20261112.log`；预算明确退出0，`...-final2-budget-20261112.log`，Word主chunk245.2KiB，未调高阈值。既有依赖注释、混合导入、大chunk提示保留。最终manifest `4af0b04026cef0085048886c1e4e1271db5c34721013a6af15527f2ff9582867`。build/browser均等待原句柄终态后才修改产品/static/smoke，TMPDIR=/dev/shm。

最终`/tmp/office-docx-caption-final2-built-20261112/evidence.json`退出0：long/blocked/reopened三状态×1440×900、768×720、320×640、640×360、390×320=15场景，105控件记录、100次可用控件Tab/Shift+Tab往返、30张入口/末端截图。窗口边界、无横向溢出、结构及预览命名、主题字体、28–32px紧凑控件、焦点环及中心/四内角命中通过，布局前后所有字段/预览及localStorage草稿操作一致；允许内部滚动，不宣称长内容同时全部可见。取消回题注入口、非法段落中间位置禁用、Esc/标题关闭无操作、undo/redo/reload相同操作均实际验证。人工查看桌面长预览、390×320受阻状态末端、修订2重开截图。

实际Python native_office薄桥与打包Node DOCX引擎只保存一次修订1→2，实际HTTP附件下载并重开读取精确题注文字。授权/CSRF/context/修订登记/保存应答为显式fixture，非生产鉴权或完整发布门禁验收。fixture明确返回validation.ok=false及“题注版式验收待复核，文件已生成。”，页面正常显示原因并可下载，不将版式标为通过。147个实际200资源（136JS/11CSS）SHA/尺寸与冻结磁盘一致，manifest与bridge前后一致；page/console/HTTP及资源错误为空。

独立`.venv/bin/python /tmp/verify-office-docx-caption-20261112.py`退出0，`independent-check.json`：来源36724字节SHA `f631b3eec2349e3dbd58fe097dfd93e4d67aaea9cd870be4fac8d58ae5e509e8`；保存/浏览器下载均36923字节且逐字节相同，SHA `4365c9c15805a617a6bd16c7d125623efc2d1d7a69968527a7205fe76759d08f`。ZIP健康、部件集合相同、所有XML/rels可解析；仅word/document.xml改变。恰好新增首段“图 1 收入 & <保真> 😀”，包含真实`SEQ 图 \* ARABIC`、begin/separate/end及dirty=true、缓存编号1。移除新增段后完整document.xml canonical与原件一致，原四段、标题样式和节设置保留。python-docx另核对5段及1节。DOCX CLI SHA `870bf8460d5cac896e2a25c59c35c4714361fd3783bf768cb54bb3967d363844`，本批未修改引擎。

清单同步`/tmp/office-ui-inventory-docx-caption-final-20261112/`：728模块4420声明点，全部来源SHA及canonical Markdown字节核对一致；这些计数不是功能数、验收分母或完成率。局部语法及diff空白检查通过。完整四格式目标仍active，未提交、推送或部署。复现需新证据目录：`TMPDIR=/dev/shm DOCX_CAPTION_OUTPUT=/tmp/office-docx-caption-repeat DOCX_EXPECTED_MANIFEST_SHA256=4af0b04026cef0085048886c1e4e1271db5c34721013a6af15527f2ff9582867 node smart_reporting/report_editor/frontend/smoke/office-docx-caption-smoke.mjs`。已有saved-request.json的目录会拒绝重跑，防止重复成功保存。

## PPTX 自定义幻灯片尺寸窗口 PC 续批（拉取前证据补记）

本批已完成的产品改动为`slides-size-dialog.ts`及局部`slides.css`：480px紧凑窗口，固定标题/底部操作区，主体内部滚动，28px控件、主题字体和焦点环。新增标题关闭，复用现有focus trap；取消、Esc、标题关闭和dispose释放监听并回到实际入口。保存说明和错误提示有名称及键盘入口；重复dispose不抢焦点。沿用原尺寸单位换算、未更动EMU精度及范围校验。`vite.config.ts`仅将尺寸窗口单独分包，未抬高原250KiB主chunk预算：分包后主块247.4KiB、窗口2.9KiB。

专家文件检查额外发现真实引擎缺陷：`setSlideSize`先写回母版，再解析继承该母版坐标的版式，导致继承坐标缩放两次。只在`pptx-engine/src/index.ts`先解析全部master/layout来源、再缩放写回；其余缩放规则保持。新增0.5倍、2倍两条独立继承坐标反例，红灯复现ratio²；修复后`-t setSlideSize`10条通过、2条无关image-fill跳过。尺寸窗口11条、宿主3条，加上引擎10条，共24条不同定向绿色测试。原日志为`/tmp/office-pptx-size-{red,green,host,inheritance-red,inheritance-green}-20261112.log`。未重复全仓完整测试。

拉取前最终TypeScript/Vite构建及预算退出0（`/tmp/office-pptx-size-corrected-{build,budget}-20261112.log`）；manifest `7a366502a29675355d12c65750a9aa84cf0402d54c3e4f7b5ca8aac344134bb8`，edit bridge `c206202cc157d1cb1a10d60530b059403e703577ab77ede4e6f59d8d17417f09`，render bridge `4fd9061aca988f83794ee246227546f8fd46af9fe93a47475be0d9ebb3707592`。这组浏览器证据只适用于此冻结构建，不能当作随后拉取合并后构建的端到端结果。

`office-pptx-size-{fixture.py,layout.mjs,smoke.mjs}`使用实际RenderTree、Python原生保存、打包引擎、HTTP附件及浏览器download。授权/CSRF/context/修订登记和应答为显式fixture；初始preview.pdf回退GET返回204，不冒称验证PDF渲染。窗口检查覆盖1440×900、768×720、320×640、640×360、390×320，以及initial/error/recovered/reopened四状态；单位切换、非法输入、取消/关闭不改草稿、undo/redo、刷新、保存和重开均检查。fixture返回validation.ok=false及“幻灯片尺寸版式待复核，文件已生成。”，可正常下载，不冒称版式验收通过。

保留失败证据：旧基线`/tmp/office-pptx-size-baseline-final-20261112/baseline.json`为5视口记录模式；首次新版`.../office-pptx-size-built-20261112/`20场景完成并已保存，随后等networkidle超时。应答回放补验`.../office-pptx-size-recovered-built-20261112/`未再次patch/保存，但独立检查发现40个继承坐标错误，`independent-failure.json`明确失败，不将旧产物算正确。引擎修复后在全新隔离目录保存一次；整批共两次真实浏览器保存（旧错版一次、修复版一次），回放不增加保存次数。

最终`/tmp/office-pptx-size-corrected-built-20261112/evidence.json`退出0：20场景、145次控件焦点往返、40截图、138资源，errors=[]。人工查看桌面窗口、390×320错误态和重开画布；短屏允许内部滚动，不宣称所有字段同时可见。独立`/tmp/verify-office-pptx-size-20261112.py`及`independent-check.json`通过：源29571字节SHA `eff539312eee88213125ab8371a7f35187c0d960cbff7861bc6fcc50e78c0c41`；实际保存与下载45508字节逐字节相同，SHA `4319880449355c1cc5dec62f6bb8eeec46f3165aa0edb88bac8f501e6409e050`。两页四对象变为9000000×7200000 EMU（25×20cm）；67个变换正确，包括40个继承变换只缩放一次；15个part改变、25个其他原part字节不变，12个新增空ZIP目录并非OOXML内容。保存器原有行为另补67个唯一creationId，独立核对位置/结构后，仅归一这些身份及请求尺寸/坐标，原XML canonical完全一致；原文字、20pt字号和粗体保持。

## 拉取最新代码后的证据边界

2026-11-12按用户要求将`code`从`4cfaac2396018ecd40cd178cf7f0c64a561edba4`快进18提交至`3b4ff524a402936a7c92fd38982824f8721dc120`；保留本地工作，融合7个stash冲突，恢复原空index。备份`/dev/shm/smart-reporting-pull-20261112.1n6g55u8`与stash `bf980abb062bc7927c987253617af59b22cc9966`保留。再次fetch确认HEAD与origin/code差异0/0，没有新增提交。

合并后重新打包DOCX/PDF/PPTX bridges，前端TypeScript/Vite构建、预算退出0。`/tmp/post-pull-ui-tests-20261112.log`117项前端定向测试、三份`post-pull-*_engine-20261112.log`26项引擎定向测试，以及`post-pull-publication-tests-20261112.log`3项HTTP测量告警非阻断回归通过，共146条。未声称合并后四格式完整浏览器验收通过。合并后初始manifest `b325aee1e046740c0c7d9131864f4c9ea8db54377cc414ca50e7633a64169edb`，后续每批以其各自冻结构建重新记录。旧清单在本批完成后重新生成及逐文件SHA核对，模块/声明数不作为整体完成率。

## PDF 编辑已有图像窗口 PC 续批

前一目标回合为progress：重新fetch并核对code与origin/code为同一提交，本地工作保留。继续四格式完整目标，本批选择远端新增像素替换能力的已有图像窗口。窗口原有桌面主题/坐标字段及替换按钮，并非全部未经美化；实际缺口为缺少标题关闭、固定标题及操作区、尺寸/替换语义分组，说明与错误不支持命名键盘入口，关闭回焦不完整，替换禁用原因只在title中。

仅局部修改`pdf-existing-image.ts`及`pdf.css`相应规则：620px桌面窗口，48px标签列，所有按钮/数字框/选择框实际28px高；固定标题/底部操作区，主体滚动，480px以下尺寸字段单列。位置与尺寸、替换图像两个fieldset；长说明、长文件名和错误可键盘聚焦并内部滚动。替换状态使用命名status，禁用原因同时显示在正文。新增标题关闭，取消/Esc/原生close/dispose释放focus trap并返回仍存在的入口；已打开时不重复覆盖入口。沿用PNG/JPEG转换、2000px降采样、原始PDF坐标、来源身份、替换许可、并发草稿保护及已有图像须单独保存的规则；不改引擎、发布或下载协议。

新增`pdf-existing-image-desktop.test.ts`5条用例，覆盖分组和可见禁用原因、取消/标题关闭/Esc回焦且不提交、非法尺寸保持可编辑以及有效尺寸入草稿。红灯日志`/tmp/office-pdf-existing-image-red-20261112.log`记录5条预期失败；最初测试文件名与上游panel测试重名，随后拆为独立desktop文件，原`pdf-existing-image-panel.test.ts`完整保留且与HEAD无diff。最终桌面5条、原panel6条、原操作10条，共21条定向通过（`...-green-20261112.log`），包括0/90/180/270°页面坐标、只读、来源变化和并发草稿保护。未重复全仓完整测试。

修改前`/tmp/office-pdf-existing-image-baseline-20261112/baseline.json`在合并后初始构建记录5视口7项结构/尺寸缺陷，savedRevisions=0；该基线按记录模式退出0，不代表UI通过。首构建类型检查发现新增夹具缺mediaBox及共享工作区数据刷新接口正在并行变更；补齐自身夹具，其他会话随后补完自身接口，未改写其代码。原失败日志保留。下一构建及预算通过，首浏览器`/tmp/office-pdf-existing-image-built-20261112/`完成20场景、真实保存和独立文件验证；人工看图发现通用样式仍将按钮撑至34px、标签列偏宽。加强实际尺寸和列宽检查后，`.../office-pdf-existing-image-density-red-20261112/baseline.json`在5视口复现25项，0保存。仅提高本窗口选择器的局部优先级，不改公共样式或降低断言。

最终TypeScript/Vite构建退出0，Vite45.01s，`/tmp/office-pdf-existing-image-final-build-20261112.log`；预算退出0，`...-final-budget-20261112.log`，未调高阈值。保留既有依赖注释、大chunk和字体运行时解析提示。最终manifest `99a3091dae69434fe7166868720fa664d281a86e42f7a63d87592939598d52bc`，PDF CLI SHA `e57678430c28abc62d336311c0a5f6cc9e630e51e066a1114cc8319d052069a4`，本批未改引擎。构建期间只有不在原生UI导入闭包内的management文件由其他会话变化；本批732个可达模块在构建开始、清单生成、浏览器后逐文件SHA一致。每次build/browser均确认原句柄终态后才修改本批产品/static/共享smoke，TMPDIR=/dev/shm。

最终`/tmp/office-pdf-existing-image-final-built-20261112/evidence.json`退出0：initial/error/replacement/reopened四状态×1440×900、768×720、320×640、640×360、390×320，共20场景、230次控件焦点往返、40张入口/末端截图。窗口边界、分组、固定区域、主题字体、焦点环、中心及四内角命中、实际28px高和48px标签列通过。布局检查前后所有字段与完整草稿操作一致；长文件名包含中文/&/<保真>/emoji，仍按纯文本显示。非法几何/GIF文件不入草稿；不替换按钮、标题关闭、取消、Esc及重开初始值均检查；替换后undo/redo/reload精确恢复同一操作和PNG。

实际原生grant/cookie/CSRF/preview/preview.pdf/打包PDF引擎/发布/下载路由均使用真实代码；复用`pdf-existing-image-server.py`的隔离内存文档、授权和产物仓储，不替代生产数据库/真实用户验收。最终隔离修订4→5只保存一次，实际点击链接取得浏览器download并重开读取新修订；此前首新版另有一次隔离成功保存，整批两次保存分别属于两个不同构建的全新fixture，未覆盖或重放原成功保存目录。validation.ok=false及native_source_review_pending具体原因保留，可正常下载，未标为业务或完整版式验收通过。

独立`.venv/bin/python smart_reporting/report_editor/frontend/smoke/office-pdf-existing-image-verify.py /tmp/office-pdf-existing-image-final-built-20261112`退出0，`independent-check.json`：源5385字节SHA `4b6b0d68df3a4161dd5ed141f958f65054922664dd5367e68f14a4260e90ae08`，实际下载2670字节SHA `6e4c19eaaee5015c38bed5271eca6cf3f591a9a91bf966c9d7e48225f4bb1f6b`与签发身份一致。目标图像变为40×30，全部RGB像素与请求PNG逐字节相同；原始PDF范围[60,90,160,170]按请求变为[80,110,230,210]，独立PyMuPDF顶部坐标bbox由[60,230,160,310]变为[80,190,230,290]。三页原文、MediaBox/CropBox/旋转保持；第一页原/新图像范围之外所有渲染像素相同，第二/三页整页渲染像素相同，无新增批注/表单。没有声称PDF内部重序列化字节完全不变。

最终50个实际200 JS/CSS资源SHA/尺寸与冻结磁盘一致，manifest前后相同，page/console/HTTP错误为空。人工查看最终桌面长文件名、390×320错误态和保存重开画布；允许长内容内部滚动，不宣称所有字段同时可见。清单同步自`/tmp/office-ui-inventory-pdf-existing-image-final-20261112/`：732模块4449声明点，全部来源SHA和canonical Markdown字节核对一致；这些数值不是功能总数、验收分母或整体完成率。四格式完整目标继续active，未提交/推送/部署。

复现需新证据目录：`TMPDIR=/dev/shm PDF_EXISTING_IMAGE_OUTPUT=/tmp/office-pdf-existing-image-repeat PDF_EXPECTED_MANIFEST_SHA256=99a3091dae69434fe7166868720fa664d281a86e42f7a63d87592939598d52bc node smart_reporting/report_editor/frontend/smoke/office-pdf-existing-image-smoke.mjs`。已有save.json的目录拒绝再次保存；独立核验脚本只读已有PDF，不重复保存。


## XLSX 插入符号窗口 PC 续批

前一目标回合对 UI 属于 no progress：只尝试 fetch 并确认超时，本地代码未更新。本回合重新核对本地 HEAD、符号窗口、测试与构建；网络不阻断本地继续。四格式完整目标仍 active，不把本窗口或源码声明数量当整体完成。

产品只改 `src/workbook-symbol-dialog.ts` 和 `workbook.css` 的符号局部规则。480px 桌面窗口，固定标题与底部关闭区，中部滚动；普通按钮实际28px、符号格36px，桌面10列、窄屏6列。分类按钮只创建一次，切换不再丢失焦点；分类与符号组各保留一个 Tab 入口。分类支持左右/Home/End，符号支持上下左右/Home/End，Enter/空格沿用原生按钮激活。tab/panel 使用实例唯一 ID 关联；说明、错误、插入结果有名称及键盘入口。保留五类符号的顺序、点击立即追加及窗口保持打开的行为，未改公式/富文本/长度保护、宿主写入、引擎或发布协议。

专家额外检查落实为：导航不修改数据，标题关闭/Esc/底部关闭回到实际入口，公式错误不入草稿，短屏提示确实可读，连续激活只改变目标单元格，撤销/恢复与刷新一致，以及真实保存/下载/重开后公式、样式和保护保持。本批没有另加提交按钮或无依据的新业务能力。

7条组件测试中原3条完整保留，新增4条在 `/tmp/office-xlsx-symbol-red-recheck-20261112.log` 为4失败/3通过；其后 `/tmp/office-xlsx-symbol-green-20261112.log` 为7通过。新增说明缺失断言最初抛 null.getAttribute，已补显式存在断言。没有运行或重复全仓完整测试。

旧构建 manifest `99a3091dae69434fe7166868720fa664d281a86e42f7a63d87592939598d52bc` 下，`/dev/shm/office-xlsx-symbol-baseline-20261112/baseline.json` 记录5视口40项结构/尺寸/焦点问题、0保存；baseline退出0只代表记录完成。首构建 `/tmp/office-xlsx-symbol-build-20261112.log` 包含 TypeScript+Vite、退出0，Vite42.87s。首新版 `/dev/shm/office-xlsx-symbol-built-20261112/` 在320px宽发现7个符号角点命中失败，0保存。追加真实命中对象、宽度和圆角诊断；`.../office-xlsx-symbol-hit-diagnostic-20261112/` 复现为6px圆角与分数列宽的命中边界，命中到网格本身，并非浮层遮挡。符号格局部收紧至2px圆角，更接近PC网格，不降低五点命中断言。

`.../office-xlsx-symbol-final-built-20261112/` 的35场景通过后，脚本在功能区按钮焦点上发送 Ctrl+Z，未进入网格撤销处理，0保存。根据既有宿主的 gridChanged/快捷键分工，改用真实“文件→撤销/恢复”，并精确等待A1恢复到仅追加€、再恢复€→，没有修改产品历史机制。随后 `.../office-xlsx-symbol-final2-built-20261112/` 仅落盘2场景，进程退出1、日志为空且无失败回执；同时观察到根分区可用空间为0，不推断未记录的具体异常。保留其证据，后续日志也写入 /dev/shm。

`.../office-xlsx-symbol-final3-built-20261112/` 曾实际保存一次，但路由 fulfill 下载报告 canceled，未取得有效浏览器下载，不能算整链通过。后续改用与已有透视筛选smoke一致的真实HTTP附件服务，保留下载失败断言；修正XLSX反馈检查为真实 `.workbook-feedback`，而非仅DOCX/PDF使用的 `.native-delivery`。该目录的 `review-followup.json` 明确记录：尝试停止时进程已经因下载失败退出，终止命令未生效，不冒称成功取消。旧保存目录未重放或覆盖。

人工检查还发现短屏说明/错误被Grid压至4px，旧的“可聚焦/命中”检查漏掉文字可读性。加强至少一行可读的实际高度检查，`.../office-xlsx-symbol-readable-red-20261112/baseline.json` 在390×320复现、0保存。仅增加主体 `grid-auto-rows:max-content`，保持提示自然行高并通过主体滚动适配；最终短屏说明与公式错误均实际43px。人工查看最终桌面、390×320说明及错误获焦截图、新修订重开窗口，文字与关闭操作可读可达；不宣称所有内容在短屏同时可见。

最终 `/dev/shm/office-xlsx-symbol-readable-build-20261112.log` Vite构建退出0、44.71s，`...-readable-budget-20261112.log` 预算退出0，没有提高阈值。收尾复核发现相对首轮TypeScript检查，原生入口闭包除 `workbook.css` 外，共享 `api.ts` 也发生变化，因此追加最终 `npx tsc --noEmit` 检查，退出0，日志 `/dev/shm/office-xlsx-symbol-final-typecheck-20261112.log`；未重复已通过的浏览器保存或完整测试。保留现有依赖注释、混合导入、循环chunk、大chunk与字体运行时解析提示。最终 manifest `f0298ca6d5f3914114e3e7072a2ec7f4289cb4abc44d0ae48984a139ca5e9b3d`，workbook CLI SHA `b5c5146aaefe5bfac152fca9ccd24e7e3e6118d4f69dc6b61d22a77fed7d7488`，未改引擎。

最终 `/dev/shm/office-xlsx-symbol-readable-built-20261112/evidence.json` 及同名.log 退出0：五分类、公式错误、连续插入、重开共8状态 × 1440×900、768×720、320×640、640×360、390×320，共40场景、1245条控件记录、1085次Tab/Shift+Tab往返、85张截图。边界、无横向溢出、主题字体、28/36px高度、单一Tab入口、焦点环、五点命中及提示可读行高通过。分类切换及实际方向键导航无草稿变化；公式拒绝、关闭回焦、€的Enter激活、→的空格激活、撤销/恢复及reload数据精确检查通过。

最终隔离修订1→2实际保存一次，Python native_office薄桥与打包XLSX引擎真实执行，真实HTTP附件响应及浏览器download成功，并载入新修订。全批实际保存共两次：旧构建下载失败一次、最终新构建一次，分别属于全新fixture。授权、CSRF、context、修订登记和保存应答是明确HTTP路由fixture，不能替代生产授权/数据库或完整发布门禁验收。fixture返回 validation.ok=false 及“符号插入版式待复核，文件已生成。”，实际页面显示原因并可下载，未标为业务/版式验收通过。

独立Python核对 `independent-check.json`：来源5579字节，SHA `c4db1ebce31730672d08eb5466bbc8c1eba7ebe4acb30cf6fa91c43a390a4729`；实际下载5611字节，SHA `2f671790d65ae3500d1efb6723d3877dbd4be45aa37d13c64a9194364b8529b6`，与保存文件逐字节及签发身份一致。A1为“价格 & <保真> 😀€→”，C1公式仍为 `=A2*2`。openpyxl核对两工作表7个单元格的其他值、font/fill/border/alignment/protection/number_format，以及列宽和工作表保护。ZIP健康、部件集合相同，只有 `xl/worksheets/sheet1.xml` 改变，Locked工作表原始字节保持。未声称桌面Excel实机验收。

171个实际200 JS/CSS资源SHA/尺寸与冻结磁盘一致，manifest前后相同，捕获的page/console error/HTTP错误为空。构建、浏览器原句柄终态后才修改本批产品/static/smoke。冻结构建清单来自 `/dev/shm/office-ui-inventory-xlsx-symbol-readable-final-20261112/`，732模块4449声明点；浏览器完成时已核对全部来源、smoke、Vite配置和引擎SHA、canonical Markdown字节一致。计数不是功能数、验收分母或整体完成率。

收尾期间共享 `api.ts`、`evidence-browser.ts`、`evidence-policy-adoption.ts` 又有并行修改，不属于本批产品写入，未覆盖或回滚。`source-verification.json` 已区分浏览器完成时的冻结校验与后续当前源差异，记录三文件旧/新SHA；本批符号窗口源码、CSS、smoke、引擎、171个资源及manifest仍与已验证构建一致。最新canonical清单重新来自 `/dev/shm/office-ui-inventory-xlsx-symbol-close-20261112/`，仍732模块4449声明点，逐文件SHA及Markdown字节在该次收尾检查匹配；它不是新的运行验收。最终类型检查退出0只代表当次检查状态，不能扩展到随后修改的共享源码。下一批需对后续共享源差异做相应类型/构建及相关验证，不能将本批40场景冒充最新四格式全链结果。整体目标继续active，未提交、推送、部署。

复现须使用全新目录：`TMPDIR=/dev/shm WORKBOOK_SYMBOL_OUTPUT=/dev/shm/office-xlsx-symbol-repeat WORKBOOK_EXPECTED_MANIFEST_SHA256=f0298ca6d5f3914114e3e7072a2ec7f4289cb4abc44d0ae48984a139ca5e9b3d node smart_reporting/report_editor/frontend/smoke/office-xlsx-symbol-smoke.mjs`。已有save.json的目录拒绝再次保存。

## PPTX 查找和替换窗口 PC 续批

上一目标回合仅尝试拉取代码，GitHub 两次超时；对 UI 目标没有新增进展，不能把本地缓存 origin/code 当远端最新。本回合恢复未完成的查找替换批次，读取原绿色日志及当前源码后继续验证。原 `/dev/shm/office-pptx-find-green-20261112.log` 已完成，17 条组件测试通过，原14条完整保留。新增三条覆盖固定结构与命名提示、readonly结果不提交、提示滚入可见区但不抢输入焦点。红灯证据为 `office-pptx-find-red-20261112.log` 和 `office-pptx-find-reveal-red-20261112.log`；未运行或重复完整测试。

产品改动只在 `src/slides-find-replace.ts` 和 `slides.css` 对应局部块：560px紧凑窗口、固定标题/底部操作区、主体内部滚动、左标签右字段、28px控件、16px复选框、主题字体与焦点环。范围说明和结果新增名称及Tab入口，结果出现时滚入可视区。标题关闭、Esc、close/dispose回焦本来已存在，保留原行为，不作为新增功能。原字面搜索、大小写选项、对象级导航、第一次替换先定位、全部替换原子提交、20000字符限制及安全来源范围保持；`$&`/`$1`仍按普通文字处理，不跨段落，未扩大混合样式/链接/表格/样式引用等安全边界，未改引擎、宿主保存或发布协议。

`office-pptx-find-{fixture.py,layout.mjs,smoke.mjs}`为本批独立证据入口。旧生产构建基线 `/dev/shm/office-pptx-find-baseline2-20261112/baseline.json` 在五视口记录30项缺陷、0保存，退出0仅代表记录完成。更早baseline因安全对象数2≠3而停止，不能算布局通过：python-pptx普通形状默认有p:style，桥按既有安全规则排除。fixture改为一个显式格式无p:style普通形状，并另保留有p:style对象验证排除边界；没有放宽产品安全规则。宿主locked()直接拒绝打开窗口，因此没有伪造真实readonly窗口布局场景，动态readonly拒绝由组件测试覆盖。

最终 `/dev/shm/office-pptx-find-build-20261112.log` 包含TypeScript+Vite，退出0，Vite45.14s。预算 `/dev/shm/office-pptx-find-budget-exit-20261112.log` 明确退出0，没有提高阈值；PPTX主块234.8KiB。保留依赖注释、混合导入、循环chunk、大chunk及字体运行时解析提示。manifest为 `8185040454d10193b5acec3abc537f0af8fc046435bc92842672c37b2f14081e`；edit bridge `6d4bae9b0bd649277632a4d927a4571e9c41cc5f1766e7c0acff73b2c659452c`、render bridge `4fd9061aca988f83794ee246227546f8fd46af9fe93a47475be0d9ebb3707592` 均未由本批修改。

最终 `/dev/shm/office-pptx-find-built-20261112/evidence.json` 和同名.log，原句柄13888退出0。initial/error/applied/reopened四状态 × 1440×900、768×720、320×640、640×360、390×320，共20场景，195条控件记录/Tab往返、46张截图，边界、横向溢出、字体/尺寸、五点命中、焦点环、提示行高全部通过。空查询/无匹配、英文大小写3→2处、中文4处、超长替换拒绝且零草稿、单次替换先定位再替换、全部替换4处/3对象、undo/redo/reload草稿精确保持均通过。人工查看桌面初始窗口、390×320错误提示和重开画布；短屏允许主体内部滚动，不声称所有内容同时显示。

真实Python inspect/patch/render-tree及打包引擎、HTTP附件、浏览器download执行，隔离修订1→2实际保存一次，重开查到新字面文字4处。授权、context/CSRF、修订登记和保存应答仍为显式HTTP fixture，初始preview.pdf回退GET为204，不能替代生产鉴权/数据库/完整发布门禁或PDF渲染验收。fixture返回validation.ok=false及“查找替换版式待复核，文件已生成。”，页面显示具体告警并照常下载，未标验收通过。

独立 `independent-check.json`：来源30998字节 SHA `4c7c2f9bd17e6011e2b9fae105fa2fc38ff9a75cac6bf8d165837a1f80a50c52`；实际下载43779字节 SHA `7dfea736b5bbd117a3da1e8ae2143f453b914d290e4ac39531296f88bd3ec9df`，下载、保存与应答身份逐字节一致。3页9对象，目标替换值为“营收 $& <PC> 😀”，4处精确替换；只slide1.xml/slide2.xml内容变化。ZIP健康、所有XML/rels可解析、内容部件集合一致，新增空ZIP目录明确列出。逐项核对名称/ID、几何/旋转、字体属性、超链接和表格，恢复请求修改的a:t并核验新增3个唯一creationId后，canonical XML必须与来源一致，未任意归一其他扩展。混合run、链接、表格、样式引用对象保持。未宣称桌面PowerPoint实机验收。

141个实际200 JS/CSS资源SHA/尺寸与冻结磁盘一致，manifest/引擎前后相同，捕获的page/console/HTTP错误为空。构建及浏览器原句柄终态后才写本批收尾文档。`source-verification.json`核对原生入口闭包732模块4452声明点全部来源SHA一致，canonical清单来自 `/dev/shm/office-ui-inventory-pptx-find-20261112/` 且Markdown字节一致。数字不是功能总数、验收分母或完成率。构建期间并行变化为管理页 `management/features/sources/editor.tsx`；构建后为 `management/components/ConfigurationWorkspace.tsx` 和 `smoke/management-built-postgres-smoke.mjs`。已记录旧新SHA，未覆盖；本批不将冻结原生构建结果套用到这些后续管理源码。

根分区曾写满，恢复记录补充：仅将本目标五个旧静态证据目录迁至 `/dev/shm/office-ui-root-space-migration-20261112/`，原路径保留symlink，每文件SHA复制前后及symlink后一致，清单为 `migration.json`。本批新日志与证据使用/dev/shm，未删除其他任务文件。

复现须新目录：`TMPDIR=/dev/shm PPTX_FIND_OUTPUT=/dev/shm/office-pptx-find-repeat PPTX_EXPECTED_MANIFEST_SHA256=8185040454d10193b5acec3abc537f0af8fc046435bc92842672c37b2f14081e node smart_reporting/report_editor/frontend/smoke/office-pptx-find-smoke.mjs`。已有saved-request.json目录拒绝再保存。四格式整体目标仍active，本批完成不代表穷举验收完成；未提交、推送或部署。

## XLSX 单变量求解与模拟运算表 PC 续批

上一用户回合只尝试拉取代码，两次 GitHub 连接超时，对 UI 目标没有新增进展；本轮继续此前尚未收尾的模拟分析批次。仍为 `code` / `3b4ff524`，不能宣称远端最新。四格式完整目标保持 active，未提交、推送或部署。

产品修改限定于两个窗口 TS、`workbook.css` 末尾模拟分析局部块，以及真实验证发现的两处计算适配器。窗口使用480px上限、28px控件、左标签右字段、固定标题/操作区和可滚动主体。说明、结果与错误有独立名称及Tab入口；运算开始聚焦状态，失败时若用户仍在读状态则转到错误，并保留字段值以供重试。长提示滚入可视区。原运行期间禁止关闭/取消、字段锁定、Esc、关闭回焦及宿主锁继续保留，不将既有行为称为新增功能。未修改求解算法、静态结果语义、历史、发布门禁或下载协议。

真实带 `0.00` 的来源A1暴露数值误判：Univer NUMFMT会把 `getValue()` 投影成显示字符串，原求解器因此拒绝数值5。保留来源格式，改用官方 `getRawValue()`，仅5处读取：求解输入/公式结果，以及数据表原输入/候选值/公式结果。没有编写显示字符串解析器。新增真实Univer+NUMFMT+Formula回归覆盖百分比、货币、自动/手动计算、恢复输入及undo/redo。有效红灯 `/dev/shm/office-xlsx-analysis-number-format-red-recheck-20261112.log` 为4失败/1通过；更早同名red日志仅因路径错误未找到测试，不作为RED。绿色 `...-number-format-green-20261112.log` 为新5条与原求解12条、数据表13条，合计30通过。两个窗口新增4条组件测试，`office-xlsx-analysis-red-20261112.log` 4失败/2通过，`...-green-20261112.log` 6通过；本批合计36条不同定向绿色测试。后续仅补新test的 `ICellData` 类型标注以解决TS2322，最终完整类型检查通过，没有重复完整测试。

新增 `smoke/office-xlsx-analysis-{layout.mjs,component-smoke.mjs,fixture.py,smoke.mjs}`。组件基线中曾漏载Office主题，不能将242项失败全部归因于产品；还修正程序化click未设置入口焦点、入场动画中测量27.88px的检查器问题。人工发现关闭SVG被通用按钮padding挤到6×18px，增加最小16px断言，`office-xlsx-analysis-icon-red-20261112/` 的10场景恰10项失败，局部提高关闭按钮选择器优先级后为18×18px。`component-final2` 的40场景虽通过，旧断言未覆盖居中；本轮追加水平/垂直留白对称检查，`centered-red` 的10个初始场景在320/390px宽共4项失败，左右留白为20px/4px。原因是card按viewport计算宽度超过已有20px遮罩padding可用宽度。只将模拟分析局部宽度改为 `min(480px,100%)`，高度上限改为 `100dvh - 40px`，保留480px桌面宽度，不修改共享遮罩。

最终 `/dev/shm/office-xlsx-analysis-centered-green-20261112/evidence.json`，原句柄99031退出0：两窗口×initial/busy/error/success×1440×900、768×720、320×640、640×360、390×320，共40场景、240条控件Tab/Shift+Tab记录、0失败/page error。检查窗口居中及边界、无横向溢出、固定区域、命名提示、主题字体、28–32px高度、18px关闭图标、五点命中、焦点环、首末Tab循环和提示至少一行可读；检查前后字段与草稿不变。回调为可释放Promise，仅证明产品组件状态，不冒充实际计算或文件保存。已人工查看桌面初始窗口与390×320长错误末端；短屏允许内部滚动，不宣称全部内容同时可见。

生产尝试完整保留：`office-xlsx-analysis-built-20261112/` 复现格式化数值误判，0保存；`raw2-built` 真实求解已得15，但脚本误用同名功能区按钮等待dialog状态，0保存。改为精确 `[role=dialog][aria-label=...]` 后，`raw3-built` 两计算、undo/redo/reload、30个布局场景通过，已真实保存/下载一次；独立检查却直接比较跨工作簿Dimension对象而失败，不能把那次进程称为整链通过。只读诊断确认 `ColumnDimension.__eq__ is object.__eq__`，A/D/G宽度17/18/28及行1高度24均相同。改核对行列键集合、序列化属性及样式，并保留完整canonical sheet检查；在原下载文件上独立重验通过，没有重放保存。其来源/下载分别7353/7359字节，SHA `13a261d63d8273ff4b17fbf869f6825ab80f23818d8d2853de37b40bea96d31c` / `46dca734c99d53d633a5fcd48e0ec7bb998e84e6d30b5a73b30f3e5fc788d50b`。另在/dev/shm复制文件后分别篡改列宽、行高、单元格样式和无关数值，四项均拒绝，见 `office-xlsx-analysis-fidelity-mutation-check-20261112.json`；未放宽保真契约。

最终完整 `npm run build` 日志 `/dev/shm/office-xlsx-analysis-centered-build-20261112.log`，原句柄77308退出0，含TypeScript与Vite43.90s；预算 `...-centered-budget-20261112.log` 明确退出0，没有提高阈值。旧raw构建曾因新test的联合类型推断失败，修正后raw2构建完整通过；当前居中修复后的构建再次包含TypeScript。保留既有依赖注释、混合导入、循环chunk、大chunk和字体运行时解析提示。最终manifest为 `db004742ab578fd79c1d2b2d0ed21c14b86d3548ebb02ee025b677685fdc21f8`，workbook CLI仍为 `b5c5146aaefe5bfac152fca9ccd24e7e3e6118d4f69dc6b61d22a77fed7d7488`，未改引擎。

最终 `/dev/shm/office-xlsx-analysis-centered-built-20261112/evidence.json`，原句柄48388退出0：真实生产资源宿主中，两窗口initial/error/success/reopened四状态×五视口，共40场景、280条可用控件Tab/Shift+Tab记录、101张截图，0失败/page/console/HTTP错误。Infinity及同一行列输入单元格拒绝时草稿不变；带格式A1求得15，列式数据表E3:E5为20/40/60，精确草稿仅四个cell edit。数据表一整步撤销/恢复、reload、保存和修订2重开通过。真实Univer计算、Python原生patch、HTTP附件和浏览器download执行；授权/context/CSRF/修订登记/保存应答仍为显式fixture，不能代替生产鉴权、数据库、完整发布门禁或桌面Excel实机验收。fixture返回 `validation.ok=false` 及“模拟分析结果版式待复核，文件已生成。”，页面显示原因并照常下载，没有标验收通过。

最终隔离fixture只保存一次；全批实际保存总共两次（raw3与centered各一次，均为不同构建的全新目录）。没有覆盖/重放旧成功保存。独立回读来源7353字节、SHA `d69c4836c54b5dbeee70792d6b8aefaef7c3bf065d1d93f4f4a5ae8856479221`；下载7359字节、SHA `d301af88811fb6063d9401dcea001470f16e70fe8724f758037f2df6ba38250e`，与保存文件逐字节一致。两表41个单元格的值、font/fill/border/alignment/protection/number_format、链接/批注/名称、列宽/行高/冻结及工作表保护保持；B1/E2仍为 `=A1*2`。ZIP健康、部件集合相同，只有sheet1.xml改变；将A1/E3/E4/E5替回源XML后，整个工作表canonical字节必须与来源一致，没有忽略其他属性。人工查看最终桌面成功、390×320错误获焦及重开工作表截图。

`source-verification.json` 核对171个实际200 JS/CSS资源SHA/尺寸、最终manifest和引擎，及原生入口闭包732模块全部来源SHA，均与冻结证据一致。最新清单来源 `/dev/shm/office-ui-inventory-xlsx-analysis-centered-20261112/`，4452声明点，canonical Markdown字节相同，无须为样式变更重写清单。声明点不是功能数、验收分母或完成率。构建期间6个、构建后5个、首次收尾后4个管理端文件变化分别记录旧新SHA；首次收尾断言因这些并行管理改动而停止，检查其均在 `src/management/` 且不属于原生入口闭包后单独登记，没有覆盖或为此重跑产品验证。本批不将原生窗口/资源结果套到后续管理源码。构建和浏览器原句柄终态后才写收尾文档；三个JS smoke语法、Python AST及本批既有产品文件 `git diff --check` 通过。

本轮落实的专家附加检查包括：显示格式与数值计算分离、检查器自身的故障注入、忙碌状态的键盘阅读入口、错误保留输入、标题图标真实命中尺寸、窗口视觉居中、真实下载而非链接存在，以及只允许指定单元格变化的文件保真。四格式剩余菜单/嵌套状态和完整功能逐项验收继续进行，不能以这两个窗口通过替代整体完成。

复现使用全新目录：`TMPDIR=/dev/shm XLSX_ANALYSIS_OUTPUT=/dev/shm/office-xlsx-analysis-repeat WORKBOOK_EXPECTED_MANIFEST_SHA256=db004742ab578fd79c1d2b2d0ed21c14b86d3548ebb02ee025b677685fdc21f8 node smart_reporting/report_editor/frontend/smoke/office-xlsx-analysis-smoke.mjs`。已有save.json目录拒绝再次保存。

## DOCX 超链接窗口 PC 续批

上一目标回合完成XLSX模拟分析收尾，属于实际进展。本轮按原四格式目标继续检查Word超链接窗口，没有将范围缩为单一格式。产品仅修改 `src/docx-link-dialog.ts` 和 `docx.css` 的链接局部块：560px上限、28px控件、左标签右字段、固定标题/底部操作区、主体内部滚动，宽度遵守遮罩20px边距。错误增加中文无障碍名称与Tab入口，失败时滚入可视区而不主动抢输入焦点，保留URL供修正重试。原Link/Link URL定位名称、safeDocxLink规则、UTF16来源选区、只读/保存锁、过期选区拒绝、关闭及调用方回正文焦点保持；不改链接引擎、发布或下载签发协议。

新增来源选区回归在真实React+Tiptap插入区上验证不安全URL错误的键盘入口、滚动、输入/正文保持和纠正后精确写回。`/dev/shm/office-docx-link-error-red-20261112.log` 在缺少错误名称处失败；首命令误带额外 `run` 过滤词，执行3文件16条（1失败/15通过），不能称为仅执行链接文件。绿色改为精确 `./node_modules/.bin/vitest run src/docx-link-dialog.test.tsx`，`...-error-green-20261112.log` 5条通过，包含原4条Escape、不安全URL、动态只读、过期选区/卸载合同。没有运行或重复完整项目测试。

新增 `smoke/office-docx-link-{layout.mjs,component-smoke.mjs,verify.py}`。基线 `/dev/shm/office-docx-link-baseline-20261112/evidence.json`：initial/error/readonly/readonly-error×1440×900、768×720、320×640、640×360、390×320，共20场景，138条重复视口上的失败断言、0page/console error；退出0只代表基线收集结束。短屏长错误截图确认标题/字段被滚出可视区，没有固定区域和独立键盘错误入口。最终 `...-component-green-20261112/evidence.json` 原句柄12435退出0：20场景、70条真实Tab/Shift+Tab往返、50张截图、0失败/page/console error。检查窗口边界/水平垂直居中、标题/操作区与可滚动主体、左标签右字段、主题字体、28–32px高度、关闭SVG至少16px、五点命中、焦点环、首末Tab循环及错误至少一行可读，前后字段保持。长URL、长错误、只读保留值、错误后修正重试、Esc和入口回焦通过。apply/宿主可用性为显式回调夹具，不冒充真实选区或文件写回。

复用既有 `docx-hyperlink-smoke.mjs`，仅以 `DOCX_LINK_PC_LAYOUT=1` 增加本批布局和独立检查；沿用原真实新增/修改/移除场景。PC模式用实际HTTP附件下载，逐修订保存request/文件，成功保存目录禁止重放。资源仅对200响应读取正文，同时核对JS/CSS身份并收集异步核对错误，避免304正文误判；新增失败截图/回执。`office-docx-link-verify.py` 首次历史文件特征检查因lxml attrib.update不接受关键字参数而失败，改用字典后通过；该检查使用旧保存文件的副本，不能称为本轮浏览器下载。它独立构造预期XML，不调用产品检查器生成预期：新增/修改链接只允许指定rId/URL、Hyperlink字符样式和目标段已知xml:space规范化；移除后字符样式按现有引擎保留，不冒称恢复到源字符样式。核心属性仅允许revision和合法modified时间变化，其他正文/属性/关系及所有未修改ZIP文件必须精确一致。另对其他段落、其他链接tooltip、creator及styles分别故意篡改，4项全部拒绝，记录 `/dev/shm/office-docx-link-fidelity-mutations-20261112.json`，未放宽其它变化。

完整 `npm run build`：`/dev/shm/office-docx-link-build-20261112.log`，原句柄71160退出0，含TypeScript与Vite43.54s；`...-budget-20261112.log` 明确退出0，未提高阈值。保留既有依赖注释、混合导入、循环chunk、大chunk及字体运行时解析提示。最终manifest `9dc09d852e646d8ac13073cc63a13c22f32b87562ddb1031edecb9383bdd0b87`；实际 `engine_dir('doc')` 使用打包 `doc_engine/dist/edit-docx.mjs`，SHA `67f0f4c75eb677b9c896cedc81d36ce52e40aad3d1518f920038c4f0bd0cb2aa`，未改引擎。构建期间本批来源、smoke及Vite配置无变化。

最终 `/dev/shm/office-docx-link-built-20261112/evidence.json`、`independent-check.json` 和同名.log，原句柄57777退出0：insert/invalid-url/edit-saved×五视口，共15真实生产资源宿主场景、65条可用控件Tab往返、37张截图，0布局失败/page error/HTTP错误。组件20场景与此15场景属于不同上下文，不能当作35个独立功能。实际鼠标/键盘选中“经营收入100万元”，每次仅一个 `setParagraphLink`，UTF16范围严格为[3,12]；javascript URL拒绝、https创建、mailto修改、移除、undo/redo、刷新草稿和各修订重开通过。独立修订1→2→3→4共真实保存3次，每次实际HTTP下载，保存、下载、应答SHA及独立回读逐一一致，没有重放原成功保存目录。`office-docx-link-replay-guard-20261112.log` 单独验证重放在浏览器/引擎执行前拒绝，原证据文件逐字节不变，未再次执行真实保存。

真实Python薄桥/打包Node引擎与浏览器宿主均执行；授权/context/CSRF/preview模型/修订登记/保存应答是原有明确HTTP fixture，不代表生产授权、数据库或完整发布门禁。三个保存应答均返回 `validation.ok=false` 及“链接验收待复核，保留 Word 下载”，页面显示原因且照常下载，未标业务或完整版式验收通过。没有验证桌面Word实机或任意复杂来源对象。

来源36828字节、SHA `baa1e5e0c653031f949e80b3e598557a6ac1da3e7b6dfd28e31695e572fc40af`。下载修订2为37550字节、SHA `7dafd7b623e6992d76fe279b2fef9fc89d95fe1bfe4069cf6e02ca5331321374`；修订3为37548字节、SHA `72ddefd2eeeef93fd1ec40e1e5cee123a620f2de3198d27cd8f34a79b5314e05`；修订4为37525字节、SHA `0127b2b2ddb2dd6ae2963d742a4ed328afd620c06f865d0242a8acc00ef3e1a7`。ZIP健康、非目录部件集合相同；新增7个空目录单独记录。创建/修改仅document.xml、其关系和core.xml内容变化，移除后的关系原始字节回到来源，只有document.xml/core.xml变化。整个文档canonical比对覆盖目标段精确混合粗斜体、同段无样式链接及其tooltip、另一段原有链接/tooltip、页面/分节属性；其余部件原字节保持。已人工查看桌面窗口、390×320不安全URL错误与最终重开正文。

`source-verification.json` 重新核对149个实际200 JS/CSS资源SHA、manifest、引擎、三次精确操作/下载和原生入口闭包732模块来源SHA。清单来自 `/dev/shm/office-ui-inventory-docx-link-20261112/`，4452声明点，canonical Markdown字节一致，无须为局部结构模板重写同内容清单。数量不是功能总数、分母或完成率。构建后并行变化为管理端rule-fields源码/测试，以及新增management-linked-maintenance smoke；首次收尾断言据此停止，确认不属于原生闭包和本批smoke后只登记旧新SHA，未覆盖或重跑无关代码。本批产品/static/smoke在原运行句柄终态前保持冻结。三个JS smoke语法与本批 `git diff --check` 通过。

本轮专家附加检查具体落在错误可阅读且不抢焦点、只读时URL保留、长地址与短屏操作可达、真实来源选区精确性、同段其他链接不被附加样式、下载身份和校验器故障注入。四格式其余菜单/嵌套状态/外部依赖及完整功能逐项验收仍未穷尽，目标保持active；改动未提交、推送或部署。

复现须全新目录，从frontend运行：`TMPDIR=/dev/shm DOCX_TEST_DIST=../static DOCX_EXPECTED_MANIFEST_SHA256=9dc09d852e646d8ac13073cc63a13c22f32b87562ddb1031edecb9383bdd0b87 DOCX_LINK_PC_LAYOUT=1 DOCX_LINK_SMOKE_EVIDENCE_DIR=/dev/shm/office-docx-link-repeat node smoke/docx-hyperlink-smoke.mjs`。

## HTML 模板 UI 声明补全续批

本轮先接续未完成的模板盘点。`office-ui-named-region-red-20261112.log` 原进程已终止，7条中1条有效失败：有aria-label但无role的引用列表漏计，fieldset名称混入其子控件文字。仅在盘点工具补入命名区域选择器和直接legend文本优先级；产品运行时代码和static未在这一批修改。

`frontend/scripts/office-ui-inventory.mjs` 使用既有jsdom依赖，展开innerHTML及createModal content的静态片段，保留动态插值来源但不执行表达式、脚本或外部资源。schema2新增html-control与templates；line为模板表达式源码行、htmlLine为解析片段行，不冒称按钮精确源码行。声明名称只作静态标签/文本摘要，不是完整运行时accessible name。测试覆盖安全文本、实体、注释/脚本、动态表达式、状态属性、引用名称和命名列表。

最终 `/dev/shm/office-ui-named-region-green-20261112.log` 原句柄95800退出0，7条定向测试全部通过。生成原句柄80925退出0，目录 `/dev/shm/office-ui-template-inventory-final-20261112/`：732模块5093声明点，其中641个新增HTML控件/命名区域（XLSX237、PDF0、DOCX153、PPTX128、shared123）；141个模板写入点中53个有动态表达式。PDF主要直接创建DOM，0个新增模板条目不是无PDF组件。数字不是新增功能数、验收分母或整体完成率。

`verification.json` 确认732个当前源码SHA全部一致，移除html-control后与上一轮 `/dev/shm/office-ui-inventory-docx-link-20261112/inventory.json` 原4452声明逐项相同，无模块丢失。生成的inventory.md同步至 `NATIVE_OFFICE_UI_INVENTORY_20261112.md`；template-controls.md保存为 `NATIVE_OFFICE_UI_TEMPLATE_CONTROLS_20261112.md`，两者字节回读一致，全部641条仍为“待映射”，53处动态模板另列。历史已验收范围不因此自动判失败或通过。初次核验命令使用不可用的python未执行，改用python3成功，不将前者计为验证。两个脚本node --check通过。未重建前端、未重复完整测试，整体目标继续active。

## XLSX 高级筛选窗口 PC 续批

本轮先完成HTML模板盘点，再沿已确认的PC方向改进高级筛选。范围仍为固定源的单列一至两个自定义条件、AND/OR、保留其它列筛选和手动隐藏；没有新增Excel条件区域、复制结果、unique或新的筛选算法。产品改动主要为 `src/workbook-advanced-filter-dialog.ts` 与 `workbook.css` 末尾局部块：480px上限、28px控件、左标签右字段、宽屏运算符/条件值同行、窄屏对齐换行，固定标题/操作区及内部滚动主体。说明、范围、忙碌状态和错误有独立名称/Tab入口。提交时聚焦状态；失败后保留原条件，若仍在读状态则转到错误；校验错误滚入可见区而不抢输入焦点。原忙碌锁、禁止重复提交/关闭、Esc、取消及关闭回入口保留，不当作新增功能。

`office-xlsx-advanced-filter-baseline-20261112/evidence.json` 原句柄67751退出0，仅表示完成旧组件基线：5视口48项结构、尺寸、命中或居中问题，0保存。新增3条组件测试先在 `office-xlsx-advanced-filter-red-20261112.log` 有效失败、原3条通过；绿色 `office-xlsx-advanced-filter-green-recheck-20261112.log` 原句柄32397退出0，6条通过。初次绿色命令从错误cwd执行未找到vitest，不算通过。初次组合patch因CSS锚点不符而整体未应用，已回读两个目标确认未写入后拆分，未盲重试。

首组件浏览器轮次记录96项控件尺寸问题，实际是共享表单选择器优先级高于局部设置。调整局部优先级后，`...component-final-20261112` 在import时出现ERR_CONNECTION_RESET，尚无场景证据，不能算产品回归。随后为组件Vite进程保存完整日志并使用独立的/dev/shm缓存，不改生产Vite配置。`...component-final2-20261112` 原句柄55900退出0，20场景通过，但人工看图发现1440px宽屏条件值仍换行，原尺寸/命中断言不足。补充宽屏同行/窄屏换行几何断言，`...columns-red-20261112` 原句柄30423退出0、5场景记录1项有效布局失败；只修正输入框grid-column的局部优先级，没有放宽断言。

最终 `/dev/shm/office-xlsx-advanced-filter-component-final3-20261112/evidence.json` 原句柄1242退出0，initial/empty-error/busy/long-error四状态×五视口1440×900、768×720、320×640、640×360、390×320，共20场景、190条键盘记录、70张截图、0失败/console/page error。真正运行产品构造器与CSS，仅apply回调为可释放Promise；这只证明忙碌/失败/重试交互，不当作真实引擎或保存证据。保留首条件原样的“ A ”，两次回调输入相同；Esc忙碌时保持窗口，成功关闭回焦通过。人工已查看最终桌面、短屏长错误及生产窗口/重开画布截图，短屏通过内部滚动阅读，不声称所有字段同时显示。进程终态后只清理本批三份派生Vite缓存，源码、截图、日志与证据JSON保留，记录为freeze目录的cache-cleanup.json。

第一次 `npm run build` 原句柄92331退出2，TypeScript指出并行刷新入口在PDF/Word视图union上直接可选调用Word方法。参照同文件既有能力检测，仅在 `native-main.ts` 的refresh flush回调补 `view && 'flushPendingEdits' in view` 类型收窄；没有接管并行刷新功能。随后 `/dev/shm/office-xlsx-advanced-filter-final-build-20261112.log` 原句柄59773退出0，含TypeScript与Vite44.47s，预算日志明确退出0，未改预算。保留既有依赖注释、混合导入/循环chunk、大chunk和字体运行时解析提示。manifest为 `2f3d5846cbb6cdf122d35c250655707e7813b234e89c3634b1b6b1574b51162f`，实际workbook打包引擎 `dist/cli.mjs` SHA `b5c5146aaefe5bfac152fca9ccd24e7e3e6118d4f69dc6b61d22a77fed7d7488`，未改引擎。

生产宿主复用 `workbook-advanced-filter-built-smoke.mjs`，新增显式PC模式和manifest锁、同一布局检查、JS/CSS资源SHA核对、真实复杂文件fixture及严格独立保真校验。首次 `/dev/shm/office-xlsx-advanced-filter-built-20261112/` 原句柄52947退出1：AND初始/空条件10个布局场景均通过，随后1→2实际保存成功，但在下载前因测试夹具validation.issues误用字符串（真实接口为{code,message}对象）而失败，不能算告警展示通过。保留原回执、文件、失败页面与日志，没有重复保存该来源。修正夹具类型不改产品。新增只读复核模式要求每个场景已有回执，并在save路由强制拒绝；把既有AND来源、产物和回执逐字节复制至独立review目录，只读执行实际下载/重开。

首次AND只读复核原句柄71062退出1：新增fixture的D6保留0.00格式，公开Ctrl+C真实返回5.00，旧预期仍为5。将PC模式的三个相关预期改为精确5.00，没有解析数值或放宽字符串比较，也未删除源格式。最终 `/dev/shm/office-xlsx-advanced-filter-and-review-final-20261112/summary.json` 原句柄75835退出0，saveCount=0：既有AND产物实际浏览器下载、新修订身份/空草稿、画布可见行、改条件后Undo/Redo/再次Undo的草稿/已保存状态与精确复制5.00/10均通过；此目录不声称验证了首次错误夹具的告警展示。

`/dev/shm/office-xlsx-advanced-filter-or-built-20261112/summary.json` 原句柄26587退出0；`...text-built-20261112/summary.json` 原句柄3553退出0。分别覆盖无筛选确认创建OR（10→11）和文本equal/保留其它列条件/手动隐藏行（20→21），各实际保存一次。两份保存应答均返回validation.ok=false及“高级筛选版式待复核，文件已生成。”，界面显示具体原因，仍实际HTTP下载并重开新修订，没有标业务/版式验收通过。全批实际保存共3次（首次AND1次、OR1次、文本1次）；两个AND只读复核均0次，不以重新保存制造绿色结果。

最终三份成功summary合计25个生产资源宿主布局场景、275条键盘记录、50张布局截图、171个实际200 JS/CSS资源的SHA一致、page error为空；先前AND初始/空错误10场景只作阶段证据，不累计进这25个成功回执场景。组件20场景与生产25场景是不同上下文，不等于45个功能。条件值、草稿、Undo/Redo及刷新精确检查保持。真实Python native_office薄桥/打包引擎和HTTP附件执行；授权、CSRF、context、保存应答、修订登记仍为明确HTTP fixture，不代替生产数据库/授权/完整发布门禁或桌面Excel实机验收。

三个下载均与对应保存文件和应答SHA逐字节一致：AND来源7321字节 SHA `08bc8bcc86fa4ef23369170a4a18aa49956e1bd62d6fcab758af27b9c7b15dd6`，下载7362字节 SHA `ebf05531054996ee159d1a437ea521afe49cf053dfbbe038aa64bb0a0d006097`；OR来源7199字节 SHA `4e2517d9e2899000ceac6b1e7fdecc74f50fc6223dd98af1c292f53c6159ade6`，下载7284字节 SHA `bc08d6c3b89b8e7b469228fbbd01baaba0963f473f1d36f5c0453a32d7c22eeb`；文本来源7322字节 SHA `2b19ecbcf966ffe99285b48dd640b2474f2a8170f67de3f1dac9f1f77797e300`，下载7322字节 SHA `84d04f8b0c8987330acd982c483b83dab7a872db6637fe98ceed67acf9407465`。ZIP CRC及XML解析健康，非目录部件集合一致，仅sheet1.xml字节改变；去掉请求修改的autoFilter/row.hidden后canonical XML必须完全相同。openpyxl逐项比对单元格值/公式、字体/填充/边框/对齐/保护/数字格式、批注、超链接、合并区、列宽；另一张Keep工作表原字节不变。

`...and-review-20261112/verifier-faults.json` 原句柄69138退出0，校验器先验证真实产物，再拒绝范围外值、格式、批注、另一张工作表、行可见性、AND/OR六种故意损坏，实际保存文件未修改。`freeze-20261112/replay-guard.json` 证明对成功OR目录普通重跑在浏览器/引擎执行前退出1，32个原证据文件逐字节未变，没有再次保存。该故障注入只验证独立校验器及smoke保护，不冒充服务器安全或签发门禁测试。

收尾首次全源一致断言因后续并行改动停止，未盲重建/覆盖。`/dev/shm/office-xlsx-advanced-filter-freeze-20261112/source-verification.json` 分别记录已测manifest、171个资源、引擎、本批TS/CSS及最终smoke SHA，以及build后 `native-main.ts`、`binary-refresh.ts`、`pdf-main.ts`、`workbook-main.ts`、`slides-main.ts` 五文件旧新SHA。并行PDF句柄已新增flushPendingEdits，保留对方改动和本批防御性类型收窄。已测静态构建不因此变成后续刷新源码的运行验收；本批浏览器/构建原句柄终态前没有写本批产品、static或正在执行的smoke。

冻结运行清单为 `/dev/shm/office-ui-inventory-xlsx-advanced-filter-final-20261112/`；当前源码清单另从 `...-close-20261112/` 生成，734模块5104声明、644个模板控件、53处动态模板。当前模块逐文件SHA及两份canonical Markdown字节回读一致，已同步主清单与模板定位表。所有新模板条目仍为待映射，不根据标签/回调自动给通过；本批具体验证范围由以上证据限定。模块/声明数不是功能总数、验收分母或完成率。整体四格式目标继续active；未重复完整测试，未提交、推送或部署。

本批专家附加检查已具体落实为：人工图像复核补出自动检查遗漏；短屏提示可读与焦点不丢失；数据/格式/非目标部件精确保真；实际下载身份及新修订回读；验收告警非阻断；校验器故障注入与禁止重复保存。其余菜单、嵌套状态、动态模板、外部引擎UI及完整四格式功能仍需继续逐项验收。

对上述五个并行源码差异追加一次最新 `tsc --noEmit`，原句柄14131明确退出0，日志 `/dev/shm/office-xlsx-advanced-filter-close-typecheck-20261112.log`；最新734模块在检查前后的收尾SHA一致，两份canonical Markdown字节一致。此检查只证明当前类型兼容，不把冻结浏览器运行扩大为后续刷新逻辑的运行验收。两个盘点脚本、三个smoke脚本node --check及本批git diff --check通过，未再次运行完整测试或重复构建。

## XLSX 合并计算窗口 PC 续批：八模式与文件闭环

本批范围是 `workbook-consolidate-dialog.ts` 与 workbook.css 末尾专属样式。沿用原生窗口/同步 apply，不添加虚假异步进度，不改汇总算法。窗口上限520px，28px紧凑控件、16px复选框；固定标题和底部操作，中部滚动；引用与添加宽屏同行/窄屏换行，引用列表内部滚动。说明、输出范围、引用计数、错误及引用列表有明确阅读名称/Tab入口。删除后聚焦同位置下一项、末条退前项、删空回输入；错误揭示到可视区并保留输入。保持未添加引用也参与提交、去重、标签函数限制、Esc/关闭回焦和目标身份检查。

组件前后证据为 `/dev/shm/office-xlsx-consolidate-baseline-20261112/` 与 `...component-20261112/`：基线5个状态/视口组合记录38项问题；改后25组合、560条焦点记录、无失败。4条定向窗口测试原句柄4879退出0；保留 `/dev/shm/office-xlsx-consolidate-{red,green}-20261112.log`，没有因续批而重复已通过的窗口测试。组件apply是同步夹具，不作为公式引擎/保存证据。人工图像复核确认长列表内部滚动和短屏错误可读。

新增 `smoke/workbook-consolidate-built-smoke.mjs`、`office-xlsx-consolidate-fixture.py` 与操作说明。根分区一度仅3MiB，因此构建放 `/dev/shm/office-xlsx-consolidate-build-20261112/`，没有覆盖项目static。沿用vite.config.ts分包、插件及源码处理，仅重定位outDir/cacheDir，运行时复制插件替换为复制既有static的licenses/pdfjs资源。`...freeze-20261112/build-method.json`明确边界。原句柄73159退出0：最新tsc通过，Vite42.71秒；393个JS包通过现有体积预算函数，未提高预算。隔离manifest SHA `058a23d7e0f49111657aa4fdca342d44206d10327dc0437c8f5b2d2a735f7745`；项目static仍为上批manifest `2f3d5846cbb6cdf122d35c250655707e7813b234e89c3634b1b6b1574b51162f`，不冒称已更新或部署静态资源。

首次真实构建宿主运行原句柄88134退出1，保留 `/dev/shm/office-xlsx-consolidate-built-20261112.log`、原始失败HTML/截图、实际来源、下载、保存回执及 `modes.json`。退出前完成全部八模式：按位置SUM/COUNTA/AVERAGE/MAX/MIN分别得[12,24,6]/[2,2,1]/[6,12,6]/[10,20,6]/[2,4,6]；左列Ada/Bob/Cara三模式SUM/COUNTIF/平均分别得[8,14,20]/[2,2,1]/[4,7,20]。共33目标单元格，经真实Ribbon、定位、窗口、Ctrl+C精确读值、每步Undo/Redo草稿比对及刷新回读；E1保留0.00并精确复制12.00。标签写入H1替换原=99公式。空引用错误与18引用长列表各五视口无失败，取消不产生草稿；这些初始阶段只保留日志和截图，不把后续只读运行覆盖后的layout.json冒称为初始详细焦点回执。

实际保存1→2仅一次，HTTP附件下载与回执/保存字节一致。首次失败是校验器要求所有公式有缓存，实际E1缓存为空。追查 `workbook-vendor/core/session-core.ts::diffToEdits`确认既有保存策略将公式value置null；保存回执同样为null，文件写出公式而不写v，并非下载错文件。来源与下载均保留fullCalcOnLoad=1。修正独立校验器为：非空缓存必须准确；缺失缓存要求打开重算且非manual；仍要求新修订公开界面逐项实际重算正确。没有修改产品保存策略，也没有向文件填入测试预期值。严格要求完整缓存的首次失败不删除、不包装成通过。

只读复核原句柄96317退出0，日志 `/dev/shm/office-xlsx-consolidate-review-20261112.log`，最新回执 `...built-20261112/summary.json`：saveCount=0，171个实际200 JS/CSS资源与隔离构建SHA一致、page errors为空；已保存文件全部八模式公开复制正确，新修订2身份/源SHA/空草稿/已保存状态正确。重开窗口5视口、55条焦点记录、10截图无失败。首次运行的10个阶段布局只有日志/截图，不与此详细回执合成新的完整成功运行。组件25组合也不与生产回执混算功能数。

来源7889字节 SHA `0cb4e9086e88a0912a157c93fc8c890d1877f3cd49b0a5ecdc65098fc922441d`，实际保存/下载8041字节 SHA `c3d8b3c427a730c44b2349770991c11bbb37937114eb67cd3a69f3fce60a9765`。`independent-check.json`核对33个目标公式/标签、9个文字值，明确记录24个公式缓存缺失并要求重算；不声称有完整公式缓存。ZIP CRC/XML健康、部件集合相同，仅sheet1.xml字节变化；恢复33个已核对目标单元格后canonical XML必须与原文件相同，并单独验证目标单元格样式/身份属性。两个来源表字节不变，范围外公式、批注、超链接、合并区、命名区域、行高列宽、冻结、样式等由严格非目标XML/部件相等覆盖。

`initial-save-warning-evidence.json`从首次真实失败HTML提取具体“合并计算结果版式待复核，文件已生成。”反馈并记录HTML SHA：应答validation.ok=false且告警结构正确，仍成功下载；没有标业务/版式验收通过。`verifier-faults.json`阳性对照通过，错误公式、错误非空缓存、缺重算标记、manual计算、目标样式、非目标值、来源表值、合并区、批注九种故意损坏均被拒绝，原保存文件不变。`...freeze-20261112/replay-guard.json`原句柄86929退出0，普通重跑在浏览器/引擎前退出1，64个既有证据文件逐字节不变，没有再次保存。临时故障注入与重放保护只证明校验器/smoke行为，不代替生产服务端安全或签发门禁验证。

构建前冻结清单 `...office-ui-inventory-xlsx-consolidate-frozen-20261112/` 与收尾 `...-close-20261112/` 的734模块SHA完全一致，5107源码声明、647模板控件、53动态模板。`...freeze-20261112/source-verification.json`记录配置、锁文件、产品TS/CSS、smoke、布局helper和真实保存引擎SHA；唯一后续差异为已明确修正的测试校验器，修正发生于原句柄终态之后。引擎SHA仍为 `b5c5146aaefe5bfac152fca9ccd24e7e3e6118d4f69dc6b61d22a77fed7d7488`。主清单与模板定位表已同步当前源码并字节回读，两表仍是声明定位而不是完成率，所有模板运行映射仍需逐项审计。

本批专家附加工作落在可验证结果上：长列表/短屏阅读与键盘焦点；Undo/Redo及刷新一致性；实际下载身份、新修订重算和非目标保真；验收告警非阻断；校验器故障注入；失败产物保留与禁止重放成功保存。HTTP身份/授权/CSRF/修订登记和保存应答仍是fixture，真实执行的是构建宿主、Univer、Python保存薄桥/引擎和HTTP附件。未声称桌面Excel实机、生产数据库/授权或完整发布门禁通过。整体xlsx/pdf/docx/pptx穷举目标继续active，未重复完整测试，未提交/推送/部署；远端拉取HTTPS及SSH超时，不能认定当前HEAD为远端最新。

## PPTX 背景格式窗口 PC 续批

本批补充前述图表/图片属性之外的“背景图片/设置背景格式”窗口。`slides-main.ts::openBackgroundImageDialog`仍使用旧dialog.showModal路径，未接已有`showSlidesSettingsDialog`；无标题关闭，原生cancel清理未覆盖，checkbox被通用样式拉到34px。新增真实编辑器回归，初次7项中5失败、2通过，`/dev/shm/office-pptx-background-red-20261112.log`原句柄62179退出1。再把异步阶段拆开，以实际dirty状态而非仅spy调用作主断言，`...background-async-red-20261112.log`原句柄11857退出1，选图返回后窗口已关闭、解码完成后窗口已关闭均从“可编辑”错误变为“有未保存修改”，重复点击另复现两次选图。三个失败独立存在，不把后一问题藏在前一断言之后。

最小产品改动限于原函数和slides.css末尾背景窗口块：复用既有设置dialog的关闭/焦点trap与入口恢复；标题、可滚动body、footer分开；520px桌面窗口、左标签右字段、28px选择/操作、16pxcheckbox，窄屏保持紧凑排布。错误和真实选图状态有中文名称及Tab阅读入口。选图等待时禁用重复确认/重置与设置字段，取消和标题关闭仍可用；两次await后均检查dialog.open/isConnected，防止已取消的异步结果落入草稿。保持原来的图片字节、拉伸/平铺、四种渐变方向、隐藏背景图形、应用全部、重置、目标身份/草稿检查及提交数据结构。未改变绘图/保存算法或共享设置辅助函数。

`...background-green-20261112.log`原句柄58606退出0：新增8项与既有slides-main 21项合计29项定向测试通过，含三个关闭路径、两个异步取消边界、禁止重复选图、渐变/全部页面/隐藏图形的原保存字段。没有重复完整项目测试。jsdom原生dialog与选图/解码依赖是明确mock；真实浏览器另测取消后选图返回，但不冒称实际长时间解码取消或系统文件选择器性能验收。

真实旧构建基线 `/dev/shm/office-pptx-background-baseline-20261112/` 原句柄46773退出0，仅代表记录完成，saveCount=0；图片/渐变×五视口10场景记录124条失败检查，不是124个独立产品缺陷。人工短屏截图可见checkbox放大且标题滚出。首次新构建 `...background-built-20261112/` 原句柄14710退出1，10场景仅剩关闭按钮五点命中失败，0保存。曾推测标题层级覆盖并加局部z-index，第二构建 `...background-final-built-20261112/` 原句柄78032仍以同样10项退出1，0保存；两份失败均保留，没有放宽尺寸/焦点断言。

专门真实浏览器诊断 `...background-hit-diagnostic-20261112/close-hit-diagnostic.json` 原句柄29640退出0：关闭按钮28×28px、圆角8px，中心及圆角内四点均命中，原包围盒右下角2px点落在HEADER；移除z-index后结果完全相同。原层级判断不正确，已撤回这条无效产品样式。布局检查器按圆角半径选择内部五点，保存具体坐标/命中；仍检查实际尺寸、字体、焦点环、Tab循环、窗口边界与标题/底部滚动位置，未把按钮改方来迎合错误检测。最终产品源码恢复为第一新构建的逐字节版本，因此直接复用已构建资源，未做第三次无必要构建。

隔离构建位于 `/dev/shm/office-pptx-background-build-20261112/`，manifest SHA `be236e5dc472580bafe895fac949fe24c8954eb33809aeecd17665c99c02be40`。原句柄69391退出0：最新当时tsc通过、Vite43.64秒，393个JS包通过现有预算，slides-main为241739字节。仅重定位输出/cache并将运行时复制插件替换为复制既有licenses/pdfjs资源，沿用源变换和分包；没有覆盖项目static，static manifest仍为`2f3d5846cbb6cdf122d35c250655707e7813b234e89c3634b1b6b1574b51162f`。第二z-index诊断构建原句柄43940退出0、Vite42.90秒/预算通过，但不是最终验收构建。产品/config/锁文件/桥包与第一新构建snapshot一致断言在最终浏览器启动前通过，记录于`...freeze-20261112/verified-files.json`。

最终真实构建宿主 `/dev/shm/office-pptx-background-verified-built-20261112/evidence.json` 原句柄84629退出0：六状态（image/gradient/invalid-image-error/pending/reopened-image/reopened-gradient）×五视口30场景、240条焦点记录、60张截图，failures为空。宽/窄/短屏窗口居中、固定标题底部、正文内部滚动、字段/按钮实际尺寸/字体、圆角内五点命中、Tab正反循环及输入/草稿保持均通过。人工补看PC渐变、390×320无效图片错误与重开渐变截图。短屏上方字段随body滚出是内部滚动，标题与底部不移动，不声称所有字段同时可见。

实际UI取消、Esc、标题关闭均恢复入口且草稿不变；真实filechooser等待中关闭窗口后再交付PNG，草稿仍不变；无效PNG揭示具体错误后可重试。真实图片字节选入全部三页并平铺/隐藏背景图形；再对第二页设置#FF8800→#004488、45°渐变并恢复显示背景图形；第三页重置到版式背景。每步Undo/Redo精确比对草稿，刷新后全部操作精确恢复。实际Python原生patch/打包Node引擎只保存一次修订1→2，HTTP附件/browser download及新修订重开通过；保存应答validation.ok=false与“背景版式待复核，文件已生成。”具体告警仍可下载，见save-warning.json，不标业务/版式验收通过。

独立 `independent-check.json`：来源 SHA `5f2277f638610d98da8fc2dd96ce538179a4b2d55303ea5eba9e2a8171fb7a3e`，保存/下载 SHA `3d48aed294d2c55592d1b0c85b6a6395da8b072277f6e1d277aace5435578a08`。ZIP CRC/XML健康，未删除部件；仅三个slide XML及slide1.xml.rels变化，新增唯一`ppt/media/image2.png`与上传PNG原字节相同。核对平铺关系目标、两色停止点、角度2700000、第三页无自有背景及三页showMasterSp为0/1/0；删除请求变更的背景节点/图形显示标记后，三个slide canonical XML与来源精确相同；删除新增图片关系后关系XML精确相同。正文、对象几何、讲稿、链接、原媒体、母版、版式及其他部件保持，下载身份与新修订context一致，新修订草稿为空。未验证桌面PowerPoint实机或初始preview.pdf转换（明确204回退）。

新增 `office-pptx-background-verifier-faults.py`，原句柄17394退出0：阳性对照通过，平铺模式、渐变颜色、渐变角度、重置背景、背景图形标记、正文、对象几何、讲稿、链接、背景媒体十种故意损坏均拒绝，原下载SHA不变。`...freeze-20261112/replay-guard.json`证明普通重跑在浏览器/引擎前退出1，73个原证据文件逐字节不变，没有再次保存。这些是独立文件校验器/smoke测试，不扩大为服务器安全或完整发布门禁证明。

141个实际200 JS/CSS资源逐一核对隔离磁盘SHA/大小；page/console/HTTP错误和route异常为空，配置/本批产品/CSS/smoke及真实桥包在各次运行期间保持冻结。本批桥包SHA为edit-pptx `6d4bae9b0bd649277632a4d927a4571e9c41cc5f1766e7c0acff73b2c659452c`、render-pptx `4fd9061aca988f83794ee246227546f8fd46af9fe93a47475be0d9ebb3707592`。HTTP身份、授权、CSRF、上下文、修订登记和应答是显式fixture；不代替生产鉴权、数据库或全发布链。窗口交互/文件保真证据不据此扩展为真实用户/AI/外部连接器全功能验收。

收尾首次全源一致断言发现共享工作区另外四个源差异而停止，未覆盖对方修改或盲目重建：native-main.ts、native-pdf-form-ai.ts、native-pdf-review.ts、pdf-main.ts。source-verification.json记录冻结旧SHA/当前SHA与mtime，并明确隔离manifest时间及浏览器回执时间；本批10个产品/config/桥包/smoke路径仍与最终运行相同，141资源身份也相同。当前734模块源码盘点为5108声明、648模板控件、53动态模板，canonical两表从`/dev/shm/office-ui-inventory-pptx-background-close-20261112/`同步并字节回读；当前清单不是上述四文件新行为的运行验收，数量不是功能总数或完成率。新增最新tsc检查结果另记，不把类型检查扩大为运行证明。

本批专家额外检查具体落实为：取消和两个异步边界无副作用、禁止重复提交、故障后可重试、真实圆角命中而非错误矩形启发式、短屏键盘阅读、历史/刷新一致性、背景图片原字节和非目标保真、验收告警可下载、校验器故障注入与禁止重放已保存来源。整体四格式穷举目标继续active，未提交/推送/部署，未重复完整测试。

对收尾四个并行源差异追加一次最新 `tsc --noEmit`，原句柄86635明确退出0，日志`/dev/shm/office-pptx-background-freeze-20261112/close-typecheck.log`；只证明当前类型兼容，不扩大为这些后续源的运行验收。两个JS脚本node --check、两个Python脚本AST解析及本批git diff --check通过。

## XLSX 允许用户编辑区域 PC 续批与保护撤销保真

上一目标轮已取得实际进展；本轮先完成用户要求的拉取，再继续原四格式目标。`git fetch --no-auto-gc origin` 成功，`git merge --ff-only origin/code` 返回 Already up to date，HEAD/origin/code 均为 `3b4ff524a402936a7c92fd38982824f8721dc120`，ahead/behind为0/0。未覆盖其他会话改动，未提交、推送、部署。

### 窗口和专家交互检查

- `workbook-editable-ranges-dialog.ts` / `workbook.css` 局部增加600px PC窗口、28px控件、左标签右字段、固定标题/底部和内部滚动；窄屏字段换行。说明、状态、错误为具名键盘阅读区，繁忙时焦点移到状态，失败后揭示并聚焦具体错误，保留输入以便重试。
- 新增区域直接进入名称编辑；删除后移到下一项名称、前一项名称，删除全部后回新增按钮。删除按钮有逐项名称，区域计数及时更新。取消、Esc、标题关闭均不提交定义并回入口。
- 打开时复制工作表/选区/范围快照，调用方之后改变对象不会把定义提交到另一个工作表。带密码/权限的范围保持只读，原因可聚焦阅读，不改权限规则或写入协议。
- 初始6项专项测试5失败1通过：`/dev/shm/office-xlsx-editable-ranges-red-20261112.log`，句柄35668 exit1；失败分别为新增回焦、删除回焦、快照目标、繁忙阅读、只读阅读。修复后新旧窗口和范围权限3文件11项通过：`/dev/shm/office-xlsx-editable-ranges-green-20261112.log`，句柄46315 exit0。
- 浏览器初始5场景30条失败断言：`/dev/shm/office-xlsx-editable-ranges-baseline-20261112/evidence.json`，句柄90368 exit0只代表基线记录完成，`ok=false`。人工查看390x320截图确认滚到底后标题/关闭一起滚出。
- 第一轮组件修复发现非桌面宽度的通用输入选择器仍将字段撑到36px，局部提高选择器针对性后修复。最终组件夹具 `/dev/shm/office-xlsx-editable-ranges-component-fixed-20261112/evidence.json`，句柄27567 exit0：默认、7项长列表、繁忙、长错误、工作表受保护、密码范围只读六状态×五视口=30场景，失败及浏览器错误为空。apply边界为可释放Promise夹具，不当作真实权限/保存验收。五点命中位于真实圆角内，保留坐标与命中结果。人工检查PC长列表和390x320长错误截图。

### 真实宿主发现并修复保护撤销缺陷

- 第一实际宿主检查使用可访问角色定位弹窗；宿主在apply时设置inert，角色暂时从可访问树移除，脚本误以为窗口已关闭。`...editable-ranges-diagnostic-20261112/defined-draft.json`当时为空，随后`failure-storage.json`却包含正确定义，证明是等待条件错误。脚本改为原始节点`hidden=true`且宿主解除inert，未为此改变产品。
- 继续检查保护Undo，真实草稿出现未请求的`frozenColumns:0`。独立真实sheets栈探针证明B2两轴冻结可以重复加载，根因为保护操作调用markDirty后被标为网格修改，Undo误走Univer历史，撤销加载时的冻结列命令。
- `workbook-main.ts` 仅在工作表/工作簿保护元数据变化后将历史路由标为原生草稿；原生Undo可等待尚在采集的dirty草稿。没有全局改写网格Undo、冻结协议或保护权限。
- 失败证据：`office-xlsx-protection-history-isolated-red-20261112.log`，句柄62610 exit1，sheet/workbook两项均复现；`office-xlsx-protection-immediate-red-20261112.log`，句柄30902 exit1，保护后立即Undo未恢复。
- 修复后 `workbook-main-protection.test.ts`13项加冻结加载探针1项=14项通过：`/dev/shm/office-xlsx-protection-history-green-20261112.log`，句柄44514 exit0。包含现有受保护值/公式、表头权限、表格筛选保存、验收失败照常下载等回归；已有getSnapshot弃用提示仍存在，不称输出零告警。

### 最终构建与真实文件闭环

- 最终隔离构建 `/dev/shm/office-xlsx-editable-ranges-final-build-20261112/`；句柄37934 exit0，`tsc --noEmit`通过，Vite42.57秒，393个JS包预算通过。manifest SHA256=`494a32ce87c94dbd42446adcf716eac20980e761e5b13afa5fd102713635789e`。
- 只覆盖outDir/cacheDir及运行时资源复制目的地，沿用原分包和源变换；项目static未覆盖，原manifest SHA仍为`2f3d5846cbb6cdf122d35c250655707e7813b234e89c3634b1b6b1574b51162f`。本轮产品历史修复前构建manifest为`18f0...4751`，不可替代最终构建。
- `/dev/shm/office-xlsx-editable-ranges-verified-final-built-20261112/`保留实际保存与下载。初次句柄46634 exit1在下载后独立XML检查失败，但已经保存一次且下载成功，未重跑创建修订。`steps.json`记录定义、保护、允许值、允许公式四步精确Undo/Redo；源修订1刷新恢复通过；范围外A2输入仍为locked；密码范围只读；`save-warning.json`记录saveCount=1、具体失败原因“允许编辑区域待人工复核，文件已生成。”和可用下载链接。
- 初次文件校验失败是夹具OOXML顺序错误：旧来源把protectedRanges插在hyperlinks之后，引擎正确移至sheetData/保护之后。保留原始来源/下载不动；新夹具按规范插入，校验器独立检查目标内容和规范顺序，再移除两个已核对的目标节点比较范围外XML。故障注入也检查保护权限，未放宽到忽略目标内容。`failure.json`及初次日志为历史失败证据，不能称其为最后一次运行失败。
- 只读复核句柄10033 exit0：`/dev/shm/office-xlsx-editable-ranges-review-20261112.log`及原目录`evidence.json`，`reviewOnly=true,saveCount=0`；实际浏览器/HTTP下载与新修订2重开通过，172个实际200 JS/CSS与最终构建SHA一致，页面/console/HTTP异常为空。重开值42、公式SUM结果45、保护正确；在新修订草稿暂时撤销保护回读三个定义，再Undo恢复空草稿，不保存。
- 初次保存前20个实际宿主布局场景在初次日志中完整记录：初始、重复名称错误、刷新回显、密码只读各五视口，均0失败，40张截图保留。只读复核重新写入的`layout.json`/`evidence.json`只含重开定义5场景、75焦点记录、10张截图；**不能把其结果数组/布局数声称为初次20场景或四步编辑的回执**。初次步骤在`steps.json`，保存结果在`saved.json`，初次布局细项JSON已由只读复核覆盖，日志和截图仍保留。人工查看重开PC/短屏截图。
- 独立`independent-check.json`通过：来源SHA=`3ae13fe2ba9a0131ed8412a1e4dd8d72ca7eeac41f134757048779b90bce6b83`；保存/下载SHA=`ce11fa3f1ac9cb41796a43cc8a5d8755629c3bc625be3a7de16e38c6388d33ab`。仅`xl/worksheets/sheet1.xml`改变，核对三个范围（含并集/新增/删除）、默认保护权限、B2=42、E2公式；移除已核对目标范围/保护、恢复两目标单元格后，其余canonical XML精确相同。B2冻结、几何、批注、链接、图表、样式、名称、其他工作表/密码保护和其他全部部件保持。ZIP CRC和XML健康。
- `office-xlsx-editable-ranges-verifier-faults.py`阳性对照通过，12种故意损坏全部拒绝：扩大区域、错误名称、删除项重回、取消保护、修改保护权限、目标值、目标公式、非目标样式、链接、批注、图表、其他工作表保护。故障脚本首次将ZipInfo对象直接传入新ZIP写入器，导致内存CRC被修改；已复制ZipInfo后修复，原文件未改。最终`verifier-faults.json`通过；没有新修订。
- 普通重放保护提前exit1，66个已有证据文件逐字节不变：`/dev/shm/office-xlsx-editable-ranges-freeze-20261112/replay-guard.json`，不启动浏览器/保存桥、不重复保存。
- HTTP身份、授权、CSRF、上下文、修订登记和保存应答均是明确夹具；Python patch/Node桥、构建宿主、网格、下载字节与重开为实际执行。不称生产数据库、完整发布门禁、PDF转换或桌面Excel实机通过。真实保存桥`workbook_engine/dist/cli.mjs` SHA=`b5c5146aaefe5bfac152fca9ccd24e7e3e6118d4f69dc6b61d22a77fed7d7488`，Python入口/桥身份在freeze目录`save-bridge.json`。

### 清单、证据冻结与范围

- 本轮一度因根分区0可用导致新增探针测试写入失败；读回确认为0字节。确认无Vite进程/无打开句柄后，将2026-11-11遗留`node_modules/.vite/deps_temp_2b367f01`缓存移到freeze目录保存，恢复空间后写入完整测试。未删除用户源文件/证据，构建/截图继续使用/dev/shm。
- 最终1428个源码/配置/锁文件SHA在构建前后及第一次收尾检查一致，记录于`freeze/final-verification.json`。追加审计后再次检查，其他会话开始修改管理端：先发现`src/management/app.test.tsx`，随后记录到7个`src/management/`文件（含contracts、ConfigurationWorkspace、source连接构建/详情/编辑/列表）。旧/新SHA及mtime分别记入`close-source-differences.json`和`close-source-differences-latest.json`。原生入口清单734模块、本批产品代码、配置/锁文件和Python保存链/Node桥仍一致；管理端新变化未做运行/类型验收，不回滚他人修改。
- 清单重新生成 `/dev/shm/office-ui-inventory-editable-ranges-20261112/`：734模块、5110声明点、650模板控件、53动态模板。所有清单模块SHA核对匹配，canonical inventory/template-controls同步并逐字节读回。这些数不是功能数或完成率。
- 本批累计定向测试25项（11窗口/权限+14保护/冻结），未重复完整项目测试。操作/布局/文件/故障注入是不同证据，不能相互替代。复现命令与边界见`frontend/smoke/office-xlsx-editable-ranges-smoke.md`。
- 四格式全部组件、动态菜单、状态组合和桌面实机尚未穷尽；整体目标保持active，不因本批通过标记完成。


## PDF 添加链接窗口 PC 续批与链接文件保真

上一回合按用户要求执行远程代码同步，fetch 与快进核对后 code/origin/code 同为 `3b4ff524a402936a7c92fd38982824f8721dc120`，本地改动保留；这提供了当前代码基准。本回合继续完整 XLSX/PDF/DOCX/PPTX 目标，不把本专项或源码声明清单当成全量完成。

### 需求与局部修改

核对旧审计后确认：链接窗口已有基础设置主题，但缺少标题关闭、固定标题/底部操作区、可键盘进入的说明及错误区、关闭回焦。只修改 `frontend/src/pdf-main.ts` 的链接构造/关闭/校验与待定区域身份，及 `frontend/src/pdf.css` 的 `.pdf-link-dialog` 局部样式。560px PC 窗口、28px紧凑输入/按钮、主题颜色与焦点环，主体滚动，窄屏字段纵排；正文说明网址/页码互斥及草稿/保存区别，页码输入关联当前页数说明。

标题关闭、取消和原生 Escape 统一 close 后清除待定区域并回到链接 Ribbon 入口；入口隐藏时沿用现有当前标签回焦逻辑。错误保留输入/区域并聚焦可滚动的具名 alert。新增打开时草稿快照及 PDF 实例身份，提交时核对保存/只读/预览/打印/关闭/实例/快照，防止过期几何提交。保留原 URL scheme/2048长度、www转https、页码互斥及按源页索引绑定目标的行为。未改 PDF 引擎、发布/验收链路或下载协议。

### 专家额外检查与定向测试

本批将“好看”扩展到已授权的可用性和保真：真实取消不得留隐形待定区域、焦点不得落到背景；键盘必须能到达说明/错误；非法输入不丢数据；Modal期间异步保存/草稿变化不能误提交；文件链接正确不等于宿主已有点击层。新增 `src/pdf-link-desktop.test.ts` 使用实际 createPdfEditorView/NativeDraft，PDF.js与浏览器原生API为显式jsdom夹具。

`/dev/shm/office-pdf-link-red-20261112.log` 句柄55087退出1，8项中7失败1通过，分别暴露结构/关闭回焦/错误焦点/保存中与草稿变化误提交。最初命令误用不存在的python，测试文件尚未创建导致No test files found，该输出不算有效RED；更正python3后取得上述真实断言失败。`office-pdf-link-green-20261112.log` 句柄57040退出0：link桌面8项、object host44项、operations17项，共3文件69项通过。未重跑完整测试集。

### 构建与浏览器证据

`/dev/shm/office-pdf-link-freeze-20261112/source.json` 冻结1580个src/config/lock文件，构建前后及收尾 differences=[]。第一次冻结脚本cwd路径错误，修正后完整记录，不采用空记录。TypeScript句柄14451退出0；隔离Vite句柄72831退出0、43.36s，沿用原plugins/分包（只将runtime资产复制重定向隔离输出），393个JS包预算通过。最终构建 `/dev/shm/office-pdf-link-build-20261112/`，manifest SHA `41542d32671caaf2de70cd4707495fc0b1da38694e4acc00d5358b362080a64f`。项目static manifest与冻结值相同，无覆盖或部署。

基线 `/dev/shm/office-pdf-link-baseline-20261112/` 使用上一冻结构建 `494a32ce…`，句柄75453退出0，仅记录初始5视口30条失败，不保存。基线原始简单PDF与最终富内容PDF不同，不能把窗口布局对照称文件保真前后对照。

首轮新构建 `/dev/shm/office-pdf-link-built-20261112/` 句柄5066退出1：20布局已过，但脚本错误地等待链接操作不需要的隐藏预览确认框；同时隔离构建复用旧static/pdfjs缺少qcms_bg.wasm，3个404。实际宿主预览已显示，未发起/api/save，未生成save回执。修正smoke按现有PDF_REVIEW_KINDS处理链接不强制确认的契约；仅修复隔离输出，复制当前pdfjs-dist的cmaps/standard_fonts/wasm共198资产，逐文件SHA记录pdfjs-runtime.json，保留该失败证据，不改产品协议。

最终 `/dev/shm/office-pdf-link-verified-built-20261112/` 句柄81364退出0，initial/invalid-url/long-url/invalid-page/reopened五状态×1440×900、768×720、320×640、640×360、390×320，共25场景、165次Tab/Shift+Tab回返及控件测量、50张窗口截图。窗口/横向溢出、字体/28px控件、焦点环、圆角内五点命中、滚动后标题/操作可见通过，输入和草稿在各布局检查前后不变。人工查看PC初始及390×320错误截图。51个实际200 JS/CSS/wasm响应逐字节对隔离磁盘身份一致；page/console/HTTP异常空。

真实取消/标题关闭/Escape清空未提交区域并回焦；javascript scheme、超2048网址和越界页码不入草稿，具体错误聚焦且值保留；www/邮件/页内三个链接的互斥和目标正确。Undo/Redo/刷新精确恢复3项。预览appliedOperationIndices=[0,1,2]、skipped=[]。实际授权、CSRF、PDF打包桥、发布、HTTP下载与重开，内存修订仓储为明确夹具，不称生产DB/桌面Acrobat实机验收。仅保存一次 revision4→5，原来源摘要保持；validation.ok=false，具体返回 `native_source_review_pending`（业务事实与完整版式尚未重新核验），下载照常签发。下载SHA/长度匹配回执，重开当前PDF的实际/api/file字节与下载相同；重开草稿为空，不再次保存。

### 独立文件检查与检查器反例

`.venv/bin/python frontend/smoke/office-pdf-link-verify.py`（从仓库根以完整smart_reporting/report_editor路径执行）只读已有source/download/save回执，最终退出0。原6454字节SHA `956410409d4a12fa373e6fdd73b8dae982a649e81a6702a6a87acf65502e0aa1`，下载7305字节SHA `b556218454ea73b93cf7aab9cb8f83871a1937c307ed4d373a468475f7607632`。PyMuPDF/pypdf独立读得网页 `https://www.example.com/report?year=2026&kind=office`、邮件 `mailto:review@example.com?subject=Report` 和第3页，区域在0.001内匹配请求。原有链接/便签、图像资源、用户元数据、目录、正文内容流、页框/旋转/表单集合保留，全部三页渲染像素相同。

初始独立元数据断言把PyMuPDF派生的format（PDF头）也当用户元数据，发现原序列化器将1.3写为1.7。核对其余全部元数据相同后，改成分别严格断言头版本1.3→1.7与用户元数据相等；此变化明确记录，不隐瞒也不重存原文件。`office-pdf-link-verifier-faults.py` 最终退出0：重序列化正例通过，网页/邮件目标、页内目标、扩大矩形、原链接删除、原便签改文、标题、目录、裁切、正文流、图像资源11种损坏分别触发对应语义断言。故障注入跳过签发摘要核对，只验证内容守卫；原下载常规校验仍核对SHA/大小。反例生成最初pypdf默认头版本不同，正例即失败，显式保留1.7头后通过；未修改原始文件或回执。

复跑防护 `freeze/replay-guard.json`：同目录普通重跑在mkdir处退出1，服务/浏览器/保存前拒绝，68个既有证据文件SHA全部不变。源码清单重新生成并逐734模块SHA核对，仍734模块/5110声明/650模板控件/53动态模板；两份canonical清单字节回读相同。数字不是功能数量或验收完成率。

### 尚未完成与边界

本批没有声称浏览器宿主支持保存后点击链接：当前尚无已保存链接的点击层。文件目标由独立读取器证明、宿主重开身份由实际接口证明；点击跳转交互仍为后续功能缺口。全量四格式UI仍需继续按组件与状态核对，第三方运行时、动态菜单和桌面实机不在本次源码枚举的穷尽证明范围。整体目标保持active。

## PDF 已保存链接点击层、焦点可见性与旋转几何续批

### 需求与修改

接续上批明确记录的“文件有链接、宿主无点击层”缺口。新增 `frontend/src/pdf-saved-links.ts`，复用锁定版本 PDF.js 原生 AnnotationLayer，只接入合法 http/https/mailto 与文档内目标；禁用脚本、表单和其他动作。外链真实 a 元素使用 `_blank`、`noopener noreferrer`，具名焦点环使用现有 Office 主题；URL 显示名称隐藏用户名密码。选择模式及只读阅读可用，绘图、保存、打印、预览处理中禁用并退出 Tab 顺序。

`pdf-main.ts` 局部接入延迟批注读取和动态模块导入，使用当前 viewport/CropBox/UserUnit，由 PDF.js 处理旋转和批注几何。独立异步加载避免慢批注读取阻塞页面 pointer handlers。实例、generation、页面可见性及 canvas 身份防止迟到层挂入旧页面；刷新、卸载和销毁释放原生层。命名/显式目标解析后再次检查状态，按源页身份适配草稿重排，目标已删除时给出具体阅读告警；跳转后聚焦目标页标签，不写草稿。

浏览器真实复现窄屏 Shift+Tab 回返后首链接只露出约43px，而阅读区186px可容纳150px链接。新增 `focusin` 时 `scrollIntoView({block:'nearest',inline:'nearest'})`，保存/销毁后不执行，销毁移除监听。最终同场景链接 [134,444,284,472] 完整位于可视区域。局部 CSS 只增加点击层、焦点环、inert 和打印隐藏，不改发布/下载链路。

### 专家额外检查与定向测试

专家会区分外观、键盘可用性、文件目标正确及实际点击行为：不能用生成了链接文件替代宿主导航验证；不能用焦点已落在元素上替代焦点区域可见。还核对外部窗口隔离、脚本/Launch 拒绝、绘图事件避让、只读可用、延迟读取/导航和实例销毁、目标删除/重排、缩放/裁切/旋转/UserUnit，以及阅读行为不污染草稿或源文件。

`src/pdf-saved-links-host.test.ts` 使用实际宿主与 NativeDraft，AnnotationLayer/AnnotationType 为 `vi.importActual` 官方实现；getDocument/TextLayer/viewport 为明确 jsdom 夹具，不作为浏览器几何证明。初始 `/dev/shm/office-pdf-saved-links-red-20261112.log` 退出1、8项缺层失败；异步事件回归 `office-pdf-saved-links-async-red-20261112.log` 退出1，证明慢 annotations 时 pointerup 尚未绑定，之后产品改为独立异步加载。先前测试中数组参数和按钮英文选择器夹具错误已修，未修改产品迎合错误断言。

新增焦点回归 `office-pdf-saved-links-focus-unit-red-20261112.log` 句柄65043退出1：scrollIntoView调用0次。修正后最终 `office-pdf-saved-links-focus-green-20261112.log` 句柄82813退出0：saved-links 13、link-desktop 8、object-host 44，共3文件65项通过；未重复完整测试集。

### 构建与冻结

首次类型检查直接 cast 窄导航适配为完整 PDFLinkService 被 TS2352 拒绝。首轮构建/检查终态后改为显式 unknown 中转，限定只有两种链接进入；转换前后 esbuild 运行代码逐字相同，记录在 `office-pdf-saved-links-freeze-20261112/type-only-correction.json`。该阶段最终类型检查退出0。

焦点修复后重新冻结 `/dev/shm/office-pdf-saved-links-focus-freeze-20261112/source.json`，1582个src/config/lock文件；相对前一冻结仅 helper 和其测试两项变化。TypeScript句柄72791退出0；隔离Vite句柄12677退出0，43.98s，保留原plugins/别名/分包，仅重定向outDir/cache及运行时复制。构建 `/dev/shm/office-pdf-saved-links-focus-build-20261112/`，manifest SHA `b10157714d0dd7ea008c604869eccd224a9f9822b82f63289df27d74928dc128`，394个JS包预算通过。当前PDF.js cmaps/standard_fonts/wasm实际复制；不复用旧static，不覆盖项目static或部署。

### 浏览器证据、检查器修正与反例

最初浏览器目录 `office-pdf-saved-links-built-20261112/` 句柄41559退出1，初始15场景8项失败。独立检查器错误地对PyMuPDF `get_links()['from']` 再乘rotation_matrix；该返回值已经旋转，第三页真实矩形应为[460,80,520,320]，实际浏览器一致。另将高于短屏的240px区域要求一次全部五点可见，也属检查策略错误。修正为严格保留完整几何断言、按祖先裁剪检查可见交集，并分段覆盖超高区域。诊断运行句柄26458退出0、40场景；它只证明可见交集命中，不能掩盖窄屏焦点未完整露出的问题。

加强“可容纳时完整可见”后，旧构建 `office-pdf-saved-links-focus-red-built-20261112/` 句柄83076退出1，精确暴露 source-0-320x640 的7R回返焦点。焦点产品修复后的首轮 `office-pdf-saved-links-focus-verified-built-20261112/` 句柄38602退出1，12项90°裁剪断言失败：检查器把批注层未旋转clientWidth当屏幕宽度。修为通过CSS矩阵转换祖先内容框，再计算裁剪交集；未更改产品几何或放宽<1px误差。全部失败记录保留，均无保存。

最终 `/dev/shm/office-pdf-saved-links-final-verified-built-20261112/` 句柄52891退出0：三页×五视口15场景、全幅/裁切×四旋转×三缩放24场景、撤销后重开1场景，共40场景、130个链接的Tab/Shift+Tab及几何/命中/名称检查、4次超高区域额外分段、40张截图。第三页CropBox/UserUnit=2/Rotate=90的700×520页框和[460,80,520,320]矩形还与已知参照严格相等。可容纳焦点完整可见，超高区域分段连续覆盖，布局前后草稿相同。

实际Enter外链打开新窗口且window.opener为空；显式与named destination到第三页并聚焦页标签；绘图inert/tabIndex=-1、恢复选择重新可用。52个实际200 JS/CSS/wasm响应逐字节核对隔离文件，page/console/HTTP异常空。人工检查PC初始、窄屏、短屏高链接及裁切90°截图。真实授权/源文件接口/PDF.js/构建；派生PDF、内存修订仓储和外部网页响应为明确夹具，不称生产DB或桌面Acrobat实机。

全程savedRevisions=0，无/api/save；源下载接口匹配派生夹具SHA `799beb91548a5fd59d6007bd4d1d679d356c4a52f525f320088913966250d0c0`；前批真实下载SHA仍为 `b556218454ea73b93cf7aab9cb8f83871a1937c307ed4d373a468475f7607632`。原有保存/验收证据不重复生成。普通同目录重跑在mkdir处退出1、启动服务前拒绝，50个最终证据文件全部不变，见focus-freeze/replay-guard.json。

### 清单与未完成项

重新生成 `/dev/shm/office-ui-inventory-saved-links-20261112/`，逐735模块SHA核对并同步两份canonical清单，字节回读相等：735模块、5111声明点、650模板控件、53动态模板（共141模板）。这些数字是声明索引，不是功能总量或验收完成率。

本批关闭上批记录的已保存链接点击层缺口。其后补齐页内目标的 XYZ/Fit/FitB/FitH/FitBH/FitV/FitBV/FitR 坐标与缩放，并处理 null/省略参数、命名目标及旋转/CropBox/UserUnit。详见下节。邮件仅检查属性和命中，不启动系统客户端。只读等状态的部分保护由宿主单元夹具验证，不扩称真实浏览器覆盖。全量四格式仍需逐组件、动态分支和运行状态核对，整体目标保持active。

## PDF 页内链接 Fit/XYZ 目标定位

### 根因与实现

已保存链接先前只跳目标页，没有读取目标数组的 `/XYZ` 或 Fit 变体，也忽略 XYZ 的目标缩放。实现后由 `pdfLinkDestination` 将官方目的地坐标转换成宿主缩放和滚动计划，使用现有 `clampPdfZoom` 限制缩放。复用 PDF.js 当前版 PageViewport 的坐标转换，覆盖页面 CropBox、UserUnit、旋转，不手写旋转矩阵。XYZ 空缩放保留当前缩放；Fit/FitB适配页面，H/BH适配宽，V/BV适配高，FitR按目标矩形实际旋转后的可见尺寸取适配比例。FitH null 保留当前 PDF 位置；PDF.js 接受但省略的 H/V 参数使用页边界默认。错误类型/范围先软告警，不更改视口。

异步目标解析以 token、PDF 实例、refresh generation、模式、锁定状态和草稿快照保护；更新草稿、保存、关闭、滚轮/按键/点击和后续导航使旧目标失效。刷新时自身排版会产生 scroll 事件，不能将它当成用户取消目标。首轮浏览器重现这条竞态：缩放和活动页已更新，但状态仍停在默认提示，后续滚动定位未执行。已移除 scroll 事件本身的 token 递增，真实用户输入仍由捕获阶段 pointer/wheel/keydown/click 取消；刷新期间合法完成坐标定位。

### TDD 与验证

`src/pdf-link-destination.test.ts` 通过实际 `pdfjs-dist` 空白 PDF 加载创建官方 PageViewport，覆盖28项：XYZ null/省略/缩放边界，八类目标、FitH/FitV参数默认与PDF坐标、CropBox/UserUnit=2/90° XYZ/FitH/FitV/FitR、非法数组/数值/范围。首轮25项均因 helper 不存在而按预期失败；后续加入省略参数后3项 RED 暴露 undefined 与 null 语义不同（PDF.js省略FitH y回页顶，不能按null保留当前位置），实现后28/28通过。与 `pdf-saved-links-host`、reading-state、fit-state 一起最终定向测试62/62通过；不重复完整套件。

一次较早的有效类型检查发现测试 it.each 的无效目标测试将数组展开，得到 TS2345；测试表包装为对象后通过。更早构建 runner 自身有 SyntaxError，未启动构建；修正 runner 后的独立最终构建通过。构建冻结 `/dev/shm/office-pdf-destination-fixed-freeze-20261112/source.json` 共1585源码/config/lock路径，build-source-check differences=[]。TypeScript检查句柄59365退出0，Vite句柄11135退出0，59.17s，沿用现有插件、别名和分包，只改隔离outDir/cache及PDF.js资源复制目的地。394 JS包均低于既有预算，manifest SHA `b932dac13f9da0ac771d8e2300e88c1b4e784f4ce376ec849dcb45eab089d777`；项目static manifest保持不变，未部署。

目标验收使用 `/dev/shm/office-pdf-destination-input-20261112/source.pdf`，由仓库 `test_native_pdf_extract.source_pdf()` 创建的三页只读输入；原前批临时下载在这次上下文恢复时已清理，不将它谎称为本次输入。pypdf仅从该测试夹具派生测试PDF，内存修订仓储、授权路由的静态资产、测试用户都是明确夹具。真实浏览器加载实际构建和PDF.js，真实访问授权/源文件路由；51个200 JS/CSS/wasm响应逐字节核对隔离构建。最终 `/dev/shm/office-pdf-destination-final-verified-built-20261112/` 句柄90436退出0：15种目标参数×5视口，共75场景；每个检查zoom、页、目标在视口、阅读焦点、状态文案及草稿不变。named destination实际解析，旋转90°/CropBox/UserUnit目标点与PDF.js几何相符；错误目标只告警。0次保存、0新修订、无/api/save，输入源字节和静态manifest无变化，浏览器JS/console/HTTP异常空。

第一份 browser smoke 对 FitH 默认目标屏幕点使用了PDF坐标，且用滚动前scroll值重复计算当前位置；修正为验证目标处于可见视口。第二份 smoke 发现 product refresh scroll 竞态，去除错误取消条件、重建并重新完整运行75场景。`XYZ` null-null case也改由明确PDF.js默认 [0,页高] 建立 screen point 参照，而不是把上一位置错当目标。

页内导航目前可精确处理上述八类目标；外部 URI 仅支持合法 http/https/mailto，mailto未启动系统客户端，附件/脚本/Launch等PDF动作刻意不可执行。四种格式其余控件、动态分支和真实桌面运行仍未穷尽，整体目标保持active。

## 2026-11-12：Excel 条件格式缺省文字色保真

### 根因和修改

锁定的 `@univerjs/sheets-conditional-formatting-ui@0.25.1` 在高亮规则编辑器挂载时把 `#2f56ef` 文字色与 `#e8ecfc` 填充色作为控件默认值，并由 effect 写回规则。用户只改阈值时，这两个未选择样式也会进入下载文件，改变原始规则语义。

导出操作现在以导入时生成的稳定 CF ID 对应原规则；当源样式未指定 `cl`/`bg` 且编辑后值仍为框架默认色时，从导出规则移除该字段。不同于默认值的显式选择仍写入文件。此规则仅规范化该框架隐式默认，不改编辑器显示、阈值、填充或公式。

### 验证

- `workbook-conditional-formatting.test.ts` 新回归先按预期失败：阈值从10改20后操作载荷出现源文件未定义的两种默认色。修复后条件格式定向测试7/7通过，包含真实 Univer 命令与默认值/显式颜色回归。
- 全量 `tsc --noEmit` 通过；隔离 Vite 生产构建退出0、42.88秒，manifest SHA256 `81d1bed64dabe33bc1303cd46dd33a375a4dc9cdea199c11b29f8c62e9d5178c`；按既有预算函数复核394个 JS 包均通过。临时构建配置已移除，项目 `static` 未作为构建输出目录。
- 真实构建规则保存烟测 `/dev/shm/office-xlsx-cf-default-save-built-20261112/evidence.json` 退出0：真实浏览器打开 DV/CF 面板修改并保存修订，独立下载及 openpyxl 回读确认填充仍为 `FFFF6666`、CF 字体颜色为 `null`，操作载荷未新增 `cl`，JS/page/console 错误为空。授权与修订 API 是 route fixture，不代表生产授权或发布链路。
- 开发服务器烟测也执行到最终 `pageErrors` 断言；条件格式载荷和 XLSX 回读断言已通过，但被 Univer 页脚缩放控件的嵌套 `<button>` React 开发态警告判为失败。生产构建复验通过，未放宽错误检查。
- 快速卸载后的 Injector 异步 resize 回调在当前两模式定向复现中未出现；既有162场景运行曾捕获该错误，因此仍保持未解决，不以这次间歇性未复现关闭问题。

未运行完整前端测试集、未提交/推送/部署。四格式组件、动态状态、菜单和桌面实机仍需逐项穷尽，整体目标保持active。

## 2026-11-12 续批：XLSX 函数参数折叠状态与侧栏卸载复查

### 函数参数浮窗

专家可访问性检查发现，Excel 函数参数浮窗的范围选择按钮同时折叠/展开参数区，但没有暴露当前展开状态。按钮现增加 `aria-expanded` 与 `aria-controls`，参数行容器提供对应 ID；原网格点选、折叠布局和公式提交保持不变。

`workbook-insert-function.test.tsx` 的真实 React 组件回归先红（`aria-expanded` 为 null），修改后4/4通过。`workbook-insert-function-gui-smoke.mjs` 在真实 XLSX 宿主验证展开/折叠状态、网格点选、公式输入、保存/下载及重开；烟测退出0，`pageErrors=[]`，openpyxl回读确认目标 C3 为 `=SUM(A1:A2)`、非目标 B2 仍为 `keep`。授权和修订接口使用 route fixture。

全量 `tsc --noEmit` 退出0；smoke `node --check` 和本批 `git diff --check` 通过。未运行完整前端套件。

### Injector 卸载竞态复查

当前构建上连续执行8次真实 `dv-add` 侧栏打开/关闭（1440×900，每次独立真实页面），`office-workbook-panel-lifecycle-stress/evidence.json` 记录8场景，`failures=[]`、`pageErrors=[]`。这不能撤销此前162场景运行的两条真实异常，因此原问题仍未关闭。

源码阅读还发现锁定版 `@univerjs/sheets-data-validation-ui` 的 Undo/Redo effect 订阅 `commandService.onCommandExecuted` 时没有返回清理函数；尚无证据证明它就是先前 resize 异常的来源，本批没有修改 node_modules 或增加猜测性异常吞噬。后续仍需取得准确堆栈或构造同一 Univer 实例内的重复开关复现。

本续批未提交、推送或部署；四格式组件、动态状态、菜单和桌面实机仍未穷尽，整体目标保持active。

## 2026-11-12 续批：四格式弹窗 axe 探测及 Excel 缩放输入尺寸

本轮接续原目标；前一拉取回合确认 GitHub HTTPS 请求不返回、SSH公钥失败，没有更新工作树。没有将网络失败当成UI工作的阻塞。

专家补充检查落实到已有产品组件夹具：`office-dialog-layout-smoke.mjs` 增加可选 `OFFICE_DIALOG_AXE=1`，扫描打开弹窗的全部默认axe规则并保存完整违规节点；显式创建browser context，满足axe辅助页面要求。首轮失败是axe拒绝browser.newPage隐式context，不是产品缺陷。修正后25种代表弹窗的桌面扫描全部零违规，范围包含四格式、函数、排序、透视、保护、链接、图表、脚注、段落、表格及数据操作，不等于所有UI或所有动态状态通过。

扫描同时发现旧布局检查器与已审计PC紧凑样式不一致：PDF提取、Excel合并计算/高级筛选/单变量求解/允许编辑区域实际要求28px，却仍统一断言32px。只对已核实的具体窗口改用28px，其他窗口维持32px；Word长注释正文不套用Excel左右标签断言。保留旧失败证据 `/tmp/office-dialog-axe-probe2-20261112/` 和 `office-dialog-axe-extended-20261112/`。

真实产品缺陷：Excel自定义缩放输入高25.5px。局部CSS增加min-height:28px及border-box；宽度与原视图操作保持。修复前 `/tmp/office-dialog-zoom-red-20261112/` 定向浏览器退出1，只有输入尺寸断言失败；修复后 `/tmp/office-dialog-axe-verified-20261112/` 9种弹窗×1440×900/640×360/320×640共27场景退出0、axe零违规、failures/pageErrors均空，覆盖原焦点回返、焦点环、无横向裁切及滚动末端主操作可达性。另四种紧凑窗口 `/tmp/office-dialog-axe-compact-verified-20261112/` 4场景退出0、axe零违规、failures/pageErrors均空。人工查看缩放桌面与640×360截图；短屏允许内部滚动，不宣称全部选项与操作同时可见。

`vitest run src/workbook-zoom-dialog.test.ts` 7/7通过；smoke node语法检查通过。本批仅CSS和浏览器检查器变化，没有运行完整测试、构建或重复文件保存测试。夹具使用真实产品组件和Vite源模块，业务回调是夹具，不扩称真实Office宿主、桌面应用、生产授权或文件保存验证。没有提交、推送、部署。四格式其余组件、菜单、动态状态、真实桌面运行与既有Injector卸载竞态仍未穷尽，整体目标保持active。

## 2026-11-12 续批：四格式错误/空白/繁忙状态及配色语义

上一目标回合属于progress：新增axe检查和修复Excel缩放输入高度。本批按完整四格式目标继续，扫描24种状态及12种工作簿设置状态。`/tmp/office-dialog-axe-states-20261112/`完成24场景后退出1：3项是已审计28px控件与旧32px检查器冲突（模拟运算表和PDF已有图像），1项是PPTX图表设计配色预览的真实ARIA缺陷；Word修订正常/空白/锁定、段落错误、题注锁定、Excel数字格式/图表/求解、PDF转换/图片导出的等待/错误/结果等状态保留完整axe结果。`/tmp/office-dialog-axe-settings-20261112/`保存12次axe结果，函数目录正常/空白/选中暴露缺少列表名称、空列表框缺少option；名称管理器、定位、查询、注释等其余扫描零违规，但运行在打印预览错误的等待检查超时，仅11场景完成，不能当全批通过。单独不带axe打印预览错误检查通过；最终带axe三视口也通过，超时原因未定，不归因产品或静默放宽等待。

产品修改保持局部：`slides-native-chart-edit.ts`为配色预览添加group角色、为色块添加img角色及真实颜色值名称；`workbook-function-catalog-dialog.tsx`和词条补充搜索框/结果区名称，空结果使用具名region及status，恢复结果时回listbox。保留配色提交、图表数据、函数过滤/双击、公式/网格选择及保存链路。本批未修改CSS；只在已有smoke中对已核实28px的具体两个窗口更新最低高度，不降低其它窗口要求。配色烟测实际选择warm并核对5色块的角色和颜色名称。

TDD：PPTX新增回归先失败（role为null），修复后图表窗口19/19通过。函数目录两项新增回归先失败（搜索框名称缺失）；首次绿色尝试还发现测试默认Recent导致非空目录无结果，显式initialCategory=All修正夹具。最终6/6通过，额外验证分类切到空结果再恢复时region/listbox和选项同步。没有更改产品默认分类。全量tsc --noEmit退出0；node语法及本批相关git diff --check通过；没有运行完整套件或生产构建。

最终浏览器证据：`/tmp/office-dialog-axe-states-fixed-20261112/`（配色设计/模拟运算表错误及繁忙/已有图像错误）与`/tmp/office-dialog-axe-catalog-fixed-20261112/`（函数目录正常/空白/选中/打印预览错误），各4状态×1440×900、640×360、320×640=12场景，共24场景退出0，所有axe违规、failures、pageErrors为空。验证仍包含既有关闭回焦、焦点环、无横向裁切和末端主操作可达性。人工查看桌面暖色预览和320px函数空结果截图；目录固定高度是保留列表位置以支持双击的既有设计，没有借语义修复改变它。产品组件通过Vite加载，业务/失败回调为明确夹具，不扩称真实桌面应用、生产授权或文件保存回读验证。

清单重新生成`/tmp/office-ui-inventory-axe-states-20261112/`，735份模块SHA逐一核对；两份canonical Markdown逐字节同步。5111声明点仅用于定位，不是独立功能总数或完成率。四格式菜单、更多动态状态、真实桌面运行及已知Injector释放竞态仍未穷尽，整体目标保持active；未提交、推送、部署。

## 2026-11-12 续批：函数目录键盘操作和短屏长说明

上一批为实际progress。本批继续完整四格式目标，先检查尚未覆盖的19个工作簿设置夹具：填充序列、插入删除、行列尺寸及错误、去重及错误、页眉页脚变体/错误、打印缩放/错误、自定义格式/错误、查询空白、定位名称。`/tmp/office-dialog-axe-remaining-settings-20261112/evidence.json`退出0，19桌面场景axe违规、布局失败、pageErrors均空，仅证明这些组件状态，不代表真实保存或全部格式。

源码及RED回归确认函数目录每个option都占一个Tab入口，缺少ArrowUp/ArrowDown/Home/End；分类变化后可能确认旧选择。产品局部补齐单一Tab入口、焦点跟随选择、上下键边界不循环、Home/End首末定位；查询/分类改变清除旧选择，禁用确认直到选择新结果。Enter/空格仍沿用原生按钮选择，确认按钮及双击的既有提交行为保持。没有改过滤顺序、函数语义、公式写入或保存链路。

浏览器首轮`/tmp/office-function-keyboard-20261112/`检查器把select原生option算入函数结果；改为`.fn-list [role=option]`后，`...keyboard-scoped-20261112/`桌面/窄屏通过，短屏仍真实失败。诊断`...keyboard-short-diagnostic-20261112/`记录当前行47px、结果列表仅34px，焦点正确但行被裁切。不是靠放宽可见性断言解决：CSS给非空列表80px最小高度，长说明允许内部滚动；说明新增具名region、Tab入口和主题焦点环。固定窗口高度与列表坐标策略保持。

TDD：列表初始回归先失败（所有tabIndex为0）；追加说明阅读区回归也先失败（role为null）；最终`workbook-insert-function.test.tsx`7/7通过。最终`/tmp/office-function-keyboard-fixed-20261112/`正常/空白/选中×1440×900、640×360、320×640、390×320共12场景退出0，axe/failures/pageErrors均空。`...keyboard-scroll-verified-20261112/`额外验证长说明实际End到底、Home返回且焦点保留，4视口退出0；记录每步focus/selected/单一Tab入口和结果行/列表几何，仍验证Tab经过说明/操作区、Shift+Tab返回当前项、分类清除旧选择。人工查看640×360选中态截图，结果列表不再裁掉半行，说明内部滚动；不宣称所有长文本同时可见。

真实XLSX宿主`node smoke/workbook-insert-function-gui-smoke.mjs`（进程68671）退出0：函数目录/分类/双击、真实Univer预览、网格选区、公式草稿、保存/回读及重开通过；openpyxl回读C3=`=SUM(A1:A2)`，B1原公式保留，B2=`keep`，pageErrors=[]。授权与修订路由为夹具，真实patch_office/openpyxl处理文件，不扩称生产授权/数据库。该烟测stdout由工具会话保留，没有独立证据目录。

最终tsc --noEmit进程91525退出0，smoke语法及本批diff检查通过；未运行完整前端套件或生产构建。735模块SHA逐一核对，两份canonical清单逐字节同步；5111声明点非功能总量。新增coverage.json仅汇总当前已注册夹具与历次零违规axe观测，明确不是功能验收率，未扫描项保留逐项名称。四格式菜单、更多动态分支、真实桌面运行及Injector竞态仍未穷尽，整体目标保持active。未提交、推送、部署。

## 2026-11-12 续批：Word 覆盖边距 PC 窗口及剩余 Word/PDF 探测

上一回合为实际progress。本轮`/tmp/office-dialog-axe-word-remaining-20261112/`完成23个尚未扫描Word状态（题注、边距、段落/缩进、表格属性、缩放），桌面axe与布局检查退出0。`/tmp/office-dialog-axe-pdf-remaining-20261112/`完成19个PDF状态但退出1：裁切8个无语义span上的aria-label被axe报aria-prohibited-attr；链接/水印实际采用已审计28px，检查器仍要求32px；水印产品明确close后focusRibbonEntry(stampButton)，夹具却要求回“打开设置”。后二者按真实尺寸和Ribbon回焦契约修正夹具，`/tmp/office-dialog-axe-pdf-host-checks-verified-20261112/`两场景退出0。没有改产品回焦。裁切语义问题保留，不能仅为了消除axe告警随意加role；须核对数字字段等效键盘操作和图形控制语义。

### Word 单元格覆盖边距

桌面截图确认原恢复继承按钮被form通用网格撑宽；标题、长说明及错误和操作没有分区。局部修改`docx-table-cell-margin-overrides-controls.ts`及`docx.css`：520px上限、32px字段/28px按钮、64px左标签列、自定义边距fieldset、固定标题与底部操作、主体内部滚动。恢复继承靠左保持紧凑，取消/确定靠右；来源状态、说明、错误均具名并可Tab进入，失败揭示错误并滚入视图，保留输入焦点。沿用单位换算、奇数twip、混合选区、来源/选区过期保护、继承set/reset和三级属性切换；没有改DOCX引擎或发布链路。

新增`docx-cell-margins-desktop.test.ts`两回归先RED（缺少header、错误名称），修改后与既有覆盖边距UI、属性回焦测试共3文件12项通过。浏览器RED`/tmp/office-word-cell-margins-red-20261112/`12场景确认缺结构与阅读入口；首轮GREEN仍失败6条横向边界（12px边距不足原16px要求），已修正到32px总边距。之后`...-final-20261112/`5状态×4视口20场景退出0。人工查看又发现移动后二级属性按钮失去主题样式、桌面标签列被旧选择器更高优先级覆盖，局部修正并重新构建；最终样式`...-styled-final-20261112/`custom/mixed/error×1440×900、640×360、320×640、390×320=12场景退出0，axe/failures/pageErrors均空。固定区域位置、操作可见、恢复按钮紧凑、字段值前后一致均检查。

阅读焦点首轮`...-reading-20261112/`9条失败：程序化focus在鼠标模式下不触发focus-visible；位置、焦点和可见高度都已正确，outline=0。检查器改为真实Tab遍历，未改产品焦点CSS或放宽断言；最终`...-reading-verified-20261112/`错误态×3视口，9个来源/说明/错误阅读区均真实Tab获焦、2px焦点环、至少20px可见，退出0。短屏允许主体滚动，不宣称所有字段和说明同时一屏。

### 构建及真实文件保真

隔离配置复制原Vite配置，只重定向outDir与PDF.js/LICENSE复制目的地到`/tmp/office-word-cell-margins-build-20261112/`，保持别名/插件/分包。首次构建后人工看图修正样式，因此重新构建，未用首次结果冒称最终；最终进程92852退出0、45.45秒，394个JS包按原预算检查failures=[]。tsc --noEmit进程72681退出0。项目static没有用作本次输出目录；构建已有循环chunk/大chunk提示保留，未放宽预算。

真实保存探针基于既有`docx-table-cell-margin-overrides-built-smoke.mjs`，临时副本仅重定向preview配置及资源SHA比较目录。进程40177退出0，证据`/tmp/docx-cell-margin-overrides-built-kOsJQB/evidence.json`及完整stdout`/tmp/office-word-cell-margins-real-built-20261112.log`：四种来源（普通、样式继承、合并/隐藏continuation、RTL/竖排），多次set/reset、混合矩形no-op、undo/redo、草稿reload、四次真实保存/浏览器download及修订重开通过。全部非目标末行cell、tcMar以外XML、段落/部件字节及整表默认保持；有效边距等于步骤回放。138个实际JS响应逐字节SHA匹配隔离构建，errors=[]。授权/修订仓储为route夹具；真实DOCX引擎、patch_docx、浏览器与文件下载回读，不扩称生产DB或微软Word实机。临时配置及runner已归档证据目录并从工作树移除。

源码清单735模块SHA逐项核对并同步两份canonical文件，现5114声明点，不是功能总数或验收率。coverage.json更新于reading-verified目录，明确只是已注册夹具axe观测；未扫描与既有缺陷继续保留。node语法及本批相关diff检查通过；没有重复完整套件、提交、推送或部署。四格式菜单、动态状态、真实桌面运行、裁切语义和Injector竞态仍未穷尽，整体目标保持active。

本次隔离最终manifest SHA256：`923e13754b60b4fe78670c4001fae0dd8cd7bf2a6fbaf0bac7407f672404c872`。


## 2026-11-12 续批：PDF 裁切可访问语义与真实保存

前一用户拉取回合为实际progress：成功fetch，code与origin/code均为3b4ff524，ahead/behind 0/0，保留684条工作区改动。继续原四格式目标，没有将拉取作为整体完成。

裁切此前8个span控制柄使用aria-label而没有合法语义。本批保留既有拖拽算法，以已有四边百分比输入提供完整等效键盘路径：预览stage设role=img并随数值更新中文裁切名称，内部视觉裁切区域aria-hidden，去除无效柄名称；四个输入归入“裁切边距（百分比）”fieldset，并关联唯一帮助说明，说明明确键盘填写与拖动等效。没有新增伪键盘拖柄或修改裁切/发布算法。

先前本批两项回归先RED后GREEN，canvas/dialog/crop/crop-all共4文件59项通过，tsc进程42500退出0；本续轮不重复完整测试。四视口真实Tab和键盘输入10/20/30/10验证具名预览、60%×70%视觉区域、帮助关联和未提交草稿不变，证据`/tmp/office-pdf-crop-keyboard-20261112/evidence.json`，failures/pageErrors/axe违规均空。桌面截图已人工检查；短屏采用内部滚动。

接续构建原句柄3826，确认退出0、45.16秒；原预算检查394个JS包failures=[]，未放宽预算。隔离产物`/tmp/office-pdf-crop-a11y-build-20261112/`，manifest SHA256为4519e5aea99047dc35e74f135832d671f7b18bb5b48290eedea3ff7fcccf55f3。临时配置只重定向产物与资源复制目录，未覆盖项目static。

真实宿主烟测进程44520退出0，`/tmp/office-pdf-crop-a11y-real-built-20261112/summary.json`的ok=true、errors=[]。覆盖0/90/180/270度旋转、UserUnit=2、已有CropBox、实际拖柄及数字输入、PDF.js真实预览、保存及浏览器下载。独立pypdf回读四页CropBox符合预期，内容保留、表单值仍为original；保存/下载字节与独立实际预览完全一致，40个实际JS资源记录身份。授权/修订接口为route夹具，不扩称生产HTTP/数据库或微软Office桌面验收。临时配置和runner归档到该证据目录后，仅移除这两个自建临时文件。

剩余30个XLSX夹具桌面axe扫描`/tmp/office-dialog-axe-xlsx-final-list-20261112/evidence.json`退出0；与本次裁切汇总后，152个已注册夹具均有至少一次零违规axe观测，coverage.json存于本批真实保存证据目录。这不是全部菜单/动态状态、所有视口、真实宿主或保存验收率。已知Excel Injector卸载竞态仍保留未解决，不能用本批没有pageErrors关闭。

735个模块当前SHA逐项匹配生成清单，两份canonical Markdown同步后回读字节一致；5114声明点不是功能分母。两个相关smoke语法及本批产品/测试/smoke diff检查通过。四格式菜单、未登记动态状态、真实桌面验证和Injector竞态仍需继续，整体目标保持active。未提交、推送、部署。


## 2026-11-12 续批：PPTX 内联设置窗口固定操作与错误阅读

上一目标轮为实际progress。本批对照源码发现，已登记152种通用夹具不包含所有内联设置窗口；没有用152零违规宣称穷尽。选择既有PPTX“插入表格、 新增节、页眉和页脚”，延续已有PC主题、窗口宽度、关闭回焦及输入/提交规则，只将模板分成固定header、滚动主体和固定footer，并让已有错误具名、可Tab阅读、具备焦点环。未改变表格尺寸校验、节名校验、页眉页脚字段逻辑或文件写入。

先在slides-main.test.ts新增两项无效输入回归，原句柄49012退出1：2失败/21通过，失败为错误缺少名称。修改后原句柄32740退出0，23/23通过；验证错误可聚焦、保留输入、窗口不关闭、不改变脏状态且无额外请求。浏览器检查器增加真实Tab阅读、焦点环/主体可视区、滚动前后header/footer坐标、可选axe；PPTX宿主使用显式browser context以支持axe。

浏览器RED使用上一批冻结构建，原句柄49679退出1，`/tmp/office-pptx-settings-reading-red-20261112/settings-evidence.json`记录两个视口下缺少阅读名称/Tab入口和主体分区，page/console/route/HTTP错误为空；没有以工具异常冒充产品RED。最终隔离构建进程88372退出0、44.63秒；tsc进程85336退出0，394个JS包原预算failures=[]，未放宽预算。manifest SHA256为e456acad3b144a5534f8f148f4175df323655d0bb8dbe05e435d991b63bb52c4，产物在`/tmp/office-pptx-settings-reading-build-20261112/`，项目static未覆盖。

最终真实PPTX宿主进程92970退出0，`/tmp/office-pptx-settings-reading-final-20261112/evidence.json`：三个窗口×1440×900、640×360、320×640、390×320共12场景，settings failures=[]，12次axe均零违规。检查字段值、无效输入不提交、错误实际Tab及至少2px焦点环、关闭/取消回焦、重开值恢复、底部按钮命中、主题/控件尺寸/标签布局与主体滚动。人工查看640×360页眉页脚截图，固定标题和操作可见、长页脚保持输入区；该视口主体210px、内容233px，390×320主体170px、内容233px，滚动不移动标题与操作，不宣称全部设置同时一屏。

同一最终宿主继续完整备注/页面保存回归：中文/emoji/空白和字面符号、多页切换、undo/redo、刷新草稿、页面重排、两次保存/下载/修订重开、清空备注立即保存全部通过，最终revision=3。独立python-pptx/ZIP回读保留目标备注与页面对应关系和非目标内容。129个实际JS响应身份核对构建一致，pageErrors/consoleErrors/routeErrors/failedResponses均空。这里三个设置窗口验证的是修改/取消与错误交互，不扩称它们各自提交后的全量文件保存；真实保存覆盖备注及重排。授权/修订使用route夹具，PDF附件预览是占位夹具，不扩称生产授权/DB、PDF转换或微软桌面验收。

735模块来源SHA核对一致，两份canonical清单同步并逐字节回读；5114声明点不是功能总数。source-verification.json在浏览器退出后再次核对本批5文件SHA保持一致。临时构建配置已归档最终证据目录并仅移除自身临时文件。两个smoke node语法、本批相关diff检查通过，没有重复完整套件、提交、推送或部署。四格式未登记动态状态/菜单、桌面实机及Excel Injector竞态仍未完成，整体目标保持active。


## 2026-11-12 续批：Word 书签键盘焦点及文件保真

上一目标轮为实际progress。本轮对照未登记侧栏及既有引用组件发现，docx-bookmarks每次编辑器transaction都会replaceChildren，键盘焦点落在列表按钮时，普通选区事务也会删除当前DOM节点；删除后没有相邻焦点，所有删除按钮也仅名为“删除书签”。面板打开/关闭尚未交接焦点。沿用既有双栏/紧凑PC样式，不以重复换色代替真实操作修复。

新增三项真实Tiptap组件回归，进程86150退出1：3失败/5通过，分别确认无关选区事务使按钮断开、删除名称缺失、打开未进入名称字段。产品保留原节点直到可见条目/操作/锁定状态确实变化，用包含ops的签名避免旧回调保留过期操作；需要重建时恢复同身份焦点，已删除项转下一可用同类按钮、前一项、名称框或关闭。鼠标未聚焦列表时不主动抢编辑器焦点，原mousedown选区保护保留。删除按钮增加逐项名称；打开聚焦名称（禁用时转关闭），关闭回已连接入口，事件调用优先使用实际Ribbon currentTarget，兼容原程序调用。

进程62560退出0，docx-bookmarks.test.ts 8/8通过；原精确选区、UndoRedo、可信身份、只读、跨段落和mousedown回归保持。tsc进程95264退出0。浏览器首次进程47048退出1是新检查器将Playwright :visible交给原生axe querySelectorAll，未将其计作产品失败；修正为标准:not([hidden])后，进程97010退出0。`/tmp/office-word-bookmarks-focus-verified-20261112/evidence.json`覆盖空白/32项长列表/只读×六视口（1440×900、768×1024、390×844、320×640、640×360、390×320）18场景，failures/pageErrors=[]，18次axe零违规。真实Tab到删除、普通事务保留同节点焦点、Space删除后跳过只读项、撤销恢复全部正文/意图、关闭回入口均验证；列表布局、末项滚动与原有尺寸检查保留。夹具增加与真实宿主相同的bookmark intent文档属性，以实际UndoRedo验证，不假装文件写回。

隔离构建68843退出0、43.97秒；394个JS包原预算failures=[]，manifest SHA256=d94df323ce8ed38551368543d319afad39d82c0758c22dedb61f00dbc0ebe0e5，产物`/tmp/office-word-bookmarks-focus-build-20261112/`。项目static未覆盖，临时配置归档后仅删除自身文件。

真实冻结宿主进程55220退出0，`/tmp/office-word-bookmarks-focus-real-built-20261112/evidence.json`的ok/keyboardChecked=true、errors=[]。检查真实Ribbon打开字段/关闭回焦、精确chor t选区创建、UndoRedo、草稿reload、定位、保存/下载/修订重开、Space删除及再次保存重开。138个实际JS响应SHA与构建一致；两个保存应答明确返回“书签版式待复核”，仍可取得下载文件并显示告警，未标记验收通过。授权/修订路由为夹具，真实Python/Node引擎写回；下载是HTTP fetch所得字节，不冒称本批用了浏览器download事件或生产授权/数据库。

独立lxml/ZIP读取本次真实输出，`independent-fidelity.json`：两次文件分别SHA 2cfa91de1ae584bad03b28fd3f30d9833474e684087c3660d00feb9576b11f66、eadd4e98cad58fd72bea1acfbfa49bc9b54b15fcfe71422d9b46b1b8324b83a8；仅document.xml变化，只有目标首段节点不同，非目标正文节点canonical XML一致、所有其他ZIP部件逐字节一致；目标全文文字、段落属性、逐字run属性和字符样式相同，精确书签名称/范围另由既有独立回读检查。没有对目标XML差异一概放行来宣称全文件字节相同。

735模块SHA在真实宿主退出后逐项核对，两份canonical清单同步并字节回读；5114声明点仍非功能总量。本批五个源码/测试/smoke SHA已登记source-verification.json；smoke node语法和相关diff检查通过。未重复完整测试、提交、推送或部署。全四格式目标保持active，未登记动态状态/嵌套菜单、真实桌面运行及Excel Injector竞态仍需继续。


## 2026-11-12 续批：Word 交叉引用键盘与短屏 PC 侧栏

上一目标轮为实际progress。本轮沿完整四格式目标检查相邻交叉引用侧栏，不将通用152夹具当成全部组件。源码确认每次transaction重建列表，焦点节点断开；打开/关闭未交接焦点、空列表缺说明、只读列表全禁用后无法键盘滚动。四项新真实Tiptap回归进程17583退出1（4失败/5通过）。仅在条目/锁定状态变化时重建，保留无关光标事务的节点；重建时维持同身份焦点或转关闭。打开聚焦首个可用来源，空白/锁定聚焦关闭；关闭回实际Ribbon currentTarget或已连接调用入口。状态具名、可Tab阅读、错误揭示到视区，空白给出“当前文档没有可插入的已保存书签”。不改可信来源校验、REF域投影、独立保存、UndoRedo或下载签发。

初轮浏览器2560退出1：夹具仅setEditable未像真实docx-main宿主那样显式refresh，产生锁定检查假失败；同时axe确认只读ul的scrollable-region-focusable是真实问题。夹具补实际宿主的刷新调用；只读列表新回归72922先RED，再给原生ul名称“已保存书签”和Tab入口。后续9292的首尾键盘断言读取了滚动动画未结束位置，改为等待同一列表达到原有首尾条件，未放宽判定。42221退出0，24场景键盘及axe通过，但人工截图发现通用30dvh限制使短屏首屏几乎只有说明/关闭，不能把扫描通过当作视觉完成。

新增固定标题/滚动主体检查，13716退出1，4场景确认缺分区。产品在既有侧栏内分出header与body：标题/关闭始终保留，主体最大min(360px,50dvh)，桌面说明与列表双栏，窄屏纵向；状态内部滚动且有焦点环。没有新增模态、遮罩或锁定正文。83677的24场景初次通过后，再严格检查readonly End后末项实际名称是否处于列表与主体交集，1257在640×360和390×320均RED。修复列表高度，使其按50dvh减去标题及留白约束，保留220px上限；不是靠放宽可见性标准解决。

最终31412退出0，`/tmp/office-word-cross-reference-desktop-final-20261112/evidence.json`：long/readonly/empty/error×1440×900、768×1024、390×844、320×640、640×360、390×320=24场景，failures/pageErrors=[]，24次axe零违规。真实Tab阅读状态/只读列表、End到末尾且末项名称未被双层裁切、Home回头、普通事务同节点焦点、动态锁定/解锁、关闭回入口、无正文变更及标题不随主体滚动全部验证。人工查看readonly 320×640以及390×320 keyboard-end截图，后者清楚显示固定关闭、末项31名称及列表焦点环。此前只在视口内的弱检查已改为同时处于主体裁切范围内。空白/错误两种状态加入引用smoke默认清单；最终运行显式执行这四种状态，登记扩展本身不代表其他新功能验收。

最终行为单测86865退出0，docx-cross-reference.test.ts 9/9（含真实桥包数字XML实体/emoji解析）。最终tsc71290退出0。最终隔离构建14223退出0、44.52秒，394个JS包原预算failures=[]，manifest SHA256=8a7748ee5b8c598f4787617e5e787164154d93ffe61b274d7225663478808288，产物`/tmp/office-word-cross-reference-desktop-build-20261112/`。中间布局前构建与真实运行另存focus目录，不混用为最终；重新构建仅因产品变化，未重复完整套件或修改预算/static。

最终真实宿主92451退出0，`/tmp/office-word-cross-reference-desktop-real-built-20261112/evidence.json`：ok/keyboardChecked=true、errors=[]。实际Ribbon初始聚焦/关闭回焦、Space在精确offset7插入、待保存状态禁用重复插入、UndoRedo、草稿reload、真实保存/HTTP下载/修订重开通过；138个实际JS响应SHA与最终构建一致。独立回读REF SavedTarget \h、begin/separate/end结构、emoji及&缓存、两侧粗体均正确；应答“交叉引用版式待复核”仍显示且下载正常，不冒称验收通过。授权/修订路由是夹具，真实Python/Node桥处理文件；下载为HTTP fetch字节，不冒称浏览器download事件、生产DB/授权或微软Word实机。

`independent-fidelity.json`额外严格核对本次文件：来源SHA b08b2d84ead298a8634915aca07cee3b1b4819139df831d7f163983858120ced，输出f01d85e4ac827d15d374b486a7c6ef8117fd172ebab12987ea186ca6c70c4536；ZIP健康，其他部件逐字节一致，非目标正文节点canonical XML一致；仅第二段改变，原文两侧文本/逐run属性/粗体保留，REF指令和新增缓存精确匹配，不以XML可解析代替内容保真。

735模块SHA在最终宿主退出后逐项核对，两份canonical清单同步回读，5115声明点非功能总量；六个产品/测试/smoke SHA记录source-verification.json。临时配置已归档并仅移除自身文件，相关node语法与diff检查通过。未提交、推送、部署。四格式未登记动态状态/菜单、真实桌面运行及Excel Injector竞态继续保留，整体目标active。

## 2026-11-12 续批：PDF 附件侧栏键盘、固定标题与保存保真

上一目标轮实际完成了远端代码同步核对，本轮继续原四格式UI目标，收尾此前已启动的附件验证。附件状态增加具名Tab入口与焦点环，读取期间标记aria-busy；下载/移除名称包含文件名和序号，支持重名区分。重试、移除及撤销后恢复同附件操作；取消最后一个待添加附件回新增按钮，用户已经转向其他控件时不抢焦点。离开附件栏清除恢复意图。保持原缓存、generation、下载、写入及只读规则，不修改发布签发链路。

新回归69951先RED（3失败/3通过/42跳过）。首轮修复误用函数内PDF代理document.activeElement，改用window.document.activeElement；测试等待改为精确“1 个附件”，避免将“正在读取”误认完成。主定向28391退出0，host/cache/edits三文件56/56。真实短屏6304及精确诊断17063均退出1：Shift+Tab确实聚焦新增，但640×360和390×320的按钮中心被吸顶header盖住。产品分出固定header和滚动body，而非放宽命中检查；布局改动后47918相关6项通过，没有重复完整套件。

最终隔离构建70851退出0（50.04秒），tsc58358退出0；394个JS包原预算failures=[]。manifest SHA256为cd8b664ed0354e96f04d486201cd1763401eab893b602ce55a7ecdea42bac14a，隔离目录`/tmp/office-pdf-attachments-focus-build-20261112`，项目static未覆盖。最终真实浏览器原句柄25377本轮poll确认退出0；`/tmp/office-pdf-attachments-focus-final-real-built-20261112/evidence.json`的ok/keyboardChecked=true。目录失败、内容失败、已加载、待添加、只读、空白六阶段×1440×900、640×360、390×320共18场景，阶段failures=[]、18次axe零违规。验证真实Tab/Shift+Tab状态阅读和新增按钮命中、Space重试/移除、取消待添加及恢复焦点、忙碌结束、状态位于body实际可视交集。人工查看640×360待添加截图，标题/关闭固定、取消按钮与焦点环可见。

同一真实宿主完成附件目录/内容故障重试、缓存、过期下载拒绝、同名与空附件、真实PDF预览及只读下载、UndoRedo/reload、过期文件读取拒绝、名称冲突拒绝。四个原附件通过真实browser download事件校验SHA，保存后的整份PDF通过HTTP fetch取得；不能将两者混称。实际PDF.js和打包引擎运行，授权/修订路由是夹具，不宣称生产数据库/授权或微软桌面实机验收。

本轮独立pypdf回读`source.pdf`和`downloaded.pdf`，记录`independent-fidelity.json`：删除folderA/same.txt，保留folderB/same.txt、空附件及76800字节中文名附件，新增zz-new.bin精确六字节[0,1,2,255,128,10]；附件字节集合完全匹配。三页内容流、MediaBox/CropBox/旋转、原注释字典和15个关联外观对象不变，原表单字段及值不变，新增批注正文存在。跨reader的IndirectObject含reader身份，初次直接字符串比较因此失败；改为PDF原生序列化比较引用编号及字典、独立比较外观流，未放宽内容相同要求。来源SHA为12cbf41eafdaa4319b48b494ec3ea874a99d549c3ad1936ddc67b4f398e4216d，输出为89a9f13fe0f904e4f2232a830096b3058d20fed74b201392311d2bd89a201a98。

最终进程退出后735模块SHA与清单逐项一致，两份canonical回读字节一致；40个实际JS响应SHA与隔离构建匹配，本批六文件SHA记录source-verification.json。5115声明点仍非功能总量。临时构建配置归档证据目录后仅移除自身文件。四格式未登记动态状态/菜单、桌面实机和Excel Injector竞态尚未关闭，整体目标保持active。未提交、推送、部署。

### Excel 卸载竞态续查：增加保留上下文的观察入口

此前早期面板证据目录当前已不可读取，不能据审计摘要猜测异常栈或直接修补依赖。采用当前最终隔离构建，仅执行既往出现过异常的dv-add/cf-edit×640×360、390×320四场景；句柄36363退出0，`/tmp/office-workbook-injector-current-diagnostic-20261112/evidence.json`的failures/pageErrors均空。这是未复现，不是竞态已修复。

原smoke在page.close后立即销毁JS上下文，难以观察卸载后的回调。新增可选`OFFICE_WORKBOOK_PANEL_TEARDOWN=1`：完成原有布局/关闭检查后，在同一上下文调整宿主宽度，经过一帧，显式分发非persisted pagehide调用真实native-main卸载处理器，再观察500ms。探针不替换ResizeObserver/定时器、不屏蔽pageerror，不声称合成事件等同真实导航或覆盖BFCache。句柄31117退出0，`/tmp/office-workbook-injector-pagehide-diagnostic-20261112/evidence.json`四场景failures/pageErrors均空，各场景canvasBefore=3、canvasAfter=0；证明这四次执行实际卸载，而非只读一个状态标记。没有重复162场景完整套件，没有因暂未复现改动产品生命周期或关闭缺陷。检查器node语法及相关diff检查通过；后续需继续获取真实失败栈、区分ResizeObserver/idle/动画帧调用来源，再建立可复现回归。整体目标保持active。

## 2026-11-12 续批：带本地 UI 修改同步远端代码

上一轮为实际progress。本轮先补开放侧栏卸载路径：`OFFICE_WORKBOOK_PANEL_TEARDOWN=open`保留dv-add/cf-edit侧栏而不先Escape，仍调用真实pagehide处理器并观察后续回调。原句柄97334退出0，`/tmp/office-workbook-injector-open-pagehide-20261112/evidence.json`四个短屏场景failures/pageErrors均空，sidebarOpen=true、canvasBefore=4、canvasAfter=0；探针新增实际卸载及侧栏初始状态断言。仍未复现既往间歇性Injector异常，不能关闭缺陷。

用户运行中要求更新最新代码。远端从3b4ff524推进20个提交到448085bf；初次pull因本地修改拒绝覆盖。先保存binary工作区/index补丁、292个未跟踪文件SHA及stash `2a5637864ee2b0997b4682f7fe2c1c26407d8a13`，再fast-forward并apply备份。六处冲突逐项合并：保留Word水印及本地批注入口事件类型，合并Word/PDF/PPTX新增样式与本地PC样式，保留PPTX标尺/参考线及设置窗口，PDF已有图像保留远端裁剪/翻转/透明度与本地固定header/body/footer、具名提示、焦点圈定和关闭回焦。没有选择整份ours/theirs丢弃另一侧功能。原index为空，恢复为未暂存状态；stash保留以便复核。`/tmp/smart-reporting-before-pull-20261112-448085bf/restoration-verification.json`确认292个未跟踪文件、413个不与远端重叠的本地文件原内容一致，HEAD与origin/code差异0/0，无未解决冲突。

定向六文件首次59项中36通过、PPTX23项因jsdom缺少远端新标尺所需ResizeObserver失败；只给该测试文件补浏览器尺寸API替身，不改生产标尺。初次补在describe内，22项通过、外层1项仍失败；将同一beforeEach提升到文件级，定向外层1项通过。另增PDF真实DOM整合回归，验证远端透明度控件位于滚动body，提交alpha=.75且恢复原入口焦点，通过。合计60个不同定向用例已分别通过，未重复完整套件；它们不证明真实浏览器新标尺/水印/主题等新组件已经完成UI验收。首轮tsc碰到同时变化的management配置函数签名，未修改该非目标模块；当前重新检查句柄64299退出0。合并相关diff检查通过。日志位于`/tmp/smart-reporting-pull-448085bf-*`。

远端新增水印、主题、标尺/参考线、图像像素编辑及图表画布能力，扩大了当前需要逐项复核的UI范围。旧冻结构建证据只对应各自原来源SHA，不能当成更新后源码的完整验收。继续更新源码清单并检查新增/动态状态；四格式整体目标保持active。无提交、推送、部署。

## 2026-11-12 续批：Word 水印窗口与短屏入口

上一轮为实际progress。本批验收刚同步的自定义文字水印窗口，延续PC Office主题、原生dialog、既有预设/字体/字号/默认值及文档级操作。新增固定header/标题关闭、滚动body及固定footer，宽440px且受视口约束，输入可收缩、版式使用具名原生分组。打开聚焦已选水印模式；标题关闭/取消/Escape丢弃未提交输入，返回可见水印trigger而非已经隐藏的自定义菜单按钮。错误具名且可Tab阅读、带焦点环，出现时主动揭示；提交失败保留窗口及全部输入，成功后才关闭。透明度空值不再经Number('')误当0%。自定义回调直接交由窗口显示失败，不再由预设菜单的apply捕获后关闭；预设和删除水印流程保持原语义。

新增七项回归52655先RED（7/7失败），79351修改后退出0，水印窗口/水印数据/Ribbon三文件32/32。覆盖当前/无水印初始焦点、三种关闭回焦、提交异常保留并重试、空白透明度不写入。既有大小/来源身份、预设、源样式回读、撤回到来源等回归保留，没有重复完整项目套件。

真实文件烟测45451首次在创建模型阶段失败：当前共享doc_engine/dist/edit-docx.mjs仍是拉取前旧包，inspect模型没有watermark；不把该环境失败算成产品UI RED。按当前源码另打包`/tmp/office-word-watermark-engine-20261112/dist/edit-docx.mjs`，通过既有AGENT_REPORTING_DOC_ENGINE_DIR明确选择，不覆盖共享dist。9022真实浏览器随后在640×360复现新的产品入口问题：预设菜单伸出视口，自定义按钮无法点击，截图`/tmp/office-word-watermark-ui-dev-engine-20261112/watermark-failed.png`可见菜单被底部裁切，pageErrors=[]。仅给该菜单按trigger底边测量可用高度，限制max-height并内部滚动；保留原锚点水平定位。没有用force点击、程序直接调用窗口或放宽可见性条件绕过真实入口。

85117开发环境12场景及真实保存退出0后，50511隔离Vite构建退出0（46.20秒），最终tsc88329退出0；394个JS包原体积预算failures=[]，未修改阈值。构建目录`/tmp/office-word-watermark-ui-build-20261112`，manifest SHA256=c76a55687a1d73929f54b1db74ee3b28a6f2e5ec7e3dde096faf3cad79c4fe54。项目static及共享引擎dist均未覆盖。

最终冻结宿主54869退出0，`/tmp/office-word-watermark-ui-final-built-20261112/watermark-evidence.json`的ok=true、pageErrors=[]。无水印/文字/错误×1440×900、640×360、390×320、320×640共12场景；12次axe均零违规。验证原入口实际点击、模式初始焦点、错误真实Tab进入与至少2px焦点环、逐项控件获焦后的中心命中及主体裁切范围、标题/底部不随主体滚动、三种关闭方式回水印trigger、取消前后草稿相同。截图人工检查390×320文字/错误：标题关闭和取消/确定固定，颜色/版式/错误可在内容区滚动查看，不声称所有字段同时一屏。开发阶段证据与最终冻结证据分开保存。

同一冻结宿主继续验证预设、UndoRedo、删除回来源、中文自定义文字/Arial/72pt/粗体/60%透明度/红色/水平、草稿reload、真实Python/Node保存、HTTP fetch下载及修订2重开。保存应答validation.ok=false仍取得Word链接，未标记验收通过；这里授权/修订/预览HTTP路由仍为显式夹具，预览与patch处理真实文件，不冒称生产授权/DB、浏览器download事件或微软Word实机。138个实际JS响应SHA逐一与冻结构建一致。

独立ZIP/lxml回读`independent-fidelity.json`：来源abd7ea8a8c6ece3de692a0aaecc65a28af06eaa5443f47c8df40e888ebf9ad74，输出7111184ea06bcb5039bde88cee20e60cef945333381aaa24c200f99711fd0a86；水印“内部资料”、Arial/粗体、#C00000、opacity=.4、水平和281×71pt范围均与提交一致。document.xml逐字节相同，原页眉节点exclusive C14N相同，只有header1.xml与core.xml文件部件变化，其余部件逐字节一致、ZIP健康。首次严格成员集比较揭示引擎增加7个目录entry，故明确记录这些空目录并比较文件部件集合，不把目录entry变化误报为内容损坏或宣称整个ZIP相同。

746模块SHA在浏览器退出后与本次清单逐项一致，两份canonical同步并字节回读；5163声明点仍非功能分母。六个产品/测试/smoke SHA及隔离Node桥SHA写入source-verification.json。临时Vite配置归档最终证据目录后只删除自身文件；相关node语法及diff检查通过。共享旧Node包尚未在本批刷新，隔离运行不能替代默认本地运行环境的更新验收。新主题、标尺/参考线、图像像素编辑及四格式剩余菜单/动态状态、桌面实机、Excel Injector竞态继续保留，整体目标active。无提交、推送、部署。

## 2026-11-12 续批：XLSX 主题菜单键盘与分组语义

上一轮为实际progress。本批检查刚同步的页面布局“主题/颜色/字体”，沿用现有136px宽原生select、来源预设与PC功能区外观，不另造下拉图库。浏览器回归16232退出1，应用主题后焦点丢失；进一步诊断80366退出1，确认原select仍连接且未禁用，activeElement实际变为BODY。根因为主题重放期间withWorkbookLocked设置editor.inert；本批只在applyTheme中记录原获焦且菜单类型匹配的入口，重放完成并刷新可用性后，若入口仍连接/可用且焦点仍在BODY才恢复。没有全局更改所有重放操作的焦点策略，用户已经转到外部控件时不抢焦点。

91456原保存烟测修复后退出0。随后新增四视口真实键盘/axe检查，72121退出1，实际暴露功能区h1→h3跳级；保留视觉字号/定位，仅把工作簿分组标题改h2并同步对应样式与两处测试的语义选择器。没有屏蔽heading-order。54579主题数据/可用性与grid guard两文件9/9，29353功能区/AI入口两文件55/55，合计64个不同定向用例；未重复完整套件。缺主题/字体方案、读取失败和只读可用性在既有主题单测覆盖，不扩称本批已经逐种真实浏览器加载这些来源变体。

44721开发环境布局/保存通过后，补充原生键盘选项提交：Alt+ArrowDown打开、Home/ArrowDown定位预设、Enter确认；12765开发环境完整运行退出0。主题Ember、颜色Forest、字体Georgia均用实际键盘选择并恢复对应菜单焦点；另在同一事件周期触发配色重放后把焦点移到外部保存按钮，验证重放期间inert=true且结束后仍保留该外部焦点，再撤销探针修改，最终保存仍只有预期三条主题操作。布局证据结构曾将viewport宽高与控件宽高同名展开，发现后改为geometry嵌套，最终记录保留真实视口，未把136px控件宽度误当视口。

98527隔离Vite构建退出0（49.46秒），97017最终tsc退出0；394个JS包原预算failures=[]。隔离目录`/tmp/office-xlsx-theme-ui-build-20261112`，manifest SHA256=6ca3423fff665a3bd42e35cb5d945ba88afc7c54b3734c7f66449432436f8169。项目static未覆盖。最终冻结宿主41921退出0，`/tmp/office-xlsx-theme-ui-final-built-20261112/evidence.json`：ok=true、errors=[]；三菜单×1440×900、640×360、390×320、320×640共12控件场景，四次整条工作簿Ribbon axe扫描均零违规。验证真实Tab/Shift+Tab、横向功能区焦点滚动、控件中心命中/视口边界/焦点环/字号、选项名称、原生展开后Escape回焦且草稿不变。人工检查桌面与390×320截图，三菜单及主题分组保持PC层次；短屏不宣称网格与所有功能区内容同时充分展开。

同一冻结宿主覆盖三类主题实际应用、外部焦点不被抢、UndoRedo、草稿刷新、真实Python保存、HTTP fetch下载及修订2重开；148个实际JS响应SHA与隔离构建逐项一致。授权/修订路由为显式夹具，不代表生产授权/DB或微软Excel实机。原生select选项弹层由浏览器绘制，axe扫描对象是网页Ribbon；不扩称扫描了操作系统原生弹层。

源文件夹具新增一张实际柱状图。独立openpyxl/ZIP/lxml回读`independent-fidelity.json`：来源f1df7fc458fe47eda1f9f2aca9df19305541b49836a23a0c0c3a10e76ebb97d4，输出ed5554d05a09e9647b79977e330db55efe92e96e93105882899d91602697a4ed；ZIP健康、成员集合相同，仅xl/theme/theme1.xml变化。Forest配色/Georgia主次字体符合目标，原单元格值/类型/style_id相同，chart1.xml及其余非主题部件逐字节相同、柱状图数量仍为1。这里证明文件图表保留，不宣称本批已经验收切换前后所有图表画布像素。

最终浏览器退出后746模块SHA与清单逐项一致，两份canonical同步并字节回读；5163声明点仍非功能总数。七个产品/测试/smoke SHA登记source-verification.json，临时Vite配置归档最终证据目录后仅删除自身。两个smoke语法及相关diff检查通过。四格式新旧未验收动态状态、PPTX标尺/参考线、PDF像素编辑、默认共享DOCX桥更新、图表画布细节、桌面实机和Excel Injector竞态继续保留；整体目标active。无提交、推送、部署。

## 2026-11-12 续批：PPTX 标尺/参考线生命周期

上一目标轮完成远端代码核对，HEAD与origin/code同为448085bf，无远端新提交；本批回到四格式UI目标，整体保持active。本批使用systematic-debugging/TDD/verification-before-completion，先检查真实挂载、切页和dispose路径。根因为slides-guides全局删除所有.slides-canvas参考线、body气泡无销毁接口、拖动window监听没有取消路径，slides-ruler未取消正在拉线的局部监听且旧content一直被ResizeObserver观察；slides-main.dispose没有调用二者清理。

48980先观察6个参考线用例全部RED：多实例互删、隐藏/切content/pointercancel后继续提交、无dispose、没有页面仍在0处新增。6605的5个标尺用例也全部RED：隐藏/取消/切content/销毁后继续上报，旧节点仍被观察。按实例登记参考线元素，增加回滚/移除监听/释放捕获、预览取消、销毁接口与disposed守卫；标尺解除旧节点观察、停止RAF/追踪并移除DOM。slides-main挂接拉线取消和两模块dispose。不修改PPTX数据或发布签发链。

进一步发现切页可能复用同一个画布节点，不能把host引用未变当作拖动可继续的证据；37421新增同host重绘/显式update两例均RED。重绘参考线前撤销旧拖动，外部ruler.update也取消拉线；实际ResizeObserver自身更新刻度仍保留。最终59824的两组件16/16通过，包括持久化成功、其他pointerId不得提交、失去捕获回滚、隐藏预览取消。编辑器定向回归79867中保存锁和对象几何保留2例通过；新dispose集成例初次因夹具默认native=false而找不到功能区按钮，修正为原生夹具后17094的该例通过。没有运行完整套件。

真实组件烟测新增smoke/office-slides-guides-lifecycle-smoke.mjs，使用隔离Vite源码宿主和真实产品CSS/模块、Chromium鼠标与pointer capture。47370首轮四视口通过但Vite默认扫描无关入口导致未配置别名警告；随后只禁用该隔离夹具的依赖发现，未改变产品配置。59824最终四视口1440×900、640×360、390×320、320×640均通过，errors=[]，evidence.json及截图在/tmp/office-slides-guides-lifecycle-20261112。覆盖移动参考线并实际存储、取消/隐藏/换host/同host重绘后的回滚且storage不变、标尺拉线实际pointerup提交、隐藏标尺取消预览、缩放刻度与实际宽度一致、dispose后无叠层/气泡。pointercancel没有鼠标API等价物，明确用真实鼠标捕获后的pointerId分发取消事件；没有称为操作系统真实取消。人工查看390×320截图，标尺和虚线均在隔离组件可视范围内。

这是隔离产品模块组件验收，不是完整编辑器布局、冻结生产构建、真实PPTX保存保真或微软PowerPoint实机验收。本批未添加axe扫描，不引用历史axe结果替代；参考线仍缺完整键盘等效操作、Escape取消及短屏气泡边界等专项验收，继续列为待办。初次整项目tsc 3687因其他会话尚未创建signature-style模块退出2；该文件随后实际出现，1683重跑退出0。本批未修改管理模块。746模块/5163声明点清单重新生成，逐文件SHA核对一致，两份canonical同步并字节回读，source-verification.json登记本批7文件身份。声明点仍不是完成率。

后续仍须完成参考线键盘/短屏气泡、完整PPTX宿主和视图不污染文档的保存回读，以及四格式其他未映射动态状态、PDF新像素编辑、默认共享DOCX桥、图表画布、桌面实机和Excel Injector竞态。无提交、推送、部署，整体目标未完成。

## 2026-11-12 续批：PPTX 参考线键盘与短屏位置提示

上一轮为progress。继续在既有视图组件内实现已授权的PC交互：参考线可Tab选中，方向键按幻灯片原始1px微调、Shift为10px，Home/End到边缘，Delete/Backspace删除；删除后聚焦剩余参考线，最后一条删除后回当前画布。以具名slider暴露方向、0–100位置和距边/中心读数，处理过的按键不冒泡到对象动作；键盘微调直接更新当前元素，避免每次按键重建失焦。Escape只在正在拖线时撤销未提交位置或拉线预览，并移除临时监听。位置气泡按实际测量尺寸限制在视口4px边距内。

62444的7个新增键盘/Escape用例均先RED，77902真实浏览器边界探针RED：1440×900右下预览气泡实际x=1452,y=914，完整越界。相应实现后5094的23个组件用例通过。首次浏览器焦点环检查69197失败（outline 0px）：隔离夹具没加载style.css，office-accent引用的基础色缺失；补充真实基础样式并按项目惯例使用office-focus-ring。1273暴露axe要求使用显式browser context，修复夹具后79455实际扫描发现整条标尺当button时数字与名称不匹配；尝试只隐藏刻度的可访问树不能消除可见名称问题，67281仍失败，未屏蔽规则。

最终采用标尺末端20px原生“+”按钮，名称包含可见“+”及“添加水平/垂直参考线”，Enter/Space原生激活，在页面中心新增；原标尺鼠标拖线保留。随后28243新增“刻度重绘保留新增按钮焦点”用例RED（焦点实际落BODY），改为永久保留按钮和指针节点，只替换独立刻度容器；49878该例转GREEN。真实浏览器加入基础CSS后短屏夹具的旧min-height导致保留滚动位置使标尺坐标在屏外；通过事件诊断确认无pointerdown命中，修正仅隔离夹具的高度/标题边距与最小宽度，不修改产品短屏布局。8927四视口完整通过。

最终87022退出0：/tmp/office-slides-guides-keyboard-20261112/evidence.json的ok=true、errors=[]。四视口1440×900、640×360、390×320、320×640各覆盖真实Tab/ShiftTab、Enter/Space新增、方向键/Shift微调、Delete全部删除后聚焦画布、再经ShiftTab新增、2px焦点环、四次axe零违规、右下位置气泡完全在视口、真实鼠标拖线提交与Escape回滚、隐藏/取消/换host/同host重绘回滚、标尺Escape与隐藏取消、缩放一致及dispose清理。最终14030定向26例通过（23个标尺/参考线、编辑器dispose、两种无效设置的具名键盘错误），21例未选中，未跑完整套件。人工查看keyboard-390x320.png，虚线、焦点环与标尺末端小型加号符合PC辅助视图层级。

本次仍是源码隔离组件浏览器证据，未声明完整PPTX编辑器短屏、冻结生产构建、实际PPTX保存/独立ZIP保真或微软桌面实机通过。未修改文档数据或发布签发链，localStorage视图与文档草稿隔离仍须由完整宿主保存回读证明。清单本次746模块、5165声明点（新增控件不等于新增功能总数或完成率）；逐文件SHA与当前源码核对，两份canonical同步字节回读，source-verification.json记录6个本批文件身份。整体目标active，继续保留完整PPTX宿主/文档保真与四格式其余动态状态、PDF像素编辑、默认共享DOCX桥、图表画布、桌面实机、Excel Injector竞态。无提交、推送、部署。

最终类型检查39170退出0；smoke语法与本批相关diff whitespace检查通过。源清单与浏览器证据中的产品源码身份一致。

## 2026-11-12 续批：PPTX 标尺/参考线完整宿主、保存保真与备注短屏

上一轮为progress，本轮从隔离组件推进至完整原生编辑宿主，使用真实PPTX（三页、粗体正文、超链接、图片、备注）及实际Python/Node渲染/保存引擎。新烟测smoke/office-pptx-guides-smoke.mjs复用背景专项的create/inspect/render/patch夹具协议，但授权/context/修订登记仍为显式路由夹具；预览PDF回退204不属于本轮PDF验收。浏览器下载使用实际download事件和字节身份校验。

62607初隔离构建47.50秒退出0，初manifest=671e025e58cde4c10448d70bc44812b71e4fec46cf4f551c1e082d91da94ba3f。15661首次失败为测试把未编辑的默认参考线误当成已持久化存储，改为读取实际DOM初始值，未修改产品持久化行为。68295随后在完整宿主实际暴露heading-order：h1后直接进入PPTX功能区h3。9871新增分组层级单测RED，PPTX分组改h2并仅调整对应Office样式选择器、AI入口测试；PDF原h3选择器保持原语义。23277的功能区37例与AI入口3例共40例通过，随后隔离构建45.58秒退出0。97426整项目tsc退出0，未重复完整测试。

19075在第二冻结构建四视口运行、真实保存/下载/修订2重开与合成pagehide清理均通过，141实际JS/CSS资源SHA与构建文件相同；但人工截图发现640×360备注展开时画布只有7.5px，390×320和320×640也只有17.5px。这说明入口存在、axe零违规不足以证明布局可用，未把本次烟测通过作为最终版式结论。1679补充画布至少120px布局区域的真实浏览器断言，在640×360明确RED。根因为响应式固定网格空间内备注auto行挤压minmax(0,1fr)画布；针对宽<=900或高<=480的原生PPTX宿主，把有备注的画布行最小值设120px，沿用现有stage/workspace滚动，备注仍可在后面访问，不隐藏来源备注、不改文档数据。14956最后隔离构建45.06秒退出0。

最终冻结目录/tmp/office-pptx-guides-ui-build-20261112，manifest SHA256=9193a8b318a9777b904395896efe00bbf5ffd06dde015eb64f9fd8c86a0d0159；394JS体积预算failures=[]，原预算未放宽。临时配置把outDir及资产/许可证复制路径全部指向隔离目录，不覆盖项目static/共享引擎dist。配置在证据目录归档并字节核对后仅删除自身。

最终33223退出0，/tmp/office-pptx-guides-host-final-20261112/evidence.json的ok=true、errors=[]，141个JS/CSS响应SHA逐一与冻结文件一致。四视口1440×900、640×360、390×320、320×640：两项Ribbon入口按焦点实际滚动后位于视口且中心命中、aria-pressed正确；原生加号Enter新增垂直参考线、方向键/Shift微调、Delete回默认；全过程文档草稿为空。四次功能区+舞台axe零违规。画布布局高度>=120px；备注实际点击可聚焦且中心命中，收起后经View ▸ Notes重新打开，不产生草稿。每个场景结束的程序化scrollTo只是后续场景复位，不冒称用户滚动操作；备注访问本身使用真实点击的自动滚动。短屏截图仍显示画布的可滚动片段，不宣称整页、横竖标尺、全部功能区与备注同时完整一屏。

同一最终宿主还覆盖桌面真实鼠标拖动参考线至约65%、切页/回原页、reload恢复本机参考线；仅通过可编辑正文框输入“参考线专项保存哨兵 PC”作为唯一文档变更，再微调/恢复参考线和隐藏/显示标尺后，保存operations与人工正文哨兵完全相同。真实保存一次、验收ok=false仍有PPTX下载、返回具体待复核原因、实际浏览器download及字节SHA、修订2重开显示新正文和恢复本机参考线通过。合成非persisted pagehide调用真实native-main清理，500ms后无ruler/guide/bubble，errors=[]；仍不扩称真实导航/BFCache或微软PowerPoint桌面实机通过。

独立smoke/office-pptx-guides-verify.py用python-pptx/ZIP/lxml核对：来源6d8a82e5b571aeaa6c4341d56f6ac01a493de00598de878b82a0acd6ea6ba8ff，下载14d9e97d703f459d616b81792dedcdc2e8fd1f09c3b96cc3e0687f2b10254450。文件部件集合相同、ZIP健康，仅ppt/slides/slide1.xml改变；三页顺序/尺寸、原粗体/字号、对象几何、其余文字、备注、超链接、图片及其他部件保留。初次严格C14N比较失败后逐节点对比，证实真实引擎为被编辑形状补了一个精确的a:ext/a16:creationId身份节点；核验只允许这一URI/UUID/属性/唯一子节点，明确不声称只变a:t。剔除目标txBody及该新增注册节点后其余幻灯片C14N相同。核验器另对超链接篡改、额外注册扩展、图片尾部篡改三种故障逐项验证拒绝，未用宽泛删除扩展列表掩盖其他改动。

746模块/5165声明点清单再次生成并逐SHA核对，两份canonical同步、字节回读；7个产品/测试/烟测文件身份在source-verification.json登记。上轮四格式仍未全量映射的菜单/动态状态、PDF新像素编辑、默认共享DOCX桥更新、图表画布细节、桌面实机和Excel Injector竞态继续保留；本次截图也看到来源备注只读原因露出notes_edit_master_registration_invalid原始码，友好文案尚待专项处理。整体目标active，无提交、推送、部署。

## 2026-11-12 续批：PDF 原有图片像素编辑的 PC 分组、异步状态与真实保存

上一目标轮完成远端代码核对，属于有证据的progress；本批继续原四格式目标，不以单批通过宣称穷尽。沿用已授权设计与systematic-debugging/TDD/verification-before-completion。产品限定在pdf-existing-image.ts及对应样式：新增“像素编辑”fieldset/操作标签/具名可聚焦状态；裁剪空值不再Number('')静默转0，透明度拒绝NaN；解码时禁用应用、替换和模式，展示aria-busy。按代次及目标身份丢弃切换、关闭重开、销毁、“不替换”后的迟到解码；失败恢复控件并聚焦具名错误。草稿已写入后若refresh失败，通过编辑器status回调说明“已暂存但预览刷新失败”，不把原因留在已关闭窗口，也不丢草稿。小于480px裁剪四列改两列；显式[hidden]样式修复已有display:grid覆盖hidden，确保翻转不露裁剪字段。

RED证据保留：97093的空值/NaN/分组3例失败；87396的异步5例4失败；58125“不替换”取消竞态失败；95345已暂存刷新失败消息丢失；68992空白裁剪真实提交失败；36447实际390×320输入宽20.5px；55045翻转模式仍露裁剪字段。修复后12382退出0，5个相关文件34/34；67694 tsc退出0。未重复完整测试。最终组件16176退出0，/tmp/office-pdf-image-pixels-final-components-20261112/evidence.json的ok=true、errors=[]；四操作×1440×900/640×360/390×320/320×640实际提交并undo，错误与busy共8次axe零违规，原生filechooser及真实createImageBitmap解码延迟后的切目标丢弃，刷新失败status均通过。人工检查390×320错误/busy截图：固定标题/按钮、可滚动主体、可见提示；不宣称所有字段同屏。该组件夹具本身不证明PDF文件保存。

85376隔离Vite构建退出0（46.56s），/tmp/office-pdf-image-pixels-ui-build-20261112；manifest SHA256=083c6e4f42ead0d2e72953821412dd668534f220acdb1ab3a4dd34149218c342。394个JS包预算failures=[]，未覆盖共享static。完整宿主1811发现默认Python加载的PDF dist过旧，existingImages缺bakeable能力字段；源码支持但默认运行时不可用，未用夹具注入能力掩盖。检查office_engine.run_bridge证实优先dist，随后用当前源码构建隔离/tmp/office-pdf-image-pixels-engine-20261112/dist/cli.mjs，SHA256=c496afc08af12c0984ac1f4e19a1834a3a03fb260089055ad6eef3b55f03f301，通过AGENT_REPORTING_PDF_ENGINE_DIR显式使用；该目录node_modules链接用于本地运行，不冒称已打包可独立部署。默认共享PDF桥尚未更新验收，继续保留缺口。

smoke/pdf-existing-image-bake-smoke.mjs增加显式隔离staticRoot、实际JS/CSS响应与磁盘SHA核对、四视口实际裁剪控件焦点/命中/Escape回焦/取消不改草稿、axe、validation.ok=false仍签发及浏览器download事件、可持久化JSON证据。22245暴露axe需要显式browser.newContext，修正夹具；27637后续超时来自烟测误套PPTX保存状态及字符串issue，核对native-session真实契约后改成已有“已保存修订2”与结构化issue，并额外断言“验收待复核或未通过”。没有为适配烟测修改产品保存行为。

最终92856退出0，/tmp/office-pdf-image-pixels-host-final-20261112/evidence.json的ok=true、pageErrors=[]，147个实际JS/CSS响应SHA一致。完整宿主四视口裁剪字段宽79.5/76.5/90/55px，高28px，实际焦点及中心命中全部通过，4次dialog axe零违规；人工检查完整宿主390×320与桌面图片窗口。水平翻转覆盖UndoRedo、reload草稿恢复、实际PDF预览确认、真实Python/Node patch保存、fetch及浏览器下载事件、修订2重开。保存回执validation.ok=false、具体原因显示且下载可用，不标为验收通过。

独立pypdf回读：来源6e2295868ffedae35c9cc709695c10957bc6bcee06f0bfa8bfe76bd315e6989f；输出525c7051a7424e46b2cab0d2fc3e34de4ed81f2cfa01793fe4e85c38aadd6806。原8×8红蓝分区图按200×150pt、3倍像素烘焙为600×450，左右采样从[220,30,30]/[31,79,216]变成相反顺序；独立2×2绿图两处采样不变、页数1、正文Image bake fixture保留、图像位置范围保持。浏览器下载与fetch/保存字节一致，来源SHA未变。这是选定水平翻转的像素样本及独立对象保留证据，不证明所有像素、所有元数据或所有PDF结构逐字节保真。裁剪/竖直翻转/透明度的组件操作已验，仍须各自真实保存后的像素回读。

HTTP授权/context/修订登记在本烟测中为显式Playwright路由夹具；PDF预览、patch和文件回读真实，不冒称真实生产授权、DB、完整服务器签发链或桌面Office实机。模块清单746模块/5167声明点重新生成，746个源SHA逐项核对、两份canonical同步并回读；声明点不代表功能总数或通过率。source-verification.json登记8文件与隔离引擎/构建身份，临时Vite配置归档最终目录后仅移除自身。相关node语法、diff空白检查通过。后续继续四格式其他动态状态、其余像素操作完整保存、默认共享PDF/DOCX桥更新、图表画布、桌面实机、Excel Injector间歇卸载异常；整体目标active。无提交、推送、部署。

## 2026-11-12 续批：PDF 四类像素编辑完整保存与独立回读

上一目标轮为progress：修复组件并取得水平翻转完整宿主证据。本批针对明确缺口补全裁剪、竖直翻转和透明度保存后的回读，不把“草稿操作正确”当成文件结果正确。当前pdf-existing-image.ts/pdf.css身份仍与上一冻结构建一致，未重复产品完整测试或重新构建前端。使用verification-before-completion，所有完成声明以本轮实际退出码及文件检查为准。

原8×8夹具只有左右颜色，竖直翻转前后相同，不能证明操作发生；本批把目标改成红/蓝/黄/紫四象限，保留独立绿色2×2图与正文。既有smoke/pdf-existing-image-bake-smoke.mjs支持PDF_IMAGE_BAKE_MODE=flip-h/flip-v/crop/opacity，默认水平翻转；全部通过真实产品窗口选择/暂存，核对正确bake与范围、UndoRedo、reload恢复、真实PDF预览确认及对应预览operations、保存、验收失败原因展示、fetch与浏览器download事件、修订2重开。来源和输出写入用wx拒绝覆盖旧证据；每次运行单独目录。没有用CSS截图或固定回执替代实际PDF patch。

新增smoke/office-pdf-image-pixels-verify.py，与产品桥接/烘焙算法独立：pypdf/Pillow检查四象限RGBA、图像尺寸及未编辑图像的完整RGBA像素SHA；PyMuPDF检查页面、两图实际放置范围和正文文本/字号/字体/颜色/位置。首次54986/98568/23464均在独立正文比较RED，定位是相同文字右边界236.51998901367188与236.52000427246094，相差约0.000015pt；未删掉布局比较，将所有浮点按0.001pt精度比较，文字/样式字段仍保留。先在三个已有实际下载文件上独立复核通过，再重跑各自最终完整宿主。每个模式额外证明“未应用操作的来源”以及“把当前输出当作另一操作结果”均被核验拒绝；这是负向交叉核验，不冒称在生产签发链故障注入。

最终竖直翻转65365、裁剪81476、透明度72712均退出0；四象限新夹具的水平翻转29511也退出0，覆盖默认烟测分支。四份evidence.json与汇总/tmp/office-pdf-image-all-modes-20261112/evidence.json均ok=true、pageErrors=[]；每份147个实际JS/CSS响应SHA与同一冻结磁盘构建一致。每种模式包含四视口窗口字段焦点/实际命中/Escape回入口/取消不改草稿，共16次dialog axe扫描零违规。没有把这些扫描扩称PDF整页或操作系统原生弹层无障碍验收。

独立结果：水平翻转600×450四象限左右互换；竖直翻转600×450上下互换；右裁50%得到300×450红/红/黄/黄，放置宽200pt缩为100pt，顶部与高度保持；透明度输入40%得到四象限Alpha153、RGB保持。四种输出的独立绿色图片完整RGBA像素SHA、位置、正文及正文样式保持。浏览器下载、fetch与保存文件身份一致，来源文件身份未变。这里证明选定夹具的像素样本、完整独立图像像素及结构字段，不宣称所有目标像素、所有PDF元数据/内容流字节保真。人工查看裁剪实际预览（仅左半红黄图，绿色图及正文保留）及透明度40%窗口，未将DOM截图当独立像素结论。

最终证据目录分别为/tmp/office-pdf-image-flip-h-quadrants-final-20261112、/tmp/office-pdf-image-flip-v-host-final-20261112、/tmp/office-pdf-image-crop-host-final-20261112、/tmp/office-pdf-image-opacity-host-final-20261112；每份归档本次executed-smoke.mjs及independent-verifier.py。输出SHA依次为9af8a14b5da29265eb9be8caca502d00baaf0562612d32eb8715704723677965、e768eb12c522b441a4578517eaa1ab8aeb43bae72ea1d49285ed6ac5b0dd7589、736217734a025c451ffbfd12e4f6ca014df88ecfa4208dd59e19bc78c29bfa1d、cc6ba65394675e81bb113732c5392614fdc46851b1a91c7abbeeca25cc5fbd55。汇总登记产品/烟测/独立核验脚本SHA、构建manifest及实际隔离PDF cli身份，回读核对所有PDF和已加载资源。

本批无产品源声明变化，沿用746模块/5167声明点清单，不重新生成制造变化。相关JS语法、Python AST及diff空白检查通过。授权/context/修订登记仍是显式HTTP路由夹具，真实PDF预览和patch由隔离最新Python/Node路径执行；不冒称生产DB/授权、完整服务端签发链或桌面实机通过。默认共享PDF/DOCX旧桥仍待更新验收；四格式剩余动态状态与菜单、PPTX备注只读原因裸技术码、图表画布、桌面实机和Excel Injector卸载竞态继续跟踪。整体目标active，无提交、推送、部署。

## 2026-11-12 续批：PPTX 备注只读原因与读屏关联

本批修复实际宿主中notes_edit_master_registration_invalid裸露问题。slides-notes新增slidesNotesReadOnlyReason：notes_edit_master_*显示“备注母版结构暂不支持编辑；可查看或复制现有备注。”，其他notes_edit_*显示通用来源结构提示，自然语言原因原样保留，无原因沿用原默认提示。面板、草稿校验及AI备注候选的只读错误共用转换；不修改引擎诊断码、来源能力或放开写入。textarea通过实例唯一ID的aria-describedby关联原因，保持readonly及原文本，非disabled。源码接口说明同步。

30074新增5例先RED（3内部码失败、2自然语言/默认原因通过）；25852组件16/16通过，但主编辑器12例均因jsdom缺ResizeObserver失败，栈定位新标尺挂载，参照已有slides-main.test.ts仅在本测试夹具stub并清理；83800主编辑器12/12通过。8825新增描述关联/多实例用例先RED，补齐aria-describedby后78820组件17/17通过。合计29个不同定向用例，未运行完整套件。54216最终tsc退出0。首次隔离构建完成后发现描述关联缺口，因此实现后重新构建；27060最终构建退出0（47.85s），394个JS预算failures=[]。

冻结目录/tmp/office-pptx-notes-reason-ui-build-20261112，manifest=a837b4f2dbfc9cd53a98f47727271afdb69c1cfc9231a0addd149eb1873924ac。复用完整PPTX参考线烟测，增加真实备注中文原因、aria-describedby实际指向内容、readonly、Ctrl+A选中全部原备注、尝试键入不覆盖、操作后草稿不变与四视口截图。42154最终退出0：/tmp/office-pptx-notes-reason-host-final-20261112/evidence.json，四视口1440×900/640×360/390×320/320×640通过，4次Ribbon/stage axe零违规，errors=[]；141个实际JS/CSS资源SHA与冻结磁盘一致。人工检查390×320备注截图，提示可见，标题、只读文本及收起按钮可访问；原生复制能力未以系统剪贴板读回验收，不把全选成功扩称已验证剪贴板。

同一宿主保留参考线/视图草稿不变、唯一正文哨兵真实保存、validation.ok=false仍下载且具体原因展示、浏览器download、修订2重开及合成pagehide清理。独立ZIP/python-pptx/lxml核验通过：来源26160348122a9a24884420ad9fcbde2e7fc83b342c733c9c54d8722ed8f9dc45，输出ce0836e70b8fc22ef0f61d6c1049357716e703b768b08a8eae439cc35be0a73d；仅slide1.xml目标正文和精确creationId身份节点变化，原备注、链接、几何、图片及其余部件保留，额外链接/扩展/图片篡改3类负例被拒绝。授权/context/修订路由仍为显式夹具，渲染/patch真实，不代表生产DB/授权或桌面PowerPoint实机。

746模块/5167声明点清单重新生成、746源SHA全部核对，两份canonical同步并字节回读；不是完成率。六个产品/测试/说明/烟测SHA写入source-verification.json；配置及实际烟测归档后只删除自身临时配置，未覆盖共享static。JS语法、相关diff空白检查通过。默认共享PDF/DOCX旧桥、四格式未映射动态菜单与状态、图表画布、桌面实机及Excel Injector卸载竞态继续待办，整体目标active。无提交、推送、部署。

## 2026-11-12 续批：XLSX 图表标题画布宽度与命名空间来源预览

上一目标轮为progress。本批继续图表画布缺口，先复用workbook-chart-render-smoke真实FastAPI服务及独立截图像素核验；99597在上一冻结构建的正负值/缺失/零值3图基线通过（171资源）。源码检查发现chart-render直接title.slice(0,24)：宽图也丢字、窄图仍可能越界。14938两个新增定向用例均RED。产品仅在标题绘制处复用既有fitted/measureText，按画框宽度减12px决定完整或省略显示，明确left/alphabetic，并单独clip标题区后restore。不改变图表数据或操作写回。65851现有画布文件37/37通过。

新workbook-chart-title-fixture.py创建真实openpyxl TwoCellAnchor图表，保留原默认命名空间。27090浏览器在charts store等待超时，page/console/HTTP/asset错误均空；不是标题浏览器RED。检查实际ZIP证实drawing和chart以默认命名空间书写，而chart-read只匹配固定xdr:/c:，导致合法来源静默不进入预览。未改夹具前缀掩盖问题。使用项目已有saxes(namespace=true)在读取时按实际URI形成内部匹配标记，复用现有类型/标题/系列/坐标轴解析；只读临时字符串，不改来源ZIP。相同词法c前缀绑定外来URI不再被当成图表。默认/任意前缀、外来同名前缀3例64833均RED，69747命名空间/既有chart-read/axis-title/value-scale四文件25/25通过；补正合成测试图表关系Type后6024该3例再通过，不重复完整套件。实际最初openpyxl文件也直接readCharts读回3种标题和系列引用，源文件保留。

88231最终隔离构建退出0（47.05s），目录/tmp/office-xlsx-chart-title-final-ui-build-20261112，manifest=efa7cb823e700fc8b74eeadef6a1335563d9974c2308996156aaffb9529a29e1；394个JS包预算failures=[]。32390前端与67971引擎tsc均退出0，未覆盖共享static。41576首轮新构建浏览器失败来自夹具错误预期：14字中文标题在实际176px图框内可以完整显示，未出现省略是正确行为。保留此证据并将中文样例扩为含地区/部门/年度的长标题，确保确实超宽；没有削弱产品断言或缩小字体。54534最终title流程退出0，18860同构建geometry回归退出0。

最终/tmp/office-xlsx-chart-title-browser-final2-20261112/summary.json与/tmp/office-xlsx-chart-geometry-final-20261112/summary.json均ok=true，pageErrors/consoleErrors/httpErrors/assetErrors为空，每份171个实际JS/CSS响应SHA与冻结磁盘一致。标题场景独立从源OOXML读取完整3标题，从最终截图恢复宽792/176/88px的3图框，标题区域深色像素393/361/98，图框右侧对应标题高度区域深色像素均0；实际canvas fillText观察确认宽图完整长标题、窄中文省略和窄W串省略，包装调用仍委托真实fillText，未伪造像素。人工检查最终全编辑器截图。几何回归仍有5/5/0柱条，正负方向、长度比例、缺失位置和零值没有制造像素，标题/网格文本实际像素存在。

两组使用原生grant开启路由、cookie与实际文件接口的隔离FastAPI服务，仓储/工作区为测试夹具；本批没有调用AI规划器（plannerCalls=0）、没有保存修订（savedRevisions=0），实际input.xlsx、服务器source.xlsx和服务读取的来源SHA逐字节一致。标题源89dfa3777919a100e01dfa2a704200b95e3b0ec45498f300f4dce0b2c97300e3，几何源b9d1dd43b2e0a228cda5c1d0aa18b99b02e421f5c9a0e4ea1850897213d93777。这里证明真实桌面视口的只读画布改进和文件不被视图修改；不宣称生产DB、主题切换全部颜色、短屏图表操作、完整保存/下载、操作系统实机或画布无障碍树已验收。

发现的后续缺口显式保留：chart-read当前只枚举twoCellAnchor，未读EMU偏移；画布仍以单元格范围估算画框，本批只检查文字不越实际画框，不证明源锚点几何精确。新增默认/任意命名空间只读预览不等同于chart-edit写入链已支持这些来源，其写入兼容仍须专项验证，不能根据预览出现就宣称可编辑。全文标题的画布可访问描述、图表主题像素、其它图例/坐标轴状态及剩余四格式菜单继续跟踪。

746模块/5167声明点重新生成并逐SHA核对，canonical两表同步并回读，外部引擎源/测试另单独登记SHA（不把它误算进src闭包清单）。最终两目录归档source-verification.json、实际smoke，标题目录归档实际Python夹具、预算、清单和临时构建配置；配置仅删除自身。JS语法、Python AST、相关diff空白检查通过。整体目标active，默认共享PDF/DOCX旧桥、桌面实机与Excel Injector卸载竞态等未完成事项仍在；无提交、推送、部署。


## 2026-11-12 续批：XLSX 图框终点边界与正负 EMU 偏移

上一目标轮实际fetch并核对code与origin/code一致，为progress。本批继续既有四格式目标，不将本批通过等同于整体穷举完成。专家检查落实到真实文件锚点保真：原画布以toCell.endX/endY作为终点，多出一列/一行；来源colOff/rowOff未读取，单元格内小图被放大。chart-read的anchor新增四个可选EMU偏移，仅非零值输出以保留零偏移对象结构；偏移接受负数。画布按两端单元格start加对应EMU/9525定位，取两端最小/最大边界，不改变来源ZIP和图表数据。

实施阶段保留RED：chart-render新增普通边界、同格70×60px、负偏移3例失败；namespace读取新增正负偏移1例失败。GREEN日志回读确认画布40/40、引擎namespace与chart-read共8/8，未重复完整测试。本轮37412前端tsc、25877引擎tsc均退出0。52806隔离构建退出0（46.76s），/tmp/office-xlsx-chart-anchor-ui-build-20261112，manifest SHA256=342590314a7c5f2fa857383de6fb8b1940d89453d0a0df798c2b29738d56345f；394个JS包预算failures=[]，未覆盖共享static。

新增smoke/workbook-chart-anchor-fixture.py，openpyxl创建显式等宽列/等高行的真实twoCellAnchor：普通边界、同格正偏移小图、正负混合偏移图；不改默认XML命名空间。独立核验不调用产品坐标代码：从源ZIP读取marker，以截图内B4/D6两个未选中橙色格的完整连通区域标定实际网格89×24px，再比较图框像素。初次97115失败是标定把Ribbon色块计入；1413失败是第一列选中边框让起点间距少1px，改用未选中B4/D6。95923已通过后，收紧核验要求两个标定区域完整，发现旧扫描横界截短第二格；扩展至整幅截图宽度且保持网格纵向范围，未放宽几何容差，89855最终完整宿主退出0。

最终/tmp/office-xlsx-chart-anchor-browser-final3-20261112/summary.json的ok=true。三个图框实际与独立预期逐项相同：[402,307,712,191]、[407,574,70,59]、[399,735,530,193]，依次为x/y/横边像素宽/两横边距离。允许1px抗锯齿边界容差但本夹具差值均0。人工查看全编辑器截图，小图保持70px宽、负偏移起点落在单元格左上方。final2同源结构截图另以最终严格核验器复核，并对源marker故意多加终点一列、删除同格终点偏移两种负控分别拒绝；negative-controls-on-final2-source.json明确登记对应来源身份，不把它混称final3文件。

同一冻结构建63273的geometry回归和35514的title回归均退出0，分别位于/tmp/office-xlsx-chart-anchor-geometry-20261112及/tmp/office-xlsx-chart-anchor-title-final-20261112。5/5/0柱条、正负方向/比例/缺失位置/零值保持；英文宽标题全文、中文/W窄标题省略且框外标题高度区墨迹为0。标题夹具图框宽由旧792/176/88变为来源实际704/88/55px。本批三份summary四类错误数组全空，每份171个实际JS/CSS响应SHA与同一冻结磁盘一致；source.xlsx/input.xlsx/服务读取来源SHA一致，plannerCalls=savedRevisions=0。

源文件身份分别为锚点2b2d942c75aaac5930c0c4e19e9106703e0395a231ef3d848bcd89d73e93e8ba、标题a5d198e679ffd2d8b10eec4a54639303e5891b770ba1a8965ae5af03041704f3、几何99f32bd77e53ca9b325553119d55b7eb1f1c894949f0bffdd059372fa1d1ef24。真实grant/cookie/文件路由的隔离FastAPI宿主继续使用测试仓储与工作区，本批仅验证桌面视口只读渲染，未调用保存或AI，不扩称生产DB、完整保存保真、变焦/冻结窗格组合或桌面Excel实机通过。

清单重新生成746模块/5167声明点，逐源SHA核对，canonical两表同步回读；仍不是功能分母或完成率。最终锚点目录归档六个源/测试/烟测SHA、三组summary身份、预算、日志、清单、实际smoke/独立夹具和临时构建配置；仅移除自己新增的配置。JS语法、Python AST和相关diff空白检查通过。下一批仍需oneCellAnchor/absoluteAnchor、默认命名空间图表写入兼容、画布可访问全文描述/主题像素、其余四格式未映射菜单与动态状态、默认共享PDF/DOCX桥、桌面实机及Excel Injector竞态。整体目标active，无提交、推送、部署。


## 2026-11-12 续批：XLSX 图表说明的全文阅读、系列名称与键盘入口

上一目标轮为progress：twoCellAnchor精确边界/EMU偏移及真实像素核验已落地。本批继续原四格式目标，按已授权的可访问性方向使用brainstorming、TDD与verification-before-completion，不重新申请例行设计许可。现有图表画布未提供可访问全文说明，多图工作表缺少只读标题浏览入口；新增“图表设计→图表说明”，不放开多图编辑或改变图表文件数据。复用createModal及其焦点约束，按当前工作表稳定sheetId找到来源，展示所有可预览图表的完整标题、类型、系列名和名称/值/分类/X值来源区域；没有标题或名称时给出可区分的编号，无法读取来源不假称没有数据。仅说明“可预览图表”，不把不支持的来源误报为文件中不存在。

workbook-chart-descriptions.ts/css沿用Office主题变量、现有GenOffice图标、标题层级/有序列表/具名可聚焦滚动区；源文本只用textContent，不按HTML解释。说明入口在只读、无选区时仍可用，加载/销毁时由宿主守卫。重复打开不会覆盖原触发按钮，工作簿重载时关闭，载入失败和销毁时移除自身弹层/全局按键监听。后续人工截图发现系列名称只显示编号，改复用chart-legend的chartLegendName读取当前网格，外部引用保留缓存；不增加网络读取或复制命名解析器。Univer getCell类型还包含void，最终以薄适配归一化nullish返回，没有类型强转或改第三方接口。

28688初次为缺模块收集失败，不算行为RED；80389 API空壳下5例行为RED。2111组件5例通过，但既有Ribbon图标覆盖用例因chart-descriptions缺图标失败，补复用IconTextBox后70384两文件59/59。83799新增当前网格名称用例RED（错误显示旧缓存），复用画布解析后16103组件8/8。初次四视口宿主虽通过，人工复核final3“start”截图却看到前次滚动位置残留；35717新回归RED（期望0、实际180），修正每次open从首项开始，5586组件最终9/9。与同批未再改动的Ribbon52/52合计61个不同定向用例；未重复完整套件。类型检查20116的void不匹配失败明确保留；21225适配后tsc与构建通过，滚动修复后21999再次tsc及隔离构建均退出0（构建46.42s）。最终394个JS包预算failures=[]。

最终冻结/tmp/office-xlsx-chart-descriptions-final4-ui-build-20261112，manifest SHA256=0b54a36fc913e4989b6488753f310ee5c087a7b804698c3d31b96c3f5a5462e6，未覆盖共享static。复用workbook-chart-render-smoke，WORKBOOK_CHART_DESCRIPTIONS_UI=1启用新独立UI检查模块；显式browser.newContext供axe运行。37801最终完整宿主退出0，/tmp/office-xlsx-chart-descriptions-host-final4-20261112/summary.json的ok=true，page/console/HTTP/asset错误数组为空，171个实际JS/CSS响应SHA与冻结磁盘一致。说明打开后等待实际动画完成再测边界，避免把入场缩放中的尺寸当成最终布局。

四视口1440×900/640×360/390×320/320×640均从首项开始；完整三个来源标题进入浏览器可访问性树，系列显示实际Revenue而不是缓存/地址，来源地址保留。实际键盘激活Ribbon入口、聚焦滚动区、End读至尾部、Tab在弹层内循环、Escape回入口通过；关闭按钮中心实际命中，长标题不制造横向滚动，4次dialog axe零违规。最终弹窗边界分别为[400,189.5,1040,710.5]、[20,16,620,344]、[20,16,370,304]、[20,16,300,624]；短屏滚动区108px高、正文404px，可滚动而不是裁掉内容。归档每视口首项/末项截图，人工检查390×320首项标题自然换行、桌面全部三图说明可读。不是所有文字在短屏同屏显示，也不是操作系统读屏器实机认证。

每视口关闭后native草稿operations与打开前一致、保存状态仍“已保存”；服务plannerCalls=savedRevisions=0。相同宿主仍执行源OOXML标题及独立截图核验：宽704/88/55px三框、宽英文全文和窄标题省略、框外标题区墨迹0均保持。source.xlsx/input.xlsx/服务读取源身份一致，为fcce39be9e3826f90a1fff77a549d43edfdfa472b9bae05d05ff15017ff3f4bf。使用真实grant/cookie/文件路由的隔离FastAPI服务，仓储/工作区为测试夹具；本批不调用保存，不扩称生产DB/完整签发链/保存保真或桌面Excel实机通过。

清单更新为748模块/5177声明点，748源SHA逐项核对，canonical两表同步回读；仍不是功能总数或完成率。最终目录归档十个源/测试/烟测/复用依赖SHA、实际smoke/检查模块/独立标题夹具、预算、RED/GREEN及最终类型/构建日志、清单与构建配置；只删除自己新增的临时配置。JS语法和相关diff空白检查通过。本批只补图表元数据阅读入口，尚未提供逐数据点的完整画布替代文本；oneCellAnchor/absoluteAnchor、默认命名空间图表写入、主题像素、其他四格式动态状态/菜单映射、默认共享PDF/DOCX桥、桌面实机与Excel Injector卸载竞态继续待办。整体目标active，无提交、推送、部署。


## 2026-11-12 续批：共用弹窗与 PPTX 输入法按键保护

上一目标轮为progress：图表说明已实际接入并完成四视口核验。本批按systematic-debugging/TDD继续专家键盘检查。源码确认createModal的全局Escape监听不检查isComposing/defaultPrevented，PPTX超链接/查找替换/图表编辑另有自定义keydown同样直接关闭；超链接Enter还会提交、查找Enter会导航。PDF多数原生dialog未自行截获这些按键，不能因共用缺陷推断其全部出错。本批产品只在modal.ts与上述三个PPTX窗口入口加同样的isComposing、keyCode===229、defaultPrevented早退，不改关闭回调、忙碌拒绝关闭、提交或文件写回规则，没有全局拦截所有输入或自行维护输入法状态机。

74509共用modal新增4例，3例RED、既有忙碌关闭契约1例通过；修复后50696共用modal/focus-trap/Word题注/XLSX设计与说明5文件28/28。第一次定向命令含不存在的docx-table-alt-text-controls.test.ts路径，Vitest只匹配实际5文件，未将其算作通过；随后用正确docx-table-alt-text-ui.test.ts及PDF提取、PPTX尺寸3文件81493退出0，26/26。85214三个PPTX窗口5个新增用例均RED，分别保护Escape/Enter组合态、legacy229及已消费事件，不触发关闭/提交/导航且保留字段值及焦点；修复后61744三个完整定向文件46/46。共100个不同定向用例，未重复完整套件。

复用office-dialog-layout-smoke与产品组件夹具，新增OFFICE_MODAL_IME=1检查：显式合成isComposing/229/defaultPrevented Escape，确认窗口/字段/焦点保持；再由子字段一次性消费Playwright实际Escape，确认父窗口不关闭，随后普通Escape仍关闭并回入口。62967退出0，/tmp/office-shared-modal-ime-components-20261112/evidence.json覆盖DOCX脚注、XLSX页眉页脚、PDF保护、PPTX超链接与图表数据，1440×900/640×360/390×320/320×640共20例，20次axe零违规，failures/pageErrors均空。PDF在这里是原生dialog对照验证，不声称修复了其输入法缺陷。

为PPTX查找新增产品组件夹具pptx-find-ime，标注无主确认操作；65114退出0，/tmp/office-slides-modal-ime-enter-components-20261112/evidence.json的超链接/查找共8例、8次axe零违规。除Escape检查，三种Enter事件均保持窗口、字段值及文本状态，没有调用提交或查找动作；普通Enter动作由真实产品单测验证。组件宿主/回调为夹具，不证明文件保存、生产授权或系统输入法候选窗操作。

74209前端tsc与隔离构建均退出0，构建46.54s；/tmp/office-shared-modal-ime-ui-build-20261112，manifest SHA256=360af1f746803934dbd2df37b76bc4051d4e84476b77bd700c61f35993c9b33e，394个JS包预算failures=[]，未覆盖共享static。10401最终冻结完整XLSX宿主退出0，/tmp/office-shared-modal-ime-built-host-20261112/summary.json的ok=true、四类错误数组为空；171个实际JS/CSS响应SHA与磁盘一致。四视口图表说明验证三种Escape保护及实际已消费Escape，普通Escape关闭回入口、Tab约束、首项滚动重置、4次dialog axe零违规；native草稿operations不变、状态仍已保存。原图表标题全文/省略及独立像素边界回归保持。source.xlsx/input.xlsx/服务读取源SHA一致，为5dcf9a04db66a386a4e2b917339c47b81a23f1471797368951a0aaaafb61e1a2；plannerCalls=savedRevisions=0。真实grant/cookie/文件路由，仓储/工作区仍为隔离测试夹具，不扩称生产DB、完整保存或桌面Office实机。

748模块/5177声明点重新生成、逐源SHA核对并同步canonical两表，非功能总数/完成率。最终built-host目录归档12个产品/测试/烟测SHA、实际组件与宿主检查脚本、清单、预算、RED/GREEN/类型/构建日志和配置；两份组件证据及原目录SHA登记。JS语法与相关diff空白检查通过，仅移除自己新增临时配置，无提交、推送、部署。组合态浏览器事件为合成测试，实际按键仅用于已消费/普通Escape；不得据此声称真实系统中文IME已验收。嵌套自定义弹窗层级、其他独立keydown（如几何/画布工具）的输入法行为仍需后续针对性审计；其余四格式未映射动态菜单/状态、单锚点图表、主题/数据点替代描述、默认共享PDF/DOCX桥、桌面实机与Excel Injector竞态继续待办，整体目标active。


## 2026-11-12 续批：PPTX 几何错误提示、输入法按键与实际保存保真

上一轮实际fetch并确认code已与origin/code同步，为progress。本批继续四格式目标，收尾已开始的大小与位置面板检查。顶尖专家还会把数值错误、输入中的草稿、已提交几何和文件保真分别核验；不能只看面板外观或单测。本批在既有尺寸/缩放/位置分组上补齐范围错误字段的aria-invalid、字段到唯一状态说明的aria-describedby，以及可聚焦状态说明的主题焦点环。keydown保留原isComposing保护，并增加legacy keyCode=229与已消费事件保护；普通Enter提交、Escape撤回及焦点恢复保持原契约。

几何三份定向测试22/22（13+5+4），本次不重复完整测试。前轮新增3例先RED，日志/tmp/office-pptx-geometry-validation-red-20261112.log；GREEN与类型检查日志已归档。首轮完整浏览器失败是烟测在Escape清空状态后仍用可见role定位器查找被p:empty隐藏的元素，定位器超时；仅将清空断言改为直接读取状态节点，没有改产品以迎合测试。第二轮/tmp/office-pptx-geometry-validation-host-final2-20261112完整宿主通过，但人工截图发现无效输入框仍为普通边框：office-theme通用样式覆盖同优先级的错误规则。真实Chromium最小样例RED读到rgb(191,211,234)，期望rgb(180,35,24)；将现有错误选择器限定为input[type=text][aria-invalid=true]后GREEN。完整布局烟测新增实际边框颜色与主题danger颜色比较，避免只检查DOM标记。保存等待定位器同时兼容宿主slides-save-state及原外壳save-state-label。

1924的tsc与初始隔离构建退出0；CSS修正后93758最终隔离构建退出0（不重复类型未变化的检查）。最终目录/tmp/office-pptx-geometry-validation-final-ui-build-20261112，manifest SHA256=0f102cc596540b05dcd826f593607a72562fcbc179f5924d3d523802afb4e144，394个JS包预算failures=[]。没有覆盖共享static。81227最终完整宿主退出0，证据/tmp/office-pptx-geometry-validation-host-final3-20261112/evidence.json，ok=true。形状和图片各覆盖1440×900、640×360、390×320、320×640，共8组；48个Enter/Escape组合态、229及已消费合成事件保持草稿，普通Escape撤回并回焦；越界字段标记、实际错误颜色、关联说明、状态焦点环/命中/视口可见、撤回清除错误均通过。8次面板axe无违规，短屏24组Ribbon命令滚动检查通过；每次只读布局检查后的native草稿均与检查前相同。人工复核最终桌面及390×320图片错误说明截图。短屏需滚动阅读不同区域，不意味着全部字段同屏；合成事件不证明系统中文IME候选窗实机通过。

最终浏览器129个JS响应SHA与冻结磁盘一致，pageErrors/consoleErrors/routeErrors/failedResponses全空。真实两页PPTX来源SHA256=569cd098199e142687725d917547963509a924df275e0f32bb197989587f9952。经厘米/百分比字段修改形状与图片，撤销/重做、草稿重载后实际保存1次为revision2，读取签发下载地址并fetch实际文件，SHA与size匹配回执。独立Python/OOXML回读断言除slide1.xml外全部ZIP部件SHA不变，目标几何精确符合预期，文字、对象身份、图片及裁剪保持；重新打开字段为宽6.35cm、高3.18cm、水平5.08cm。输出SHA256=daa0b73783a5104c224381d14e8a243db3ae60a78f1ad360e02d29e236652476。HTTP授权/CSRF/修订/下载路由仍为Playwright显式夹具，预览/渲染/patch/独立回读为真实Python引擎；PDF附件是占位。本批validation.ok=true，不宣称生产DB、完整发布门禁失败非阻断或实际浏览器下载事件通过。

748模块/5177声明点重新生成、逐SHA核对并同步canonical两表，仍非功能总数或完成率。最终目录归档8个产品/测试/烟测源SHA、实际烟测/Python夹具、清单、预算、RED/GREEN/类型/构建/宿主日志、两份构建配置及source-verification.json；只移除自己新增的两个临时配置。JS语法与相关diff空白检查通过，无提交、推送、部署。整体目标active：嵌套自定义弹窗层级、其余四格式未映射菜单与动态状态、XLSX单锚点图表/默认命名空间写入/主题及逐数据点描述、默认共享PDF/DOCX桥、桌面Office实机及Excel Injector卸载竞态仍未完成。


## 2026-11-12 续批：共用弹窗层级、单选组导航与 PDF 等待态阅读

上一批PPTX几何错误与真实保存保真已落地，为progress。本批在用户暂停后恢复，先读回中断前代码与日志，按更新后的AGENTS约束继续；不引入CodexAgent容器或改变其它业务链路。使用已加载的brainstorming、systematic-debugging、TDD及verification-before-completion落实已授权的可访问性方向。专家除外观还会检查多层窗口的按键归属、入口链、浏览器实际Tab顺序和等待时阅读能力。源码原先每个createModal都在window各自处理Escape，单次按键可关闭多个窗口；预先创建的可复用子窗也可能位于后创建父窗之后，出现焦点与视觉层级不一致。

modal.ts现在按打开顺序维护现有自定义弹窗；只有最上层接受关闭请求。Escape在最上层自身边界消费，并保留window兼容入口，避免按键先冒泡至祖先面板；组合态、229及已消费事件保护继续保留。原生dialog中的Escape交给其自身处理，不关闭下面的自定义窗口。打开时只在原父节点内移至末尾，不改用portal或重建正文；重复open保留最初入口。底层close/remove不抢顶层焦点，并将受影响的入口链回接到有效外部入口。并列底层窗口inert且aria-modal=false，关闭顶层后恢复；真正包含子窗的祖先不设inert，以免连带禁用子窗，键盘边界由最上层焦点约束处理。忙碌关闭仍由原onRequestClose决定，底层遮罩不代为关闭。

中断前初始5个新增用例RED，首次10个相关用例GREEN。续查新增边界出现5个RED；真正嵌套且只有一个焦点控件的Tab另有1个RED，修正focus-trap对已消费Tab的重复处理。浏览器随后在真实XLSX缩放窗口发现Shift+Tab逃出：未选中的单选项被当成首项，而浏览器只停靠组内已选项。新增radio用例RED后按name及form分组，只取已选项（无选中时取首项）；排除负tabindex及fieldset继承禁用的候选，另有独立RED。祖先Escape监听的1例RED后补弹窗自身处理与remove时卸载。保留所有RED/GREEN日志，不将只验证DOM的单测当作真实键盘证明。

真实PDF提取窗口继续暴露原生dialog末尾Tab可进入浏览器外壳，空闲与等待2例均RED；复用现有installFocusTrap并在dispose卸载。短屏等待态axe再报pdf-extract-body scrollable-region-focusable：页码禁用后该滚动区没有键盘入口。独立阅读用例RED后，仅给既有body增加具名region“提取说明与进度”、tabindex=0及内侧主题焦点环；不改变提取参数、请求身份、生成/下载或验收失败保留链接逻辑。最终modal15+focus-trap4+PDF提取13=32例通过；最新七份调用方定向回归46例通过，合计78个不同用例，非全仓完整测试。PDF原有验收失败保留链接、延迟结果、错误重试用例保持通过。

组件浏览器最终目录/tmp/office-modal-stack-components-final6-20261112，28483退出0，evidence.ok=true。七类为实际XLSX缩放子窗、实际DOCX表格标题/说明子窗、真正DOM嵌套、忙碌拒绝关闭、底层移除、实际PPTX原生尺寸窗口、实际PDF提取窗口；外层编辑设置及通用忙碌/嵌套窗为显式夹具。每类覆盖1440×900、640×360、390×320、320×640，共28组。720次Tab/Shift+Tab、84个受保护Escape合成事件、实际普通Escape关闭/回入口、底层移除后保留草稿值、反序创建的实际命中及草稿未提交检查通过。PDF每视口另外检查等待态：说明滚动区焦点环、End/Home阅读、禁用输入与生成后仍可关闭；请求回调为永不完成的计数夹具，不产生文件。28次打开态加4次PDF等待态axe，共32次零违规；page/console/HTTP错误数组全空。人工查看XLSX桌面、真正嵌套390×320、PPTX桌面和PDF短屏等待截图，短屏阅读区保留固定标题/操作区。

组件探索记录完整保留：最初运行xlsx反向Tab为真实产品RED；final2已通过24组后PDF首尾Tab失败；final3因运行中修改夹具触发Vite page reload造成导航超时，日志明确记载10:43:42 PM page reload，不算产品行为失败；final4在PDF短屏等待态axe失败。final5通过后又收紧底层移除场景的草稿读取断言，最终final6稳定源码重新验证通过；不依赖中间混合版本作结论。IME检查是合成事件，实际Escape与Tab来自Playwright键盘；不宣称真实系统候选窗或操作系统读屏器通过。

最新21042类型检查退出0，38954隔离构建退出0（45.86s）。冻结目录/tmp/office-modal-stack-verified-ui-build-20261112，manifest SHA256=cea66d012191ab6a399bf7335bd4735e2f81dbf69ffc79d11f858a94f7294c1d；394个JS包预算failures=[]，未覆盖共享static。初次宿主因预置归档目录与烟测exclusive mkdir冲突而EEXIST，未执行产品步骤；改用全新目录，不放宽烟测创建条件。74319完整XLSX宿主退出0，/tmp/office-modal-stack-built-host-final2-20261112/summary.json的ok=true，171个实际JS/CSS响应SHA与冻结磁盘一致，四类错误数组全空。四视口图表说明Tab约束、全文可访问性树、滚动重置、组合态/229/已消费Escape、普通Escape回入口、4次axe无违规及native草稿不变保持。原独立OOXML/截图标题核验仍通过，长标题全文/省略与画框外像素边界保持。

完整宿主使用真实grant/cookie/文件路由的隔离FastAPI服务，仓储/工作区为测试夹具；source.xlsx/input.xlsx/服务来源SHA一致，为b64cd47c75672eb4a159e402cc44662e01fd3b784c93529c93e0ef045990b730，plannerCalls=savedRevisions=0。本批没有保存XLSX、调用AI或执行真实PDF提取，不将组件回调夹具扩称文件保真、完整发布门禁、生产DB或桌面Office实机。四格式组件检查证明所列窗口行为，不证明所有独立弹窗族、宿主重载时原生窗口入口竞态或任意CSS层叠上下文已覆盖。

748模块/5177声明点重新生成，逐源SHA核对并同步canonical两表，仍非功能总数或完成率。最终built-host目录归档13个产品/测试/烟测与复用依赖SHA及源快照、实际组件证据、清单、预算、测试/类型/构建/宿主/失败日志、四个临时配置及source-verification.json；仅移除自己新增的四个配置。JS语法与相关diff空白检查通过，无提交、推送、部署。整体目标active：其余四格式未映射动态菜单/状态、XLSX独立Enter处理的输入法保护、单锚点图表/默认命名空间写入/主题及逐数据点说明、默认共享PDF/DOCX桥、系统输入法/读屏/桌面Office实机及Excel Injector卸载竞态仍未完成。


## 2026-11-12 续批：XLSX 输入确认边界、外部区域与桌面布局

前一轮按用户要求尝试更新代码：GitHub fetch 两次连接无响应，终止具体挂起进程后确认本地 HEAD 与缓存 origin/code 均为 448085bf；未据缓存声称远端最新。本轮恢复完整四格式 UI 目标，为 progress，继续中断前已有的 XLSX Enter/函数窗口批次；未创建子 agent，未覆盖共享 static、提交、推送或部署。

专家额外核验一次按键的动作归属、候选确认时草稿保护、外部工作簿名称的可访问性、实际按钮换行和短屏键盘操作。本批缩放、合并计算引用输入、函数参数父层和外部区域子字段增加组合态、legacy keyCode=229、defaultPrevented 保护；函数共用 hook 的内部及 window 外部焦点 Escape 同样保护。外部区域输入增加包含来源工作簿名称的 aria-label。父层尊重子字段 preventDefault 后，外部区域 Enter 只插入引用并回到参数输入，不再同时提交旧参数；下一次参数 Enter 才提交最新引用。折叠选区时普通 Enter 只展开，缩放与添加引用维持各自原动作。

中断前新增行为用例 19 RED/11 原例通过，/tmp/office-xlsx-input-commit-red-20261112.log；修复后 37/37 GREEN，/tmp/office-xlsx-input-commit-green-20261112.log，四份为 zoom10、consolidate7、function-dialog-keyboard13、insert-function7。此次读回测试源与 GREEN 日志并归档；后续只改 CSS 与烟测，未重复这组单测或完整测试。首次浏览器的 consumed trusted Enter 失败是测试在同一原生 input 上晚注册冒泡 listener，产品 listener 已先执行；改测试为目标捕获阶段消费，准确验证产品收到已消费事件后的契约，没有为该夹具问题改产品。

初步 24 场景通过后人工截图发现外部区域行“插入”两行、工作表名截断，axe未报告该视觉问题。新增真实 Range 文本行数、select 文本测量与横向溢出检查先 RED（2 行≠1 行），/tmp/office-xlsx-external-layout-red-20261112.log。仅为既有外部区域行增加三列网格、按钮不换行及主题边框/字体；窄屏工作表选择单独一行，保留区域与单行插入动作。桌面与390×320最终截图人工复核通过，工作表“数据表”完整显示。未全局改字体、布局或重构弹窗。

最终真实产品组件浏览器 /tmp/office-xlsx-input-commit-components-final3-20261112/evidence.json，93854退出0、ok=true。六类 zoom/consolidate/args/collapsed/external/catalog 各覆盖1440×900、640×360、390×320、320×640，共24组；132个字段受保护Enter/Escape与48个window外部焦点受保护Escape合成事件、24次实际被消费Enter、480次Tab/Shift+Tab、普通Enter单一动作与最新参数、普通Escape取消/入口恢复、控件实际命中及视口内可见均通过。24次axe零违规，pageErrors/consoleErrors/httpErrors全空。四个外部引用布局场景按钮均1行、工作表选择宽度均超过实际文字所需宽度、无横向溢出。输入法事件为合成测试，不证明系统候选窗/读屏器实机；组件工作表及文件服务是显式回调计数，不声称已保存XLSX。

84440 tsc退出0；88285初次隔离构建45.98s退出0；CSS修正后5357最终隔离构建47.07s退出0。构建保留原zod PURE注释、运行时PDF字体URL和较大chunk提示，未把这些提示称为零警告。最终目录 /tmp/office-xlsx-input-commit-final-ui-build-20261112，manifest SHA256=19a8a9030c7e7742799af01b0f4cde8e80ead0fe628b4c6ebf018366a66ecf1a，394个JS包按项目预算failures=[]。未覆盖共享static。

23120完整XLSX宿主回归退出0，/tmp/office-xlsx-input-commit-built-host-20261112/summary.json，ok=true。171个实际JS/CSS响应SHA与冻结磁盘一致，四类错误全空；四视口图表说明Tab/完整可访问性树/滚动重置/保护Escape/普通Escape与原生草稿未变、独立OOXML及标题像素边界回归保持通过。source.xlsx/input.xlsx/服务来源SHA一致=810a5b6c57156988855f615029f165a7d7a208463e19e1818b167cb1bf2e9bfb，savedRevisions=plannerCalls=0。该宿主回归不含本批函数输入的新端到端写入保存，函数窗口行为由真实组件浏览器证明；不能扩称生产DB、发布门禁或文件保真已验收。

748模块/5177声明点重新生成并逐SHA核对，shaMismatches=[]，同步canonical两表，仍非功能分母或完成率。built-host目录 verification 中归档14个产品/测试/依赖/烟测SHA和源快照、最终与探索组件证据、RED/GREEN/类型/构建/宿主日志、预算、清单、实际宿主烟测及Python夹具、两份临时构建配置与source-verification.json。只删除本批自己创建的两份临时配置；JS语法和相关diff空白检查通过。整体目标active：监视窗口/符号/透视控件等独立键盘处理、其余四格式动态菜单/状态映射、XLSX单锚点/默认命名空间图表写入/主题与逐点说明、默认共享PDF/DOCX旧桥、系统IME/读屏/桌面Office实机与Excel Injector卸载竞态仍未完成。


## 2026-11-12 续批：XLSX 独立工具按键、监视失效状态与固定表头

上一批输入确认、外部区域单动作及布局已修改并完成真实组件/宿主验证，为progress。本轮继续四格式目标，实际检查独立监视、符号及透视控件，未因批次边界缩减整体范围。专家会进一步检查动态来源失效是否被误读为空值、轮询恢复是否重建获焦节点、长表格的固定表头是否盖住实际键盘焦点，以及拖动预览/正式提交是否被输入法或已消费事件错误取消。

workbook-symbol-dialog的分类与网格方向键增加isComposing、legacy229、defaultPrevented保护；监视窗口阅读/关闭、透视控件拖动Escape采用同一现有规则，函数及分组快捷键补legacy229保护。没有重写快捷键分发体系或改变普通按键语义。五份定向测试先10例RED/34例通过，/tmp/office-xlsx-tool-keyboard-red-20261112.log；修复后44/44 GREEN，/tmp/office-xlsx-tool-keyboard-green-20261112.log，具体symbol10/watch11/pivot-geometry16/function-shortcuts3/outline-shortcuts4。透视测试保留真实RTL skeleton与非零滚动缩放映射，不只依赖浏览器视口夹具。

监视来源失效原来只显示“—”及删除线，新增1例RED后改为明确“来源不可用”，保留地址和删除动作；状态文字本身不再划删除线，失效地址仍保留删除线。来源恢复后同一行与删除按钮焦点不变，值/公式恢复。新例独立GREEN（11个原例跳过），/dev/shm/office-watch-unavailable-red/green-20261112.log；与前述44例合计45个不同定向用例，未重复完整测试。未新增发布、下载、业务数据库或Codex运行链路。

真实浏览器长内容场景另外暴露固定表头遮挡：删除监视A1的按钮focused=true、outline=2px，但中心命中“操作”表头th。初始与diagnostic均保留失败，/dev/shm/office-xlsx-tool-state-components[-diagnostic]-20261112。只给现有.watch-scroll增加按行高计算的scroll-padding，为固定表头留出空间。没有降低命中检查或把自动滚动当作可读通过。final版本16场景通过后，收紧烟测为实际Tab/Shift+Tab往返后直接检查焦点/命中/焦点环，不再依赖手动scrollIntoViewIfNeeded；增加来源失效左侧状态截图，并精确断言透视拖动提交anchor。最终94382退出0，/dev/shm/office-xlsx-tool-state-components-final2-20261112/evidence.json，ok=true。

最终组件为empty/populated/unavailable/pivot各覆盖1440×900、640×360、390×320、320×640，共16场景。12组监视场景共108个受保护Escape/Home/End合成事件、实际被消费Escape、普通首尾阅读、实际Tab往返命中、关闭回入口、关闭后900ms轮询停止通过；四组失效恢复保留原行及删除焦点，12次axe无违规。四组真实鼠标pointer capture拖动中，受保护Escape不撤回，实际提前消费Escape不撤回，松开精确提交一次row1/column1/140×110；第二次普通Escape撤回后松开不新增提交。透视浏览器使用真实几何适配器与CanvasFloatDomService，但工作簿、viewport与skeleton映射为显式夹具，不能冒充完整透视引擎宿主。监视数据源也是显式读取夹具，不生成文件。pageErrors/consoleErrors/httpErrors全空。人工查看桌面长内容、390×320失效状态与恢复截图；窄屏表格保留横向滚动，不声称所有列同屏。

71863 tsc退出0，98690初构建47.73s退出0；固定表头CSS修正后48545最终隔离构建退出0。冻结目录/dev/shm/office-xlsx-tool-state-final-ui-build-20261112，manifest SHA256=5d2b34bdddcaf98f17a118e88af2eadd4de8f8e6d97cf36f469b03733166a999，394个JS包预算failures=[]。构建保留依赖PURE注释、运行时PDF字体URL及大chunk提示，没有改预算阈值。根分区余量有限，本批产物放入/dev/shm；没有删除其它工作、覆盖共享static或改远端配置。

完整符号烟测增加显式隔离static目录和Vite preview outDir，避免写或读取共享static；布局检查加入分类/网格受保护导航、实际被消费方向键及axe。首轮19493在首次axe执行前失败，原因是旧脚本用browser.newPage创建隐式单页面context，而AxeBuilder需要显式context；saved=false。仅按报错改烟测为browser.newContext().newPage，保留失败回执，改用全新目录而非覆盖。最终42049退出0，/dev/shm/office-xlsx-tool-state-symbol-built-final2-20261112/evidence.json，ok=true。

完整宿主五分类、公式拒绝、连续插入、修订重开共8状态，各覆盖1440×900、768×720、320×640、640×360、390×320，共40场景、1245控件记录、1085次Tab/Shift+Tab往返、720个保护导航合成事件、80次实际被消费方向键、40次axe零违规。实际普通分类/网格导航没有改草稿；公式单元格拒绝插入、关闭回入口、€的Enter激活、→的Space激活、撤销/恢复、草稿reload精确保留均通过。171个实际JS/CSS响应SHA/尺寸与冻结磁盘一致，manifest前后相同，errors=[]。人工复核桌面几何/其它类别与390×320公式错误说明获焦截图，紧凑网格、正文阅读和固定关闭操作区可达。

实际Python保存一次revision2，浏览器download事件完成并独立读取真实文件，回执SHA/size匹配。源SHA=287f453599456e0fcd65b8f8afc17627b44e1facc84a1474843d6652a25b4ccd；输出SHA=c01c418456a353e03f020172af0f6e78ea5cb60b075ef0bfde757a18b20e3ef5，5611字节。独立openpyxl/ZIP断言目标值“价格 & <保真> 😀€→”、原公式=A2*2、单元格样式/其它值/列宽/工作表保护保持；ZIP部件集合不变，只有xl/worksheets/sheet1.xml变化，受保护sheet2字节不变。签发路由明确返回validation.ok=false及“符号插入版式待复核，文件已生成。”，实际反馈保留该原因，下载仍可用。授权、CSRF、修订登记和该验收结果为HTTP显式夹具，保存/下载/独立回读为真实；不冒称生产DB或所有非阻断故障注入已验证。真实系统IME、读屏及桌面Office实机仍未验证。

748模块/5177声明点重新生成并逐SHA核对，仍非功能数量或完成率。最终built目录verification归档16个产品/测试/烟测SHA与源快照、全部组件探索和最终证据、两批RED/GREEN、类型/构建/预算/宿主日志、清单、源码keydown候选列表、两份构建配置与source-verification.json。源码候选列表只是字符串定位，包含监听卸载/转发等，不是缺陷数量。浏览器等待期间仅完整宿主烟测因Axe错误修正有预期SHA变化，产品闭包全量无SHA漂移；记录旧/新烟测SHA。同步canonical两表，并修正审计开头过期的“当前HEAD/最新模块数”表述为按续批记录。仅移除本批自己的两份临时配置；JS语法、相关diff空白检查通过，无提交、推送、部署。

整体目标active。DOCX导航搜索、PDF主工具栏、PPTX线宽/独立画布等剩余键盘处理仍待逐项行为复现；四格式其余动态菜单/选区/禁用条件与保存映射、XLSX单锚点/默认命名空间图表写入/主题及逐点说明、默认共享PDF/DOCX旧桥、系统IME/读屏/桌面Office实机、Excel Injector卸载竞态继续未完成。以上局部验证不证明所有组件、所有状态或四格式整体完成。

## 2026-11-12 续批：DOCX/PDF 导航输入、压缩窗格与 PPTX 线宽错误阅读

上一轮已成功 fetch origin/code，HEAD、origin/code、FETCH_HEAD 同为448085bf，ahead/behind均0；工作区470个已跟踪改动和312个未跟踪路径保留。该轮提供了远端最新状态的实际证据，为progress。本轮继续四格式目标，没有将整体目标缩减为本批导航修复。专家额外检查输入法组合输入及旧式229、已经被其它控件消费的按键、查找和导航同时打开时的实际可用高度、标题层级、可聚焦且关联字段的错误说明，以及真实保存后的独立文件保真。

已轮询前序21649句柄，确认定向RED结束：四文件98例中本次过滤执行12例失败、1例通过、85例跳过；失败直接涉及导航跳转、失焦/清空、提前提交及错误说明身份缺失。只给DOCX导航搜索与树/标签、PDF搜索/页码/Ctrl或Meta+F、PPTX线宽Enter/Escape补现有isComposing/keyCode229/defaultPrevented三保护。PPTX每实例生成唯一稳定的状态ID，轮廓粗细aria-describedby指向状态；错误状态具名“形状格式状态”、可Tab聚焦、红色文字及主题焦点环，只读来源说明不误涂为错误。未改变普通按键、防抖、保存前flush、撤回同批填充或业务运行链路。80322四文件完整定向GREEN为98/98：navigation13/search18/shape16/pdf-host51。

真实浏览器又复现DOCX窄屏同时打开查找和导航时的遮挡：320×640导航只余约120px，查询框focused=true但hit=false，说明文字覆盖输入；失败截图/回执保留。仅在现有导航窗格内设置纵向滚动、标题sticky与scroll-padding，给搜索、树及页面列表保留最小阅读高度，避免flex将内容压扁；沿用原有桌面侧栏和短屏浮层。最终查询框可实际命中，树与关闭入口可键盘到达，没有通过隐藏查找面板来绕过问题。

PDF真实宿主axe报告heading-order：页面主标题h1后直接出现工具栏h3。分组改为原生h2，并同步两条原有主题选择器、分组测试和旧AI烟测的标题查询，视觉尺寸未变。检查同文件时为标签方向键补三保护。新增4例先RED，随后ribbon11例通过；home/page/view另4例通过，共15个不同用例，与前述98例合计113个不同定向用例。中间一次新测试误把现有英文“AI”写成“AI Review”，仅纠正测试文字，未修改产品翻译；原失败与最终GREEN均归档。未重复全仓完整测试。

新增smoke/office-cross-format-navigation.mjs并接入真实DOCX/PDF烟测；PPTX既有形状烟测扩展保护输入、错误关联/阅读/颜色与axe。PDF烟测新增隔离static目录、Vite preview --outDir及实际JS/CSS响应SHA检查；三种宿主均使用显式browser.newContext以支持axe，不覆盖共享static。探索阶段另两项失败来自烟测假设：Control+F的once消费器先消费了Control本身；DOCX末项Tab进入正文后Shift+Tab有编辑语义，不能被当作普通按钮往返。前者改为只消费f后自行解绑，后者从前一导航控件反向往返，仍检查实际键盘焦点、命中与正文/撤销不变，没有为夹具问题改产品。

最终冻结目录/dev/shm/office-cross-format-navigation-final-ui-build-20261112，manifest SHA256=a193391ea3a2a160fcad60297bf083922fde964e0894b907ef6f53d8af8ccc0e。初次71783构建45.87s、修复浏览器发现后38130最终构建46.99s均退出0；初始31481及最终81537的tsc均退出0。394个JS包预算failures=[]，未调整预算。仍保留依赖PURE注释、运行时PDF字体URL和大chunk提示，不称零构建告警。748模块/5177声明点重新生成并逐SHA核对，shaMismatches=[]；全部模块mtime均早于最终构建启动，构建后再次确认源码未漂移，同步canonical两表。声明点仍不是功能分母或完成率。

19981 DOCX完整宿主最终退出0，/dev/shm/office-cross-format-docx-built-final2-20261112/evidence.json。可编辑/只读各覆盖1440×900、320×640、640×360、390×320，共8场景；384个合成保护事件、普通Enter/ShiftEnter、树/标签普通方向键、已消费真实按键、Escape关闭、88个控件/查询焦点记录与16次axe零违规。149个实际JS/CSS响应（138JS/11CSS）SHA与冻结磁盘一致，errors=[]。真实DOCX/Tiptap覆盖正文和表格、全半角、非BMP精确跨度、字面符号、503匹配/500可见上限、原查找高亮保留及大纲返回页面。导航操作不改正文、存储和undo/redo；可编辑后的既有草稿/历史也保留。此烟测明确禁止save/export，不据此声称DOCX保存回读完成。

24096 PDF完整宿主最终退出0，/dev/shm/office-cross-format-pdf-built-final2-20261112/evidence.json。同四视口、可编辑/只读共8场景，432个合成保护事件、Home/View两处页码正常跳至真实第二页并返回第一页、Ctrl或Meta+F保护、普通搜索逐项/回绕/退出、24个控件焦点记录、8次axe零违规；49个JS/CSS响应（40JS/9CSS）SHA核对，errors=[]。真实三页PDF.js与Python patch覆盖大小写/全词、删除撤销重排后的原始页身份、预览与返回原稿、只读/草稿不变。源与通过HTTP读取的原文件SHA一致=1b8eda313f7d97e7e14bb46b0a6e9747b7a324057f5f9456db7c8757ff8ef2ae；预览SHA=2b31f6c1b493334507c4dd835a499623d40699c64f528cdbc7074de6af19b1f1。没有将原稿fetch误称浏览器download事件，也没有宣称本批PDF保存新修订已验证。

9915 PPTX最终宿主退出0，/dev/shm/office-cross-format-pptx-built-final-20261112/evidence.json。Simple RGB、Inherited outline、Complex source各覆盖1440×900、320×640、640×360、390×320、1440×360，共15场景、135控件记录、15色板/1050色块实际方向键遍历、30个合成保护事件；5组错误状态的字段关联、完整一行、Tab焦点环/中心命中、输入红边与错误文字同色均通过，普通Escape恢复来源线宽且旧定时器不写草稿。15次普通状态与5次错误状态axe均零违规。141个实际JS/CSS响应SHA匹配，pageErrors/consoleErrors/routeErrors/failedResponses均空。初次构建的6251烟测亦退出0；因随后修改共享主题中的PDF标题选择器，针对最终冻结构建重新执行此宿主验证。

PPTX真实保存一次revision2、实际浏览器download事件完成、独立读取回执SHA/size一致并重开。源SHA=018d0183502fe0c150be312b9e0509cf77eb019d5afc6317e05c60df192cba88；输出SHA=fb50b58e380d94d974323311c7ad099f819d61376a6ce686fadf130998bc733a，42762字节。独立OOXML/ZIP断言部件集合不变、仅ppt/slides/slide1.xml变化；目标填充FF0000、轮廓0070C0和3.5磅写入，目标其它属性、复杂来源、其它形状及第二页保留。授权/CSRF/修订登记为HTTP夹具、辅助PDF是占位；Python预览/保存、浏览器下载和独立文件回读为真实，不冒称生产发布门禁验收。

本批合计31个浏览器场景、846个合成保护事件、44次axe零违规；实际系统输入法候选窗、读屏软件和桌面Office实机仍未验证。人工查看DOCX桌面、320×640查找共存和390×320树获焦，PDF390×320搜索及PPTX390×320红色线宽错误获焦截图。证据与22个产品/测试/烟测/构建配置源快照及SHA、全部RED/中间失败/GREEN/构建/类型/预算日志、探索与最终证据、完整清单和summary.json归档于/dev/shm/office-cross-format-navigation-verification-20261112；仅移除本批创建的两份临时Vite配置。没有提交、推送、部署或清理其它会话改动。

整体目标继续active。DOCX/PDF/PPTX其余独立按键、菜单/选区/禁用状态与保存映射仍需逐项行为核验；PPTX画布/图表色板/标尺/参考线候选仅作源码定位，不能当作已确认缺陷。XLSX单锚点与默认命名空间图表写入、主题及逐点说明、默认共享PDF/DOCX旧桥、Excel Injector卸载竞态以及系统IME/读屏/桌面Office实机也继续未完成。不得用本批通过推导四格式功能和动态UI已穷尽。

## 2026-11-12 续批：PPTX 图表色板、配色图库、参考线与标尺

本批继续四格式功能与动态UI目标。专家额外检查弹层在输入法组合输入和已消费事件下是否误开、误关或误移焦；拖动预览是否被错误取消；短屏色板和图库是否完整可达；保存结果是否只改变预期OOXML部件。没有改变普通按键、共享配色数据或另造色板。

slides-native-chart-gallery的ArrowDown/Escape、slides-chart-format-pane的开关ArrowDown和window Escape、slides-guides的方向/Home/End/Delete/Backspace与拖动Escape、slides-ruler的拉线Escape补齐isComposing/keyCode229/defaultPrevented保护。色板内部导航另有顺序问题：先只保护外围仍有3例失败，说明Portal内部委托依然重新处理方向键。现于popup创建的useState初始化器内、React Portal注册委托之前安装原生冒泡守卫，仅对受保护的方向/Home/End停止后续同节点处理。目标控件先消费事件后，守卫才能读到defaultPrevented；改成捕获守卫会遗漏该情形。单测与浏览器均覆盖实际目标消费，不仅传入预设defaultPrevented。共享vendor的color-picker.tsx、color-picker.css、color-input.ts字节与冻结身份相同，SHA记入vendor-identity.json；SOURCE.md仅更新宿主守卫及标尺实现说明。

定向RED记录为17失败/2通过/31跳过；外围修复后独立色板导航仍3失败/8跳过。最终62504退出0，图库7、格式窗格11、参考线20、标尺12共50/50通过；40571功能区图表相关6通过/31跳过，合计56个不同用例，未重复完整测试。37260的tsc退出0，56742隔离构建45.77s退出0。冻结目录/dev/shm/office-pptx-palette-guides-ui-build-20261112，manifest SHA256=8cc196a35f13cfd693d3daa40702c2fb3b4db41fa88400849623ae50f1a023c3。394个JS包预算failures=[]；仍保留既有PURE注释、PDF字体URL及大chunk提示。没有覆盖共享static。

88232真实产品组件鼠标生命周期烟测退出0，components/evidence.json共四视口1440×900、320×640、640×360、390×320；参考线键盘、实际消费方向键、拖动与标尺拉线的受保护Escape、普通Escape撤回、松开提交、隐藏/切页/重绘/cancel/lostcapture/销毁及缩放均通过，4次axe无违规，errors=[]。组件使用显式画布夹具，不代表文件保存验收。43337完整参考线宿主退出0，同四视口4场景及4次axe无违规、errors=[]；141个实际JS/CSS响应SHA与冻结构建一致。真实保存一次revision2、浏览器download并重开，validation.ok=false及“参考线专项验收待复核，文件已生成。”仍可下载；该验收值、授权与修订登记为显式HTTP夹具。独立ZIP/OOXML回读仅ppt/slides/slide1.xml变化，只包含正文哨兵及精确creationId登记；备注、超链接、几何、图片及其余部件保持，foreign_hyperlink/unexpected_registration/foreign_image三类故障均被检测拒绝。源SHA=d34087bcdc5f7f3bd9b15cb08e635b8ad39fba8a32496006f537268a4579cfbf，输出SHA=9b3e55cd54bb5495703a986c25a620623f1695cdd9db4a01b96d25856ec050c2。

54148完整图表宿主正常退出0，chart-built/evidence.json为ok=true。bar/pie/scatter各五视口（含1440×360）共15格式窗格场景，10组色板各70色实际方向遍历、保护开关/导航/Escape、已消费ArrowRight、草稿不变；配色图库五视口各13卡片实际Tab往返，保护打开/Escape、已消费Escape、普通Escape回入口、命中与焦点环通过。15窗格+10色板+5图库axe均无违规，pageErrors/consoleErrors/routeErrors/failedResponses全空，141个实际JS/CSS响应SHA与冻结构建一致。普通点配色、恢复来源、undo/redo、草稿reload、保存后锁定及重开保持。实际一次保存revision2，浏览器download文件58905字节，SHA=8ccc02b353a8713fcdb17c1b5755debdf6de11fd8361bf4d250ede8fa0c614eb，与回执一致；源SHA=91267e84437c5ae5c80b858377269d97e66635ba57f7243bace576e826e335e0。独立读取目标逐点色为0070C0/FF0000，清除原123ABC覆盖；ZIP部件集合不变，只有ppt/charts/chart1.xml变化，其他图表/页/图像/几何/样式与数据保持。授权/CSRF/修订登记为HTTP夹具、辅助PDF为占位；实际Python/Node引擎保存、浏览器下载与独立回读为真实，不能推导生产发布门禁验收。

本批合计28浏览器场景、441合成保护事件、38次axe零违规。人工复核组件/完整宿主390×320参考线及桌面/390×320色板和图库截图。系统IME候选窗、读屏软件、桌面Office实机仍未验证。748模块/5177声明点重新生成并逐SHA核对，无构建后模块漂移；canonical两表字节一致，声明点不是功能分母。全部证据、RED/GREEN/类型/构建/预算日志、清单、27份源快照与SHA及summary.json归档于/dev/shm/office-pptx-palette-guides-verification-20261112；归档源码再次核对无漂移。只移除本批创建的临时Vite配置，没有提交、推送、部署或清理其它会话改动。

整体目标仍active：本批完成上述PPTX专项，不代表四格式穷尽。其余独立键盘、动态菜单/选区/禁用状态/保存映射、XLSX oneCellAnchor/absoluteAnchor与默认命名空间图表写入、主题及逐点说明、默认共享PDF/DOCX旧桥、Excel Injector卸载竞态以及系统IME/读屏/桌面Office实机继续待验收。

## 2026-11-13 续批：XLSX 单单元格与绝对位置锚点漏图

上轮拉取已真实fetch并核实code与origin/code同为448085bf、ahead/behind=0/0；未覆盖本地工作。随后继续四格式目标，先读回54148终态并归档上一PPTX专项，再检查清单中尚未验收的XLSX锚点。本批于11月12日开始、11月13日完成验收，/dev/shm目录保留起始日期。专家额外检查来源图表是否被静默遗漏、图框是否保留源尺寸而非猜行列大小，以及画布与可访问图表说明是否同时呈现来源图表。不能用组件声明或图标存在证明这些行为。

根因：chart-read的命名空间归一化已存在，但锚点循环只匹配twoCellAnchor。新增chart-read-anchor-types.test.ts使用真实createBlankWorkbook/applyChartAdditions/JSZip来源，单单元格和绝对锚点各覆盖常用、默认、任意命名空间前缀；加同页无效尺寸不误伤有效图表及来源字节不变。修复前8例均因图表列表为空而RED。初次测试夹具缺categories字段的错误先修正，未把夹具错误当成产品RED。冻结旧构建完整浏览器对照13534退出1：同一3图表来源只显示1个，保留browser-red/model.json、failure.json与截图，未改低预期。

最小产品修改仅在chart-read：遍历三种锚点；oneCellAnchor保留原from单元格及偏移，用同一单元格加extent表达终点；absoluteAnchor以工作表原点加pos/extent表达两端。复用既有EMU偏移渲染，不估算行高列宽、不改canvas renderer、不改写来源XML。新增读取分支对无效/非安全整数/非正尺寸局部跳过，保留有效同页图表。固定SOURCE-SHA256不变，仅在LOCAL-ADAPTATIONS-SHA256登记本地reader身份并追加SOURCE.md边界。不声称结构插删/新锚点写入/Excel实机互操作已经支持。

68466退出0：新锚点8例+既有读取/命名空间8例合计16通过。2124退出0：frontend tsc及原renderer source chart anchor geometry 3通过/37跳过。18214 engine tsc退出0。合计19个不同定向用例，没有重复完整测试。53313隔离构建46.93s退出0，冻结目录/dev/shm/office-xlsx-anchor-types-ui-build-20261112，manifest SHA256=d2de98791f1887312ffb628255734fcf6323cc54f35412414fb36b154fecbd36。394个JS包预算failures=[]；保留当前构建配置已有的循环chunk提示、依赖PURE注释、运行时PDF字体URL及大chunk提示，未称零构建告警、未调整阈值或共享配置。

39000新冻结构建完整宿主退出0，browser-green/summary.json为ok=true，171个实际JS/CSS响应SHA与磁盘一致，pageErrors/consoleErrors/httpErrors/assetErrors全空。实际openpyxl来源含oneCellAnchor/absoluteAnchor/twoCellAnchor各一；独立Python/lxml从源OOXML读取坐标并使用两枚真实网格色块标定截图列宽89px、行高24px，三个图框实际/预期像素边界分别均为[407,310,480,191]、[406,609,420,99]、[399,735,530,193]（末项是上下边框距离，包含1px边框约定），没有调用产品坐标算法作验收oracle。实际显示全部3图，不只是读取计数通过。桌面整页截图已人工复核。

图表说明另覆盖1440×900、640×360、390×320、320×640四视口：三幅源图标题、系列名和数据引用进入实际可访问性树；End滚动、固定关闭操作、Tab包围、受保护/已消费Escape与普通Escape回入口均通过，4次axe无违规。人工复核390×320关闭按钮焦点截图。与画布检查合计5浏览器场景。来源input.xlsx/source.xlsx/服务身份SHA均为7eb443c0f861204fca0aa8eb282fc05ae640cebd092007566d7006a43cac73dc；savedRevisions=plannerCalls=0，阅读过程草稿未变。此批仅验收读取与显示，没有保存新修订，不能声称新锚点保存/下载或生产发布门禁已通过。

748模块/5177声明点重新生成并逐SHA核对，shaMismatches=[]，所有模块mtime早于构建启动，canonical两表保持字节一致；模块/声明点仍非功能分母。证据、修复前后浏览器、RED/GREEN/类型/构建日志、预算、清单及16份产品/测试/烟测/配置/来源文档快照与SHA、summary.json归档于/dev/shm/office-xlsx-anchor-types-verification-20261112。仅删除本批创建并归档的vite.xlsx-anchor-types.build.config.ts，没有提交、推送、部署、覆盖共享static或清理其它会话改动。

整体目标继续active。本批解决了单单元格和绝对锚点的读取/显示遗漏，但四格式其余动态UI仍未穷尽；默认命名空间图表写入、主题/逐点色渲染说明、默认共享PDF/DOCX旧桥、Excel Injector卸载竞态、系统IME/读屏/桌面Office实机及其余菜单/选区/禁用状态/保存映射继续待验收。

## 2026-11-13 续批：XLSX 来源主题填充、逐点配色与可读说明

上一轮锚点修改、真实像素验收及证据归档为progress。本批继续四格式整体目标，检查“画布所见、说明所读、来源所存”是否一致。实际发现：chart-read只读取系列显式RGB，不投影theme和dPt；bar/column仅按系列填充，pie/doughnut只用固定调色板且numberValues压缩空值，会把后续dPt身份错绑。专家额外检查来源无填充是否被默认蓝色覆盖、复杂填充是否被误称为原色、明暗变换是否保留饱和度与操作顺序，以及颜色信息是否有画布之外的文本表达。

新增chart-fill-read定向用例先7例RED；最初夹具遗漏title的错误修正后，产品RED才以颜色/点身份/主题信息缺失为依据。UI新增8例RED/49跳过，覆盖bar/column稀疏点、pie/doughnut空槽、varyColors=false、noFill、不可预览提示及说明文本。旧冻结构建95404完整宿主对照退出1：实际来源主题accent1未投影，color为undefined而非136B4A；失败模型和截图保留，不降低预期。修复后35157引擎14例通过（7新+7图例），70129 UI59例通过（renderer46、legend2、description11），初阶段合计73个不同用例。

最小接线：chart-read复用既有parseThemePalette/themeSlotIndex，投影工作簿accent调色板、显式varyColors、系列/noFill及稀疏dPt填充；系列与轮廓/点填充严格区分，重复或无效点身份标为预览受限。bar/column/pie/doughnut使用同一颜色选择规则：显式点覆盖、显式系列填充、来源varyColors和主题调色板。pie/doughnut从原数值槽取值，空值不参与扇区但不压缩后续点编号。图表说明追加系列填充、按源编号列出的点覆盖及限制原因，按文本创建DOM，不只依赖色块；沿用现有排版、滚动和固定关闭区，没有重构弹窗。未支持的渐变、图像/图案、透明度和其余颜色变换不再悄悄退回未变换基色，画布与说明给出“来源填充暂不支持预览，请下载原件查看”。这只是渲染提示，不影响保存/下载链路，也未引入业务验收门禁。

先完成普通填充的72130完整宿主（退出0、5来源图表+4说明视口）后，继续补齐常见亮度变换，而非把lumMod/lumOff永久留在预览限制内。新增4例亮度RED/7跳过；style-color的applyDrawingLuminance复用已有HLS转换，按源顺序逐步限幅并在末尾取整；hlsToRgb新增内部round参数且默认false，原单元格applyTint的截断行为不变。初次亮度GREEN有1例因参考注释写2F5496而失败；独立Python colorsys计算4472C4×75%亮度得到通道[47.4878,84.5122,150.5122]、取整2F5597，故修正预期而非修改算法迎合注释，保留intermediate日志。72561最终亮度4通过、18396既有单元格theme/tint回归2通过、45123普通来源填充回归4通过；其余3个不可解析填充回归在intermediate中通过。最终契约为engine填充11+既有图例7+单元格2+UI59，共79个不同定向用例，未运行或重复完整测试套件。其它HLS/色彩能力仍未据此认定通过。

初次10632隔离构建45.32s退出0，最终36265构建48.23s退出0；初次及最终frontend/engine tsc均退出0（21279/92180、19604/42475）。最终冻结/dev/shm/office-xlsx-chart-fills-final-ui-build-20261113，manifest SHA256=eb97c532fb8d453754e31df2bd16d61a0ee32b49f8f381cb15f902de44c6fe1b。394个JS包预算failures=[]，未改阈值。构建保留已有循环chunk、依赖PURE注释、运行时PDF字体URL和大chunk提示，没有称零告警。没有覆盖共享static。

31608最终完整宿主退出0，browser-final/summary.json为ok=true。实际openpyxl来源6图（柱形、条形、饼图、圆环、渐变限制、主题亮度），5个浏览器场景为1组1560×1850画布+1440×900、640×360、390×320、320×640四组说明。独立lxml回读主题槽、dPt idx2、条形idx0/noFill、圆环varyColors=false、渐变两端与75000亮度值；openpyxl确认数据[3,None,6]。最终截图像素独立恢复6图框：柱形/饼/环为136B4A和A02040，条形只保留A02040（第一点无填充），明暗图两柱均2F5597，渐变限制图无虚构色柱。Python colorsys独立计算亮度预期，不调用产品坐标或颜色实现。完整标题和点编号/无填充/系列颜色/渐变原因进入实际说明及可访问性树；4次axe零违规，焦点、End滚动、固定关闭动作、Tab包围、受保护/已消费Escape、普通Escape返回入口和草稿不变均通过。人工复核最终桌面画布、桌面说明及390×320关闭焦点截图。

最终171个实际JS/CSS响应SHA与冻结磁盘一致，pageErrors/consoleErrors/httpErrors/assetErrors全空。source.xlsx/input.xlsx/服务来源SHA均为58e4cf87c7f7c71b2806f44f133ff101015ce48760d50b2c2f93dffed0a633e4，savedRevisions=plannerCalls=0。这是读取/显示专项，不把来源fetch称为浏览器download，也未声称本批保存新修订或生产发布门禁已验证。系统IME、读屏软件与桌面Office实机仍未测试。

清单现为748模块/5178声明点（说明新增一个DOM声明），逐SHA核对无漂移且模块mtime均早于最终构建，canonical两表同步；声明点不是功能分母或完成率。原SOURCE-SHA256保持不动，更新引擎reader/style-color及本地renderer/helper的LOCAL-ADAPTATIONS身份和来源说明。28份最终源码/测试/烟测/配置/来源文档快照、22份初阶段源码、修复前/初阶段/最终浏览器、全部RED/中间失败/GREEN/类型/构建/预算日志、清单和summary.json归档于/dev/shm/office-xlsx-chart-fills-verification-20261113。仅删除本批创建并归档的vite.xlsx-chart-fills.build.config.ts；没有提交、推送、部署或清理其它会话改动。

整体目标仍active。本批完成bar/column/pie/doughnut的上述来源填充接线及亮度子集；其它图表类型、chart-local theme override、渐变/图像/图案/透明度及其余色彩变换仍待实现/验收。四格式动态菜单/选区/禁用条件/保存映射、默认命名空间图表写入、默认共享PDF/DOCX旧桥、Excel Injector卸载竞态和系统IME/读屏/桌面Office实机也继续待验收，不得用此专项通过推导四格式已穷尽。

## 2026-11-13 续批：PDF 拖动、侧栏与字段设置的键盘保护及短屏滚动

上一轮真实fetch/快进检查确认code与origin/code同步，未覆盖现有工作；该轮为progress。本批继续四格式整体目标，不把源码声明数当成功能覆盖率。专家额外检查输入法组合输入与目标已消费事件是否误取消指针事务、偏好设置是否被方向键误写、面板关闭后的焦点返回、短屏标题遮挡，以及真实保存/下载与独立文件回读。

实际根因：pdf-drawing-canvas在document捕获阶段无条件处理Escape，先于目标控件消费事件；pdf-sidebar方向/Home/End及拖动Escape缺isComposing/keyCode229/defaultPrevented保护；三种字段设置共用面板已有前后两保护，但漏legacy229。新增27个定向契约，59245修复前为21失败/36通过（原有普通操作通过）；最小修复把绘图Escape移到冒泡阶段并补三保护，侧栏与设置面板按各自作用域补齐早退。目标真实调用preventDefault的用例覆盖事件顺序，不只构造预设defaultPrevented。12653最终70/70通过，包含既有图片画布13例及绘图19、侧栏17、字段设置21例，没有运行完整套件。

浏览器原冻结构建52448/62409均在首个composition ArrowLeft实际把150改为140并持久化而RED。新侧栏辅助检查中发现两个夹具问题并保留失败证据：320宽屏可用侧栏区间仅120–128，不能硬编码向左10；390×320须先滚动到分隔条再发送真实指针。修正为基于实际ARIA范围的位移与真实scrollIntoView，不降低事件保护断言。97013最终侧栏宿主退出0，四视口1440×900、320×640、640×360、390×320，60个合成保护事件及普通Escape、真实拖动提交/取消、原有键盘上下限、只读/损坏和拒绝存储、切换/卸载/懒栅格/预览返回等均通过；源/HTTP读取原件SHA一致，40个实际JS响应SHA与冻结构建一致。该工作流未保存新修订，原件fetch不称浏览器download。

82444绘图首轮在保存等待超时；此前四视口指针保护已经通过，但不把该轮当保存成功。保留失败日志，保存辅助流程增加实际存在的预览确认、浏览器download及失败状态诊断，随后34394及最终14731均退出0。最终四视口共12个合成保护事件；实际SVG pointer capture在保护Escape后保留，在普通Escape后释放；每次提交后undo回到精确原草稿。完整宿主继续验证双胞胎绘图精确身份、移动/删除、旧面板/旧回调拒绝、undo/redo/reload、旋转与倒序、真实预览、保存revision2、浏览器download和重开。独立pypdf断言三页文字和表单保持、目标正方形唯一且坐标[96,288,172,357]与AP绘图一致，来源旋转/重排保持。40个实际JS响应SHA匹配，errors=[]。授权/修订路由为明确HTTP夹具，实际PDF.js/Python引擎保存及download为真实，不冒称生产发布验收。

字段设置45场景初轮76565实际发现1440×360在连续切换视口后首行输入被sticky标题覆盖，细化到text五视口的73890重复RED：字段top276.5、标题259–304，elementFromPoint命中header。不是把此失败改为允许；pdf.css只给该面板的滚动区域增加54px scroll-padding-top，留出固定标题区域。61387同一五视口路径以及三次真实保存/下载退出0，遮挡消失。无障碍首轮70521因Playwright browser.newPage不允许axe创建辅助页而终止，保留工具夹具失败，改为显式newContext/newPage后99896最终退出0。

最终字段设置为九模式×五视口（含1440×360）=45场景、135个合成保护事件、590个控件命中/字体/尺寸/焦点检查，45次axe零违规；普通Escape回原命令、radio方向选择与表格横滚、输入错误保留值与焦点、undo/redo/reload均通过。三次真实原生服务保存revision5/6/7，均validation.ok=false并正常签发链接、实际浏览器download与回执SHA/size一致并重开。独立pdf-form-settings-file-verify.py不调用产品读写：正文操作数和绘图操作符（只归一化引擎增加的成对q/Q隔离）、文字、页框/旋转、无关字段值和widget几何保持；精确验证新radio三选项/第三项选中、Courier-Bold18/居中/MaxLen32及追加原radio选项后原选择保持。最初原始内容流字节相等断言会把合法q/Q包装当差异，保留调查证据后改为有明确边界的语义操作核对，未声称PDF字节不变。

本批53个最终浏览器场景、207个合成保护事件、45次axe零违规。字段宿主50个实际JS/CSS响应SHA一致，page/console/http/assets错误为空。人工查看390×320绘图、1440×360字段与390×320关闭焦点截图。65882frontend tsc退出0；58961初构建46.44s、29767最终46.03s退出0，394个JS预算failures=[]，保留既有chunk/PURE/PDF字体URL提示。最终冻结/dev/shm/office-pdf-escape-final-ui-build-20261113，manifest SHA256=6dc5a9e57bf3609ec54b36a91809916bb5d701a6a82d0329749ea0b22f10b9b0。未覆盖共享static。

最终清单748模块/5178声明点，canonical两表字节不变；16份产品/测试/烟测/配置源快照、RED/中间夹具失败/GREEN/类型/两次构建/预算、最终浏览器、实际PDF及独立回读归档/dev/shm/office-pdf-escape-verification-20261113。整体目标仍active，实际系统IME、读屏软件、桌面Office以及四格式其余动态菜单/保存映射未穷尽。用户随后明确授权子agent并行，另行推进PPTX剪贴板、DOCX独立页码菜单和XLSX默认命名空间写入；不将尚在进行的并行任务计入本批已通过证据。

## 2026-11-13 续批：按用户要求拉取最新 code 并整合本地对齐工作

前一轮对固定源与当前缺口的复读属于产生下一步依据的progress；本批优先执行用户“拉最新的code代码”。实际git fetch origin code后，远端由448085bf更新到6a713d05（6a713d053527d6b0cec938aeb8c4263709eb1d8b），7个提交、48文件。当前code已fast-forward，HEAD与origin/code相同，ahead/behind=0/0。未提交或推送。

9个与上游重叠的本地修改先逐文件备份与导出补丁，再定向stash；apply发生7个内容冲突。逐处整合图表reader、renderer、测试、烟测及来源记录，保留本地URI命名空间归一、oneCell/absolute锚点、标题度量、稀疏点填充/noFill/亮度/说明能力，并纳入上游刻度、分类排序与标签字体/主题/亮度能力。零值标签不被本地跳过零柱逻辑丢弃。全部冲突已标记解决，暂存区恢复为空；拉取前状态中的路径没有缺失。stash 9fb32929d0b787a70bad551624272be52ae8c9d5及/tmp/office-code-pull-20261113/before与local.patch保留，未清理其他会话文件。

初次引擎整合101通过/1失败：本地旧填充夹具缺少theme关系且仅6个槽，与上游严格真实主题解析合同不同。修正夹具为有效12槽内部关系，增加移动主题与缺失主题负控，缺失主题先失败：旧系列填充逻辑会猜成Office默认蓝色。最小修复为系列填充也使用实际关系解析的palette，缺失主题时给预览限制。最终引擎104个不同用例分批通过（初批其余91加最终fill13），前端105通过，两端tsc退出0。没有重复完整测试。

隔离Vite构建45.84秒退出0，/tmp/office-code-pull-20261113/static，manifest SHA256=e8cedbc254bc3bf7d161e24ab96463440d3ab4b7509cc6631a0fa1531676f188；394个JS包预算failures=[]，未改阈值、共享Vite配置或共享static。保留已有循环chunk、PURE注释、动态/静态导入、运行时PDF字体URL及大chunk告警，不称零构建告警。

沙箱内两组首次完整宿主在server阶段超时，未进入页面，不计产品失败或通过。faulthandler与asyncio诊断保留：原生工作区anyio线程已闲置而主循环等待，任务超时后清理亦迟滞；本批诊断已终止。经授权沙箱外同一脚本、同一冻结资源和合成临时本地工作区复跑两组均退出0。MPLCONFIGDIR限定临时目录，FONTCONFIG_FILE继续复用已有画布字体环境，不修改产品字体或系统配置。

browser-fill-final/summary.json为ok=true：6幅真实openpyxl来源图，独立lxml/颜色像素确认主题136B4A、点覆盖A02040、条形noFill、亮度2F5597及渐变无虚构柱。1440×900、640×360、390×320、320×640四组说明含完整来源、点编号、限制文字及实际可访问性树；4次axe无违规，焦点/滚动/保护事件与草稿不变保持。savedRevisions=plannerCalls=0，不称本组执行过保存下载。

browser-label-luminance-final/summary.json为ok=true：真实6图标签、主题切换、Undo/Redo、1次保存修订4→5、授权HTTP下载校SHA、明确新修订重开；独立OOXML与字形像素确认新主题亮度、系列/点RGB、字号/粗体/位置和两组不应绘制标签。下载SHA256=66b99b6078d0a0f9634d8b8ac7ca624df36d53eaea4365a4899f8c7d826930ac。下载为已授权HTTP读取，不冒称浏览器download事件。宿主复用真实NativeEditorService、授权、CSRF、Python/Node保存/签发，仓储为合成内存夹具；不称生产部署或真实AI provider验证。两组各171个实际JS/CSS响应SHA与冻结资源一致，pageErrors/consoleErrors/httpErrors/assetErrors全空，人工复核两份最终整页画布截图。

重生成清单为751模块/5178声明点，canonical两表与本批输出同步；声明点仍不是功能分母。备份、补丁、日志、诊断/失败/最终浏览器、构建、预算、完整清单和summary.json位于/tmp/office-code-pull-20261113。临时Vite配置归档后仅移除本批创建的该配置。整体目标继续active；本批完成代码同步与合并验证，默认命名空间写入、复杂图表/主题、四格式剩余动态入口/保存映射、完整Agno AI、系统IME/读屏/桌面Office实机仍待继续，不能认定全量对齐完成。

## 2026-11-13 续批：用户授权三条子 agent 并行及独立回读

用户明确要求“子agent并行推进”后，按独立范围启动同模型三条任务：DOCX页码弹窗、PPTX画布剪贴板、XLSX图表命名空间写入；root完成PDF专项、跨任务评审、统一构建与真实文件回读。各自保留共享工作区其它改动，无提交/推送/部署。专家额外工作是验证事件传播顺序和输入焦点、审查XML等价命名空间的实际目标身份、检测重复标题及静默漏改、校验真实下载身份与非目标部件，而非只检查UI声明或图标存在。

DOCX只给docx-page-number-dialog的自定义keydown补isComposing/keyCode229/defaultPrevented早退，保留原焦点trap与保存格式。3新增用例先RED，最终6/6通过；四视口12个源码组件场景验证三保护、实际目标消费Playwright Escape、普通Escape回入口、值/正文不变与零提交。开发态既有page-number全流程曾因React flushSync生命周期console警告退出1，未降低断言；root在统一正式构建81602复跑退出0。真实修订2为upperRoman/0与lowerLetter/5，修订3恢复decimal/续前节并保持第二节；浏览器download、Python/OOXML回读和重开通过，页眉/页脚及关系身份保持，138个实际chunk SHA匹配，pageErrors=[]。真实DOCX1/2/3与证据已复制到联合归档docx-built。

PPTX实际Konva点击后焦点曾留BODY，Ctrl+C/V不执行；window捕获监听又先于目标消费按键，组合态x/v误删/粘贴对象，文本框Escape会退出格式刷。焦点2例和保护6例分别RED，浏览器保留10个真实边界失败。最小改动在slides-main：native画布tabIndex=0，已通过来源/代际/锁校验的单选/框选交接焦点，保留既有group角色及名称；快捷键改window冒泡并同步dispose，三保护早退，editable/dialog过滤先于brush Escape。最终19/19通过。真实源码Chromium验证body/外部按钮/文本框×Control/Meta、空白粘贴、输入/组合态、目标消费、锁定及dispose，errors=[]；不冒称macOS或系统IME。

root为既有pptx-clipboard-links-smoke增加可选真实画布键盘路径，50513统一冻结宿主退出0：实际点击来源图像并Ctrl+C，在第二页空白点击后Ctrl+V；保存重开后同样Ctrl+X/V。完成三个修订保存/浏览器download和独立python-pptx/ZIP回读，最终revision4；图片字节、裁剪、偏移几何、复制图像的新身份与剪切后的来源删除正确，格式刷的文字/段落/填充/线条保持，URL设置与移除正确。129个实际JS响应SHA匹配，page/console/route/failedResponses全空。授权/CSRF/修订路由为显式夹具，辅助PDF为占位，真实Python inspect/patch/render及PPTX下载回读不等于生产部署或PDF转换验收。人工复核revision4桌面截图。

XLSX写入原固定c:/a:及严格无属性标签，与读取按URI识别的能力不一致。默认/任意主prefix先RED；初方案将非主别名opaque的保守做法，经独立review用真实openpyxl来源发现会漏改实际title/ser/barChart，局部xmlns还造成两个title。未将这些失败改成允许：补局部声明3例及真实目标混合别名6例RED后，所有Chart/Drawing URI目标参与既有编辑，恢复时按局部绑定选择来源主prefix；混合别名可规范合并，default shadow不改变目标URI。仅foreign/ext保留不透明原片段，注释/CDATA/PI保留，不整份serialize；修正相关title/chart/plot/series属性匹配。最终四文件76例（namespace16）和engine tsc通过。独立review原两组探针最终9项按URI回读均通过、无重复标题。11份实际保存XLSX独立stdlib ZIP/ElementTree验证，143个非目标部件字节/SHA保持。SOURCE-SHA256原始记录未动，LOCAL-ADAPTATIONS登记writer，SOURCE.md明确混合别名规范化边界。未声称该专项已做浏览器XLSX保存或Excel实机互操作。

27848统一隔离构建46.83s退出0，74213 frontend tsc退出0；394个JS预算failures=[]，保留既有chunk/PURE/字体URL构建提示，没有改阈值。冻结/dev/shm/office-parallel-ui-build-20261113，manifest SHA256=a1a6c90cca03fcffa1ab12b2301ebe85594c20401f969f9556f324e97262677a。最终清单751模块/5178声明点并同步canonical两表；这是定位清单，不是功能分母或完成率。13份源快照及SHA、构建/类型/预算、生产DOCX/PPTX与source-verification归档/dev/shm/office-parallel-ui-verification-20261113；三个子任务完整RED/GREEN/浏览器/独立回读分别保留各自证据目录。构建后其它并发任务仅向SOURCE.md追加同步说明，保留新增内容并分别归档构建时和最终文档；受测751模块SHA无漂移。只归档并删除root创建的三份临时构建配置，没有清理其它会话文件。

与此前PDF专项合计171个不同定向契约通过，未运行完整测试套件；整体四格式穷举仍active。其它动态菜单/选区/禁用状态/保存映射、复杂图表与变换、共享旧桥、Injector卸载竞态及系统IME/读屏/桌面Office仍需继续核查，不能由本批通过推导整体完成。

## 2026-11-13 code同步后的XLSX图表命名空间编辑/删除闭环

本轮接续已有chart-edit命名空间适配，新增chart-delete默认/任意前缀真实ZIP矩阵：15项中10项合法来源先因固定xdr/c/r身份正则RED；改用既有Saxes按URI、解码关系ID、真实graphicFrame祖先链精确删除。首轮剩9项原字节断言暴露EntrySource默认归一会改写pkg关系前缀，新增可选preservePrefixes，仅此命名空间感知写入选择原始文本。最终删除18项、编辑/读取36项、ZIP/标签56项，共110个不同定向测试通过；两级engine tsc与frontend tsc均通过，没有运行完整测试套件。source原始迁移SHA不改，LOCAL-ADAPTATIONS登记4个新增/更新的本地文件身份并核验全部9条匹配。

隔离构建47.24s，394个JS预算failures=[]；manifest=2c54ea70768964953067ff38276aae83038389282bd4c414fc7865c7431f5640，没有覆盖共享static。真实浏览器默认XDR/默认Chart/ink/link/pkg混合前缀、chart&one关系ID、外来扩展/注释及二进制哨兵双图：人工加粗→精确候选/采纳→UndoRedo→刷新恢复→保存4到5/点击真实下载/重开→删除候选先拒绝再采纳→保存5到6/点击下载/重开。171个实际JS/CSS响应SHA匹配；4类错误为空。独立openpyxl/lxml/ZIP确认图数2/2/1、标题/类型/图例/数据与公式正确、另一图及非目标部件字节保持、drawing/rels只删目标区间，截图像素及人工查看通过。provider为ScriptedModel，修订仓库为限定内存夹具；没有声称真实provider/生产鉴权/桌面Excel验收。

证据及12份源快照/SHA：/tmp/office-xlsx-chart-namespace-20261113；范围见NATIVE_XLSX_CHART_NAMESPACE_ACCEPTANCE.md。源ribbon-actions与ExcelShell实际回调同时确认：GenOffice按selectedVisual操作，本地多图功能区仍被charts.length===1限制，快速布局/配色方案入口亦缺；现有六种转换与分组对话框不能重复列成全缺。四格式范围/当前缺口索引已更新，整体goal仍active；本批不新增UI声明点，不把751模块/5178声明点当作穷尽功能分母。

## 2026-11-13 续批：三代理并行检查独立动态控件与 XLSX 浏览器保存

继续用户已授权的四格式 UI 对齐工作，复用三条同模型子 agent：DOCX 题注/水印动态状态、PDF 裁剪/静态文字输入生命周期、XLSX 命名空间图表真实浏览器保存；主 agent 完成 PDF 字段设计、交叉核查、统一隔离构建、文件回读与归档。专家额外检查实际事件传播顺序、禁用当前按钮时的焦点去向、输入法兼容事件、显示与文件设置一致性，以及实际运行后端桥是否包含源修复。未以图标、声明数或单测通过推导完整 PC Office 对齐。

DOCX 真实 Chromium 先在 1440×900 与 390×320 复现：题注确认按钮已聚焦时，保存锁定/选区变化/校验异常使其 disabled，焦点掉到 BODY，下一次 Tab 进入背景入口。仅在原确认按钮聚焦且刷新后被禁用时，移焦至已有具名状态说明；不抢输入字段焦点、不改题注业务与水印。新增三例 RED，题注六例与水印七例共 13/13 GREEN。源码组件四视口 12 题注状态与四水印对照通过；曾因带 datalist 的 combobox 被夹具误当 textbox 超时，保留记录并修正定位，没有修改产品规避。

正式冻结 DOCX 宿主最终 14923 退出 0：真实 Tiptap 选区事务四视口验证状态聚焦、Tab 留在弹层、输入焦点及值保持、Escape 回入口和草稿不变；另长文本/禁用/重开三模式×五视口共 15 布局场景。完成真实插入、撤销/重做、刷新恢复、修订2保存、浏览器下载与重开，验收待复核原因展示且下载照常。独立 stdlib ZIP/XML 回读确认真实 SEQ 图 \* ARABIC 域、begin/separate/end、dirty 标志和缓存1，原正文全部子树保持，16个非目标 ZIP 部件字节保持。149个实际资源 SHA 与冻结磁盘一致，errors=[]。首轮 2572 在 640×360 设置正文光标时被 docx-notice 遮挡，保留失败；最终在桌面尺寸设置正文选区、打开窗口后再切目标视口，不能称短屏正文遮挡已修复。授权/context/登记路由仍为显式HTTP夹具，真实Python/Node保存及文件回读不等于生产服务验证。

PDF crop/static 两个独立 Escape 监听原忽略 defaultPrevented/isComposing/keyCode229，错误取消活动裁剪拖动或待选文字落点。各入口仅补三保护，保留普通 Escape、既有事件阶段和坐标计算。单测六例 RED、普通取消两例对照通过；真实浏览器同时保留六个对应错误。最终相关三文件 54/54，源码组件验证非零偏移、260×325 CSS尺寸和26px拖动，保护事件保留后续移动、普通 Escape 正常取消、焦点恢复与 dispose。冻结真实授权 PDF 宿主进一步八项检查通过：裁剪右边距30→20%、普通取消保持30%；静态文字待落点保护/普通取消均通过。41个JS资产身份一致，四类错误为空，源身份不变、草稿为空、savedRevisions=0；不声称该子专项执行保存或业务事实验收。

主 agent 的 PDF 字段设计发现 legacy229 Escape 误关面板。新增三保护对照，RED 为1失败/12通过；旧冻结真实宿主 browser-red2 在 legacy229 直接复现，page/console/http错误为空。仅给现有条件追加 keyCode!==229，最终字段设计13+实际宿主15共28项通过。最终92573冻结宿主五视口全部控件命中、字体/焦点/滚动及15合成保护事件和五次实际目标消费 Escape 通过；普通 Escape 仍回入口。字段实际删除、撤销/重做/刷新恢复、预览确认、保存修订5、浏览器下载及重开通过。独立 pypdf 核验 remove_me 被删除、长名只读字段/其Ff/widget关系/原文保持，下载身份匹配。validation.ok=false/native_source_review_pending 原因保留，下载正常；49实际资源SHA一致，所有错误为空。首轮静态目录夹具只改挂载未传HTML路由，404失败另存browser-red，修正同一static_dir后才得到上述真实RED，不算产品缺陷。

XLSX 补齐上一批尚缺的浏览器保存证据。先发现共享 workbook_engine/dist/cli.mjs 未含已验证writer修复：最小真实Native save返回422，直接桥错误为 Chart part has no c:chart element，证据保留。未覆盖共享dist，仅授权esbuild隔离Node桥至/dev/shm/office-xlsx-chart-namespace-engine-20261113，AGENT_REPORTING_WORKBOOK_ENGINE_DIR指向该处。新桥SHA ac9390bebb2a77498d182f674e505cfb6752b6b655857f1f8e7f17340aea571b；共享桥d497db5df41704cb22e8f5192d4d6829cc10630d23a64fc1db1abd18349698f7未动，writer源c68bff…未动。不能称共享运行环境已自动更新。

default/arbitrary/mixed三来源均真实浏览器对话框改标题/标签，颜色通过现有AI面板明确采纳受控HTTP候选（非真实模型）；真实NativeImport/Editor/Publication、隔离Node保存修订2、签名浏览器下载、重开通过。内存仓储为明确夹具。独立ZIP/lxml/openpyxl核验单一标题、系列、2F9E6E及标签实际落盘，仅chart1改变，45个非目标部件字节/SHA保持；重复标题、旧颜色、缺标签、错误URI和改非目标表五种损坏均被独立verifier拒绝。三次validation.ok=false均保留具体原因并签发下载，171个实际资源哈希匹配上一冻结manifest a1a6c90c…，errors=[]。首轮夹具把绝对重开URL重复加origin失败，修正脚本后新鲜目录全部退出0。人工查看mixed/reopened.png发现现有单元格文字/背景叠在图表之上，作为独立视觉缺陷待查，本批不扩改renderer，也不宣称完整Excel版式验收。

本批95个不同定向契约（DOCX13+PDF54+28），未运行或重复完整套件。47359 frontend tsc退出0；73728统一隔离Vite构建47.51秒退出0，394 JS预算failures=[]；保留已有循环chunk/PURE/PDF字体URL和大chunk提示，未改预算阈值。冻结/dev/shm/office-dynamic-controls-ui-build-20261113，manifest SHA256=adf9bb91d174632be4fa94de98ee495531d40152f367a913e382cc39d675c777。共五次浏览器实际下载（DOCX1、PDF1、XLSX3），不同宿主的显式夹具边界分别记录，没有冒称真实AI、生产发布、系统IME或桌面Office验证。

构建时清单751模块/5178声明点、初始源码SHA全部匹配。归档时发现共享工作区另有12模块在构建后被其它并发任务修改，具体旧/新SHA在source-verification.json；本批四个实际产品修复文件仍与受测身份一致。故本批结论只适用于精确冻结资源，不声称当前整个工作区已通过。另生成inventory-current为751模块/5180声明点，并同步canonical两表；清单仍非功能分母，未将并发新状态算入本批测试。21份相关源码/测试/烟测及SHA、RED/失败/最终浏览器、独立文件回读、预算/类型/构建和summary.json归档/dev/shm/office-dynamic-controls-verification-20261113；各子任务更完整证据仍在独立目录。只归档并移除本批创建的vite.dynamic-controls.build.config.ts；未提交、推送、部署、覆盖共享static/dist或清理其它会话改动。

整体目标继续active。短屏DOCX正文提示遮挡、XLSX单元格/图表绘制层级、共享后端桥更新、其它四格式动态菜单/状态与保存映射、复杂图表填充变换、旧桥/Injector竞态及系统IME/读屏/桌面Office仍待继续。

## 2026-11-13 续批：短屏正文、参考线焦点、字段组合键与图表视觉分层

按用户要求复用三条同模型子 agent 并行推进。DOCX 负责真实短屏正文操作，PPTX 负责参考线指针到键盘的焦点交接，XLSX 负责图表层级与格式化数值；主 agent 处理 PDF 字段画布、统一隔离构建、证据交叉核对与归档。专家额外检查覆盖实际命中、选区同步、输入法保护、分数像素与透明抗锯齿、真实保存下载，以及非目标文件部件保持。没有把美化等同于仅调整图标和颜色。

DOCX 640×360/390×320 下 References 工具区自然高度与提示占满容器，正文可用高度为0；正常点击被提示/状态区截获。仅在屏高≤480px约束工具区最大35dvh并允许内部滚动、提示最多2行，桌面与竖屏几何保持；短屏正文恢复88/62px。真实点击、滚轮、正文选择与首尾定位、Ribbon Tab及内部滚动均通过。最终冻结完整宿主四视口短屏与15长内容/受阻/重开场景通过，149资源身份一致、errors/failures为空。真实插入/撤销重做/恢复/保存/浏览器下载/修订2重开完成，仅一次save。独立ZIP/XML确认真实SEQ begin/separate/end、dirty与缓存1、原正文保持，16个非目标部件字节不变。首次完整宿主失败保留：夹具click+Home后PM仍可能offset2，改用实际Control+Home并等待段首选区，再构造middle场景；未放宽题注业务前提或改产品规避。授权/context/修订登记等仍是明确HTTP夹具。

PPTX reference guide 的pointerdown.preventDefault阻止默认聚焦，点击/拖动后焦点留在外部输入，后续方向键不移动参考线。仅在原守卫通过后element.focus({preventScroll:true})。两项新契约先RED，guides+ruler定向34/34通过；真实水平/垂直×点击/拖动4场景及四视口通过，0.5缩放后的步长与dispose正确。冻结宿主真实保存1次、浏览器下载、修订重开完成；141资源身份一致、axe及浏览器错误为0。独立ZIP精确核验仅目标正文/creationId登记变化，备注、链接、几何、图片及非目标部件保持，三类故障注入被拒绝。授权/保存应答的夹具边界没有扩大为生产验收。

PDF 字段画布widget/document键盘入口补isComposing/keyCode229保护，并保留既有defaultPrevented守卫。此前组合态Enter会误选字段、方向键会修改位置并生成草稿、Escape会误清选择。15保护事件矩阵先10失败/17对照通过，最终27/27定向通过。真实组件四视口60保护事件与普通Enter/Space/方向键/Escape及dispose通过。冻结native API宿主在0°/90°各验证15事件，完成5次真实保存、5次浏览器下载与重开至修订9；41资源身份一致、四类错误为空、来源身份不变。独立pypdf针对nudge0/nudge90两份产物验证rect分别[31,190,111,214]/[50,181,70,201]及delta[1,10]/[-10,1]，28/31原对象、流、页框和字段树保持。不能把两份对象级验证扩大为5份同级保真。真实router/授权/字节/下载复用测试workspace与内存仓储；合成IME兼容事件不等于物理系统输入法测试。validation=false的具体原因保留且不阻止下载。

XLSX 图表扩展原zIndex32先于文字45/边框50/自定义55/角标60绘制，且getCell()的numfmt拦截器把真实10变成显示文本10.00，导致首柱消失。仅将图表层改61，数值读官方getCellRaw()，分类标签保留显示语义，不猜字符串数值、不动源单元格。最小修复版本75/75画布测试；后续并发饼图接线暴露null分类标签TypeError/类型冲突，另一会话以label??空字符串保留分类索引修正，新增空标签及原始数值4个定向通过/76跳过。75通过的版本早于最终c28，未冒称最终全文件80项通过。最终renderer SHA=c28eec7b4468f99a852e63fc680a699989c5be56c8f792d5df0b3a3a5954c313；原始SOURCE-SHA256不动，本地renderer登记匹配。

XLSX最终mixed宿主唯一一次save完成revision2、浏览器下载并重开；下载与实际revision字节一致，独立回读15非目标ZIP部件不变、B2仍raw10与0.00、验收待复核原因保留。完整smoke在像素检查报错，原failure.json保留，不能标绿。检查器先遗漏亚像素颜色，再遗漏原canvas透明RGBA与截图对白底合成的差别；已用真实Univer小数锚点RED/GREEN定位。最终helper统一白底合成，仍要求来源边框色三通道共用alpha≥0.4/误差≤0.75、每边>98%且最大断点≤1px。七项离线正负控保留三类旧RED、6像素断边与格线伪框拒绝，并接受透明raw画布。随后从已下载文件启动独立只读宿主（导入为新夹具修订1，不冒充原revision2），HTTP POST=0；171实际静态资源SHA一致、errors=[]。两柱15438/31042像素，四边100%/断点0/角标透出0，raw边最小alpha172；保存链与渲染复核分别有据，没有再重放保存。冻结图标仍136px，另一会话随后修复18px约束，未算入此冻结通过范围。

初始隔离manifest=14ac4330406dbc3d57e7c88422d4ca12e5266cba0d7bd6c19e80aa2f3d993025；PDF/PPTX完整证据限于该构建。修正饼图空分类后的最终构建47.09s退出0，frontend类型检查退出0，394个JS预算failures=[]，未调门槛；final manifest=8d4ca1394b78848aed62e1dbfc80add3b9b629cac8b91683c5d0976ee5cef2b4，DOCX及XLSX保存/只读复核采用该版本。最终入口资源发生变化，未把较早PDF/PPTX证据说成最终构建端到端通过。既有大chunk/循环依赖/PURE/字体URL提示保留。

清单快照758模块/5215声明点已同步canonical两表；这是源码定位快照，不是功能总数或完成率。构建后ribbon/CSS并发变化、枚举后workbook-chart-selection持续变化，旧/新身份均归档；chart-legend本地适配登记亦有并发漂移，保留他人修改而未静默认证。四个本批产品目标文件身份与受测记录一致，不能据此声称整个当前工作区通过。18份最终源码/测试/烟测副本及SHA、两次构建与类型/预算、失败/只读复核/独立ZIP及交叉核查统一在/dev/shm/office-visual-continuation-verification-20261113，更多RED/GREEN证据目录见summary.json。只移除本批两份已归档临时Vite配置，未提交、推送、部署、覆盖共享static/dist或清理其它会话文件，未运行完整套件。

四格式整体目标继续active；其它动态菜单/状态与保存映射、并发图表菜单新版、复杂图表填充变换、共享旧Node桥、Injector卸载竞态，以及系统IME/读屏/桌面Office仍需逐项核验。


## 2026-11-13 源入口与多图预设最终收尾（0015）

三条同模型子agent按用户要求并行：PDF目录外链，Word/PPTX源枚举和AI预设，XLSX预设/主图表接线；root负责共享几何/指针选择/菜单样式、真实宿主保存链、统一构建和独立交叉核对。code实际fetch/ff-only核对为`6a713d053527d6b0cec938aeb8c4263709eb1d8b`、0/0；拉取阶段942个本地路径与暂存区不变。后续各专项变更另行保留，未清理他人文件。

最终构建manifest为`0015c3b33b9184ffa601a0d60d3d501b498986b98865d7d41eb1e4f6accf3bfe`，冻结`/tmp/office-four-format-source-increment-20261113/static`。`frontend-typecheck-history.log`与`build-history.log`所属命令退出0，Vite43.98秒；`budget-history.json`394 JS/failures=[]，没有提高阈值。6bb完整产物另存static-6bb，所有失败目录不覆盖。已有模块指令/循环chunk/PURE/字体URL/大chunk告警保留。共享工作区management等外部并发变化仅记录，不算作本批产品验证。

XLSX本批支持按真实chartPath选第二张同名图、说明面板键盘选择、Escape及Delete、四布局/五配色、饼环分类百分比与图例、人工草稿/保护/来源对象身份复检。Univer在pointerup自行合成双击，单拦DOM dblclick会进入A1编辑并夺焦点；最终按pointerId认领图表起始手势并在window capture收尾，13项控制器回归及真实双击两帧焦点检查通过。图表完整重放后markDirty错误设置gridChanged，使File撤销误走空Univer栈；新主集成RED→GREEN，改用既有NativeDraft操作前后历史，撤销精确恢复独立读取的来源颜色，重做/保存保留人工A1=9。其它4项既有主图表定向同版本通过，没有完整69项重跑。原始失败和脚本误用可见canvas、File页签、点色预期的失败分别保留。

`/tmp/office-xlsx-chart-selection-20261113/browser-built-history/summary.json`为最终完整通过记录：真实grant/cookie/CSRF、现有工作区/Node引擎、人工A1加粗、图2标题Selected/pie/四布局再2/green、File撤销恢复、reload、保存4→5、浏览器点击下载及明确修订重开、75%再选择/Delete、保存5→6并再次下载重开；限定内存修订仓库，plannerCalls=0。171实际JS/CSS逐SHA匹配，page/console/HTTP/asset错误均空。独立openpyxl/lxml/ZIP读取两份实际下载，A1=Quarter且bold、B2=10/B3=20，编辑图为pie/top/category-percent/375623与548235，删除仅剩原图；原图XML两次原字节不变。两次validation=false均保留native_source_review_pending而提供真实下载，不以此替代完整发布故障注入套件。root目视蓝框、18px图标、75%饼图完整Q1/Q2和33%/67%、删除重开；截图两种实际绿色8206/16578像素。详见NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md。

PDF完整外链点击/Enter、内部第2页/aria-current、opener隔离、零草稿及双视口仍绑定8d4；9bd/6bb/0015均是最小入口和资源身份续验。0015证据`/tmp/office-pdf-source-gaps-20261113/browser-built-final-0015`：50实际资源中46原字节相同、4精确配对引用名变化，归一无内容差异/未匹配，响应SHA和依赖集合与冻结磁盘一致，五条目录/mailto/入口及errors=[]。没有重跑popup矩阵或双视口。详见NATIVE_PDF_OUTLINE_LINKS_ACCEPTANCE.md。

PPTX完整候选链仍绑定8d4，真实Agno+ScriptedModel，含人工未离焦草稿、当前页英语、整稿拼写、明确采纳/UndoRedo/放弃/语言切换/过期及关闭取消，独立python-pptx回读引擎补丁产物；没有save/export/download或真实provider质量结论。0015最小续验`/tmp/office-word-pptx-source-gaps-20261113/ai-presets/browser-built-final-0015c3b3-identity`：129实际JS中126原字节相同、3仅精确资源引用变化、归一全部相同，响应SHA与集合匹配，21语言DOM/slide与deck入口、0job及三个错误数组为空。仅依据实际PPTX依赖连续性衔接，不声称394个bundle全部字节相同。见NATIVE_PPTX_AI_PRESETS_ACCEPTANCE.md；源中文尺寸/圆形转场/艺术字按该专项既有枚举证据分层，不冒称本轮重跑。

SOURCE两处补充本地适配范围，engine9项及frontend18项LOCAL哈希全部匹配；原始SOURCE-SHA256不变。758模块/5215声明点仍只用于定位，不是功能分母。最终专项、构建、失败、类型/预算、源身份和浏览器证据按各/tmp目录保留；临时vite配置归档后删除，仅停止本批preview。未提交、推送、部署、覆盖共享static/dist或运行完整suite。整体四格式目标继续active；拖动/resize、复杂图表/高级工具面、生产仓储、真实provider效果、系统IME/读屏及桌面Office仍开放。


归档时发现共享源码有外部并发漂移，见`/tmp/office-four-format-source-increment-20261113/source-history-postbuild-drift.json`：包括workbook-ribbon及docx/focus-trap/pdf-object-dialog等9文件。0015的ribbon产物相对6bb除局部标识符改名外，实际新增defaultPrevented/isComposing/keyCode229键盘守卫；该外部变化被保留，不归为本批独占修复，也未单独补做该守卫专项。最终171资源与完整XLSX浏览器结论绑定实际0015静态文件；不宣称整个当前工作区已通过相同验证。`source-final-identities.json`逐文件记录当前归档SHA及与构建开始身份是否相同，不将当前副本冒称所有原始受测源码。没有为追赶并发状态反复构建或覆盖他人改动。

## 2026-11-13 续批：真实提交回执、组合输入与弹窗销毁闭环

上一goal turn属于实际进展（四格式修复、冻结宿主及文件回读已归档），本批继续原始穷举/PC Office对齐目标，未把目标缩成容易通过的单测。三条同模型代理分别处理Word页码、PowerPoint设置与共享焦点循环、PDF原生对象窗口；主代理核验Excel功能区、构建与预算、交叉review及归档。专家额外检查落实为：确认按钮必须依据真实提交结果关闭；区分有效no-op和拒绝写入；真实输入法组合事件与浏览器默认取消；abort/close监听释放及旧窗口不抢新窗口焦点；实算SVG尺寸/命中；冻结实际源码和加载资产身份。

Excel功能区onTabKeyDown原无defaultPrevented/isComposing/229守卫，组合态/已消费的方向键/Home/End会重建页签与控件并改变焦点。新矩阵12例先RED、4正常对照通过，单行早退后16/16通过。真实组件四视口RED共48处，GREEN全部通过，正常方向/Home/End、Tab进入快速布局、菜单回调及锁/保护/无图表说明、dispose均保留。此前并发的图表菜单18px修复也实际核验：快速布局/更改颜色两个SVG在四视口均18×18且可命中，不再只凭CSS推测。最终冻结Native工作簿宿主四视口复核48保护事件及普通键盘、8个图标尺寸/中心命中通过，171个实际JS/CSS SHA一致，四类错误为空，HTTP POST=0/save=0。原两次夹具失败保留：相对editor URL未解析origin、未限定Ribbon而与工作表role=tab发生strict冲突；修正定位后新目录只读复核，不改产品规避、不重放保存。

PowerPoint共享installFocusTrap仅追加isComposing/keyCode229守卫。首尾Tab/ShiftTab原错误preventDefault并移焦，4个新增单测及真实四对话框16处RED；相关focus/size/main定向43/43通过。源码模式四对话框×四视口16场景/96保护边界通过，正常Tab/Escape/取消/校验及25.4cm→254mm、300mm→30cm/实际EMU对照均通过。最终新冻结宿主使用当前slides-main源872cabe2…，不是早期e11aae版本：143实际资源SHA匹配，参考线/标尺四视口、4指针交接、保护拖动/切页/reload/pagehide及四类设置通过；设置12case、尺寸5视口与4Escape场景、153保护键断言、16次axe均无违规，errors=[]。只读模式保存入口硬守卫，保存请求/次数/下载事件均0，来源身份不变，没有重复旧保存链或修改正文。

Word页码首先在真实Layout/Insert组件复现锁定/异常后未提交却关闭并丢12输入。新增live禁用原因、确认失焦后状态聚焦、窗内错误保留及成功才关闭，保持原捕获节身份守卫，不抢输入/取消/外部焦点。31项相关测试及后续聚焦/回执定向通过，不将后续targeted重跑累加为完整套件总数。交叉review进一步发现真实main内部catch(reportError)正常返回，组件throw探针不足以关闭生产缺口，继续沿现有main→ribbon→Layout/Insert→dialog传递SectionChangeResult（void或具体error）。main保留reportError/syncSection/meta；普通layout可忽略回执，不新增未处理throw。commit=false时用同一native操作归一器比较实际与目标：相等为有效no-op，不等为未写入。最终冻结真实main完成pending分节拒绝2例、正常/取消/no-op/切节/事务抛错/普通layout失败8例、静默丢弃docAttr不抛错2例。拒绝均保留12/具体原因/原操作，正常成功才关；每份探针核对138实际JS SHA，pageErrors=[]/save=0。原错误与只读review历史保留，顶部已更新最终修复状态，不再把旧“内部catch仍未接通”当作当前结论。未重复保存或声称生产数据库授权验收。

PDF对象便签、位移、缩放三类真实产品窗口发现原生默认行为缺陷：CDP实际组合输入下可信Escape(isComposing=true/keyCode27)会触发dialog cancel并丢窗口。仅组合态Escape preventDefault，close移除具名监听；229对照并未误关，故未机械添加无依据的229拦截。8项helper RED→GREEN，连9项既有关闭对照共17通过/42跳过。12交互场景覆盖真实点击、全顺序Tab/ShiftTab、无效值/取消重开/普通Escape一次cancel/组合Escape零cancel。新监听销毁检查又实际发现便签dispose仅移除DOM未close；按相邻绘图实现为editNoteContents绑定abort→close/resolve(null)，finally卸载。四视口dispose关闭一次、监听释放、替换及外部新modal不被抢焦通过；三类有效应用/数字Enter及精确操作属性保持、原共享夹具单一兼容用例通过。CDP compositionstart/update及Escape可信，清空组合产生的compositionend实测非可信，未包装成物理OS输入法测试。此专项是Vite源码模式，未执行保存/发布。

为避免共享工作区持续变化导致清单与受测源漂移，本批在/dev/shm/office-modal-lifecycle-source-20261113物理复制前端及引擎源码（复用已安装依赖），沿原Vite配置将static写在该隔离目录，未覆盖共享static/dist。初构建45.34s/tsc退出0，但当前并发PowerPoint代码使slides-main达257019B、251.0KiB，违反既有250KiB预算；失败manifest c5cfef79…及budget-red保留，没有调高阈值。仅按既有manualChunks模式将guides/ruler/settings-dialog纯视图模块归native-pptx-view-controls，静态ESM调用不改；最终44.43s构建、类型检查、预算契约均退出0，396个JS预算无失败，main247074B(241.3KiB)、view-controls9506B。final manifest=da53f3fbb74a92cadbe20120f6762155cffecb00dab5f50f21feffbba81896cb。既有循环chunk/PURE/字体URL及大chunk提示保留，未宣称零warning。

冻结清单761模块/5233声明点，全部冻结来源SHA一致，canonical两表字节相同；仍只是可达源码定位而非功能分母/穷尽率。共享工作区抽查已有11模块后续漂移，含Word main/operations/ribbon及PDF main等，旧/新身份见inventory-frozen/source-verification.json与source-identities.json，没有覆盖并发修改。尤其PDF源码专项main身份2a4b545…，物理快照收拢时已并发变为8b99f694…，不能把旧Vite交互专项冒称最终冻结PDF整体验收；最终构建/类型通过也不证明当前整个工作区通过。Word/Excel/PPTX上述冻结证据均绑定最终da53版本，各自保留授权/数据fixture、只读及错误采集范围。

统一证据/dev/shm/office-modal-lifecycle-verification-20261113：summary.json、review-note、原/最终构建与预算、3302份来源身份表、三个冻结宿主、root组件RED/GREEN及失败记录；DOCX/PPTX/PDF源码专项完整记录仍保留独立目录。未运行完整项目套件，未提交/推送/部署或清理其它会话。整体goal继续active：其余动态菜单和禁用功能族、完整段落/多级列表/表格/图表/媒体能力、并发新状态、最终冻结PDF与系统IME/读屏/桌面Office、共享旧桥及其它卸载竞态仍需逐项推进。


## 2026-11-13 续批：上下文页签导航、输入保护与 PDF 冻结补验

本批继续三个同模型子agent并行，root负责Excel函数窗口及统一冻结。只修已复现问题：Word功能区保护导航事件不再改变页签，跳过hidden/disabled页签，上下文页签消失时仅恢复原本聚焦在该页签的焦点；PowerPoint沿原tablist结构增加同类保护、实际可用页签筛选及原焦点位于被隐藏上下文tab/panel时的恢复，不扩张原上下文选择策略。Excel函数目录仅增加一行isComposing/keyCode229/defaultPrevented早退，保留正常方向/Home/End选择。没有改本批CSS、产品保存或后端链路；PDF本批只有验证工具改动。

Word定向RED15→GREEN18，21个无关旧用例跳过；真实带样式createDocxRibbon四视口涵盖48保护事件、3类上下文消失、4不抢焦对照、disabled/readonly、横滚与命中。新冻结完整native宿主另补四视口48保护键、16步常规导航及中心命中、Tab进入真实面板，天然表格选区退出后context隐藏且正文焦点保留；文本与持久化草稿不变，139JS+11CSS实际身份匹配。完整main原有End→页眉页脚面板后聚焦编辑器行为保留，未用组件夹具的tab焦点假设强行改产品。启动GETcontext/GETfile及1次只读preview POST独立记录，验收交互新增请求0/save0/pageErrors=[]。精细context/disabled矩阵仍限真实组件夹具，未重复页码或保存链。

PowerPoint新增29例中RED24失败/5对照通过，与既有37例合计66定向通过；真实styled组件四视口48保护键、24普通导航、60上下文焦点场景、Tab进出及横滚可见通过。新冻结完整native宿主143实际JS/CSS身份匹配，四视口48保护键/24普通导航/Tab入View标尺再返回通过，自然shapeFormat可见、其余4上下文隐藏并跳过，草稿及源PPTX身份不变；实际状态没有自然disabled tab，没有注入DOM伪造该集成结论。saveRequests/saveCount/downloadEvents均0，page/console/resource errors=[]。首次探针假设End=View错误，实际自然shapeFormat为最后可见tab，原失败在initial-assumption保留，按真实列表修正，无产品变化，未重跑设置/参考线/保存链。

Excel函数目录定向RED3失败/14对照通过，GREEN17；真实带产品作用域CSS组件四视口48保护键/16普通导航/Tab首尾循环/4取消、0确认通过。新冻结完整native工作簿同样四视口通过，171实际JS/CSS响应SHA与文件一致，GET以外请求0，pageErrors=[]；没有据此扩大宣称指针中心命中、所有工作簿内容不变或保存链验收。早期CLI使用已废弃cache参数未启动测试，改no-cache后执行；早期smoke的role=option选择器误纳入分类原生option造成12普通导航假阴性，已限定.fn-list [role=option]，48保护键RED仍真实成立。组件夹具缺CSS/UTF-8的早期记录保留，最终styled截图与真实宿主通过。冻结runner当时读取的live来源元数据已另与物理快照逐项核对一致；后续工具添加显式SOURCE_ROOT元数据参数，不冒称其本身进入产品构建。

PDF关闭前批明确的最终冻结缺口：使用当前main=3e7ccc6…而非早期2a源，完整native.html/context/file/preview及原pagehide→native-session.dispose→实际view.dispose链，四视口三类窗口12场景完成；4次可信CDP组合Escape、12普通Escape、12dispose/监听释放，四组ribbon共24点击/16键盘切换通过。50资源(41JS/9CSS)逐一独立SHA回读，36来源请求(12context/12file/12preview)，save/export/publication0，页面/控制台/资源错误为空。原12场景运行在全部断言后的最终元数据阶段因冻结frontend没有未使用的组件smoke文件而退出1，保留interaction-failure原记录；独立audit逐项复核12结果、4组ribbon及全部实际资源后exit0，native模式元数据只取实际src的修正再以短屏便签单场exit0确认，没有重复12矩阵。此汇总不伪称原矩阵命令exit0。可信CDP组合输入不是物理系统IME验收。

统一物理源码快照/dev/shm/office-ribbon-navigation-source-20261113登记3324文件，全部SHA回读一致，依赖只读复用。隔离构建48.66s、tsc退出0；397JS预算无失败，阈值不变，保留循环chunk/PURE/字体URL/大chunk提示，不宣称零warning。统一manifest=dd3cbbca36170e479fca2892b9f053439ef8e30288d66ca3c461fef2e34a55e5。清单更新773模块/5388声明点，两份canonical表与本次冻结输出逐字节相同；清单仍不是功能分母。当前抽查2文件后续漂移均属management签章配置，已记录原/新SHA，未覆盖并发改动，结论仅绑定快照。

统一证据/dev/shm/office-ribbon-navigation-verification-20261113/summary.json及README，三个冻结宿主子目录、构建/类型/预算、source-verification与inventory-frozen齐备；源码专项分别在office-docx-ribbon-navigation、office-slides-ribbon-navigation、office-xlsx-function-navigation-20261113，PDF完整复核在/dev/shm/office-pdf-frozen-interaction-20261113/frozen-full-results-audited.json。未运行或重复完整测试、未覆盖共享static/dist、未提交/推送/部署。整体goal保持active：其它动态菜单/禁用功能族、完整段落/多级列表/表格/图表/媒体能力、系统IME/读屏/桌面Office对照及快照以外并发状态仍需逐项推进，不能据本批通过宣布穷尽完成。


## 2026-11-13 多级列表、图表几何、书签编辑与公式续批

固定参照仍为GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。root与三个同模型子agent并行；本批只关闭下列源子能力，不把模块/声明点计作功能分母，整体对齐仍未完成。

| 格式 | 本批交付及实际验证 | 仍保留的边界 |
| --- | --- | --- |
| Word | 八套九级预设，最近/文档/级别区与完整自定义对话框，可信顶层多段单事务；真实UI/UndoRedo/恢复/390px布局，以及68ce修订4→5保存、授权下载、重开，150项HTTP资产匹配；独立lxml/python-docx确认共享numId、九级、第%1章/start4及原文/旧编号/其他部件保全。 | 普通符号/编号库、设置编号值、图片符号、完整段落对话框及复杂对象仍缺。见[多级列表](NATIVE_WORD_MULTILEVEL_ACCEPTANCE.md)。 |
| XLSX | 两格锚点移动和八向缩放、单格锚点只移动，最小24px、Escape/滚轮取消、UndoRedo/草稿/75%/RTL及人工A1保留；87a手势与68ce RTL/保存续验分层，修订4→5，171项资产匹配，独立openpyxl/lxml/ZIP回读保全另一图锚点和两张chart part。 | absolute锚点明确拒绝；推荐图表、完整ChartPanels轴/间隙/环孔/扇区/标签格式/点填充、完整SelectData与细粒度series/point选择仍待补。同sheet多条applyPageSetups视图覆盖疑点已记录，不宣称视图持久化通过。见[几何验收](NATIVE_XLSX_CHART_OBJECT_GEOMETRY_ACCEPTANCE.md)。 |
| PDF | 书签当前页新增、嵌套改名、删子树和清空，支持空白页/删页/重排/旋转/便签组合；源码真实HTTP保存下载重开及pypdf回读通过，87a冻结最小入口/50资源与桌面/390px验证独立记录。 | URI/异常树/坏目标/签名保护来源只读，固定源其它非AI工具族仍按18行差距表逐项推进。最终68ce连续性结果以[书签专项](NATIVE_PDF_SOURCE_GAPS_BOOKMARKS_20261113.md)最终附录为准，不把87a浏览器结果冒称68ce完整保存重跑。 |
| PPTX | 12模板/自定义Unicode、取消、UndoRedo、草稿/未失焦保存、修订2下载重开；源码HTTP完整链与冻结桥同payload重放分别验收；68ce最小入口/实际131资源及两处并发Ribbon键盘/焦点变化补验。 | 固定源是Cambria Math数学字体文本框，不是OMML。夹具连续插入中心框有明显叠放，像素仅证实绘制可见，不证明无重叠或清晰排版。其余放映/媒体/AI工具面继续开放。见[公式验收](NATIVE_PPTX_EQUATION_ACCEPTANCE.md)。 |

本批最终隔离static为 `/tmp/office-four-format-source-entry-20261113/static`，manifest `68ce99975149470621d980fcf040694372b986a4c037e5463f07d85a8edf67e2`。完整前端类型检查退出0；Vite 51.87秒，397JS原预算failures=[]，没有提高预算；既有循环chunk/PURE/字体URL/大chunk提示保留。四引擎隔离桥构建通过并记录逐SHA，未覆盖共享static/dist。root逐一复核Word150/XLSX171/PPTX131实际HTTP资产与最终磁盘一致，独立重读Word与XLSX实际下载，目视三个重开截图。

真实保存找出两项Python边界漏登：Word docx_native仅追加setParagraphCustomList；XLSX native_office仅追加applyChartAnchors字段。各自真实桥定向RED→GREEN后续验保存通过，均是前端构建后单独验证的Python增量，不假装已包含在原前端源快照。Word/XLSX/PPTX保存仍返回 `validation.ok=false/native_source_review_pending`，已核验身份文件照常下载，不称业务验收通过。PDF写后复核故障同样只告警，原非阻断链保留。

失败证据原样保留：首轮Word超预算、第二轮字体行窄屏裁切、Chromium资源不足、Word烟测误用preview按钮、Word/XLSX Python 422、PPTX过早截图及错误context夹具前提、PDF末端验证器NullObject。只修目标或对应测试条件，不将失败日志删改为通过。87a→68ce slides-main存在其它会话的两处真实Ribbon变化，已明确区分并补必要UI；不是全部仅导入更名，也不归本专项独占。构建后源漂移两文件属于management签章配置，保留原/新身份，不覆盖并发修改。

统一证据 `/tmp/office-four-format-source-entry-20261113/summary.json`，包括构建/预算/桥身份、分层浏览器及下载证据、Python增量、失败和源漂移。Word源迁移七项原始身份已追加SOURCE，LOCAL逐项匹配；XLSX frontend/engine本地适配身份已核对，未改原始SOURCE-SHA。本批临时Vite配置已归档删除，自己的测试服务已结束；未重复完整测试，未提交、推送或部署。完整目标保持active，不能据本批宣布穷尽完成。


PDF 68ce连续性最终补记：root重新运行精确manifest比对脚本，87a浏览器实际50资源中45项原字节相同，5项仅登记的生成资产路径变化，替换后一字不差；静态imports/css/assets闭包51项，补出的cursor SVG原字节相同，依赖图无变化，native.html也仅入口引用变化。真实逻辑变化0。证据 `/tmp/office-pdf-source-gaps-20261113/final-68ce-continuity/resource-continuity.json` 与root复核日志。没有重跑UI或HTTP保存；源码完整保存链、87a实际交互与68ce静态连续性保持分层，不把最后一层称作新的完整保存验收。


## 2026-11-13 续批：侧栏输入保全、长树可见焦点与图表真实提交回执

继续三个既有同模型子agent并行，root处理XLSX与统一冻结。专家额外检查落实到跨面板防抖、长列表焦点实际可见/命中、关闭后焦点恢复、真实提交回执和失败后的输入保全，不把只增加组合键守卫当作穷举。本批只修复已复现目标，未重新设计整页。

Word长标题树原preventScroll使End聚焦第45项却仍在视口外；仅树键盘最终focus取消preventScroll。源带样式真实main先RED，新增1单测通过/13旧例跳过；最终冻结四视口加只读5例，每例45标题/31可见与中心命中，Home/End/20次逐项/Enter第21项、45→43→45折叠通过。仅移动树焦点不滚正文，正文JSON/草稿不变，4编辑模式Escape回入口。140JS+11CSS实际身份一致，交互非GET0/save0/pageErrors=[]，2次启动只读preview POST独立记录。截图只证明本轮树路径，不能据此宣称全部Ribbon或整页绘制完成。

PowerPoint真实shape填充200ms防抖回执会重建geometry pane，覆盖尚在输入的7.或非法值并丢焦点/error；update仅在target、exact geometry、slide尺寸、reason、picture、lock全部相同时no-op，权威变化仍刷新。源四视口8例加4错误status焦点/滚动命中，30定向单测通过；最终冻结真实native/PPTX/inspect/render同样8例通过，143实际JS/CSS SHA匹配，source身份不变，save/download0，errors=[]。源RED输入115/123ms早于200ms，保留原证据；不再采用早期口述22–26ms。冻结另用复用PPTX的实际几何数据，不冒用源夹具的对象B数值。

PDF共用三pane及design关闭时，原入口因切Ribbon被隐藏会落BODY。仅两处hide增加回本宿主当前selected tab。8路径先RED，新增16加相关旧例50/50通过。最终冻结四视口×四pane×click/Escape32例，另32原入口对照、32真实关闭命中，草稿不变。42JS+10CSS独立回读匹配，同3页PDF身份保持；context/file/preview各1，save/export/publication0，errors=[]。

Excel图表设置原apply:void调用后立即关闭，真实main内部void/catch又吞Promise。现沿原链返回Promise/错误、成功才关，pending禁用控件/重复提交及取消，保留标题/具体alert；generation隔离close/reopen/dispose的迟到回执。真实浏览器又复现控件全disabled后Tab进入背景、锁内祖先inert时card收不到Tab；仅本modal正在applying且aria-modal=true时window监听正常Tab/ShiftTab，聚焦状态提示，dispose卸载，尊重IME/229/已消费事件。17定向unit通过；完整源宿主四视口显式前置hold/reject，重试实际writer/reload，锁内只延迟，验证draft/chart store/reopen/cancel及两层Tab通过。最终冻结另4例正常writer/reopen/cancel、171实际JS/CSS SHA一致，无故障注入，不能把该层冒称冻结失败注入。现有loadOperations在loading=true后内部抛错缺统一finally/rollback且可能使捕获目标过期，本批未修；只验证前置失败可重试，未宣称所有锁内失败可重试。轴/图例/标签/格式的当前值预填也仍开放。XLSX早期转义/locator/inert隐藏误判/Shift采集问题等夹具失败原样保留，最终证据与旧失败区分。

统一物理快照/dev/shm/office-panels-continuation-source-20261113登记3347文件，全部SHA一致。首构建46.28秒/tsc0但docx-main256076B、pdf-main262291B违反250KiB预算；未提高阈值，仅沿现有manualChunks拆pdf outline/view及docx header/footer模型。45.60秒中间构建后又因锁内Tab真实缺口必要更新dialog/test；最终46.11秒、tsc及预算契约exit0，400JS failures=[]，docx-main251645B/model7960B，pdf-main254711B/controls7853B。循环chunk/PURE/字体URL/大chunk提示保留，原/中/最终manifest与日志都保留，最终manifest a0ad8e0892645e8a56882aae7262bf6fbef974d032c48880533fa50d0eda83d3。没有覆盖共享static/dist。

最终清单781模块/5450声明点，canonical两表与inventory-final逐字节相同，仍非功能分母。归档时已记录13份共享源后续漂移，含列表库、PDF Bates、PPTX视图及XLSX chart-add等；不覆盖并发修改，也不把冻结结果外推全部live源码。统一证据/dev/shm/office-panels-continuation-verification-20261113/summary.json、README、source-verification、asset-verification及三个专项目录完整保留。98项是本批各组定向unit通过数，非完整测试套件；未重复完整测试、未提交/推送/部署。整体goal继续active：剩余功能族、图表设置预填与重建异常、系统IME/读屏/桌面Office对照及快照以外并发状态仍需逐项推进。


## 2026-11-13 普通列表库、推荐图表、Bates与视图续批

固定源仍为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。root和三个同模型子agent并行，本批物理复制4119份源码身份，构建只在 `/dev/shm/office-four-format-source-library-20261113/source` 执行；隔离static的manifest为 `845d993207be6b2d6eeae28cf0b5abab8c1aaded0b9a9e60e7ca86a890a4d56c`。完整前端类型检查退出0，Vite45.97秒，400个JS原预算failures=[]，四引擎桥构建退出0，未提高任何预算或覆盖共享static/dist。

| 格式 | 本批关闭范围与实际验证 | 仍开放范围 |
| --- | --- | --- |
| Word | 六套符号/八套编号库、最近/文档/级别区、清除和源完整符号/编号定义，可信顶层多段同事务。845d真实UI/UndoRedo/390px/reload/修订4→5保存/下载/新修订重开通过，151实际HTTP资源逐SHA匹配；独立lxml/python-docx/ZIP确认★、两份九级定义、upperRoman/start7/Arial14/颜色/粗斜体/右对齐及旧文和15个部件保全。见[普通列表验收](NATIVE_WORD_LIST_LIBRARIES_ACCEPTANCE.md)。 | 独立设置编号值continue/restart、图片项目符号、完整段落与复杂目标仍缺。不能把start字段等同独立重新编号对话框。 |
| XLSX | 推荐图表源算法、真实选区数据SVG/排名/理由与选择插入，取消/Escape不脏；Year数值分类不误作系列。845d首次完整HTTP链包含D20人工值及bold、FileUndoRedo/reload/保存4→5/下载/重开，171实际资源逐SHA匹配；独立openpyxl/lxml/ZIP确认新LineChart、分类refs/values、原图和anchor及7个part保全。真实文件发现绝对drawing Target解析缺陷，最小移植源已有resolver，4失败→13通过；未改夹具绕过。见[推荐图表验收](NATIVE_XLSX_RECOMMENDED_CHARTS_ACCEPTANCE.md)。 | 完整ChartPanels/SelectData、细粒度series/point及复杂格式仍开放；不称完整图表族完成。 |
| PDF | 源Bates可搜索文字、原字段/六位置、页面身份快照编号；源码HTTP完整保存下载重开及独立pypdf检查通过。最终845d只做最小冻结续验，106资源响应/52独立文件逐SHA匹配，12产品文件三方身份一致，0save；桌面/390px按钮可达。见[Bates验收](NATIVE_PDF_BATES_SOURCE_ACCEPTANCE_20261113.md)。 | 不扩源不存在的suffix，不以图像页脚近似；删除不补号、重排不重编号、后增blank不编号。其它源工具族继续逐项对齐，不把冻结minimal冒称完整保存重跑。 |
| PPTX | 源SlideThumb/slide-selection/useVisibleThumbs与Normal/Sorter，真实多选/拖排/键盘/双击/批删一次历史及备注保留；源码完整HTTP保存下载重开独立ZIP回读只改presentation和目标notes，另45part原字节。845d最小冻结从实际下载重导入、互切/真实缩略图通过，145实际资源含132JS/13CSS及HTML字节匹配，0save。见[视图验收](NATIVE_PPTX_VIEW_MODES_ACCEPTANCE.md)。 | Outline/Reading、桌面IPC剪贴板/上下文菜单及其余工具面仍缺；未重复完整保存，也不宣称桌面PowerPoint等价。 |

Word真实浏览器发现源Dropdown置于label内导致选字体后默认二次激活trigger，菜单重开遮挡确认；宿主capture阶段preventDefault局部修复，不改原vendor，真实三种对话框RED→GREEN。JSDOM基线本已通过，不作为复现证据。源码01–04失败和中间失败修复均保留；04末端开发字体URL404使全脚本失败，即使该次下载独立通过也不改称完整GREEN；最终冻结完整链无404并退出0。PPTX冻结首轮harness假定manifest含native.html键失败，改按实际HTML脚本与HTTP字节核验后最小续验通过，未改产品。

Word实际下载38307字节SHA `3a58ed202e9a9c081bf4dd88afef8cf874449e51d282caa17b2f86e10f1bf02c`；XLSX7464字节SHA `7d79ccfa23326729cf464512170b06698abded49d2edf3e26f44301bf766cab8`。两者仍返回validation.ok=false/native_source_review_pending，已核验身份的文件照常签发下载，未标业务验收通过。root额外逐资产核对四格式实际响应与冻结磁盘、独立读回Word/XLSX下载ZIP并目视关键对话框与重开图；不将替身HTTP路由等同生产授权仓储或桌面Office验收。

统一证据 `/dev/shm/office-four-format-source-library-20261113/summary.json`。快照后测试工具两项有意增量：Word开发字体夹具symlink、PPTX实际HTML入口判定；产品身份与冻结源码分别核对，后续并发漂移另表记录、不覆盖或外推。原始来源登记与LOCAL适配身份保持分层；PDF几何/类型为源摘录而非整文件原字节，protocol为本地适配。未重复完整测试，未提交、推送或部署；本批仅关闭明确子能力，四格式整体对齐goal继续active，不给未经穷尽的总完成率。

归档并发边界：最终4119份物理快照身份复核无漂移；live工作区另有9路径变化。两项为本批有意测试工具修正，其余包含docx-line-spacing、pdf-protection、slides-native-chart-edit、workbook-chart-design-dialog/workbook-main及chart-read等并发改动，详见统一目录worktree-drift-final.json。冻结XLSX LOCAL11项与PDF LOCAL200项均匹配；live chart-read与其旧LOCAL登记不匹配属于后续并发状态，未擅自重登记、覆盖或追赶重建。五项实际Python后端文件前后SHA均与物理快照一致。最终结论绑定845d冻结包，不认证这些后续live变化。


## 2026-11-13 续批：真实当前值、无修改确认与等待状态保全

root与三个既有同模型子agent并行，继续落实接续源码中的四项UI行为。专家额外检查落实到：显示值必须来自文件、无修改确认不得写草稿、增删后焦点可见且实际命中、等待期间屏幕值与提交值一致、取消与重开保全、打包性能与真实资源身份。未将装饰变化或声明点数量当作PC Office等价证明。

重要证据恢复边界：本次接续时旧/dev/shm验证目录已不存在、旧进程已退出。此前摘要提及的RED/错误夹具/HMR中断日志无法恢复，本批不宣称仍保留；重新读取共享工作树、重建物理快照并生成本轮独立证据。四项产品实现的SHA均与接续摘要一致，未为重复交付而改写。上一目标轮属于已改变源码的进展，本轮完成重新验证、分包修复与归档。

| 格式 | 本轮现存证据 | 保留边界 |
| --- | --- | --- |
| Word | 行距38定向unit exit0；冻结真实native桌面1440×900与390×640两例。原auto/raw250显示1.04，未修改确认不改JSON/草稿/撤销；取消、非法1.234、实际1.23、重开与二次noop/Escape通过；151实际JS/CSS SHA匹配，交互非GET0/save0/errors=[]。 | context/file/preview为fixture授权；启动preview只读POST单列，未跑保存/导出/下载。 |
| XLSX | 当前设置16+旧dialog17定向unit，reader回归23；轴标题、底部图例、值标签、堆积、网格线由真实XLSX回填。冻结四视口各5次无修改确认草稿不变，取消/重开保持，单独关闭网格线仅生成gridlines:false，堆积不被覆盖。series/point/不支持标签组合保留自定义状态，长标题noop与清空轴标题有unit。171实际资源匹配，非GET0/errors=[]。 | 数据标签替换只作用于现有plot写入目标，不宣称重置所有series覆盖。旧loadOperations内部异常finally/rollback仍未修；复杂ChartPanels/SelectData尚未完成。 |
| PPTX | 图表数据26定向unit；真实源bar图经完整native宿主打开，四视口×类别/系列×增/删16例。新建/邻近名称焦点可见且center-hit，27.5当前值保留，取消/Escape草稿不变、重开回到来源。143实际资源匹配，源文件不变，save/download0/errors=[]。 | fixture授权与inspect/render路径；本批未确认图表写入、保存或业务下载，短屏沿既有对话框滚动。 |
| PDF | protection pending6定向unit；三视口×成功/失败/点击关闭/Escape共12例。3密码+4权限在等待期间冻结，提交copying=false与显示一致；回执后恢复、清密码、焦点返回，草稿不变。54实际JS/CSS匹配，24截图、独立审计exit0。 | 源是实际3页PDF，但延迟protect-pdf响应明确为HTTP夹具；未生成真实加密产物、下载或保存发布。 |

统一隔离物理源码4140文件全部摘要匹配。首次Vite44.93秒/类型检查exit0，但并发新增文档属性面板使pdf-main253.0KiB超过既有250KiB；失败日志保留。仅沿既有manualChunks新增metadata/protocol控件分包，不提高限额、不改变运行对象；45.02秒最终构建exit0、402JS预算failures=[]、预算契约exit0，pdf-main255055B、metadata-controls4259B。最终manifest `b57df8780f2d7ed6cea9c120aa7dc80abfc510e577551fd24ef57b50dfe52f53`。元数据类型交集集成已有源码另3项定向unit通过，不归本批独占功能；先前类型失败日志已随旧shm丢失，不伪称复原。

129是本轮不同定向unit用例总数（Word38/PPTX26/PDF6/XLSX设计33/reader23/metadata3），不是完整测试。四份native结果均绑定同一manifest；root独立再核519格式内资源记录、333独立路径，页面错误为空。root目检Word窄屏、XLSX桌面/短屏、PDF错误状态与PPTX短屏新增系列截图。XLSX原短屏截图捕获有限过渡动画，仅给新smoke截图增加animations:disabled，额外单视口稳定重拍；不把它计作新产品修复或重复累计四视口通过数，快照旧runner与live测试增量单列。

最终源码定位清单788模块/5511声明点，canonical两表与inventory-frozen逐字节相同，仍非功能/运行验收分母。共享工作树快照后的15项漂移另表记录，不覆盖、不追赶重建或把冻结结果外推。完整图表、复杂段落/其它动态功能族、系统IME/读屏及实际PC Office对照仍开放，整体goal保持active。

统一证据 `/dev/shm/office-current-state-verification-20261113/summary.json`；轻量证据归档 `/tmp/office-current-state-evidence-20261113`，含三专项目录、原失败/最终日志、快照清单、资源独立复核、runner和截图。与本轮之前已失效的历史路径明确区分。未重复完整测试、未覆盖共享static/dist、未提交/推送/部署；本批未修改发布签发或Codex工作区链路。


## 2026-11-13 编号值／打印设置／文档属性／大纲阅读续批（最终 f9e161a9）

本节记录这一批最终物理版本，覆盖此前历史表格中仍写为缺口的对应子项，不将历史通过结论直接外推到后来并发代码。固定源仍为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；整体穷尽对齐目标保持 active。

| 格式 | 本批实际交付与证据边界 | 仍开放的范围 |
| --- | --- | --- |
| Word | 原源“设置编号值”对话框接入，restart／continue／advance 从当前项向后重绑，同 abstractNum 的 restartNums／startOverride，保留层级、正文和格式；UndoRedo、过期拒绝、NativeDraft、真实修订4→5保存下载重开、lxml/python-docx/ZIP独立回读通过。最终入口0save续验153个实际JS/CSS及HTML身份匹配。见[编号值专项](NATIVE_WORD_NUMBERING_VALUE_ACCEPTANCE.md)。 | 没有可核验定义的未保存Home synthetic列表、复杂嵌套/只读目标、图片符号及完整段落/其它工具族不在本批关闭范围。 |
| XLSX | 源PrintDialog可执行的范围、纸张、方向、边距、缩放、页码裁切、网格/行列标、HF回返、fit/actual、刷新/取消接入原pageSetupJournal。实际发现并修复隐藏表状态在reader→Univer投影丢失，以及草稿恢复误把窄边距分类为custom。实际spool HTML经Chromium打印为两页B5横向PDF；唯一一次保存/授权下载/修订5重开和独立openpyxl/lxml/ZIP/pypdf回读均有证据。04总脚本因harness在沙箱iframe读storage失败，保留false；产物从原r5/saved.json、HTTP和bytes恢复证据，05/06零保存授权重开均通过，173资源逐字匹配、四live后端起止身份稳定，390px另存PDF/打印/取消均滚动可达。见[打印设置专项](NATIVE_XLSX_PRINT_DIALOG_ACCEPTANCE.md)。 | 桌面打印机枚举/指定设备、静默打印、份数/逐份、应用直接PDF输出无浏览器宿主API，仍是明确缺口；浏览器系统打印中的另存PDF不能被称为应用直接导出。完整图表/其它工具族仍开放。 |
| PDF | title／author／subject／keywords完整草稿→预览确认→保存下载重开；关键字归一与空串清空、取消/历史/恢复、组合重排旋转及其余元数据/书签/附件保留由pypdf独立确认。修复了setMetadata遗漏实际预览加载白名单的问题。最终0save层108响应/54独立资源及HTML身份匹配，390px可滚动到确认。见[属性专项](NATIVE_PDF_METADATA_SOURCE_ACCEPTANCE_20261113.md)。 | 不代表其余PDF源文件工具、批量派生产物和复杂导航/表单保真全部完成；拆分等其余能力仍需独立实现和验收。 |
| PPTX | 复用源Outline提取与Reading静态SlideThumb：大纲标题/正文/省略号、隐藏/空白页、键盘/IME、编辑Canvas历史与草稿、源HTTP保存下载及ZIP/python-pptx回读通过。最终0save层147实际资源及HTML匹配，390px实际阅读Canvas和翻页可用。见[大纲阅读专项](NATIVE_PPTX_OUTLINE_READING_ACCEPTANCE.md)。 | Reading只按源静态逐页显示，不包含动画、转场、媒体播放。母版/版式编辑、桌面IPC及完整AI/其它工具面不由本批关闭；母版等后续改动需对应证据。 |

最终物理源码：`/dev/shm/office-four-format-numbering-print-metadata-20261113-v4/source`。4147份源码摘要、102份后端Python基线摘要、各阶段补丁来源及后续live漂移分别登记。v3严格复制v2，仅加入隐藏表reader/投影、测试与LOCAL摘要；v4严格复制v3，仅将workbook-main的一行边距fallback替换为既有matchMarginPreset并加入测试。没有把后续共享工作树的段落属性、PDF目录显示、PPTX动画预览等并发改动混入本批，也没有覆盖这些改动。后端HTTP宿主实际执行live Python；复制的后端是身份基线，不虚称隔离执行。

最终manifest SHA256 `f9e161a924c55a6c9c0e5dc3bca80f5d9607b62e2c0552663bd39f830fd211be`，HTML `b2693d7db9506a240ca768e33be181c81d579bbfce8bc18451bf6731fd77f9d6`。最终Vite、tsc、原预算和预算合同exit0，Word主块246.2KiB、XLSX主块223.2KiB；原Word252.7KiB超限失败保留，通过列表host/原生操作模块边界拆包解决，没有提高预算。四引擎桥初次全部构建成功，隐藏表修复后重建工作簿桥，其余源/桥字节相同后复用，最终桥摘要均登记。

定向日志：Word前端及相邻51项、原生10项；拆包后8项是前述用例重验，不累加；XLSX既有打印29项、新hidden2项（连相邻6项共8项日志）、新margin1项；PPTX视图及相邻50项；PDF当前非阻断服务1项。均为定向证据，不是完整测试。root独立逐资源再核最终四格式HTTP字节、四个实际下载身份、原r5登记、SOURCE摘要与LOCAL11项，并目视Word/PDF/PPTX窄屏、XLSX打印按钮与实际PDF渲染；结果保存在统一 `root-independent-verification.json` 和 `summary.json`。

实际下载：Word38243B／`d6be33132de0dec65fe1d36d4178c50272e6281f5bd7eb20e49316691b8d6b4c`；XLSX8218B／`23c6012149da45e825f501853eca0669504e1fd5094a6acdb9d1e41e1ef393d1`；PDF1499B／`ca73227b8638444ac05962559f79f80f3723f6a57e6b30f655f981baf72fac81`；PPTX／`aea1806ab2b8086f361a92c02f294cd2e22d9ec0b0c7396214ed384fd0fc111a`。Word/PDF/PPTX保存响应保留native_source_review_pending失败且照常签发；XLSX04响应未持久，明确不伪造其validation字段，登记/HTTP/文件与零保存续验分层保留。业务验收未标通过，四格式整体目标未完成；未重复完整测试，未修改发布门禁、未提交/推送/部署。


## 2026-11-13 续批：完整段落、动画预览、标题目录与重建恢复

root 与三个既有同模型子 agent 并行。本批把专家额外检查落实到真实当前值/混合值、无修改确认、原子段落格式、方向键焦点语义、短屏实际命中、异步失败输入保全与撤销恢复，以及浏览器/实际文件身份。整体穷尽 PC Office 对齐目标仍 active。

| 格式 | 本批实际关闭与证据 | 明确保留边界 |
| --- | --- | --- |
| Word | 完整“缩进和间距／换行和分页”双页签，当前/混合段落值、对齐/缩进/间距/完整行距/六项分页标志/大纲；setParagraphProperties 原子写入、保护未知 XML/原始间距。单一 tabindex、左右循环/Home/End/ARIA 双向关联。20 前端 + 13 后端不同定点用例；最终冻结 full9、三视口 keyboard3 通过。 | 列表/样式控制的大纲仍受原协议保护；同段正文或其他格式混改明确拒绝、不静默丢弃；不认证其余完整工具族或所有桌面行为。 |
| XLSX | loadOperations 在异步准备前加 loading，统一 finally；准备完再替换工作簿。图表重建失败恢复原操作、人工数据、活动表/选区/图表/保留对话框目标；沿原 NativeDraft 撤销恢复。恢复再失败时保留持久草稿、禁编辑/保存并明确提示重开。7 新 + 9 既有定点用例。隔离源码两视口 × read/create/loaded/render 四种真实故障共8例，输入/重试/人工 D20=77/UndoRedo 通过。最终冻结四视口另验证当前值、noop、取消与只改网格线。 | 冻结正常路径无故障注入；开发故障只在 Vite 测试转换层，无产品开关。冻结旧 insert-chart:* 仍绕过 currentOperations 保护事务，其余泛化重建不因此自动有回滚保证；完整图表继续开放。 |
| PPTX | 固定源 animation-play/AnimatedSlide 接入来源与当前草稿同一 render snapshot，异步防过期、定时器/rAF/图片/resize 清理、焦点圈、自动完成/点击/Escape/重启。真实320×640及390×320发现退出被状态栏/祖先裁剪，专属 CSS 局部修复。90 不同定点用例；最终冻结四视口真实来源淡入/擦除/路径、UI pulse 帧轨迹、退出按钮命中、焦点/草稿保全全通过。 | 20算法代码测试不等于20效果全部视觉验收；不含 SlideShow 媒体播放。未知 presetXml/缺对象明确告警跳过，源数据保留。save/download0。 |
| PDF | 固定源标题推导目录，内嵌目录优先，异步/过期取消/400页上限，明确只读不写书签或草稿；numeric destination0及真实页索引兼容修复。41 不同定点用例；最终冻结 headings/plain/embedded 三真实PDF × 两视口6例、12次实际点击后scroll/viewport/canvas导航通过。 | context/file/初始preview为明确HTTP夹具；无目录/内嵌优先/来源身份单列；save/export/publication/download0，不外推发布或全部PDF导航工具。 |

统一物理快照4181份源码最终全部摘要匹配。首轮 build 已通过但 docx-main255.7KiB/pdf-main252.2KiB/slides-main251.0KiB 超原250KiB预算；仅沿既有 manualChunks 分段落控件、标题目录及 PPTX ribbon，未提高限额。短屏 CSS 修复后最终 npm run build（内含 tsc）exit0，Vite44.64秒，413JS预算 failures=[]、预算合同exit0；docx-main252579B、pdf-main255778B、slides-main184032B、workbook-main229579B。最终 manifest `2c115d1d0badb94930c51c5917349df1f2a17ac7efa1c439641ddd43711b6bae`。没有写共享 static/dist。

180为不同定向 unit 通过数（Word33/XLSX16/PPTX90/PDF41），由多份精确日志组成，不是单次完整套件；Word最终桥12项复验未重复累计。root独立核对532格式内资源记录、346跨格式路径；另Word键盘运行154重复资源单列，合计686运行记录全部与冻结磁盘SHA一致，浏览器 errors=[]。目检Word两页签及窄屏滚动、XLSX短屏、PDF标题跳第3页、PPTX桌面与390×320退出。清单800模块/5571声明点，canonical两表与冻结inventory逐字节相同，仍非功能分母。

Word冻结完整链产生修订2实际38182B文件，保存/HTTP下载/独立python-docx与ZIP回读 SHA `f9cf53547b2b47cfb87ee3bb7e34f19603e66bf977f636aa56f7e32ff9427791`；18个文件part仅改word/document.xml，新增7个空目录记录单列。fixture validation=false 仍HTTP200下载，未标业务验收通过。实际Python是live .venv，docx_native与快照摘要一致，office_engine明确live-only且固定摘要；不冒称全Python隔离。doc桥60个symlink本地输入逐字节与快照一致，重建bundle仍2918d371…e9b2；PPTX桥显式28个workspace/子路径alias，255输入中105冻结代码/150npm，最终实际edit/render桥摘要另表。

失败证据原样保留：预算超限、Word键盘RED、XLSX四故障及准备期加锁RED、共享HMR中断、PPTX早期帧时序/夹具颜色遮挡误判和真实两类短屏裁切、PDF旧host缺sourceFile.path导致20例失败（仅修测试夹具后该文件通过）及早期导航只等active的较弱证据。root读回诊断先误比ZIP空目录、再遇无pPr段落，修正诊断后通过，未改产物或隐去原因。

统一证据 `/dev/shm/office-next-verification-20261113/summary.json`；轻量归档 `/tmp/office-next-evidence-20261113` 保存各专项日志/runner/fixture/截图、4181份物理源码、实际桥及SHA清单，排除npm与Vite缓存。最终身份检查时live已有36份并发漂移，含Word/PDF/PPTX与图表reader后续改动，另表记录且不覆盖、不认证；冻结结论不外推整份live。剩余工具族、完整图表、系统IME/读屏与真实PC Office对照继续开放；未重复完整测试、未改发布签发或Codex工作区链路、未提交/推送/部署。


## 2026-11-13 Home编号值／SelectData／PDF多文件拆分／母版文字续批（最终 b8b97ee）

固定参照仍为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。统一物理根 `/dev/shm/office-next-split-master-chart-home-20261113` 的最终源码清单为4203份，最终manifest为 `b8b97ee76d41a565f94e9f8c902e226031ada09ad9cd3bcf52deb886f421f04c`，实际native HTML为 `aaa3eb21c2eb976afff3d1ae6a7ace757b75e2613a1b7272c6613cc4728a29c2`。最终类型检查、Vite、原预算和预算合同exit0，PDF主块249.3KiB，未提高预算。历史构建及失败记录保留。

证据分层：Word、XLSX、PPTX的完整保存/下载/新修订重开绑定原manifest `352eb5fc3903b0d6c145c1f1e873e2ad983a2f58b7ec1e0d3567f18b3ba1a560`；三者在最终b8b97ee上仅重开各自原实际下载文件作0save续验，没有重复保存或签发。PDF的352eb5首次入口因初始化TDZ失败，实际0save/0split；仅修复两处document前置短路并补回归后，b8b97ee才完成该专项首次完整HTTP链。不得把两层合并写为四格式均在最终构建重跑完整保存。

本批技术闭环及UI证据按专项分别记录：

- Word Home普通列表从无定义synthetic改为可核验原定义或源五级缺省定义；稳定binding/listKind支持未使用定义与默认定义的设置编号值、历史和草稿，清除后保留原文/标题样式。352eb5完整链唯一一次4→5保存，ZIP/lxml/python-docx确认numId10/11共享abstractNum7、start1/9及15个非目标parts保全；最终b8b97ee仅重导入同一38145B下载，0save、155资源及HTML匹配、errors=[]。见[Word专项](NATIVE_WORD_HOME_NUMBERING_ACCEPTANCE_20261113.md)，证据根 `/dev/shm/office-next-word-home-numbering-20261113` 的 `browser-frozen-01/evidence.json` 与 `browser-readonly-final/minimal-evidence.json`。
- XLSX单plot SelectData沿原目标身份复核、raw向量及writer，支持取消/逐系列跨表换绑/增删重排/源缓存literal转置；修复writer已有numLit却被reader丢弃，原生预览可见。16个不同定向用例，未完整suite。352eb5完整链唯一一次4→5保存，独立openpyxl/lxml/ZIP保留人工J2/bold与另11个parts；b8b97ee重导入原7124B下载，canvas双色柱体比例、A/B与分类回读正确，390px实际取消后ops=[]，173资源、0save/0POST/planner0、errors=[]。见[SelectData专项](NATIVE_XLSX_SELECT_DATA_ACCEPTANCE.md)，证据根 `/dev/shm/office-next-xlsx-source-gap-20261113` 的 `browser-frozen-01/evidence.json` 与 `browser-final-readonly-01/evidence.json`。组合图plot/secondaryAxis仍缺。
- PDF复用原flush、实际预览确认、保存、新修订context/CSRF和extract writer，每N页生成多文件；七种批量故障注入及签发静态守卫已登记通过，实际身份不可用只丢对应份，其余继续。352eb5初始化TDZ失败完整保留；旧代码真实回归RED，document两处短路后初始化/host四项GREEN。b8b97ee首次完整链一次4→5保存、唯一一次N=2拆分、三份浏览器下载及第一份子文档重开，pypdf页序[5,4]/[3,2]/[1]，来源字节不变；60次资源响应（58个不同文件）、错误为空、390px无横溢出。见[拆分专项](NATIVE_PDF_SPLIT_BATCH_SOURCE_ACCEPTANCE_20261113.md)，证据 `/dev/shm/office-next-pdf-split-batch-20261113/browser-frozen-initialization-fixed`。拒绝AcroForm/批注/保护来源，来源级书签/附件不保留，不认证并发compare/native-AI。
- PPTX沿固定源runTxn/setText编辑真实master/layout顶层文字，部件/SPID/源身份约束，UndoRedo/草稿/IME与390px对话框通过。352eb5完整链唯一一次保存至修订2，ZIP/lxml/python-pptx仅两实体变化、另45实体保全，母版全文/两段版式文字由两页继承；初轮GET错误在保存前失败保留。b8b97ee用同一实际下载0save续验，153资源身份匹配、普通画布稳定后两页截图与文字回读通过，102后端起止检查回执均报告匹配（未保留逐文件原始哈希）。见[母版文字专项](NATIVE_PPTX_MASTER_TEXT_ACCEPTANCE.md)，证据根 `/dev/shm/office-next-pptx-master-text-20261113` 的 `browser-02/summary.json` 与 `readonly-04/summary.json`。不等于逐run富文本/组内对象/创建删除/完整MasterView，外部播放链排除。

最终三种0save与PDF完整链使用同一实际HTML入口 `lazy-preload-helper-BPPmGX_j.js` / `lazy-unified-main-D3q1w4ic.js`，按实际HTTP响应逐SHA核验，不以manifest列表替代实际加载记录；各专项截图目视及独立文件回读由专项证据支持，root统一独立复核另按已落盘JSON记录。PDF预算255.7/250.7/250.4KiB的失败历史与初始化失败均保留，通过本次职责拆包和精确初始化修复收敛，没有提高250KiB原预算。

HTTP宿主实际执行live Python，物理复制的102份后端文件仅为身份基线，不是隔离后端。XLSX四文件、PDF八文件保留实际逐文件before/after哈希且匹配旧基线；PPTX保留102文件匹配的检查回执，未保留每文件原始哈希；Word没有保留逐次后端起止身份回执，不能由前端哈希推定后端稳定。验收结束后的live后端持续并发漂移：初始记录见统一根 `live-backend-drift-after-evidence.json`，更新状态见 `root-independent-verification.json` 的 `postEvidenceLiveBackendDrift`，以具体时间的清单为准，不写全live稳定。不覆盖、不追赶重建，也不把后续live状态纳入本批结论。

保存回执继续保留 `validation.ok=false/native_source_review_pending`；PDF三份派生结果也保持validation false。已核验身份的实际文件照常签发下载，技术闭环不等于业务验收通过。各专项的独立ZIP/lxml/python-docx/openpyxl/python-pptx/pypdf回读按原记录引用；root随后完成统一只读复核，`root-independent-verification.json` 为 `ok=true`：4203源码、四格式实际下载包、最终HTTP资源和LOCAL适配登记匹配，预算未提高。该复核不等于后续live代码或生产数据库鉴权验收。整体四格式穷尽对齐目标仍active，未给全能力完成率。本次仅追加审计记录，没有重跑测试、保存、构建或修改产品。


## 2026-11-13 续批：完整字体、真实放映、PDF 比较与直接插图表

本批沿用同模型子 agent 并行推进 Word/PPTX/PDF，root 处理 XLSX 与统一集成。总体穷举与桌面 Office 对齐目标仍 active，不把本批或源码声明数当成四格式全部完成。

- 最新代码：实际 fetch 到 PR #223 的两个提交，HEAD 从 `6a713d05` 前移至 `1138887d`，与本次 fetch 的 origin/code 相同。38 个上游文件经三方核对：29 个 clean 输出与现场一致；9 个本地后续变更保留后的解析输出也与现场一致。备份 index/binary diff 后只前移 Git 分支/index 基线，6679 个工作区文件 SHA 全部不变，无 stash/覆盖、无新提交/推送/部署。证据见本批 `upstream-integration/`。
- Word：完整 Font/Advanced 双页签、Latin/EastAsia 字体槽、效果/字距/缩放/位置/kerning、混合值保留、预览和键盘焦点；复用既有 format/source-run writer。光标 pending marks 本身不保存，实际键入才继承并产生原生操作。保持普通旧 style 协议边界；表格、注释及复杂保护内容明确禁用。40 个不同定向用例（前端12、后端10、相邻18）；源浏览器15项、冻结增强18项。冻结新增三视口未编辑取消，12条确定/取消按钮真实命中；640×320 内部实际滚动后按钮完整可见。
- XLSX：九种 `insert-chart:*` 统一复用已有 captured-target/身份校验/人工网格快照/回滚/原生草稿历史事务；修复直接插图表丢失未存数据、绕过保护及错误提示隐藏。15个新增定向用例加5个相邻回归共20个不同用例；源模式两视口×四故障共8场景，明确只在测试 Vite 转换层注入故障。冻结真实UI对九种图表逐一插入，保留D20人工文本+粗体、Undo/Redo、草稿恢复、一次保存/HTTP下载/新修订重新打开；窄屏九按钮真实可命中。ZIP/lxml/openpyxl 独立核对10图表、每系列公式引用和缓存、原图XML/anchor与无关部件。九图同一选区逐次插入产生重叠，验证不冒称九种图表均逐幅目视验收。
- PDF：完整复用固定源 ComparePanel 与 compare-text 字节，真实文件选择、来源SHA/size、按页行LCS、交换、相同摘要、增删计数、4000行截断、实际来源pageId导航。未保存操作及textarea尚未暂存文字均阻止把已保存来源冒充当前内容；扫描/密码/坏文件及第二份独有页边界明确。实际同步十页上限规模约2189ms阻塞，原算法放入模块Worker后UI计时器约22.7ms可响应，支持取消/dispose。14个不同定向用例；冻结三视口、六次scroll+canvas导航、三次dispose、24个Worker创建=终止、草稿不变。首轮交互完成但资源回读因主动关闭Worker失效，单列失败；仅修runner为读取真实HTTP字节后原样fulfill，修复后的完整冻结资源核验通过（64资源/235次实际响应）。无PDF保存/导出/发布。
- PPTX：固定源 SlideShowView/动画播放器/转场/键盘与菜单核心，来源及当前草稿动画、分步、前后/跳页/结束屏、B/W黑白屏、右键/历史/查看全部、隐藏页起播、focus恢复。真实宿主补身份核验的preview直通；末页退出回到实际来源index；修复AnimatedSlide背景width在已缩放Layer中再次缩放。70个不同定向用例/12文件，来源行为探针与背景/退出短验证分开。媒体、录制、演讲者视图、自动换页及文字内链接仍为明确缺口；Morph使用实际名称而非伪造sourceID，不冒称桌面身份完全等价。

统一物理快照为 `/dev/shm/office-font-show-compare-source-20261113`，4265份登记文件；manifest `14fa70f8c1e0960a4554466df5332313a1dd9b0266fd114a8951c2a66aee6a89`。npm run build（含tsc）exit0，Vite45.17秒，原预算427JS failures=[]、预算合同exit0，未提高预算。只将字体及比较组件放入既有manualChunks自然边界，保留并发split/page-ribbon/docx-ribbon拆分；不写共享static/dist。

三类Node桥均显式映射本地workspace，所有物理输入核对位于冻结source或npm依赖：DOCX251输入（120冻结），PPTX279，XLSX254。最初provenance guard错把合法冻结frontend共享文件判为越界、继而未处理metafile的?raw后缀，两次工具失败原样保留；修正证据工具后最终构建与输入身份通过，不冒称产品RED。源runtime/测试使用的Python环境仍live；明确记录包装层边界。另用冻结docx_native/office_engine模块和新DOCX桥重放同一浏览器保存请求，所有非core部件与真实下载完全一致，core仅modified/revision元数据变化；不把该重放改称原HTTP全部Python隔离。

实际Word下载SHA `4112d20ad8b190e488718d0ab85019c032187f032f16a5fe13491f34581bef8d`；实际XLSX下载SHA `e9c8c488334d73f3b5a3dd3802013a659dd53bfce0a3511c38352bac63fee8fb`。root独立核对两文件，Word仅document.xml及允许core元数据变化，其余部件/邻段/表格保留。Word显式fixture验收失败时HTTP下载200，不改发布签发实现、不声称业务验收通过；XLSX使用授权/修订内存fixture+真实writer，不冒称生产仓储权限验证。

本批不同定向自动用例合计144（Word40、XLSX20、PPTX70、PDF14），多份目标日志去重，非完整仓库套件；未重复完整测试。冻结清单824模块/5677声明点，canonical两张表逐字节匹配；声明不是验收分母。冻结后的live并发改动单列，不被本构建认证。后续仍需真实桌面Office对照、IME/读屏、其余工具族/复杂图表及放映媒体；放映提示中的cNvPr实现术语也登记为后续用户文案清理项，本次不篡改已验收artifact。

冻结PPTX四视口最终4/4通过，背景覆盖率均1.0、最后页定位及入口焦点恢复通过，来源文件未改、保存/下载0。root独立复核四格式551条格式级资源身份记录、360个去重JS/CSS（含真实比较Worker），均与同一static字节匹配。快照4265文件无漂移；核验时后续live并发变化35份单列，不被本构建认证。 汇总见本批summary.json/asset-verification.json/README.md。证据归档至 `/tmp/office-font-show-compare-evidence-20261113`，含物理源码、实际Node桥、实际静态构建、夹具、失败和成功日志、截图及保存文件，排除npm/Vite缓存并逐文件SHA复核。


## 2026-11-13 续批：首字下沉、组合图、PDF合并、母版文字增删

本节更新上述历史缺口，仅关闭已验证范围。详见 [四格式本批验收](NATIVE_FOUR_FORMAT_DROPCAP_COMBO_MERGE_MASTER_ACCEPTANCE_20261113.md) 及其四专项。统一物理根 `/dev/shm/office-next-dropcap-combo-merge-master-elements-20261113`，4283份源码、104份后端身份基线；manifest `615163c4c3ded620bb13234122204fc6f4002f03c2c8079a1d1c444da6373650`。tsc/Vite/原预算/预算契约/四桥通过；PDF仅修构建banner后7个mjs语法通过，前端manifest未变。

- Word：固定源首字下沉无/下沉/悬挂及与正文/局部斜体组合，草稿/UndoRedo/390px/唯一4→5保存下载重开；实际38201B，16非目标部件保全。相邻一个既有装饰断言仍失败并在前批复现，不宣称全部旧测试通过。
- XLSX：bar+line组合图逐系列plot/secondaryAxis、family×axis分组与全局顺序、原主轴保留；人工J2/bold、唯一4→5保存下载重开，实际6900B。不能继续把本轮覆盖的组合子集列为未实现；完整图表格式仍需逐项源核对。
- PDF：多文件按用户列表顺序合并；未确认0save/0merge，之后一次保存及一次merge；实际3931B，独立6页回读3/2/1+B1/A1/A2并派生重开。沿既有6MiB上传边界；外部表单字段树/目录/附件不保证完整迁移、签名有效性不保证，明确告警。
- PPTX：已有母版/版式部件内新增顶层文字框、改pending文字/几何、移除pending、删原文字；唯一保存至修订2，实际48179B，47个非目录文件中只两目标parts变，45个保全。源MasterView并无创建/删除母版版式部件入口且不进入组内；这些仅作边界，不再当作已确认源差距。现有对象填充/描边等仍未由此完成。

四种保存均一次，不重复完整测试。Word/XLSX/PPTX各104实际live Python文件起止相等，但render_preparation.py/service.py两项在运行前已与冻结基线不同；PDF只核验9条签发链且匹配稳定。物理后端副本不是隔离执行。资源Word159/XLSX174/PPTX155不同文件，PDF128条响应/64不同文件均与冻结文件SHA匹配；XLSX未保留完整链原始HTML哈希，不冒充已有该回执。冻结LOCAL四旧登记通过独立sidecar调和，SOURCE和旧清单未改。

root独立复核 `root-independent-verification.json` 为ok=true，四实际下载由ZIP/lxml/python-docx/openpyxl/python-pptx/pypdf独立回读；首次工具误把ZIP目录条目计成文件身份失败保留，修正文件判定后exit0，未改产品或重保存。业务validation仍false且具体原因保留，身份已核验产物正常签发；生产数据库鉴权与全量业务验收未完成。完整对齐goal保持active，未提交/推送/部署，也未覆盖继续变化的并发live工作。

## 2026-11-13 UI审计增量：页面边框、删除/合并、母版填充、PDF检测

四个已实现UI子项及各自边界集中记录于[NATIVE_FOUR_FORMAT_PAGE_BORDER_RIBBON_FILL_DETECT_ACCEPTANCE_20261113.md](NATIVE_FOUR_FORMAT_PAGE_BORDER_RIBBON_FILL_DETECT_ACCEPTANCE_20261113.md)。专项记录了真实控件、取消/历史/恢复、桌面与窄屏操作、唯一保存及下载身份。每份保存响应仍是 `validation.ok=false/native_source_review_pending`，链接签发与业务验收状态分开。

汇总期间原临时 `/dev/shm` 冻结包无法重读，因此不新增root独立复核通过项。PDF随后发现 live 静态填写实现已经存在但未验收；在审计表里应标记为“并发实现待验收”，不要再写成确定缺少实现。固定源支持的完整边框对话框与普通画布边框层仍须分别对照源 UI；PPTX逐run也须找到真实菜单路径后才可认定为源支持能力。
