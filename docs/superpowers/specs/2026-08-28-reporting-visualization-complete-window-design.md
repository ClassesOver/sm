# Reporting 可视化完整窗口设计

## 目标

保留模型生成 Python 图表脚本的现有架构和全部可视化预算，消除全局 facts 聚合结果与已签发图表脚本被 16 KiB 二次截断后产生的分段读取、自循环和额外模型请求。

## 已确认根因

- `query_analysis_facts` 使用 16 KiB 业务回执上限。最近一次真实 CLI 中，覆盖 16 个 analysis 的首个查询被自动从 `maxItems=200` 降到 25，并返回 `truncated=true`，模型随后不断追加查询。
- Reporting 工具结果统一只展示 16 KiB。`read_file` 已一次读取完整的 40,314 字节 `charts.py`，但执行层向模型省略中间 23,930 字节，迫使模型继续按 offset 分段读取。
- 两个限制相互独立。只修改提示词、探索状态或工具预算不能让已经被服务端截断的内容一次可见。

## 设计

### Facts 聚合

`query_analysis_facts` 在 `taskKind=visualization` 时使用 128 KiB 业务结果和模型预览窗口。单项 analysis、Profile、analysis context 与 section 保持原 16 KiB 边界。

128 KiB 是单次回执上限，不是必须填满的输入配额。JMESPath、`maxItems`、冻结文件身份校验、Task 总输出存储上限和 Reporting analysis 输入 hard cap 保持不变。

### 签发脚本

visualization 成功读取 `visualizationWorkspace.scriptPath` 时使用 64 KiB 模型预览窗口。其他文件仍使用原 Reporting 预览边界；visualization 原有路径门禁继续禁止直接读取 facts/evidence。

服务端在任何 visualization Python 写入落盘前校验候选脚本不超过 64 KiB。创建、覆盖、精确替换和补丁都校验最终候选内容，超限返回稳定错误 `report_visualization_script_too_large`，且不创建写入意图、不修改 Workspace。

### Vision 模式

vision 和 deterministic 模式共享完全相同的 facts 与脚本窗口。两者只在现有最终图片检查阶段分流，本设计不改变视觉回执、图表登记或 fallback 语义。

## 不变量

- 不降低或重置 facts、读取、总工具调用和脚本失败预算。
- 不引入 ChartPlan/DSL，不替换 matplotlib，不修改公共 HTTP API、Workflow ID 或数据库结构。
- 不扩大纯 Coding Agent、单项 analysis、section、Profile 或任意工作区文件的默认预览窗口。
- 超过完整窗口的内容仍通过既有 `outputHandle` 恢复；合法 visualization 脚本本身不得超过一次完整读取上限。

## 验收

- 大于 16 KiB 且小于 128 KiB 的 visualization facts 聚合回执不因字节边界降低 `maxItems`，并返回 `truncated=false`。
- 40 KiB 已签发脚本一次 `read_file` 后 `outputTruncated=false`，正文完整可见。
- 相同大小的普通 Reporting 输出仍按 16 KiB 截断。
- 超过 64 KiB 的 visualization 脚本在 mutation 前失败关闭；其他 analysis 文件继续服从原 4 MiB 写入意图上限。
- 现有动态预算标量及使用量测试保持不变。
