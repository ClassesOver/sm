# 系统配置与格式偏好管理实施计划

2026-11-12 密度与排版维护增量：系统日常配置保持12项，表单自然高度/限宽；修复390px横向目录网格最小宽度溢出。Word/PDF六种文字角色折叠维护与修正错误后保持展开接通；23项组件、11项密度/视图、实际原生2项、浏览器保存/回读1项通过，构建预算通过。全设计及应用入口仍未完成，不整体勾选。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付系统配置、偏好管理两个菜单，并使经过验证的全局默认真正作用于新任务的生成、预览及五格式导出。

**Architecture:** 复用现有 PostgreSQL 管理存储、管理员认证、事务锁、CAS 与审计。配置清单、格式偏好模型、版本服务和执行适配分别承担一个职责；任务保存所用版本和解析值，不依赖可变进程环境。未接通实际执行器的能力不开放应用入口。

**Tech Stack:** Python / Pydantic 2 / SQLAlchemy / Alembic / FastAPI，React / Ant Design / TanStack Query / Zod，现有 Word/PDF 运行时和 XLSX/PPTX 原生引擎。

**Spec:** `docs/superpowers/specs/2026-11-12-system-config-format-preferences-design.md`

## 全局约束

- 两个独立一级菜单：「系统配置」「偏好管理」。现有「数据源」保持置顶。
- 偏好采用全局默认，由管理员维护；首版不增加个人覆盖或组织管理。
- 必须有可设计的落款，页眉页脚及常规 Office 偏好纳入同一设计。
- 不改变业务原值、计算口径及历史修订；原生 Office 内容可编辑。
- 尚未实现或实际验证的能力不能显示成已生效。禁止新增可保存却被执行器忽略的配置。
- 不修改全局 `os.environ`；部署基础项只读；敏感值复用凭据库，不进入配置文档和审计。
- 仅运行受影响的定向测试，不重复完整测试。修改签发链路时必须跑 AGENTS.md 指定非阻断回归。
- 当前 `code` 分支包含前序大量在途改动，原地增量推进，不提交、重置或部署；本次新增文件和局部修改单独记录。

## 任务 1：格式偏好契约与继承解析

**文件：**
- 新建 `smart_reporting/preferences/models.py`：五种格式的完整类型、字段约束、公共值继承、适用性边界。
- 新建 `smart_reporting/preferences/__init__.py`。
- 新建 `smart_reporting/tests/test_format_preferences.py`。

**接口：** `FormatPreferences.from_delivery(settings)` 从当前交付设置初始化；`resolve_format_preferences(document, format)` 返回独立的已解析字典。署名必填，日期仅指定格式、不在解析时取当前时间；字体仅支持实际内置的 sans / serif。

- [x] 先写失败测试，验证中文署名、继承及逐字段覆盖：

```python
prefs = FormatPreferences.from_delivery(ReportDeliverySettings())
changed = prefs.model_dump(mode="json", by_alias=True)
changed["common"]["signer"] = "报告编制人"
changed["word"]["common"] = {"accentColor": "#123456"}
resolved = resolve_format_preferences(FormatPreferences.model_validate(changed), "word")
assert resolved["common"]["signer"] == "报告编制人"
assert resolved["common"]["accentColor"] == "#123456"
```

- [x] 执行 `.venv/bin/python -m pytest smart_reporting/tests/test_format_preferences.py -q`，确认因功能缺失失败。
- [x] 实现类型、初始化和解析；拒绝空署名、未知字段、非有限数值、无效页眉字段、格式不适用的设置和越界页面边距。
- [x] 同一命令验证通过；检查解析不修改原文档，恢复继承不重置其他字段，MD 没有物理页眉页脚。

## 任务 2：全局偏好草稿、版本和恢复底座

**文件：**
- 新建 `smart_reporting/management/configuration_schema.py`、`configuration_store.py`、`format_preferences.py`。
- 局部修改 `smart_reporting/management/repository.py` 注册新表。
- 新建 `smart_reporting/management/migrations/versions/0010_global_configuration.py`。
- 新建 `smart_reporting/tests/test_format_preferences_persistence.py`。

**接口：** `FormatPreferenceService(auth, initial)` 提供 `detail(raw_session)`、`save_draft(raw_session, document, expected_version)`、`restore_draft(raw_session, revision, expected_version)`；所有写入先在事务内重验会话。发布方法在任务 4 执行器验证完成后才接入 HTTP。

- [x] 写独立 PostgreSQL 测试：首次读取固定部署初值；两个同版本保存只有一个成功；过期会话不能写；重建服务保留文档；损坏哈希拒绝读取；恢复产生新草稿版本并保留历史。
- [x] 运行 `REPORTING_MANAGEMENT_TEST_DB_URL=<隔离库> .venv/bin/python -m pytest -o addopts='' smart_reporting/tests/test_format_preferences_persistence.py -q`，确认新增能力缺失。
- [x] 实现草稿与不可变版本表，保留部署初值；使用已有短事务锁和 CAS，审计只登记版本与哈希。
- [x] 验证迁移 `0009 → head → head` 保留账号及原业务版本；回滚仅移除本次新表。测试使用临时数据库，不访问业务库。

## 任务 3：环境变量清单与系统配置生命周期

**文件：**
- 新建 `smart_reporting/management/system_configuration.py`、`configuration_catalog.py`、`configuration_api.py`。
- 测试 `smart_reporting/tests/test_system_configuration.py`、`test_configuration_api.py`。
- 修改 `smart_reporting/app.py` 注入实际 `AgentSettings` 与配置服务。

**接口：** 清单项包含 `key/label/category/type/unit/owner/sensitive/activation/source/dependencies`。仅登记源码确实读取的变量；偏好项 owner 为 preferences。`SystemConfigurationService` 保存类型化覆盖，生成新任务参数，不动态修改启动对象。

- [ ] 构造带 `UNRELATED_SECRET` 的环境输入，断言清单和响应不含该键或值；数据库 URL、令牌和主密钥均不回显。
- [ ] 覆盖无效类型、并发/令牌预算交叉约束、重启项、生效版本和初始化来源。
- [ ] 接入草稿、差异、历史、恢复和应用；无法在任务初始化时消费的项显示真实的重启需求。凭据替换复用 `CredentialVault` 加密，不复用数据源身份。
- [ ] API 验证认证、Origin、CSRF、严格请求字段、CAS 冲突和响应丢失后回读；不接受组织参数。

## 任务 4：任务冻结与 Word/PDF/MD 实际适配

**文件：**
- 新建 `smart_reporting/preferences/runtime.py`、`document_adapter.py`、`markdown_adapter.py`。
- 修改 `management/runtime.py` 的可信 `register_run`，不调用已退役 `freeze/load_pinned`。
- 修改 `reporting/workflow/runtime/base.py`、`analysis.py`、`publication.py`、`datasets.py`，每个执行路径读取任务冻结值。
- 修改 `reporting/delivery/report_runtime/report_design.py`、`markdown.py`、`docx.py`、`runtime.py` 及现有页面样式生成函数。
- 测试 `smart_reporting/tests/test_preference_task_snapshot.py`、`reporting/tests/test_format_preference_delivery.py`。

- [ ] 先写两任务测试：任务 A 冻结旧偏好，应用新默认，任务 B 使用新值；任务 A 恢复/再下载与历史快照完全相同。
- [ ] 扩展纸张/方向/边距及封面布局换算，避免仅扩大 A4 校验常数；独立落款的署名/日期保持同页。
- [ ] 原生 Word 字段实现目录、页码、首页/奇偶页与表格重复标题；PDF 使用真实渲染页码和分页；MD 输出标准 Markdown 落款。
- [ ] 显式任务要求/模板/已确认编辑器设计覆盖默认，模板示例署名日期重新绑定、避免重复落款；沿用旧运行原状态，不能让全局更新改变旧输出。
- [ ] 生成实际三格式样例，渲染 Word/PDF 逐页检查长落款、跨页表、横向纸张、不同首页和落款与页脚间距。验证原生段落/表格/字段仍可编辑。

## 任务 5：XLSX/PPTX 实际适配

**文件：**
- 新建 `smart_reporting/preferences/workbook_adapter.py`、`slides_adapter.py`。
- 修改 `reporting/delivery/xlsx.py`、`pptx.py` 和现有 Node 桥的 create/build 入口。
- 测试 `smart_reporting/reporting/tests/test_office_format_preferences.py`。

- [ ] 在真实原生文件中断言 XLSX 数据值/公式不变，数值格式、冻结、筛选、打印标题和原生打印页眉页脚生效，说明页包含落款并进入打印范围。
- [ ] PPTX 使用原生主题/版式、日期/编号及文本落款；空间不足新增结束页，标题页隐藏规则单独处理；不把整页图片当可编辑幻灯片。
- [ ] 使用内置字体；输出实际样例，检查长表头/打印缩放/末页空间不足场景，并核对字体/图像输出质量。
- [ ] 五格式执行器通过后，才开放相应偏好的发布应用与真实样例预览 API。

## 任务 6：两个菜单与设置/预览交互

**文件：**
- 新建 `frontend/src/management/features/settings/{page,contracts,fields,history}.tsx` 及局部样式。
- 新建 `frontend/src/management/features/preferences/{page,contracts,preview}.tsx` 及行为测试。
- 修改 `frontend/src/management/app/{shell,router}.tsx` 与管理页面服务端路由。
- 测试对应页面 `.test.tsx` 及 `smoke/management-preferences-smoke.mjs`。

- [ ] 系统页分类目录/表单明确，搜索支持中文和环境变量名；仅保留常用项（后续用户要求移除高级入口），值来源、单位和生效时机可读。
- [ ] 偏好页横向占满方角五页签，公共偏好独立入口；格式内分区切换、所有屏宽统一设置/预览视图切换，面板限宽自然高度。历史按需展开。
- [ ] 每字段显示沿用/独立覆盖、恢复沿用；切换格式保留输入，保存前显示涉及格式/公共项；校验定位字段。
- [ ] 浏览器行为验证键盘访问、未保存离开提醒、并发冲突、网络响应丢失回读、还原默认、历史恢复与应用后状态。
- [ ] 构建 `npm run build:management` 和预算检查，浏览器截图核对宽屏/窄屏及视觉规则；不重复全量前端测试。

## 任务 7：非阻断契约与交付证据

**文件：** `output/system-config-preferences/{README.md,verification.md,browser/}`、设计文档状态。

- [ ] 运行 AGENTS.md 所列非阻断定向回归，新增签发失败步骤必须登记故障注入。
- [ ] 验证偏好渲染/验收失败时保留真实产物身份和下载链接，准确返回问题，不误标通过。
- [ ] 逐条映射设计文档验收要求与实际测试/文件/截图证据，记录未具备试用环境，工程验证不替代管理员可用性试用。
- [ ] 只有所有要求都有当前证据才把设计状态改为实现完成、把线程目标标记完成；否则保留目标进行中和明确后续任务。

## 进度记录

- 2026-11-12 MD目录增量：正式组装/真实样例共享目录、唯一锚点与移除逻辑，重复应用稳定，代码/引用标题不进目录，跳级标题不变代码块；Word/PDF投影去除MD导航避免重复，实际双格式渲染通过。专项11条、相关30条、UI5条、浏览器76.53s通过；非阻断81通过/1既有跳过。新增verification.md逐条记录要求、直接证据和缺口，不据此标记总目标完成。表格写法尚未接通，后续继续。

- 2026-11-12 PPTX 模板增量：明确文本框落款复用/结束页补齐、冻结内容和真实 PDF 转换接通；空间不足/重叠/越界返回告警并移至结束页，业务页、主题及媒体保留。长署名样例已实际渲染查看；新增落款回读故障仍 HTTP 可下载。偏好编辑/预览、无标记示例消歧及全部格式极端场景验收仍未完成。

- 2026-11-12 XLSX 模板增量：命名落款区域复用/独立说明页、打印范围、冻结值与恢复接入，实际文件验证公式及缓存不变。修复引擎单元格扩展未更新 dimension 导致流式读取缺行的问题。新增 XLSX 回读失败签发测试通过，指定非阻断契约 81 passed、1 skipped。PPTX 模板和完整界面能力仍未完成。

- 2026-11-12 模板增量：Word 明确落款占位符/正文内容控件接入冻结署名与日期，保留样式；缺少位置补齐，重复声明软告警，去除 MD 标记落款。DOCX/PDF 实际文件、恢复身份和派生子快照有定向证据；新增回读故障仍 HTTP 可下载。PPTX/XLSX 模板、无标记示例消歧和长落款视觉验收尚未完成，不整体勾选任务 4。详见输出记录。

- 2026-11-12：任务 1、任务 2 完成并经定向验证。任务 3 的 93 项启动/外观配置清单、系统普通值版本服务及认证草稿 API 已实现；其余环境读取点、凭据替换和真实生效接入仍未完成。新增定向测试 72 passed，旧管理入口回归 11 passed；迁移和降级再升级通过。两个菜单尚未实现，应用入口未开放。详见 `output/system-config-preferences/README.md`。
- 2026-11-12 后续增量：两个菜单、系统常用/高级视图及发布/重启消费已接通；可信任务与派生修订冻结、MD 落款和部分五格式原生适配已验证。偏好仍为只读，模板优先级、编辑预览、凭据替换等未完成，各任务不据此整体勾选。Word 起点 1/5、正文 1/3 页及封面/目录三种组合真实分页 12 条通过，缓存安全/目录起点/原生域 6 条通过，完整渲染入口通过；指定非阻断契约 81 passed、1 skipped。当前证据与剩余项见输出目录 README。

- 2026-11-12 表格增量：Word/PDF tables 冻结值接入实际渲染；重复表头、跨页断行、边框、条纹及显式设计优先级有原生属性/实际多页 PDF 证据。新增定向 12 条通过，非阻断契约 81 passed、1 skipped。旧设计无 tables 时哈希不变；图表及全部界面执行能力仍未完成，不整体勾选任务 4/6。

- 2026-11-12 表格维护增量：已有实际适配证据的 Word/PDF/XLSX 表格字段开放草稿编辑，统一差异确认/版本保存；新增真实浏览器 CAS 冲突、响应丢失回读、未保存离页、错误定位聚焦证据。落款说明校验与保存中禁用输入已接入，其他设置编辑/真实预览/应用仍未完成。

- 2026-11-12 预览增量：五格式已保存草稿真实生成、原生文件/PDF/页面图身份、管理页按页抽屉接通；认证/CSRF/CAS/错误脱敏/转换失败原生保留有定向证据。完整编辑/并排预览/应用及全部参数执行适配仍未完成，不整体勾选任务 5/6。

- 2026-11-12 页面维护增量：纸张/方向/比例、格式适用的页眉页脚/首页/偶数页草稿编辑接入，动态字段选择及本地校验、错误变体定位聚焦，仍按内容限宽而不堆叠全部位置。差异按实际 story 路径显示。完整字段适配、并排预览/窄屏切换及应用未完成。

- 2026-11-12 PPTX 布局增量：原生图文左右/上下布局和内容密度接入，偏好模式不再截断第六条正文；两比例真实几何/图片字节与样例 PDF 验证，管理页配置保存及 Matplotlib 静态图预览接通。极长内容自动拆分和其他执行适配仍未完成。

- 2026-11-12 页面内预览增量：真实样例由抽屉改为桌面并排/小屏设置与预览切换，工作区最大 1280px、表单保持限宽；修改标明旧样例，保存版本变化清空，错误回到设置。组件定向 7 条通过，真实构建/HTTP/隔离 PostgreSQL 浏览器 66.60s 通过；全字段编辑与应用未完成，不整体勾选任务 6。

- 2026-11-12 MD语法增量：listMarker/codeFence真实组装/预览接通，解析器确认块位置、围栏长度与相邻列表边界保护；MD语法样式两字段草稿维护及真实浏览器v9保存/预览通过。其余MD选项与完整应用未完成，任务不整体勾选。

- 2026-11-12 XLSX数字维护增量：已有原生适配的小数/千分位/负数样式开放草稿维护；实际原值/公式/缓存/任务显式样式优先4条与UI5条通过，真实浏览器v10保存并回读实际XLSX确认。百分比/日期语义及其他字段仍未完成，不整体勾选。

- 2026-11-12 边距维护增量：Word/PDF/XLSX预设与自定义、毫米范围/可打印区校验、错误定位聚焦接通；12项UI/校验、实际原生Word/XLSX与PDF正文坐标通过，真实浏览器确认30/12.7mm。未开放无执行项，完整偏好应用仍未完成。

- 2026-11-12 落款样式增量：四Office格式默认折叠的字体/字号/颜色/对齐/加粗维护接通，恢复字体继承与颜色默认、错误展开聚焦、中文差异；原生XLSX/PPTX/Word与实际PDF文字证据通过，真实浏览器确认Word样式。其他样式及完整应用未完成。

- 2026-11-12 XLSX打印增量：导出区开放互斥的页宽/整页/比例/自定义模式和重复标题行，3项UI与4项实际原生/PDF分页通过，真实浏览器v11保存回读75%打印设置。其余字段与应用未完成，不整体勾选。

- 2026-11-12 PPTX续页增量：正文按布局/字号/行距预算自动续页、超长单条分段，保留证据备注与实际总页数；4项原生分页与1项真实PDF覆盖，21项相关兼容通过，实际7页样例审计0问题。极端长落款等总体验收仍未完成。
- 2026-11-12 复核收尾：紧凑配置筛选3条、真实浏览器1条通过；PPTX长署名/日期同页、说明续页与4:3真实宽度测量接通，相关29条与实际PDF1条通过，非阻断契约81通过/1既有跳过，11页实际样例已查看。仅此增量有验收证据，其余极端样式及全设计未完成，不能据此整体勾选任务。
- 2026-11-12 凭据替换增量：模型服务凭据可按需替换，独立加密不可变存储、版本引用、CAS/认证/CSRF、发布后重启消费、历史恢复、缺密钥回退与轮换均有实际数据库证据；0012迁移升级/重复执行/回滚重升通过。前端普通保存保留凭据引用，确认不回显引用或秘密；真实HTTP浏览器75.32s通过。元数据令牌服务端支持，不新增冗余表单。完整设计仍未完成。

- 2026-11-12 通用样式增量：通用字体/主题与Office格式覆盖恢复沿用维护接通，XLSX主题表头和对比色真实生效。11项UI、24项Office、3项实际预览、真实浏览器131.25s及非阻断81通过/1跳过。完整排版与应用仍未完成，不整体勾选任务。

- 2026-11-12 XLSX百分比/日期增量：正式指标百分数保持原尺度，登记DATE复用原生日期序列转换；管理维护、实际样例、浏览器打印接通。80项后端+1工作流、14项UI、7项打印、真实浏览器125.50s及非阻断81通过/1既有跳过；完整排版和应用仍未完成。

- 2026-11-12 XLSX排版增量：页面维护数据对齐、自动换行、行列尺寸及折叠正文/表头角色样式；清空恢复默认、错误定位、中文差异和真实保存下载已接入。17项UI、9项实际XLSX相关、浏览器1项44.14s通过，构建/预算/Ruff通过。长内容及长落款打印和总体应用仍未完成，不整体勾选。

- 2026-11-12 XLSX长落款打印：独立说明页固定可读列宽、强制换行、按真实字体测量行高，脱离业务表紧凑行高/列宽和整页压缩；超限时缩字并返回软告警，原始文字不变。按纸张可打印高度预留署名和日期同页，二者缩字后字号一致。workbook-signature-print-final.log三组实际PDF通过（12/72磅、中英极限长度、横向），workbook-signature-final.log受影响16项通过/4项未选，先前相关33项通过；workbook-signature-nonblocking.log 81通过/1既有跳过，桥接构建与类型检查、Ruff通过。实际最终落款及说明页截图已查看；业务表刻意设置8磅行高/2字符列宽仍按用户显式设置保留，其裁切不视为落款验收通过。全设计仍实现中。

- 2026-11-12 编辑器冻结设计增量：修复完整PDF默认被写成通用覆盖导致Word独立偏好被覆盖；导出/预览仅存相对冻结基线的明确差异，恢复内置默认值也保留为显式覆盖。Word单格式的设计读取/历史展示使用Word基线；旧报告保留既有完整导出设置合同。editor-frozen-related-final.log 26项通过，editor-frozen-native.log实际PDF14磅/Word12磅及标题23磅通过；editor-frozen-nonblocking-final.log 81通过/1既有跳过，Ruff通过。首轮非阻断9项因旧报告导出设置键被清除失败，已修复兼容后重验通过；真实渲染夹具的上下文/路径错误已修正，未放宽生产验证。历史恢复跨格式及MD/native冻结全链仍须继续审计，整体应用仍未完成。

- 2026-11-12 历史格式偏好恢复：按已核验来源修订同时恢复_formatPreferences/_formatDesigns/_documentContext/_pageLayout，缺失的旧版字段明确移除，不残留当前版本默认；保留当前job及执行身份。预览/导出差异以历史来源为基线，设计读写返回历史落款上下文；新修订和重启读取保留历史署名与日期。editor-history-preferences-red.log先复现当前署名串入历史；专项通过，组合回归38项通过/1项真实渲染夹具漏来源失败，补齐后editor-history-native.log实际PDF/Word通过，未放宽来源校验。editor-history-nonblocking.log 81通过/1既有跳过，Ruff/diff检查通过。完整MD/native冻结、其余适配和应用入口继续推进。

- 2026-11-12 PDF字体输出：源码确认现有WeasyPrint字体流始终嵌入，PDF/UA交付不开放关闭开关；移除只读参数清单中的embedFonts，兼容字段保留且不改变旧快照哈希。历史false在renderIssues返回pdf_font_embedding_required，照常生成文件；界面明确字体始终嵌入。pdf-font-embedding-warning-red.log/pdf-font-ui-red.log先失败；pdf-font-native.log 4项实际字体流、书签/JPEG质量/真实预览通过，pdf-font-ui.log 6项通过，构建预算和Ruff通过；pdf-font-nonblocking.log 81通过/1既有跳过。未新增签发步骤，完整目标其余缺口不据此完成。

- 2026-11-12 最新布局复验：view-switch-wide-browser.log真实HTTP/隔离PostgreSQL浏览器1项通过126.40s，覆盖1920/1440/390px、保存/发布/原生样例读取及视图切换输入保留。preferences-wide.png已查看；本次用户反馈覆盖此前桌面并排预览设计。


## 2026-11-12 PPTX文字维护与标题防重叠

- 文字排版默认折叠，PPTX仅提供引擎实际使用的正文/标题两种角色；支持字体、字号、文字颜色、加粗及折叠行距。未执行的段前/段后/缩进及h2/h3/表格/图注角色不开放。校验错误自动回到PPTX页面、展开并聚焦；保存差异保留具体角色。
- 极端72磅/3倍行距/长标题回归先失败（pptx-title-layout-red.log）；桥接按封面130px、内容及落款标题64px可用高度调整标题字号，保留原文并返回pptx_title_font_adjusted软告警。实际PDF确认长标题完整且正文仍存在；极端样例字号较小，不据此声明所有长标题可读性通过。样例pptx-typography/large-title.pptx、large-title.pdf及第2页截图已查看。
- PPTX维护组件与校验先失败（pptx-typography-ui-red.log）；夹具小数显示/加粗预期修正后，受影响26项前端通过（pptx-typography-ui-final.log），管理端类型检查、生产构建、体积预算和Ruff通过。桥接已重新打包，原生样式/比例/长标题实际PDF及既有正文/落款分页11项通过（pptx-typography-native-final.log）。
- 真实HTTP/隔离PostgreSQL浏览器排版维护验证通过（pptx-typography-browser-verified.log），覆盖错误跨格式定位、保存v4、真实原生PPTX标题27磅/颜色543210/1.4倍行距独立回读，以及390px无溢出；桌面、手机、真实预览截图已查看。前两次浏览器脚本的变量重名及图片选择器歧义已修正，未修改业务断言或放宽验收。
- 指定非阻断签发回归81通过、1既有跳过（pptx-typography-nonblocking.log，61.54s）。完整MD/表图偏好执行、模板语义处理、应用前校验和应用入口等继续推进；未完成管理员试用，整体目标仍实现中。


## 2026-11-12 MD表格写法执行增量

- 语法样式区新增一个已接通的表格写法选择，标准Markdown/HTML两种，导出摘要不重复展示。HTML转换复用markdown-it表格解析与渲染；仅处理顶层真实表格，代码样例、嵌套块及用户手写HTML原样保留。表格数据、行内加粗/链接/代码、转义竖线、列对齐和精度文本均保留。
- 生成HTML携带原始表体；只有重新渲染与可见HTML完全一致时才恢复，漂移/无效/伪造来源不使用。切回标准表格恢复原始文本，重复应用幂等。Word/PDF在业务排版变换前通过format_tables/1恢复，并纳入渲染投影回执；实际DOCX原生表格及PDF保留1234.5600和-234.56，未泄露隐藏来源。实际页面截图md-tables/restored-table-page-1.png已查看。
- 来源表格逐格读取、未登记表格识别、AI改表对比及语义复核的当前数值引用上下文接入相同的严格恢复。清单和AI改表并发身份继续按实际表体原文计算SHA-256，不放宽哈希或事实授权；漂移HTML不产生可用网格且仍识别为未登记表格。
- 回归先复现MD转换4失败、维护界面1失败、来源网格1失败及语义上下文1失败（md-table-*-red.log）。转换/幂等/防漂移/真实预览/实际PDF与Word/来源身份8项通过（md-table-final.log）；已有语法/投影组合35项通过，实际渲染夹具初次含未授权外链及无效临时目录，分别修正夹具后实际原生专项通过，未修改安全边界。来源/改表受影响84项通过（md-table-trace-tests.log），语义复核受影响112项通过（md-table-semantics.log）。
- 前端21项、类型检查/生产构建及体积预算通过；真实HTTP/隔离PostgreSQL浏览器56.36s通过（md-table-browser.log），实际保存HTML草稿v5、下载读取、切回标准草稿v6后重新读取，并确认恢复文本一致、手机无横向溢出、无页面错误。桌面/手机截图typography-browser/markdown-tables-*.png已查看。
- 指定非阻断回归81通过/1既有跳过（md-table-nonblocking.log，60.72s）；Ruff及定向diff检查通过。图片说明/引用/标题级别、其余Office适配、模板语义和完整冻结/应用验收继续推进，整体目标保持实现中。


## 2026-11-12 冗余配置与页面撑开修复

- 偏好页的格式页签、工具条、设置与预览统一在最大908px的容器内；不再出现页签横跨整页、内容只占左侧的错位。页签继续占满自身容器，保留方角与设置/预览切换。
- 实际报告初始边距20/18/22/18毫米新增“报告默认”预设，修复默认值误判为自定义而自动展开四项毫米参数的问题。历史自定义值原样保留，点击“调整自定义边距”才展开；校验错误仍自动展开并聚焦。
- 移除MD中重复目录及未接通引用的导出摘要分类，移除PPTX没有维护操作的表格与图表分类；有效落款、页眉页脚、字号设置保留。
- 回归先复现2项组件失败与真实浏览器默认展开失败。修复后定向前端24项通过，类型检查、生产构建及体积预算通过；真实HTTP/隔离PostgreSQL浏览器1项通过（14.95s）。1440/1024/768/390px均无页面横向溢出，页签与工作区等宽，最大908px。桌面与手机截图已查看。
- 证据：output/system-config-preferences/compact-{ui,browser,build-budget}.log；截图与宽度记录位于output/system-config-preferences/compact-settings/。本轮仅调整管理页展示，不修改报告生成或签发链路；整体执行适配、应用验收与管理员试用仍按原计划推进。


## 2026-11-12 图片说明执行增量与浏览器复验状态

- 正式图表组装传入冻结的MD偏好，控制系统生成图注显示；图片、替代文字、标题、来源引用及手写说明保持不变。未带偏好的旧组装保持原输出，不推断或删除未标记的历史图注。隐藏说明可恢复，重复应用幂等；代码、嵌套块、修改过的图片和手改可见说明不被覆盖。
- 恢复时同时核对图片段落SHA-256、可见内容和解析后的图片标题。伪造的隐藏说明、额外段落及HTML不被用来恢复正文。Word/PDF投影单独恢复图注并登记format_captions/1，不串用MD显示开关；图表展示指纹与语义上下文同步归一化，原始文档身份继续按实际原文计算。
- MD语法区仅增加一个已接通的“图片说明”开关；真实预览使用自包含PNG，不依赖外部图片地址。实际Word/PDF均保留一张图片、一处图注、正文和冻结日期落款，Word仍为原生图片/段落。两格式实际页面已查看，样例见md-captions/restored-caption*。
- 图注核心8项通过；标点与真实Word/PDF2项修正来源引用/日期格式夹具后通过，未放宽业务校验；既有组装稳健性和图表指纹34项通过。相关语法/表格/语义99项、前端28项、类型检查/生产构建/体积预算/Ruff通过；指定非阻断回归81通过、1既有跳过（60.97s）。
- 真实HTTP/隔离数据库浏览器曾完整通过一次（md-captions-browser-observed.log，60.72s），覆盖草稿v7关闭/v8开启、下载内容恢复一致、390px无溢出；复验仍出现连续保存后预览按钮角色定位超时，失败期间未发出对应预览请求。增加DOM/请求/截图诊断，下一步继续定位；不以一次通过认定该项稳定验收完成。失败日志和failure*证据保留，当前结果见md-captions-browser.log。
- 尚未开放全局偏好应用入口。引用/标题级别、其他Office偏好、模板语义、完整冻结和应用验收仍未整体完成；管理员试用尚无环境与人员，不与工程验证混同。


## 2026-11-12 格式入口中文表述

- 根据最新反馈，页签、分区标题与保存差异摘要统一使用：文本报告（MD）、电子表格（XLSX）、演示文稿（PPTX）、PDF、文字文档（DOCX）。扩展名及Markdown/Excel/PowerPoint/Word名称放在辅助提示中；后台格式键、冻结快照和文件类型不变。
- 修复手机端四字中文标签被“更多”入口挤占：页签允许收缩，小屏内边距与字体单独适配；仍保持横向铺满与方角。真实浏览器核对四种屏宽、全部五个名称与扩展名提示、无多余格式菜单和页面横向溢出；生产构建、体积预算通过。实际日志见format-labels-browser.log、format-labels-build.log及format-labels-budget.log，截图见compact-settings/settings-*.png。
- 标签变更不代表完整偏好规格验收完成；前述图片说明连续保存预览复验及其余执行/应用验收继续推进。


## 2026-11-12 图片说明浏览器复验完成

- 用独立真实HTTP/隔离PostgreSQL短流程复现：加载退出动画把带loading无障碍文本的图标保留在按钮中，按钮名称变成“loading 预览已保存草稿”，而非弹窗遮罩或草稿版本错误。失败时按钮可见、未禁用，但精确角色名称匹配为0；原始DOM/无障碍快照保留于save-preview-aria-red.json，失败日志为save-preview-immediate.log。
- 生产修复仅为预览入口增加固定aria-label。移除上轮临时的弹窗等待、截图前置和全局点击追踪，不依靠延长等待或屏蔽动画通过。连续四次保存即预览（HTML表格、标准表格、关闭/开启图片说明）均返回当前草稿版本，加载图标退出期间按钮名称仍匹配。新增test_preference_preview_after_each_saved_draft_uses_current_version通过（save-preview-green.log，22.84s）。
- 完整排版/图表说明浏览器在一个旧脚本过早读取下拉列表项的问题修正后通过（md-captions-browser-verified.log，60.28s）；仅增加选项可见等待，保留正文/标题两项内容断言。覆盖文字文档/电子表格/演示文稿真实原生文件样式独立回读、文本报告草稿v5至v8、图片说明真实下载的隐藏/恢复一致、390px无横向溢出。桌面/手机截图已查看，旧失败日志保留。
- 前端预览组件7项、类型检查/生产构建、体积预算、Ruff与定向diff检查通过（save-preview-ui/build/budget.log）。本轮只修改管理端无障碍名称与回归验证，不重复运行未受影响的生成/签发测试；上一执行适配增量的非阻断回归证据仍为md-captions-nonblocking.log。
- 本节关闭前述图片说明连续保存复验待办。总体设计仍实现中：引用/标题级别、其余Office适配、模板语义、完整冻结/应用验收及管理员试用未整体完成，偏好应用入口继续保持未开放。


## 2026-11-12 五格式冻结消费跨层验证

- 新增真实隔离PostgreSQL集成用例test_restarted_tasks_and_child_revision_render_all_frozen_formats：先发布旧偏好并登记任务，再发布新偏好、登记新任务、继承派生修订，随后重建配置Provider并改变部署署名；执行读取使用可信任务身份和数据库快照，不直接用测试手写配置代替冻结记录。
- 三份快照分别进入正式MD组装、XLSX/PPTX生成器，以及工作区格式/文档上下文/标题映射绑定与Word/PDF渲染器。独立回读15份实际文件，核对MD目录/HTML表格/图片说明/列表/代码围栏、XLSX小数位及原值、PPTX原生文字字号、Word正文样式、PDF可见正文字号和Word原生图像/表格结构。旧任务及派生修订保留旧偏好，新任务采用新偏好；错误部署署名没有串入产物。
- 日期使用可控测试时钟：两个原任务冻结2026-11-06，派生修订冻结2026-11-07，并非当前日期。重启读取保持原快照；派生修订继承样式但使用其自身生成日期。实际Word/PDF均保留一处图注、正文和落款；MD隐藏图注不影响它们。
- frozen-all-formats-integration.log：1项通过（62.57s）；frozen-snapshot-related.log：其他14项通过（8.21s），涵盖身份隔离、数据库不可变约束、篡改拒绝、旧运行兼容及派生读取。仅新增测试和证据，未修改生产生成/签发逻辑，未重复完整测试或非阻断签发套件。Ruff及定向diff检查通过。
- 样例位于output/system-config-preferences/frozen-native/，evidence.json记录三组原生文件及图片共18项实际大小/SHA-256，落盘后再次核验一致。三组Word实际转换预览与PDF共六张页面已查看，样例正文、表格、图片、落款未发生遮挡。标准render_docx.py缺少pdf2image，改用项目既有LibreOffice转换与Poppler渲染，未新增项目依赖。
- 范围限制：这是代表性配置的数据库到实际执行器验证，未覆盖全部正式HTTP入口、全生命周期历史编辑/重复下载、所有配置组合或管理员试用。引用/标题级别、其他Office适配、模板语义、应用前验收与偏好应用入口继续按原设计推进；整体目标保持实现中。


## 2026-11-13 引用编号执行增量

- 已完成：MD引用编号维护、已登记来源映射、可逆显示及隐藏、草稿真实预览、Word/PDF独立来源投影、位置敏感追溯与语义上下文恢复。
- 红绿回归发现并修复：末尾Markdown表格丢失来源、引用式链接捕获编号、超长来源名称导致数值窗口误报。保留代码/链接/图片/HTML属性及未登记来源；初版v1未转义展示保持兼容。
- 最终核心14项及补充v1兼容1项通过；前端24项、真实六次保存预览1项、五格式冻结集成1项及指定非阻断81项通过（1既有跳过）。追溯703项、组装371项定向回归有独立日志，未重复完整测试。
- 实际MD/Word/PDF及转换页面见md-references/，14项文件身份已登记；冻结原生样例18项身份再次核验。六张当前Word/PDF页面已查看，未见正文与落款遮挡。
- 下一执行项仍按原规格：MD标题级别、其余Office适配与模板语义，随后完整冻结链路及应用前验收。偏好应用HTTP/UI继续未开放，未将工程验证当成管理员试用。


## 2026-11-13 文本报告章节起始级别

- 已完成模型sectionHeadingLevel（严格整数2–4）、语法样式区单项选择/差异标签/错误定位、正式组装权威标题传入及真实样例。旧快照缺字段沿用二级起始，显示调整不改HeadingNumber或Word/PDF语义层级。
- 核心先8失败/5通过，前端先2失败；实际原生专项初版16通过，后续补充结束井号、幂等恢复、编号语义与陈述指纹，均先复现后修复。最终语义定向116通过、1未选；受影响指纹/质量/追溯322通过。未重复完整项目测试。
- 浏览器9次保存即预览通过36.83s，覆盖三级→二级→四级以及既有表格/图注/引用操作；数据库五格式冻结1通过63.59s，旧任务及派生仍二级，新任务四级。前端25通过，类型检查/生产构建/预算通过。
- 实际Word原生标题1/2/3及PDF正文、落款回读并查看两张页面，md-heading-level/evidence.json登记6项文件身份；frozen-native的18项身份复核。当前源文件按最后实现重新验证跨格式投影回执；最终指定非阻断81通过/1既有跳过（59.24s）。
- 下一步继续其他Office适配、模板无标记示例语义消歧、正式HTTP/历史/重复下载冻结审计及应用前验证；不据此整体勾选任务4或开放偏好应用。


## 2026-11-13 Word/PDF封面目录与来源附录维护

- 文字文档和PDF的“导出”区新增已接通的生成封面、生成目录、来源附录三项开关，复用各格式草稿、保存差异摘要和设置/预览切换；PDF保留书签与JPEG质量，不新增菜单、嵌套表单或无效参数。关闭附录不删除来源绑定。
- 原生渲染器原已消费cover/toc/sources；本增量补齐管理页维护，并为固定排版预览登记明确标注“固定排版样例，非业务数据”的来源，使附录开关能实际预览。未向正式报告注入样例来源，未修改正式生成、发布或下载签发算法。
- document-output-native-red.log先复现来源附录两项失败、封面目录两项通过；新增组件缺失的UI红阶段为导入失败，未执行断言。实现后document-output-ui.log记录13项组件通过；document-output-native.log四种真实Word/PDF组合通过（64.80s），document-output-preview-related.log其余八项预览通过（43.24s）。类型检查、生产构建和体积预算通过（document-output-build/budget.log，登录297.6KiB、列表447.5KiB）；Ruff和浏览器脚本语法检查通过。
- 新增真实HTTP/隔离PostgreSQL浏览器专项test_document_output_controls_save_independently_and_download_actual_native_files，通过（document-output-browser.log，79.26s）。保存Word v2关闭封面目录/开启来源、PDF v3保留封面/关闭目录来源、Word v4关闭来源，三次预览均对应当前草稿；逐项摘要、未保存预览禁用、格式独立、刷新回读、无嵌套表单、390px无横向溢出和无页面错误均核对。原生样例实际经浏览器下载并核对大小/SHA-256，Python另行读取原生Word表格/目录域及实际PDF正文、封面和附录，不以响应字段代替文件检查。
- 样例见document-output/，浏览器下载与桌面/手机截图见document-output-browser/；四组原生样例共十张页面及两张管理页截图已查看，正文、数值、目录、附录和落款无文字遮挡。document-output/evidence.json记录29项实际文件身份，落盘后重新读取核验一致。管理页截图仍可捕获既有页签墨线切换动画，不将其宣称为已修复。
- 本轮只改管理页与固定样例预览，没有修改正式签发链路，不重复运行未受影响的非阻断套件；最新正式链路证据仍为md-heading-level-nonblocking-final.log的81通过/1既有跳过。其余图表/表格说明、演示文稿样式、模板语义、完整HTTP/历史下载冻结、应用前验收及管理员试用尚未整体完成；偏好应用入口继续未开放，整体目标保持实现中。

## 2026-11-13 并行维护、图注入口与复核补修

- Word/PDF图文分页维护、系统配置来源/服务地址边界、模板落款安全绑定、演示文稿原生图注已分别推进；完整分工、失败记录、文件与覆盖边界汇总于 `output/system-config-preferences/parallel-maintenance-closeout.md`。
- 演示文稿在现有“页面与排版→文字排版”增加图注角色，维护字体、字号、颜色、加粗、折叠行距及图注编号；只开放真实消费字段，保存摘要与跨格式错误定位复用原入口。21项前端通过，类型检查/生产构建/预算通过。真实HTTP/隔离PostgreSQL浏览器1项通过（27.74s）：v2关闭编号/v3开启编号、保存后即时预览、浏览器下载PPTX并独立读取14磅/衬线/颜色/加粗/1.4倍行距，Word/PDF独立、刷新与390px无横向溢出。第一次14.0与14的字符串断言失败已保留，修正为数值比较。
- 演示文稿4:3极长图注按最终宽度测量；最小6磅仍不足时续页并精确保留原文，图像/图注/页脚不重叠。实际原生8项专项与五组真实文件检查完成。极端6磅样例只证明边界保护，不宣称所有长图注阅读体验已验收。
- 模板字体测量缺命令、非零退出、字体不可读时，保留未知容量的原落款区，追加冻结落款说明页并返回具体软告警，明确旧样例可能保留。专属8项和模板HTTP六种故障通过；新增`xlsx_signature_measurement`已登记，实际下载回读验证失败状态仍签发链接。审查I1已关闭。
- 本轮较早的11个指定非阻断节点记录81通过/1既有跳过（`parallel-maintenance-nonblocking.log`）；最后字体故障补修后仅补跑四个相关节点，13通过/12.65s（`parallel-maintenance-final-nonblocking.log`），没有重复完整测试。四份产物清单共55项文件大小及SHA-256重新核验一致，见`parallel-maintenance-file-readback.json`。
- 整体目标仍未完成：系统冻结执行参数跨重启消费仅有接线计划，完整HTTP/历史下载冻结、无标记模板语义消歧、偏好应用前验收与应用入口及管理员试用尚未整体完成。`canApply=false`保持不变；本轮未部署。



## 2026-11-13 冻结执行、模板来源及真实材料验收增量

- 冻结系统参数已从只读接线计划推进到实际执行：可信Provider核对运行/用户/线程、快照与历史版本，显式消费33项执行参数并复用Vault历史凭据；本次模型、规划器、代码工厂、视觉与并发视图按冻结值创建。工作区、仓库、资源、取消与路由策略沿用现有链路，父/子运行互不改写。详细代码与覆盖边界见 `output/system-config-preferences/frozen-execution-closeout.md`、`frozen-system-values-agent.md` 和独立 `frozen-execution-review.md`；本节更新此前“仅有接线计划”的现状，旧节保留为历史记录。
- 真实隔离DB的A/B发布、Provider重建及child验证通过；实际Agno SQLite暂停→重建B→继续A专项通过。SDK首次请求另核对冻结地址、认证、模型和321秒超时（1通过/11.37s），HTTP传输层为本地固定响应，不是外部模型报告测试。已有受影响执行节点34通过/12.44s，不宣称全部HTTP生命周期已完成。
- 正式模板 `validation.readback` 新增实际落款位置、模板/回退布局、声明样例处理和冻结内容身份；历史恢复只复用身份完全匹配的回执，未知/损坏来源明确未核验。嵌套声明漏报M1已用一个XPath谓词修复，5项DOCX定向通过且独立复核关闭。模板9项实际文件身份重新读取一致；来源记录不等同版式验收通过。完整证据见 `template-provenance-agent.md`、`template-nested-slot-m1.md`、`template-provenance-review.md`。
- 新增服务端真实材料preflight runner：绑定草稿version/hash和已登记材料，调用正式五格式生成器、独立原生回读、输出逐字段能力及具体缺口。生成后验收/预览异常仍保留实际文件身份。它尚未接入认证服务、任务材料解析、HTTP/UI或应用批准CAS；固定合成材料证据不能替代真实业务任务验收，未开放偏好应用。初期215条检查/180字段记录属于采样复核前结果；最终能力以补修后的回执为准，不能沿用该初期数字声称当前完整验证。
- 最后模板补修后，AGENTS指定11节点先80通过/2参数未选，再仅补原生续改参数1通过/1既有跳过，合计81通过/1既有跳过；没有重复前80项。模板生成后7种HTTP故障全部通过，含新增登记的signature_provenance，已核验文件仍可下载。日志见 `frozen-template-nonblocking-final.log`、`frozen-template-nonblocking-native-supplement.log`、`template-provenance-http-final.log`。
- 整体设计保持实现中、`canApply=false`：尚需完善承诺但未消费的格式字段、全入口历史编辑/重复下载冻结、无标记模板的语义消歧、真实任务验收服务及应用入口。管理员试用按用户安排暂缓，本轮未部署；没有新增组织管理或CodexAgent容器路径。

### 本增量最终补修与界面回读

- preflight独立复核I1发现首位置采样被提升为整字段verified，已最小修复为显式complete/sample覆盖语义；缺覆盖声明也保守不批准，实际失败优先failed。第二正文单元格/第二幻灯片标题篡改先红后绿，最终仅一次受影响套件18通过/33.76s，三文件Ruff通过。最终215条检查中89 complete、126 sample；405项能力为55 verified、270 not_verified、80 unsupported，整体incomplete/canApply=false。旧180 verified已归档；完整记录见 `preference-preflight-sample-i1.md`，独立 `preflight-review.md` 已关闭I1。
- root再次读取模板9份与最终preflight16份实际文件，大小及SHA-256全部一致，分别记录于 `template-provenance-root-readback.json` 与 `preflight-root-readback.json`。最终重生成PDF第2页和文字文档预览第1页另从当前PDF重新渲染并查看：正文、表格、静态图片/图注与落款无遮挡；新图为 `preference-preflight/root-final-pdf-page-2.png`、`root-final-word-page-1.png`，旧PNG仍只是历史视觉记录。蓝色图片为合成测试材料，不冒充数据库业务图。
- 两个现有交付入口（按原口径刷新/采用新口径）已读取实际后端 `validation.readback`，新增默认折叠“排版来源”，展示模板布局、冻结偏好落款、实际位置、声明样例处理及未知状态；始终提示来源不代表验收通过。下载名统一PDF、文字文档、演示文稿、电子表格、文本报告。无新增页面、菜单或常驻纵向区块。
- 前端三文件38项通过，定向TypeScript检查通过；原型同名未知枚举先红后修复。随后独立复核U1发现truthy原始值文件对象可能使其他链接丢失，增加object守卫，最后只补受影响坏响应专项4通过，未重复前38项。实际本地HTTP/Playwright核对1440/390px、原生details折叠/展开、损坏及旧来源响应、真实电子表格下载哈希一致、仅GET且无页面错误；root已查看宽窄截图。浏览器记录使用本地夹具及已有正式模板回执/文件，发生在最后类型守卫补修前，不冒充生产构建、新业务运行或管理员试用。
- 界面完整交接见 `output/system-config-preferences/delivery-layout-ui-agent.md`，来源展示独立复核见 `delivery-layout-review.md`，U1已关闭；最后守卫补修后的定向TypeScript检查也通过。四份独立复核均无本轮范围内待处理的确认问题，但不外推完整设计完成。


## 2026-11-13 图注、原生间距与页眉页脚并行增量

- 文字文档/PDF按各自冻结值执行图注编号，两种相反配置真实生成通过；权威Markdown、图片alt、数值和来源别名不变。表注仍缺受控caption输入，不猜普通段落。演示文稿h1/body/caption原生段前/段后与页脚前后/行高进入测量和分页；缩进仍不支持。
- 电子表格打印页眉页脚原生支持字体、整磅字号、颜色、加粗，字段转义与页码保留；小数字号及明显高度不容纳返回软告警，冻结值不改写。14磅实际控制组清楚，72磅实际裁切失败版面保留；未宣称所有宽度组合视觉通过。独立回读覆盖说明页所有预期区域，删除区域及bold=false也不能误获verified。
- 前端默认折叠四项页眉页脚样式，Word/PDF编号复用图注角色，PPTX前后间距放入低频细节；页脚保存错误返回正确格式/分区、展开并聚焦，差异摘要明确“页脚”。格式名称维持文本报告/电子表格/演示文稿/PDF/文字文档，不新增组织、菜单或常驻堆叠。
- 真实边界复核关闭H1/H2/C1/C2/S1等确认问题：PDF文字子串证据仅sample/not_verified；超长合法页脚原会导致无限空续页，现预算受限并一次保留无法容纳的说明余文、具体告警后结束。S1实际3页可读取，极端页脚仍明确排版未通过，不冒充视觉通过，不丢弃原文或文件。
- 工程证据：Word/PDF图注及相关39通过/99.63s；PPTX间距最终6通过/15.53s，S1补修2通过/7.03s及强化单节点1通过/6.55s；UI六文件39通过/7.48s。XLSX完整区域6通过/5.24s，新增高度1通过/0.90s，删除区域两参数最终2通过/5.17s。五格式最终20通过/31.79s，图注保守判定6通过/4.48s；指定11节点非阻断契约81通过/1既有跳过/59.92s。管理构建、预算、Ruff与局部diff通过。未重复完整测试。
- 最终HTTP/隔离测试DB/构建包浏览器1通过/29.80s，覆盖保存→实际预览→下载→原生数据/公式缓存及哈希、错误定位、五场景1440/390无横向溢出/嵌套form。首轮缺asyncpg属于环境错误，临时target补依赖未改项目；首次成功截图捕获页签过渡动画，增加指示条实际几何稳定检查后仅重跑该节点，旧图完整保留。历史smoke的能力缺失断言已最小同步，Node语法检查通过，未重跑其完整流程。
- 当前五格式回执250检查=116complete+134sample；405字段=60verified+280not_verified+65unsupported，整体incomplete/canApply=false。root重新核对9份原生/预览载荷、run及12张新渲染页图共22份身份，旧证据归档preference-preflight-before-caption-spacing。五格式套件在最终S1补修前运行，S1另有专属实际证据，未重复全套。
- 总交接 `output/system-config-preferences/office-preferences-closeout.md`；最新界面 `preference-style-closeout-browser/`，原生产物 `document-caption-numbering/`、`workbook-header-footer-style/`、`pptx-spacing-evidence/`。四份独立review无本轮范围内待处理确认问题。真实任务授权材料绑定、PPTX末端spec持久化、应用批准CAS、无标记模板消歧、完整历史生命周期及其他未消费字段仍待推进；管理员试用暂缓，未部署，整体目标保持active。


## 2026-11-13 真实任务材料绑定与原生输入冻结

- 三路并行推进正式PPTX最终输入留存、真实修订材料绑定复核、分格式可用性与生成消费；root补实际PostgreSQL双会话/CAS测试和独立文件回读。总交接 `output/system-config-preferences/bound-preflight-closeout.md`，专属边界见 `bound-preflight-review-handoff.md`、`preflight-format-availability-handoff.md`、`pptx-native-input/handoff.md`。
- 新增内部BoundPreferencePreflightService，复用现有管理认证、报告编辑授权、耐久context、注册运行与来源生命周期锁。生成前后分别核对双会话、version/hash、context和材料摘要；仅复制快照时持锁，完整最终复核成功才标binding有效及内部产物读取已授权。撤权、草稿或来源变化均保留内部产物、返回具体原因且不可据此应用；未来交付仍需独立鉴权。没有新增HTTP/UI入口或扩大Cookie权限。
- PPTX以内容寻址spec和不可变receipt冻结真正末端页面、分析说明、静态图及实际artifact/execution，并随初始/派生发布冻结到本修订job；消费者严格核登记和静态图集合。四阶段登记故障HTTP实测仍可下载，最终21通过/19.98s。initial PPTX另补正式assemble_slides把已核markdown_file写现有job.render.markdown，支持清单被降级丢弃后的耐久context材料恢复；load/store两故障非阻断，专项与独立边界见 `pptx-markdown-job-binding/`。这条快照消费不是完整双会话HTTP/UI验收。
- runner按服务端已核材料显式选择格式，始终返回五格式；缺原生输入明确unavailable，不造样例、空slides或逆推数据。XLSX来源映射已实际进入build_workbook和材料摘要。文档中文期间与原生ISO期间按各自已登记spec使用，生成和独立回读分格式取title/period/date，不字符串猜测或互相覆盖；缺冻结日期不补当前日期。模板专属链未接通时不以通用生成冒充验收。
- 绑定守卫39case分批红绿覆盖，最终受影响上下文6通过/10.01s，批次重叠不累计；隔离真实PostgreSQL管理auth/偏好与SQL编辑器授权4通过/12.65s（报告状态与生成使用夹具）。真实grants/editor/workspace/binder/正式XLSX及PPTX生成/原生回读2通过/14.49s，管理身份与workflow状态库为内存夹具；分格式上下文另一个真实MD/XLSX节点1通过/6.48s。原生文件身份与内容已由root独立复核，工具执行记录明确哪些批次没有原始pytest日志；没有为造日志重复测试。八个本轮新增/专属文件Ruff及compileall通过，局部diff检查通过；未重复完整五格式或81项套件。
- root重新读取12份PPTX发布证据及4份真实初始/验收原生文件，另核对正文job补接的13份证据与五个当前源文件；大小、SHA-256、spec/receipt绑定、静态图、页文、Markdown身份、XLSX原值/公式/字号/来源映射一致，见 `bound-preflight-pptx-root-readback.json`、`bound-preflight-native-root-readback.json`、`bound-preflight-markdown-root-readback.json`。补接唯一五节点已分批覆盖，最终consumer+HTTP两故障3通过/12.19s、修正旧夹具的consumer+既有组装2通过/12.19s及前批静态守卫通过，批次有重叠不累加。这些是确定性隔离工程证据，不等同业务事实、视觉版式、生产认证或管理员试用验收。
- 整体仍active、incomplete/canApply=false，未部署。普通重算父context/子execution的授权桥、initial XLSX清单丢弃后的job正文身份兜底、模板专属preflight/无标记语义、完整历史生命周期、其他未消费字段、HTTP/UI授权交接及应用批准CAS仍需继续。管理员试用按用户安排暂缓；没有新增组织管理或CodexAgent容器路径。


## 2026-11-13 并行恢复、可维护能力边界与落款间距

初始XLSX已登记Markdown身份补接、普通重算parent/child精确原生恢复、PPTX自洽父指针降级修复、未消费65项新增修改限制及Word/PDF四落款间距维护已完成本轮定向验证。包括实际XLSX独立回读、管理隔离DB/HTTP、组件浏览器布局及构建预算证据；各专项边界和重叠节点不外推或累加。独立审计保留405字段原始矩阵。整体设计仍实现中：全局批准合同/应用、真实任务HTTP授权交接、完整模板/历史/极端版式验收仍缺，管理员试用按用户要求后置。详见 `output/system-config-preferences/parallel-continuation-closeout.md` 及其最终证据索引；不覆盖旧closeout与冻结manifest，不整体勾选任务。


## 2026-11-13 实际报告HTTP验收、原生回读与维护入口

已接通管理页到精确报告修订的双权限HTTP验收，保留限定Cookie、CSRF和一次性挑战；生成后撤权抑制来源载荷，草稿/材料验收失败保留已授权且身份可读产物。页眉页脚位置/分隔线/起始页码维护、原生末尾落款回读与按需验收对话框完成定向工程验证。正式构建和预算检查通过。真实HTTP/隔离DB/正式renderer浏览器单节点1通过/40.30s；工作流材料为fixture，不是业务DB或管理员试用。原HTTP回执failed/canApply=false揭露Word目录书签及PDF同名目录标题误判；两处先红后绿最小补修后，同批未改文件另行回读MD/PDF/Word均通过，旧回执不重写，sample不升complete。没有重复五格式、浏览器整链或81项签发套件。

整体仍active、应用入口未开放：版本化批准合同/耐久证据汇总/事务应用CAS、承诺未实现字段、模板专属与历史/极端版式验收仍待推进。同步验收没有结果恢复承诺。详见`output/system-config-preferences/authorized-report-continuation-closeout.md`及新证据索引`authorized-report-continuation-evidence.json`；旧405字段数字是当时快照，不据本轮局部回读推算最新总体验收数量。管理员试用继续后置，未部署或新增组织/容器工作区。


## 2026-11-13 耐久验收、批准CAS与演示文稿表格

版本化验收合同、不可变结果/批准记录、实际产物独立留存回读、批准应用CAS及按需汇总界面已接通。隔离数据库最小合同的25节点事务批次通过；随后仅补角色资格等受影响节点。真实鉴权HTTP/正式MD、PDF、Word生成/SQL/浏览器1节点通过，实际5产物由重建仓库及root独立回读；工作流材料为fixture，不作为业务DB或完整生产批准证据。演示文稿11项原生表格维护已开放，浅色主题表头对比色已修复；全部对象读取和视觉抽样各自保留证据边界。最新管理构建及预算通过，未重跑原完整五格式/81项套件。

生产合同仍为14类要求、614项字段/场景/维度缺项，incomplete/canApply=false；405字段当前登记348 implemented / 7 compatibility_only / 37 not_applicable / 13 missing。该分类不是verified验收统计。完整V生产映射、模板专属/无标记语义、剩余消费者与全部场景/生命周期仍待推进，管理员试用继续后置，整体保持实现中。详见 `output/system-config-preferences/approval-application-closeout.md`，不覆盖历史回执和冻结索引，不整体勾选原任务。


### 接续：首批可信原生字段V（2026-11-13）

已将文本报告/文字文档/演示文稿的署名、冻结日期和完整落款说明九条受审路径接入 configured_field/native 证据：只有严格末尾reader标记、合同登记、全部同路径检查、当前绑定及独立留存原生文件身份齐备才合格；失败保留，旧记录不自动提升，无visual/lifecycle自动映射。新增SQL专项3 passed /39.62s，核有效持久化、缺尾失败及运行身份缺项，全部仍未具备全局批准。Word/PPTX实际正负文件经root另行解析/核hash。专属管理构建与预算已通过并保存在 approval-ui/final-build，避免共享静态目录的其他构建覆盖验证证据；未部署。614为此前真实浏览器快照，不是后续每份报告固定缺项数。详见 `output/system-config-preferences/approval-application-closeout.md` 及 `native-signature-evidence/verification.md`。完整目标继续实现中。


## 2026-11-13 原生表格证据、落款间距与模板验收接续

演示文稿落款页标题到落款的物理间距已接真实消费者，默认折叠维护，0/18/144磅及续页边界分批验证；11项原生表格字段新增严格configured_field/native映射，实际对象全覆盖与原文件身份不足不得通过。真实多表proof发现第二表错误沿用续页号，逐表计数最小修复后仅补两个失败节点；root已看第二表实际页面。消费者合同当前为405字段：349 implemented /7 compatibility_only /37 not_applicable /12 missing，合同hash为0510e6659e5e4a457653619401757d215284aa59ebed361bdefe8ca0427b483d；这是分类，不是verified统计。

DOCX模板Word/PDF专属验收复用正式填充器与当前修订材料身份；分格式草稿落款与冻结日期、实际SDT和未声明XML/包内容检查已接通，复杂域缓存及空登记误兜底均先红后绿修复。来源对话框默认折叠，正文/落款/模板布局分别说明；损坏回执保产物入口，局部通过不冒充完整通过。模板正文仍按Markdown字面文本填入，富文档投影和整体布局明确未验证，未声明样例继续保留并告警。

root独占隔离DB：新表格SQL首跑2通过/1执行器stale失败，只补失败参数1通过/26.38s，补验四阶段manifest一致且无放宽校验；新模板SQL唯一节点首跑1通过/25.30s，实际Word/PDF留存回读、模板漂移409且原文件不丢，汇总仍incomplete/canApply=false（该案例611缺项，不是普遍常数）。模板来源UI2新+1受影响节点通过，管理最终构建和预算通过；当前专属构建本地浏览器fixture四场景1440/390通过，root看两张展开图，无横溢，下载hash一致。没有重复旧五格式/81项非阻断/批准CAS整套。

完整目标继续active，未部署、管理员试用后置。12项消费者、模板富文档/无标记语义/其他模板格式、全视觉、全部历史生命周期与完整合同V仍需继续。详见`output/system-config-preferences/native-table-template-continuation-closeout.md`及新索引`native-table-template-continuation-evidence.json`；396/176旧索引与原始红灯不覆盖。下一批只读建议见`next-consumers-readonly-plan.md`，未实施建议不计已支持。


## 2026-11-13 Word/PDF 受控表格标题编号增量

两格式表题编号已接正式消费者、当前修订材料桥、编辑器导出/预览快照及独立回读；管理入口沿用现有表格与图表分区，差异准确称“表格标题编号”，保留低学习成本和原横向布局。相同普通段落不误编号，无登记/损坏来源明确告警；真实 Word Caption/书签/邻接表格完整核验，PDF 仍 sampled/sample，歧义场景 unverified，不增加完整 V 映射。

独立子进程实际入口及验收索引 staging 的问题已修并完成新增定向验证；执行器清单补实际来源规则、编辑器快照和 runtime ZIP 身份。新增编辑器快照与索引读取故障经 HTTP 验证保留已生成且身份可读 Word/PDF 的下载。六个新 UI 节点分批绿、专属实际构建/预算与1440/390本地 fixture 浏览器完成；不能冒充真实管理员或业务后端验收。

隔离 PostgreSQL 新专项在补齐执行器身份后暴露共享引擎漂移，原失败日志与旧成功原件分别保留。最终复用正式四引擎目录覆盖选择完整实体依赖副本，源复制差异为空、运行前后执行器完全相等，唯一受影响节点1通过/56.35s。真实授权、正式renderer、SQL分块留存回读、来源漂移409及原文件保留均验证；root与独立审查核四文件实际size/SHA，root重看最终题表页。结论仅为受控快照工程验证，未批准共享工作区部署。Word两题complete/verified，PDF sample/not_verified；案例整体incomplete/canApply=false，608缺项不是普遍常数。

当前405字段消费者分类：351 implemented /7 compatibility_only /37 not_applicable /10 missing；合同hash e120937ff40659e80ddafe61c541aee394325f3f7db015bde7ba333705f2a864。这不是verified统计。10项、模板富文档/无标记语义/其他模板格式、全视觉与历史生命周期、完整合同V继续推进；管理员试用后置，整体仍active，未部署。未重复完整五格式、81项签发或批准CAS套件。

交接：`output/system-config-preferences/document-table-caption-continuation-closeout.md`；本批目录：`output/system-config-preferences/document-table-captions/`；新证据索引：`output/system-config-preferences/document-table-caption-continuation-evidence.json`。旧closeout/索引不覆盖，累计文档以当前快照纳入新索引。

收尾磁盘身份核对另发现成功专项之后共享 `reporting/delivery/docx_native.py` 已变，差异另存本批 live-source-vs-sql.json；不将历史成功快照外推为当前共享部署通过，不盲重复已过测试。


## 2026-11-13 模板正文富文档推进

正式模板交付与管理验收已接原生标题、列表、表格及已授权静态图片，并从实际文件独立回读；声明外内容与既有依赖保留，新增定义不能激活原悬空样式/编号/图片引用。图片漂移及独立reader故障保留实际文件下载，旧字面模板恢复不重写。管理页面准确区分原生结构通过、PDF文字抽样与未验证，完整布局及应用批准不变。

隔离PostgreSQL新增专项1通过/22.22秒，真实授权、正式Word/PDF及SQL分块独立回读通过；材料为fixture，无业务库/外部模型。独立reader48个新增节点及旧11个受影响节点按限制分批通过；HTTP三类新故障保留实际字节；3页长表双图样例逐页检查。详见 output/system-config-preferences/template-rich-body-continuation-closeout.md 与 template-rich-body-continuation-evidence.json，保留历史失败与旧索引。

本批不增加完整合同V；405字段分类仍为351 implemented /7 compatibility_only /37 not_applicable /10 missing，非verified数量。模板编辑器预览/再导出同源桥、独立内部锚点目标验证、无标记语义/其他格式、全视觉/生命周期及管理员试用仍待推进。整体active、canApply=false，未部署。


## 2026-11-13 编辑器模板预览与再导出

预览和人工导出已共用受控模板桥；模板hash目录可进入新revision，根/派生/人工历史来源由耐久材料及原context摘要恢复。Word/PDF各用冻结落款，docx预览先生成Word再转PDF。真实入口、连续人工导出和三类HTTP故障保留实际字节验证通过；源数据为fixture，无业务库/外部模型、无部署。内部标题链接补独立目标核验和中文fragment，新增书签不激活宿主悬空anchor；投影版本升/2，新生成不复用旧/1，历史恢复保原字节。

来源resolver35新节点、内链22新节点、版本缓存11新节点分别分批通过，不将重叠批次相加。编辑器真实Word/PDF及两页视觉检查、独立声明外回读完成；不替代全生命周期/全布局/管理员试用。新增执行器身份覆盖实际编辑器接线，完整合同V未扩。交接 output/system-config-preferences/editor-template-parity-closeout.md，新索引editor-template-parity-evidence.json；旧139项证据原件二次读取无差异。

整体active、canApply=false。真实saved-reference child/adoption/历史恢复组合的完整端到端证据、复杂/无标记模板语义、其他格式、剩余10项消费者、全视觉/生命周期和完整V继续推进，管理员试用后置。405字段分类351/7/37/10仍不是verified计数。


## 2026-11-13 模板编辑生命周期增量

前批116项编辑器同源证据已冻结；新批见 `output/system-config-preferences/editor-template-lifecycle-closeout.md`。历史恢复7、child发布后编辑及缺失探测4、adoption目标2个不同新增节点分批有绿证据；另受影响非阻断专项10节点通过。修真实Router首次模板输出不存在被误拒，未知读错/权限/目录仍拒用。历史/child/adoption分别保留17/7/3原件身份读回与准确夹具边界；child准备/计算仍fixture，adoption真实prepare复制及grant/session/HTTP。restore_only不重生成但仍可幂等登记。历史shared lastfailed意外重复已如实保留，不累加计数。整体active/canApply=false，无部署、业务库或外部模型；405分类351/7/37/10不是verified数，合同hash不变。完整V、复杂模板和剩余消费者继续推进，管理员试用后置。

- 2026-11-13 XLSX打印范围增量：实际复现已嵌入表外图表被自动打印范围漏掉；仅创建时合并成功图表范围，保持用户编辑范围/拒图/其他sheet不变。新增8及既有4分批通过，实际四PDF与两对原件包身份/内容比对完成；桥接类型检查通过，整包另有散点图测试TS2532保留。右侧狭小图表不记作视觉通过，分隔线仍missing。交接xlsx-print-image-bounds/closeout.md；任务4/7及完整目标仍不整体勾选。


## 2026-11-13 XLSX落款原生内容增量

- 唯一末尾说明页完整结构/逐行逐格文本回读与最多三项configured_field/native接通；声明范围仅内容。隐藏、零生效默认尺寸、额外/重复结构和混合XML拒证；单次原生转义及同路径partial失败先红后绿修复。
- 新增54个不同节点及4个既有节点分批绿色，七实际HTTP/SQL/prepare场景与七原件独立冷读，正常落款页局部预览已看。各运行执行器身份分开记录，不据局部证据授完整应用批准。
- 交接output/system-config-preferences/xlsx-signature-native-evidence/closeout.md；本增量完成不整体勾选原任务4/7或全目标。图片原生输入接线、完整场景/模板/视觉/生命周期及批准应用继续推进；整体active，未部署。


## 2026-11-13 原生批准与任务冻结桥接验证

新增一个真实SQL节点，串联实际XLSX内容native证据/留存、测试合同prepare/apply、版本批准id、任务注册、重启、旧任务派生及五个实际成稿。不注入证据或seed版本，生产源码未改；完整生产合同拒绝局部receipt。最终1通过/31.74s，前两次测试/归档错误及六份中间原件保留，重复不累计。

旧来源与当前有效版本形成差异，完整说明/原值/公式缓存、五SQL快照和六原件独立读取完成。交接approval-task-native-lifecycle/closeout.md；这是局部工程桥，不整体勾选原生命周期任务或完整批准，整体active、未部署。


## 2026-11-13 XLSX数字格式与来源精度回读

局部bold/fontColor不再跳过数字偏好，数字表头按实际消费者规则逐格验收；显式numberFormat覆盖单独核验。来源数字/公式缓存改精确比较并区分bool，其他版式容差不变。日期按真实工作表关系及严格SpreadsheetML原始序列Decimal核验，关闭59/60、极小时间漂移及foreign v/c漏报；合法数字显示覆盖与区域内建14/22不误报。

19个不同新增reader节点、6个真实HTTP/XLSX/SQL/prepare节点及7个既有节点分批绿色，重复不累计。18原件标准库ZIP/XML独立核值/格式/公式缓存和最终reader冷读通过。两项复核发现先红后绿；一次写入失败截空源码已从完整基线原子恢复并复验。全部故障原件保留，prepare未批准。

各SQL运行内清单稳定，最终共享workbook源摘要变化，历史SQL不提升为当前完整执行器批准。无新mapper/视觉或全生命周期V，完整合同hash与405字段360/7/37/1分类不变；分隔线、完整场景/模板/视觉/生命周期、图片原生输入及生产批准继续推进。交接output/system-config-preferences/xlsx-number-readback/closeout.md；整体active、未部署。


## 2026-11-14 XLSX数字五字段原生证据

完整数字来源/原始值/公式缓存/可编码日期及有效格式逐对象回读接入窄mapper，最多五项configured_field/native。显式覆盖单独核验，无默认适用对象不发默认字段证据；来源歧义拒组，既有同路径失败不被成功组覆盖。不授worksheet完整场景、视觉或生命周期通过。复核指出负数样式索引别名及显式覆盖组边界，两项先红后绿关闭。

新增53个不同节点（reader20、mapper28、真实HTTP/XLSX/SQL/prepare5）与7个受影响既有节点分批绿色，非一次完整套件运行。初次SQL4通过/1执行器变化失败，仅重验失败节点1通过/29.09s，原日志保留。11份原件当前reader冷读及标准库ZIP/XML独立核验完成，最终七文件Ruff通过；旧67项冻结索引重核不变。

完整合同hash及405字段360/7/37/1实现分类不变，不是verified覆盖率。仅only_overrides历史SQL执行器与冷读清单一致，其余四项不追认为当前批准。生产跨状态库原子身份与撤权/重放、完整场景/模板/视觉/生命周期、XLSX打印分隔线/图片原生授权、历史工程缺陷仍缺。详见output/system-config-preferences/xlsx-number-native-evidence/closeout.md和current-gaps.md；整体active/canApply=false、未部署，管理员试用后置。


## 2026-11-14 偏好批准来源提交窗口串行化

真实SQL并发测试复现apply共享生命周期锁允许另一合作式来源操作在核验后、SQL提交前改动材料。仅将既有apply锁改为排他，保持工作区固定顺序和逐条核验；同任务嵌套SH按原机制重入，锁覆盖管理事务退出。

4个不同新增节点与4个受影响既有节点分批绿色：原竞态先红后绿、提交前取消/事务回滚、独立进程竞争、单连接池、精确并发重试、撤权串行化及生产合同仍拒绝局部批准。未重复完整测试，Ruff与同模型只读复核完成。测试合同及字段证据/工作流为夹具，管理/编辑会话及版本审计是真SQL；仅关闭同机同inode合作式来源窗口，不冒称跨数据库完整原子性或COMMIT取消必回滚。

完整合同hash和405字段360/7/37/1分类不变，整体active/canApply=false、未部署。跨状态库身份/撤权重放、全场景模板视觉生命周期、XLSX分隔线及图片原生授权和历史工程问题继续推进。详见output/system-config-preferences/approval-source-serialization/closeout.md与current-gaps.md。
