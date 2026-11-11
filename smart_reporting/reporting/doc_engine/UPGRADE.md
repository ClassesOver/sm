# GenOffice 服务端包升级验证（2026-11-05）

上游：`https://github.com/genspark-ai/genoffice`，从
`c9c7a5da42cb6707e829f1968f320db69a7763c5` 升级到
`4b55db9ed1994575a695160ffc6cfd0bfc866211`。

## 同步范围与本地保留

直接映射上游 `packages/` 的七个包：`agent-core`、`docx-engine`、
`pipelines`、`pptx-engine`、`pptx-ops`、`pptx-render`、`zip-gate`。
本次上游差异共 65 个文件，变动集中在 `docx-engine`、`pptx-engine` 和
`pptx-render`，含对应上游测试和二进制 fixtures。未新增产品入口。

通过 `git ls-tree -r --name-only HEAD -- packages/<七个包>` 逐文件读取上游
Git blob 并比较本地字节：上游文件缺失数 0；唯一非同字节文件为之前就存在的
`packages/pptx-engine/src/vendor/mtx/LICENSE`，保留本地完整许可文本。
`LICENSE`、`NOTICE` 与上游目标提交相同，升级区间本身未改这两个文件。

保留 `bridge/`、根 npm workspace/build 配置和锁文件，以及本地新增的
`packages/pptx-render/src/browser.ts`。锁文件离线重算无差异，因为包依赖未变。
没有替换本地画布适配，也没有增加 Plotly 功能。

## 接口与非阻断检查

- `PictureRenderNode` 新增可选 `ole?: true`，OLE 预览保留自身 fill，无 fill 时才补白底。
- `@genoffice/pptx-engine/dgm-hier` 新增子路径导出；hierarchy1 布局及连接目标 `to?` 为兼容性增量。
- bridge 请求/响应结构未变；生成和编辑仍先写文件，再将 audit 失败转成 issues。
- 上游本次新增源码行未新增 `throw`；未改报告发布或下载签发链路。

## 验证命令与结果

除 Python 命令在仓库根执行外，其余命令在本目录执行。未运行仓库完整测试。

| 命令 | 结果 |
| --- | --- |
| `npm exec --workspace @genoffice/pptx-engine -- vitest run tests/dgm-hier.test.ts` | 14 passed |
| `npm exec --workspace @genoffice/pptx-render -- vitest run tests/passthrough-preview.test.ts` | 7 passed |
| `npm run test --workspace @genoffice/pipelines` | 6 files / 77 passed |
| `npm exec --workspace @genoffice/docx-engine -- vitest run tests/char-class.test.ts tests/decorated-paragraphs.test.ts tests/duplicate-style-refs.test.ts tests/font-table.test.ts tests/hf-images.test.ts tests/metafile-render.test.ts tests/nested-field-hf.test.ts tests/numbering-defs.test.ts tests/protected-page-break-before.test.ts tests/resolve-props-body.test.ts tests/resolve-props-direct.test.ts tests/resource-cleanup.test.ts tests/shape-extraction.test.ts tests/shape-wrap-patch.test.ts tests/smartart.test.ts tests/table-style.test.ts` | 16 files / 281 passed |
| `.venv/bin/python -m pytest smart_reporting/reporting/tests/test_slides_engine_bridge.py smart_reporting/reporting/tests/test_slides_render_tree.py -q` | 18 passed；含编辑 audit 抛错后保留 PPTX |
| `.venv/bin/python -m pytest smart_reporting/reporting/tests/test_pptx_delivery.py::test_pptx_audit_exception_keeps_generated_artifact_and_returns_warning -q` | 1 passed；生成 audit 抛错后保留 PPTX |
| `npm install --package-lock-only --ignore-scripts --offline` | exit 0；锁文件无变化 |
| `npm run bundle:bridges` | exit 0；4 个 bridge 打包成功 |
| `npm run typecheck --workspaces --if-present` | 6 个包通过；pptx-engine 的既有测试工具缺失导致整体 exit 2，详见下文 |
| `node_modules/.bin/tsc --noEmit --project <临时源码配置>` | PPTX engine 运行时 src 检查 exit 0 |
| `git diff --check -- smart_reporting/reporting/slides_engine`（仓库根） | exit 0 |

PPTX 源码临时配置继承本目录 `packages/pptx-engine/tsconfig.json`，设置
`compilerOptions.typeRoots` 为本目录绝对路径 `node_modules/@types`，
`include` 仅为绝对路径 `packages/pptx-engine/src/**/*.ts`，`exclude` 为 `[]`。
临时配置位于系统临时目录并已自动删除；没有修改原包 typecheck 范围以隐藏错误。

### 既有整包 typecheck 限制

`pptx-engine` 测试引用 `../../../tools/ooxml-validate/validate-pptx.mjs`，但
vendor 未集成上游 `tools/`。本次未扩大同步范围去补测试工具树。基线证据：

```sh
git show HEAD:smart_reporting/reporting/slides_engine/packages/pptx-engine/tests/chart-workbook.test.ts
# 已包含上述 import（第 7 行）
git cat-file -e HEAD:smart_reporting/reporting/slides_engine/tools/ooxml-validate/validate-pptx.mjs
# fatal: path ... does not exist in HEAD
git diff -- smart_reporting/reporting/slides_engine/packages/pptx-engine/tsconfig.json smart_reporting/reporting/slides_engine/packages/pptx-engine/tests/chart-workbook.test.ts
# 无差异
```

同样的缺失 import 影响其他若干原有 schema 测试，并引发依赖类型无法解析的
隐式 any 诊断。标准整包检查尚未全绿；运行时 src 检查与桥接实际运行均通过。
Python 检查仅出现依赖 `imghdr` 的 Python 3.13 废弃告警。

## 原生编辑早期切片（历史检查点，最新进展见文末）

升级后新增独立的 PostgreSQL 原生文档/修订仓储，以及 DOCX/PDF 字节桥接。
它们不修改 Markdown 权威内容；当前没有新增原生 HTTP 编辑路由或浏览器页面。

- 原生仓储 9 项定向测试通过，包含真实 PostgreSQL 两个独立 Python 进程预约；
  初始验收为 pending，saved 修订不可覆盖。两个新模块的 mypy 与 ruff 通过。
- DOCX 桥接 22 项定向测试通过，覆盖段落/基础样式/简单表格、未修改部件保留、
  来源和输出身份、源文件覆盖拒绝，以及单元格静默写回失败；桥接源码类型检查通过。
  新增独立包测试仅复制 `edit-docx.mjs` 到无源码、无 node_modules 的目录，
  实际 inspect/patch 并经 python-docx 回读，1 passed。图片替换尚不支持，
  复杂对象只读；尚未经过 Microsoft Word 桌面和浏览器验收。
- PDF 基础桥接 13 项 Python 实际运行测试及 2 项 Node 边界测试通过；
  另补软链、硬链、路径别名覆盖回归，先失败后通过。支持页面与便签/高亮操作，
  便签不是内容流文字插入。后续已完成 PDF 独立生产 bundle、固定 WASM 与许可打包，
  4 项新增运行包用例通过；真实 Node 22.23.4 离线容器内完成编辑与独立回读，
  Docker 的 `report-pdf-engine` 阶段构建通过，详见 `../pdf_engine/SOURCE.md`。

升级基线与 DOCX 运行环境实际为 Node 24.18.0；PDF 独立运行包另有 Node 22 验证，
完整应用镜像与 DOCX Node 22 仍需单独验收。
完整实施计划位于本地 `docs/superpowers/plans/2026-11-05-native-office-editing.md`；
仓库忽略 docs 目录，该文件尚不在 Git 版本控制中。

DOCX 补充审查：修订行回归先失败（错误声明 cell 可编辑），修复后执行
`.venv/bin/python -m pytest smart_reporting/reporting/tests/test_docx_engine_bridge.py -q -k 'tracked_table_row or changes_text or complex_cell'`，
3 passed / 20 deselected；包含新增修订行拒绝和必要的普通单元格仍可写、嵌套表格只读对照。
含表/行修订、内容控件或合并结构的表格全部单元格只读；普通表格的安全单元格仍可编辑。
最新 5 个 bridge `bundle:bridges` 打包成功，`edit-docx.ts` 定向 `tsc --noEmit` exit 0。
未重跑原 22 项基线或 281 项上游测试。

## 原生授权与保存后端进展（历史检查点）

原生来源分支、独立授权/CSRF、上下文/文件/预览/保存/导出及下载路由已接入应用。
功能开关默认关闭，浏览器页面尚未实现；Task 3 不能等同于 Word/PDF 编辑产品上线。
原生工作区使用独立 registry，可从可信 scope 在重启后重绑，普通报告会话不能直接
访问原生修订。18 项 API 定向测试分批通过；应用工厂接线 1 passed。

发布服务使用独立修订与内容寻址路径，保留已核验文件，验收、登记、副本、授权和
PDF 转换失败均返回具体 issues。16 项原生发布用例分批通过；HTTP 新增 9 类故障
（含恢复记录检查及主格式身份故障）均保持实际可下载格式。AGENTS.md 列出的
11 个非阻断回归节点按参数展开为 69 passed / 2 deselected，未跑仓库完整测试。
新增签发函数已纳入静态守卫。原生 bearer 路径日志脱敏新增 3 项回归，与既有
脱敏检查合计 6 passed。修订 note 已真实持久化，旧表补列/幂等回归 1 passed。
DOCX 字节上限已与产品的 24 MiB 对齐，真实超过 10 MiB 文件 inspect/noop 回归
先失败后通过，未重复 DOCX 基线套件。

前端目前仅新增原生 API 和草稿基础，已验证作用域/快照隔离、撤销重做、恢复、
失败保留、稳定重试 requestId 与旧版保存后锁定。完整 Word/PDF 页面、AI、上传
和整镜像验收仍按计划继续推进。所有改动尚未提交或部署。


## 最新升级核对及浏览器交付（2026-11-05）

完整独立源码仓库 `/home/junge/pros/genoffice-source-full` 已通过 Git fetch 和
fast-forward 更新到 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，与当次
`gh api repos/genspark-ai/genoffice/commits/main` 一致（提交时间
2026-11-05T04:14:42Z）。相对上一基线新增六提交，七个服务端包无新增差异。
Word 浏览器闭包仅 `editor/hf-dom.ts` 有交集，已同步 PAGE 字段 helper 并刷新
原始/本地 SHA 清单。PDF 字节模块、PPTX 浏览器模块无交集。
XLSX 仍是明确记录的选择性回移：新增桌面外链 break/retarget、公式导出等待与
打印选项依赖桌面/Rust gateway，未移植，不宣称与完整上游桌面功能相同。

Word/PDF 原生页面已接入主入口，默认编辑开关仍关闭，尚未部署。Word 使用真实
GenOffice Tiptap 和分页预览，支持正文/基础整段格式/简单表格/段落插删；复杂对象
保留并拒绝不支持的编辑。PDF 使用 PDF.js 6.2.108，支持搜索、高亮、中文便签、
旋转、删页、重排、撤销。便签不等同 PDF 内容流改字，原位改字仍未交付。
共享页面接入草稿恢复、幂等保存、失败告警/下载、显式打开新修订和保存后旧版锁定；
渲染失败保留原件下载，编辑开关关闭不能经页面更新重新启用保存。

真实 Chromium 使用 NativeEditorService、原生 grant/cookie/CSRF、Publication、
实际引擎及下载服务（仅修订仓储为 typed in-memory fixture），完成编辑→保存→
下载→新修订重开。Word 下载由 python-docx 验证文字/粗体/页眉页脚，另验证简单
表格写回；PDF 下载由 pypdf 验证页序/旋转/非零 CropBox/高亮/中文便签。PDF
主入口 startNativeEditor 再完成同一真实链，浏览器 pageerrors=[]。PDF.js 坐标
额外验证 4 个旋转 × 3 个 zoom（CropBox 原点非零且 CSS 缩放1.3）。
临时截图与下载证据分别位于 `/tmp/word-native-web-smoke/`、
`/tmp/pdf-native-web-smoke/`；临时目录不是长期版本化验收附件。

Word AI 后端使用已有 Agno 结构化输出，真实引擎核验完整草稿与候选，选区授权、
快照过期、取消/采纳竞态已覆盖。原 13 个定向测试和新 3 个取消/缓存回归分批通过，
新增修复经独立只读复核。前端新增选区→建议→显式采纳/取消，采纳进入草稿，
不自动发布；新增 XSS 文本展示、冲突保留、等待期间继续编辑不能被旧候选覆盖测试。
尚未用真实在线模型完成端到端 AI 浏览器验收。

DOCX 独立 bundle 已在 Node22 离线容器实际编辑中文、保留页眉并核对原件与回执；
此前 DOCX Node22 缺口已补齐。PDF 独立 Node22 与 Docker 阶段验证继续有效。
完整应用镜像、桌面 Word 全版式、用户上传和四格式联合验收仍未完成。

新页面整体前端 build 与 build:slides 均通过；后者复用主入口的浏览器别名以避免
原生模块解析遗漏。Word 本地化按模块拆分，最大渲染包由约3.6MB降至约694KB；
新增固定引擎预算（含解析 Worker），普通模块250KiB和入口180KiB限制保留。
预算与预算契约检查通过。PDF.js cmap/字体/WASM及许可证、GenOffice许可证/NOTICE
纳入构建复制。未重复运行仓库完整测试，未提交或部署。

## PDF 文字、四格式上传与灰度准备（2026-11-05）

PDF 原位改字已实现。服务端重建原始文字对象身份，验证内容哈希；定位不唯一、
字体缺字、空间不足等情况保留原文并返回跳过清单。浏览器显示实际写回的 PDF，
保存绑定用户已确认的预览摘要，字体或操作变化后要求重新预览。PDF.js 与
PDFium/HarfBuzz 分别负责浏览器展示和内容流写回。定向测试覆盖中文、数字、
原文消失、无覆盖标注、资源变化、混合成功与跳过；另核对实际输出的图像对比。
PDF 文字 AI 复用 Word 的 Agno 候选服务，仅允许选区内替换，支持候选预览、取消、
采纳和快照检查。15 项新增 PDF AI 用例、2 项 Word 兼容用例和 3 项共享面板用例通过；
其中模型调用由测试替身提供，不能据此声明真实在线模型已验收。
首次合成 PDF 在线探针因测试装配漏掉生产应用的思考配置，在发送 HTTP 前失败；
外层 JSON 错误不是提供方响应。补齐生产配置后，使用同一提供方真实请求，
以 `json_object` 获得有效候选。首个较长替换被实际引擎跳过并保留原文；
第二个同宽数字样本通过候选生成、采纳和真实 PDF 预览（零跳过），pypdf 确认
旧字消失、控制行保持、源字节未变。这是合成样本服务级在线验证，未使用业务
报告或生产浏览器会话。

四格式上传 API 与同源可挂载组件已实现。签名能力确定工作区身份，上传上限 24 MiB，
按文件实际结构识别格式。Chromium 实测四格式上传、手工修改、保存、实际下载和
重开新修订；后端使用真实授权、引擎、签发与下载，修订仓储采用测试替身。
DOCX/PDF/XLSX/PPTX 分别用 python-docx、pypdf、openpyxl、python-pptx 独立读回，
且原文件身份不变。该结果不替代系统报告产物验收，也不代表外部宿主已挂载组件。
XLSX/PPTX 保存后结构回读故障的两项 HTTP 注入均保留真实修改与下载，
并返回 `native_office_read_validation_failed`。必需非阻断契约 69 passed / 2 deselected。

补做现有系统报告路径的 XLSX/PPTX 手工验收：使用隔离合成报告、真实 FastAPI
报告编辑路由、真实引擎、文件存储与签发，仓储为测试替身。两种格式均由修订 1
保存为修订 2，下载和重开均 HTTP 200，哈希与签发一致且原件未变。独立读取
确认 XLSX 改值且保留公式文本、数字格式和合并范围（未计算公式缓存），PPTX
改字、移动对象且保留页数和版式。旧报告路由的保存父版本来自授权入口，
未增加持久化父版本字段。此检查不包含实际 AgentOS 报告生成、AI 或桌面软件验收。

合并 PDF AI 面板后的前端两类生产构建、构建预算与预算契约检查已通过；
新增 Python 模块定向类型检查及 Ruff 检查通过。

新增正式功能开关、旧环境变量回退、按启用能力检查的 readiness 及 Loguru 事件。
此前完整应用镜像已用 Node 22.23.4 断网验收：三个独立引擎运行包、WASM 与许可、
PDF.js 静态资源、上传模块、中文 PDF 实际改字探针和全开关 readiness 均通过。
最终镜像 `smart-reporting:native-20261105` 已增量重建，镜像 ID 为
`sha256:0e0c1e21e73d5a997d8616c14750be8a0456742141216f866469eb4a91e1884e`。
镜像内 11 个原生 Python 模块 SHA-256 均与本地一致；再次断网通过全部 11 项
readiness 检查，DOCX/XLSX/PPTX 实际编辑并独立回读通过，PDF 实际中文替换
探针通过。未部署。灰度及回滚步骤见
[原生 Office 接入指南](../../report_editor/NATIVE_EDITING.md)。

追加移动端 Word 导出验收：390×844 触屏 Chromium 中编辑合成文档后直接导出，
修订 2 由修订 1 派生。Word/PDF 签名下载均为 HTTP 200，哈希与回执相符，
python-docx 和 pypdf 独立回读均包含修改，重开新修订保留正文且原件不变。
使用真实 DOCX 写回和 LibreOffice 转换；该样本仅验证单段编辑与导出。

## 原版功能区增量验收（2026-11-06）

固定源码基线保持 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
DOCX 桥接 modelSource 已统一为该版本，原始 docx-engine 包树在旧基线与该版本
相同；本地仅给既有编号、缩进 helper 增加 export，不改 helper 函数体。
本次逐项核对 Docs 原始来源清单 230 条，规范化相对路径后均匹配固定提交。
本地清单发现三个过期记录（来源清单、来源说明、Home 中文提取词条），已按实际
文件字节更新；没有以本地哈希替换原始上游清单。

Word 页面设置新增真实浏览器验收：
`DOCX_SMOKE_MODE=section-layout node smoke/docx-native-save-smoke.mjs` 通过。
浏览器保存、下载并重开修订 2；python-docx 独立读取 A4 横向 16838×11906 twips、
双栏、上/右/下/左边距 720/720/720/1200，以及页眉/页脚距离 800/900。
切换选区和标签后设置保持，原修订字节未变，验收失败仍保留下载。
该 smoke 的上下文/预览传输和修订登记使用测试替身，不代替真实 HTTP 授权验收。

PDF 反序复用已有 reorderPages 写回；独立 pypdf 已读回两个不同页面尺寸的反序，
四个表单值保留。XLSX 已修复真实 Univer remove-rows 结构变更采集；PPTX 已增加
16:9/4:3 页面尺寸写回和草稿恢复路径。各格式完整原版功能区仍未对齐；最新恢复
改动后的最终集成、镜像重建/断网及四格式 HTTP 验收仍需完成。此前镜像和 HTTP
结果只证明对应历史源码状态，不能作为本轮新增功能已部署的证据。功能开关未开启。


2026-11-05 PR #190 follow-up: PPTX Design adds custom cm/mm/in dimensions,
validated as integer EMU coordinates from 1 to 56 inches per axis in both
native API and file bridge. Both axes share one draft/history operation;
canvas resizing is materialized on save/reopen. New-presentation default size
remains unavailable without a blank-deck creation flow. Feature flags stay off;
no deployment or production database acceptance is implied. See
`NATIVE_RIBBON_PLAN.md` for scoped validation and remaining acceptance work.

Custom-size browser acceptance now passes with an explicit Chromium 154
executable and a native-input preflight. The earlier input failure also occurs
in bare HTML on the managed Chromium 140 runtime, so it is not evidence of an
editor defect. See `NATIVE_RIBBON_INPUT_DIAGNOSIS.md` for the controlled
comparison, exact command, independent file/geometry readback and limitations.
Custom sizes can swap orientation without selecting a preset; matching
aspect ratio alone never labels a custom size as a standard preset.


Word link bridge follow-up: `edit-docx` now accepts source/object-anchored
`setParagraphLink` UTF16 ranges (href HTTP/HTTPS/mailto, or null to unlink).
The adapter reuses the unchanged fixed GenOffice run/relationship serializer;
original unstyled links are marked for plain preservation before paragraph
regeneration, including untouched fragments. Unsupported metadata grouping and
linked-source text replacements fail explicitly. No vendored engine file changed.
See report_editor/NATIVE_WORD_LINK_ACCEPTANCE.md for targeted, independent and
packed-runtime/browser evidence and remaining limitations.


Native PPTX Home Paragraph now supports six source line-spacing multipliers and
0–500pt before/after spacing through a nonempty strict paragraph-format patch.
Readback preserves mixed/unset and alternative source units; only explicitly
changed fields are written. The pinned engine is unchanged. Scope, commands,
independent readback, restore/lock tests and packaged HTTP/browser evidence are
in `NATIVE_PPTX_SPACING_ACCEPTANCE.md`. Bullet/indent/direction and complete
source parity remain open; feature flags remain disabled.


PPTX Paragraph continuation (2026-11-06): source bullet/number galleries, custom
Unicode, start value, hanging indent, bullet size/color, relative level and
LTR/RTL are connected through strict fields and the unchanged pinned formatter.
Draft records retain execution order; mixed/inherited values, overflow and
500-record budget are handled explicitly. Picture upload stays visibly disabled;
caret/table/group editing is not covered. See `NATIVE_PPTX_LISTS_ACCEPTANCE.md`
in report_editor. Real PostgreSQL repository plus four-format ASGI/file
acceptance is recorded in `NATIVE_POSTGRES_ACCEPTANCE.md`; production grant
storage and clean application-image acceptance remain open.


Word 表格后端保真阶段（2026-11-06）：新增受限固定列宽表的增删行列
协议，复用 pinned generator 并按源坐标保留幸存格原 XML；原段落属性
丢失问题在独立探针中消除。单表单结构操作、同表文字混用拒绝、新修订
锚点及实际写回检查已接通。前端仍不开放结构编辑；详见 report_editor
中的 `NATIVE_WORD_TABLE_ACCEPTANCE.md`。未修改 vendor 源码或发布开关。


Word 表格前端阶段（2026-11-06）：新增 adapter 复用 `@tiptap/pm/tables`
和 `closeHistory`，连接六个受限结构命令与源坐标草稿/历史。没有修改
vendor 或后端序列化代码。真实浏览器发现并修复光标跨表、快速操作
历史合组问题；下载 XML/宽度保真及新修订重开通过。仍须保留复杂表格
拒绝与单表单操作限制，不把本阶段算作完整源功能区或桌面验收。


并行补缺阶段（2026-11-06）：Word 上下标新增严格整段操作与显式baseline
文件继承覆盖，pinned vendor不改；PPTX ApplyAll复用formatter，但inspect新增
源元数据gate，以拒绝旧formatter不能保留的speed/advClick/sound/变体/AC。
Excel旋转修复上游reader的direct numeric attribute路径，新增继承来源只读
gate并刷新UPSTREAM/LOCAL SHA清单；PDF RotateAll只组合现有rotatePage操作。
四格式均有真实下载与独立读取证据；PDF最终使用生产静态preview避免dev HMR
环境问题。Word baseline在Node22只读断网包通过3个受影响检查；此前新Word表
结构流程另以真实SQL修订、字节块和两类授权仓储通过，仍不是生产身份认证
或完整应用镜像验收。详见report_editor新增的四份格式专属验收和
`NATIVE_WORD_TABLE_SQL_ACCEPTANCE.md`。未开启开关、合并或部署。


2026-11-06 PPTX 单页保真补缺：新增 native bridge 薄适配层，复用 pinned
效果生成器、XML 工具和 dirty hook，只替换视觉效果，保留转场属性、
sound/ext、音频及关系字节。vendor 未改。普通来源及固定 Morph MC 支持；
未建模 MC/效果/重复容器显式只读，UI/草稿/强制后端请求共同执行。
批量 ApplyAll gate 不放宽。29 个不同新文件用例、20 个已有批量用例、
浏览器下载独立读取，以及 Node22 只读断网包三个定向用例通过；两份生产
构建和预算通过。详见 `report_editor/NATIVE_PPTX_TRANSITION_PRESERVATION_ACCEPTANCE.md`。
原 upstream setter 的历史丢失探针仍有效；未声称桌面/播放/完整镜像通过。


2026-11-06 PDF 当前页裁切：bridge 增加严格 cropPage 和明确能力标记，复用
pdf-lib CropBox 原语与 PDF.js 逆变换；不改 vendor。绝对来源坐标支持重复
裁切/旋转/删页/重排及表单组合，保留内容流。浏览器四种旋转和 UserUnit2、
实际下载/pypdf、ASGI组合、Node22断网只读与两份生产构建通过。32项本地
SHA核对中同时校正一条历史测试过期记录；SOURCE清单不变。独立bridge tsc
仍有六项已有桌面类型声明缺失，与HEAD对照零新增，不记作干净通过。详见
`report_editor/NATIVE_PDF_CROP_ACCEPTANCE.md`；全页裁切/其他Page命令和桌面/
完整镜像/生产身份仍未验收，开关关闭。


2026-11-06 PDF 裁切全部保留页：仅扩展原生对话框和草稿适配，各页复用自身
PDF.js 逆变换生成既有严格 cropPage；全部预备成功才提交一步历史，异常/
取消/超预算不保留半批结果，准备期间阻止重入。后端/vendor/运行包不变。
混合尺寸/方向/UserUnit 与实际下载、pypdf 回读见
`report_editor/NATIVE_PDF_CROP_ALL_ACCEPTANCE.md`；不累计前阶段后端验收为新增，
其他 Page 命令、桌面和完整镜像仍未完成，开关关闭。


2026-11-06 PDF 五档页面尺寸：严格 preset 操作复用未改的 setPageSizeBytes，
全局等比缩放/居中放在其他来源操作之后；源单位、导航、印刷框、签名及
未建模批注保守只读，不与裁切/改字混用。原始 UserUnit2 物理尺寸偏差
探针保留。真实写回预览使用输出页边界，服务不依赖文字开关；签发代码
未改。35个新文件用例、40个受影响文件用例、53个PDF前端检查、新服务
及既有文字服务检查、浏览器下载/pypdf、Node22两例和最终构建预算通过。
详见 `report_editor/NATIVE_PDF_PAGE_SIZE_ACCEPTANCE.md`；独立bridge tsc仍
有六项基线桌面声明问题，零新增，不视作完整镜像/桌面验收，开关关闭。


2026-11-06 PDF 文字选区标注：引入固定源 annotations.ts 的选区/匹配算法，
以单独原始/适配 SHA 与变更通知保留来源；严格 addMarkup 复用未改 AP writer，
支持四类型、多行、源颜色、待保存切换、回放与实际输出预览。已保存标注
移除仍明确禁用，读取不完整来源拒绝。44新文件/40受影响文件、14新前端/
52受影响前端、新服务/四既有服务、Chromium/pypdf及Node22两例通过；
详见 `report_editor/NATIVE_PDF_SELECTION_MARKUP_ACCEPTANCE.md`。整体差异
与真实签名依赖分别见 ALIGNMENT_STATUS 和 SIGNING_WEB_DESIGN 文档，不将
禁用项、设计或缺服务的路径算作完成。开关关闭。


2026-11-06 PDF 纯阅读补缺：源位图夜间滤镜、18阶梯/10–800%缩放、状态滑块、
Ctrl/Meta滚轮及原生DOM内容锚点接通；文件、草稿及后端运行包不变。源码
核对补列遗漏的批注侧栏/比较/附件并明确禁用，不计完成。7项定向前端
检查、只读Chromium视图/真实滚轮/打印媒体隔离/源字节相等与两份构建预算
通过，详见 `report_editor/NATIVE_PDF_VIEW_ACCEPTANCE.md`。阅读位置持久化、
完整快捷键/行布局及整体源功能仍未完成，开关关闭。


2026-11-06 PDF 已保存四类文字标注移除：固定源 pending-first/单一 saved 匹配
与先删除后改字顺序接通，使用独立来源页/原标注序号身份及字典SHA，
只解除该页引用并复制共享Annots数组；未修改vendor删除writer或增加几何
回退。关联/签名/复杂来源只读，实际预览和新修订可回读。18个新文件、
34个相关前端、2个服务、2个受影响来源用例及Chromium/pypdf通过；Node22
断网只读验证移除、无字体时改字跳过仍保留移除、伪造请求无产物。两份
构建和预算、33项本地SHA通过；独立bridge仍有六项基线诊断。证据见
`report_editor/NATIVE_PDF_MARKUP_REMOVAL_ACCEPTANCE.md`，保留失败迭代，
不声称完整镜像/桌面/生产或全PDF对齐；开关关闭。


2026-11-06 PDF 逐处搜索：固定search.ts与ui/find-text.ts算法独立复用，
保留上游/本地SHA和变更声明；逐处框/计数、大小写/全词、循环导航、
快捷键与原稿/实际预览页身份映射接通。删除/重排与异步预览重建有
浏览器检查，八个新定向/七个受影响前端检查通过；后端和运行包未变。
详见 `report_editor/NATIVE_PDF_SEARCH_ACCEPTANCE.md`，不把OCR、浮动栏、
复杂字形精确几何或完整镜像/桌面/生产对齐计作完成，开关关闭。


2026-11-06 PDF 既有便签：严格editNote/removeNote使用来源标注身份/字典SHA，
原位Contents/M及复制数组解除引用，UTC修改时间固定在草稿中；应用/取消、
恢复原文、历史/刷新、实际预览及修订下载重开接通。发现并修复pdf-lib
getForm先删XFA导致后续能力检查漏读，原始XFA提前检查保护便签/标注移除、
尺寸和表单。23新文件/7受影响文件、38前端、3服务、Chromium/独立pypdf、
最终字节重放和Node22断网只读4场景通过；两份构建/预算、33项SHA及Ruff
通过，独立bridge六项基线诊断无新增。证据见
`report_editor/NATIVE_PDF_SAVED_NOTES_ACCEPTANCE.md`，线程/回复/复杂源和
完整镜像/桌面/生产仍未完成，开关关闭。


2026-11-06 PDF 未保存便签：编辑/删除直接改变原新增记录，整份草稿快照+位置
防止相同便签移位后旧回调误删；应用/取消、历史/刷新、删页撤销和重开
接通。13新+38受影响前端检查、新浏览器指针放置/过期控件/只读/页历史/
保存重开及已有便签浏览器回归、独立pypdf保真、两份构建/实际预算通过。
后端/运行包不变，未把旧Node22/SQL结果算新检查。详见
`report_editor/NATIVE_PDF_PENDING_NOTES_ACCEPTANCE.md`；pending-only实际预览/
创建时间绑定、线程/回复和完整桌面/镜像/生产未完成，开关关闭。


2026-11-07 PDF 新增便签实际预览/时间：createdMs在草稿中固定，未改AP writer；
验证新增尾部数量/正文/源round2矩形后仅规范化新日期为UTC，旧草稿缺时间
保持未知。服务/界面实际PDF预览及下载字节一致，保留原文/原便签/表单。
14新文件+2受影响文件、2漂移守卫、57前端、5服务、Chromium/独立pypdf
和Node22断网只读5场景、两份构建/预算/Ruff/35项SHA通过；bridge六项
基线诊断无新增。上游同一瞬时在不同时区输出不同字节的反例保留，
详见 `report_editor/NATIVE_PDF_NOTE_PREVIEW_ACCEPTANCE.md`。线程/回复、
完整侧栏/桌面/镜像/生产仍未完成，开关关闭。


2026-11-09 Word 清除格式前置协议：本地 edit-docx bridge 的 formatParagraph/formatRange 接受 fontFamily/fontSize/color:null，移除直接属性及主题/复杂文字对应 XML；原样式引用保留以恢复继承。区间外 run 及其他属性保留。前端差分与 replay 同步支持，完整清除格式按钮尚未接通。80个相关前端测试、9个DOCX桥接测试、bridge bundle及定向源码tsc通过；未重复完整测试。审查独立主题字体/rtl/lang/bdr探针通过。

2026-11-09 Word 清除所有格式续批：新增原子 clearParagraphFormatting（来源身份+UTF-16有序范围），选区去除 marks、默认样式恢复、标题转普通段、保留列表编号和多数覆盖规则；rawPPr 仅清源定义的直接段落属性，非目标属性保留。来源样式继承编号具体化。packages/docx-engine/src/generate.ts 的字体生成条件加入 eastAsiaFont，修复清除其他字体槽后仅剩东亚槽被漏写的问题。10项Python回读、6项新增前端、真实Chromium保存下载重开验收通过；完整边界见 report_editor/NATIVE_WORD_CLEAR_FORMATTING_ACCEPTANCE.md。表格/子编辑器/内联对象/同段混合修改仍缺，不代表全量对齐。


2026-11-10 Word 来源注释标记后的原生输入：`parse.ts` 的既有 noteRef 分支复用
`buildRun(..., keepEmpty=true)` 补齐完整 Run 格式模型；原 rawRPr、noteRef 身份
和标记输出 XML 保留。桥接把同源 marker 样式继承为普通 text 时仅去掉 noteRef，
普通生成器因而保留 superscript/rStyle 等受管属性。无第二次 ZIP/文档解析，
不新增客户端 raw XML 协议。SOURCE.md 记录更新后的 parse.ts SHA-256。
验收证据见 `report_editor/NATIVE_WORD_NOTE_REFERENCE_INPUT_ACCEPTANCE.md`；
此项只修复可信来源继承，不表示复杂注释/任意内联编辑全面对齐。
