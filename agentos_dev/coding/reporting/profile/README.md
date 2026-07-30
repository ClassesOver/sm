# Report Agent Profile 配置规约

Profile 文件位于数据源配置边界下的 `reporting_profiles/`。目录可以使用 `organizations/`、
`hospitals/` 和 `templates/` 分类，但目录名不产生隐式继承；每个 JSON 必须通过 `profileId` 和
`extends` 显式声明关系。

加载器从部署边界到当前目录逐层发现 `reporting_profiles/**/*.json`。父目录先加载，子目录中相同
`profileId` 的文件整项替换父层定义。Profile 内部继承按 `extends` 顺序合并父 Profile，最后应用当前
Profile；dimensions、metrics、reconciliations 和 sections 均按稳定 `code` 合并，字段由后层覆盖，
`enabled: false` 删除继承项。循环、缺失父项、同层重复 ID/code 和未知字段均失败关闭。

Profile 仅支持结构化 dimension、metric、reconciliation 和 section。指标聚合限于 `sum`、`count`、
`count_distinct`、`average` 和 `ratio`；对账当前只接受 `sum`/`count` 基础指标。禁止 SQL、Python、
自由表达式和任何连接字段。字段引用固定为 `sourceId.database.table.column`，并且只能缩小已批准的
Schema Snapshot。

`pageLayout` 以 `headerLeft`、`headerRight`、`footerLeft`、`footerRight` 定义 WeasyPrint 页眉页脚。
只允许 `{title}`、`{page}`、`{pages}` 三种占位符，页脚必须同时包含当前页和总页数；禁止传入 CSS。
默认页眉左侧为“上海鼎医信息技术有限公司”，右侧为报告标题，默认页脚显示报表类型和
“第 N / M 页”。Workflow 固定执行渲染和逐页版式验收，模型不能选择渲染器或绕过版式。

数据源通过可选 `reportingProfile` 引用最终医院 Profile。一次运行的所有 source 必须绑定同一 Profile；
未配置时使用内置领域无关 Profile。解析结果写入 Workflow state，并计算稳定
`effectiveProfileHash`，报告产物必须绑定该 hash。
