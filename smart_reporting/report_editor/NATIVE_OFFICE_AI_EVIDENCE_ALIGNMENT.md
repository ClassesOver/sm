# Office AI 证据与执行对齐增量

日期：2026-11-11。基线：`code@4cfaac23`（PR #217）；GenOffice 固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次关闭三个已复现缺口，完整四格式目标仍开放，不给完成百分比。

## 原始依据与实现

- XLSX：源 `apps/sheets/src/renderer/ai/tools.ts` 的单元格 DSL。实际合成 XLSX 经 `WorkbookAIToolkit.propose_operations` → `patch_office` 复现：`set_cell/set_formula/clear_cell` 在选区模式报 selection mismatch，整簿模式报 operations invalid。翻译器原来返回 `arguments.edits`，后续统一包装再加一层 `arguments`；现统一返回平铺参数，仅在候选 schema 边界包装一次。修复前新增六项全部失败，修复后全部通过。
- Word：源 `apps/docs/src/renderer/ai/tools.ts` 的 `read_comments` 读取线程上下文。本地原来只冻结根正文；现沿可信 `commentThreads` 的原始 comment id/parentId 收集授权根的回复，保留来源顺序、正文、作者、日期和状态，进入原有完整分页读取约束。其他根不进入快照，回复身份不获得写权限，未知/循环父关系或不可读正文拒绝生成不完整线程快照。沿用已有 comments hash 与来源文件身份拒绝过期候选。
- PPTX：源 `apps/slides/src/renderer/ai/slides-skill.ts` 的对象 dump 保留对象类型和几何。本地纯阅读曾仅收集非空 text，使无文字图表没有证据；现加入 tableCells、图表缓存、类型及几何。新增桥接只读 `chartReadData` 投影直接来自既有解析模型，包含缓存类别、系列和值，以及存在时的散点 x 值、气泡尺寸、组合系列类型。标准导入图表即使 `chartEditSafe=false` 仍可读取，写权限判定保持原有规则。缓存来源、可能过期、null 缺失值和未读取备注/图片视觉均明确进入模型指令或用户边界说明。

## 可独立复核的验证

| 范围 | 验证与结果 |
| --- | --- |
| XLSX DSL | `test_workbook_ai_tools.py`：22 passed。三种 DSL × 两种授权范围使用实际 Node 引擎预览，由 openpyxl 独立回读值/公式、未选内容和原件；原复杂筛选/表格预览与采纳测试通过。 |
| PPTX 读取 | `test_native_slides_read_ai.py`：16 passed。python-pptx 独立创建标准表格/图表并确认源值，真实桥接读取无 text 图表的 59/42；真实 Agno 使用 ScriptedModel，确认工具回执可见图表数据及服务端重建引用。涵盖冻结、连续分页、未授权内容、图片无证据、实际草稿、来源/effective SHA 和只读结果。 |
| 阅读任务宿主 | `test_native_office_read_tasks.py`：12 passed，含来源变化、取消、重排身份与范围隔离。此组与 PPTX 工具最初合跑27项通过；新增草稿图表专项后仅重跑受影响工具文件16项，不重复完整项目测试。 |
| 阅读 HTTP | `test_native_office_read_api.py`：6 passed。现有 grant/cookie/CSRF/Origin、SSE、取消及严格输入契约保持通过。 |
| Word 线程 | `test_native_word_review_ai.py`：19 项通过（完整执行18项通过，修正新增用例的fixture写入覆盖参数后，剩余服务用例单独通过）。真实 Agno ScriptedModel 回执含历史回复；真实 DOCX writer、独立 ZIP/lxml、NativeAIService 预览和显式采纳、线程/来源变化拒绝、无回复根兼容、跨线程隔离和分页均通过。 |

以上五个测试文件最终75项均通过（分批、未重复完整项目测试）。Slides `npm run bundle:bridges` 通过；目标 Python ruff 与 `git diff --check` 通过。未更改前端源码，未重复完整项目测试。合成文件与 ScriptedModel 验证不等同于真实 provider 或生产数据库浏览器端到端验收。

## 拉取源码后的本地构建事实

本地忽略目录保留了旧 `workbook_engine/dist/cli.mjs`，其中没有最新源码已有的 applySheetFilter/applyTableEdits；首次专项因此失败。核对源码协议后按 lockfile 安装依赖并重建 bundle，原测试通过，没有为旧产物改变正确的操作协议。Slides bundle 同样已按当前源码重建；Word 缺少 tsx 的依赖已按 lockfile 补齐。部署需从新源码构建引擎，不能复制工作区旧 dist。构建产物和 node_modules 不纳入本次提交。

## 整体目标仍有的缺口

1. XLSX AI 图表新增/编辑/删除仍未接入 AI 操作白名单及可信 chartPath 授权；手动图表 writer 已存在。同表多图仍缺明确目标选择。
2. Word 完整段落/制表位对话框、复杂多级列表、嵌套表结构与复杂修订仍未对齐，见 [当前缺口](NATIVE_WORD_XLSX_CURRENT_GAPS.md)。本次只补阅读线程，不开放嵌套回复写入。
3. 后续增量已补齐整稿演讲者备注阅读，当前对象选区不附带备注；图片视觉、解析器未返回的数据或外部数据源重算仍缺。复杂原生编辑仍按已有能力边界执行。
4. PDF 保留最新已交付能力；四旋转×两缩放的草稿/保存 AP 字体专项已限定通过（32标签独立文字栅格边界最大差1px），见 [AP字体补证](NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md)；后续已补CropBox/UserUnit限定组件浏览器并修复草稿线宽比例；页边长标签、复杂表单及其他转换仍见 [剩余计划](NATIVE_PDF_REMAINING_PARALLEL_PLAN.md)。用户排除的 OCR 不加入范围。两个既有 PDF WIP stash 保持原样。
5. 真实 provider 与真实保存/下载已有分层证据，但生产数据库、浏览器真实 provider、显式采纳、新修订和下载的同一条链路仍未统一验收；本次不把 scripted 证据算作该项通过。

未合并、部署或开启功能开关，未改发布签发链。


## 后续优先其他能力（同一 PR）

[演讲者备注专项](NATIVE_PPTX_READ_NOTES_ACCEPTANCE.md) 已完成整稿备注阅读及清晰引用，并修复真实浏览器发现的助手侧栏字体覆盖造成文字不可见。对象选区不附带备注；生产构建真实HTTP/授权/Agno两格式浏览器链通过，18份实际JS与manifest身份匹配，原件/草稿不变，无写请求。

[PDF字体与四旋转组件补证](NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md) 已补固定字体资产、显式回退和缩放字宽稳定性；8场景、32标签及字体失败回退通过。本次没有扩充证书、OCR或复杂表单范围。

最新依赖已按lockfile补齐；两个既有测试夹具类型问题已修且23项通过。完整tsc（Node heap 4GiB）、最终Vite50.16秒和全部JS预算通过。不会据此反推历史构建通过，仍不宣称生产数据库/真实provider整链验收。


2026-11-12 PDF续批：非零CropBox/UserUnit2与默认来源各8个组件浏览器场景通过，修复草稿线宽/箭头头部未包含UserUnit的实际bug；73项定向、完整npm build/tsc和JS预算通过。见 [AP一致性验收末节](NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md)。页边长标签仍可能裁切，普通测量路径尚无专项溢出提示，保留为开放缺口。
