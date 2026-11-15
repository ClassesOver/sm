# GenOffice 全量技能迁移与 Agno 接线（2026-11-15）

用户在 PR #245 的工具一对一任务上明确追加“技能也全部抄过来”，并要求及时同步。

## 原样复制

固定源 `genspark-ai/genoffice@f8c17004fb730df11f0f743164ffd8b4281bb38c`。
`office/vendor/genoffice` 保留213个原始文件（2,575,406字节），含全部43个SKILL.md（42个推荐业务技能+1个终端技能）、21个翻译文件、Word/XLSX/PPTX/PDF/HTML/Markdown六种编辑器完整renderer AI源码、共享agent-core源码、PPTX操作提示词和技能导入/CLI接线定义。下载时逐文件匹配固定源tree中的Git blob SHA1，再记录SHA256/大小；许可证和NOTICE均保留。README和SOURCE-MANIFEST为本地来源记录，原文件不改写。

原样导入已先单独推送为34b1011d。源码快照没有被当作另一套桌面AgentLoop执行，也没有把TS模块当成已接入的Agno工具。

## 实际接线

- 通过Agno原生Skills/LocalSkills加载全部43个技能。模型先看到名称/说明，调用get_skill_instructions后读取完整原文；不把全部正文塞入每轮system prompt。
- 已接9个现有Office source-enriched planner、Word任务MCP Agent和首页Office知识问答，共11个运行入口。文件命名和搜索重排这类固定schema小任务不加技能目录。
- 保留既有文档工具、普通/可调用instructions、additional_context和租户技能。已有同名技能按原加载器优先；重复装配不会追加重复目录/宿主说明。既有加载器只有部分内置技能时，补齐另一目录，而不是漏掉42个推荐技能。
- Native host说明明确：技能是任务指导，CLI技能为终端参考；没有注册的CLI、shell、图片服务、桌面IPC或创建能力不会因复制而出现。只读、冻结授权、来源身份、读取覆盖、输出schema、预览与显式采纳继续由现有真实工具和服务控制。
- Word MCP文档工具仍必传task_id；框架技能读取工具按自己的schema调用，不要求task_id。完整MCP票据/文档权限检查保持原有边界。
- source的SKILL frontmatter包含category/scenarios/quickPrompts，超出通用Agent Skills验证字段，使用原生LocalSkills(validate=False)保留原文，不自行解析或删字段。固定资产完整性及全部43项均能解析为非空技能由专项测试覆盖；复制的包没有scripts目录，不新增可执行技能脚本。

原桌面是用户附加技能后注入正文；本次采用Agno原生渐进发现方式，让所有源技能可读取。原桌面技能选择菜单/用户技能安装管理未复制为可用网页流程，仍在后续对齐范围。

## 原指南

WorkbookAIToolkit.load_guide现在支持全部11个源guide：writing、formatting、layout、structure、charts、data、financial-formatting、data-attribution、table、pivot、shape-image。逐字保留原指南，后面单独附Native Agno adapter说明和现有本地操作映射。源自动应用/直接写文件描述不绕过预览和显式采纳；不支持的DSL仍明确为缺口。新增4种guide可读取不代表其全部操作都已实现。

## 验证记录

- source/运行时/guide初始3项失败（缺模块/未注册技能）+12项guide失败，随后18项通过。
- 独立复核无Critical/Important。复核指出部分加载器漏技能：genoffice-only场景先失败，recommended-only原已通过；修复为只添加缺失目录，两个变体均通过。
- 最终新专项20项全部通过；同次验证加Word真实认证MCP普通/skill-first两种提案链共22项通过（11.14秒）。技能工具回执包含实际原文，文档读取/候选登记仍走已认证MCP；XLSX纯阅读真实Agno工具回执和服务端引用/读取覆盖通过。
- 13份受影响文件首次157项通过，21项失败：19项root Office测试因缺pytest-asyncio未运行；1项新增表格因旧workbook dist失败；1项Word测试把丰富表格假定为单页。补测试环境依赖及重建后，修复相关节点通过；Word工具类AST与已推基线完全相同，测试改为沿nextOffset完整读取并在未读完时继续断言禁止提案，没有改产品分页来迎合夹具。
- root Office后续18项DB用例还缺aiosqlite，补环境后知识问答/数据源两份文件19项全部通过（4.09秒）。没有修改生产依赖锁或为环境缺失放松授权。doc/slides/pdf依赖按lockfile安装并重建bridge；新表格按最新workbook源码重建后通过。
- 目标Ruff和git diff --check通过。按受影响范围分批验证，没有重复完整项目测试。ScriptedModel/本地SQLite和合成文件证据不算真实provider/生产数据库/浏览器整链验收。

所有源工具的实际执行、CLI与桌面能力、技能选择/安装UI仍按既有差距清单推进。本批全量复制与技能读取接线不提升为四格式工具全量完成声明。
