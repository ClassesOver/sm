# Odoo 报表分析脚本协议

`generate_reports.py` 是 `agui.odoo.report.skill.v1` 的本地执行端。它只接受工作区内由受控工具创建的配置路径，不接受内嵌数据、任意输入路径或自定义输出路径。

## 协议模型

一份 `agui.report.config.v1` 配置就是 `ReportAssemblyInput`：宿主通过 `manifestPath` 绑定完整数据，Agent 根据当前用户需求定义报告目的、标题、维度、指标、图表和章节顺序。详细字段见 `report-manifest.md`。

脚本使用固定调用格式：

```text
python generate_reports.py <operation> [configPath]
```

| operation | 参数 | 写入工作区 | 用途 |
| --- | --- | --- | --- |
| `capabilities` | 无 | 否 | 返回版本、输入版本、唯一产物、图表类型、聚合和限制 |
| `validate` | `configPath` | 否 | 校验配置、manifest、全部分片、摘要、行数和分析口径 |
| `render` | `configPath` | 是 | 先完成相同校验，再原子生成 PDF |

正常 Agent 流程只调用一次 `render`。不要为了发现能力调用脚本；Agno 已在 Skill metadata 中公开脚本和 reference，具体能力可读取本 reference。`validate` 只用于诊断失败配置。

## 输出信封

stdout 只输出一行 UTF-8 JSON。成功渲染示例：

```json
{"protocol":"agui.odoo.report.skill.v1","operation":"render","ok":true,"reportId":"<uuid>","artifacts":[{"kind":"pdf","path":"报表/生成结果/<uuid>/分析报告.pdf","mimeType":"application/pdf"}]}
```

参数错误或执行失败只向 stderr 输出同版本 JSON，退出码非零：

```json
{"protocol":"agui.odoo.report.skill.v1","operation":"render","ok":false,"error":{"code":"report_validation_failed","message":"..."}}
```

## 执行边界

- 数据只从 `报表/原始数据/<dataset-id>/` 读取，不支持远程 URL 或内嵌 rows。
- `render` 的唯一最终产物是 `分析报告.pdf`；图表 PNG 只是临时渲染资源，成功前删除。
- PDF 使用 manifest 业务字段标签、统一数值格式、嵌入式 Noto CJK 字体、重复表头、页眉页脚、页码和文档元数据，不展示原始行样例。
- 运行环境只使用 sandbox-tools 已安装的 Matplotlib、WeasyPrint 和 Noto CJK 字体。
- 输出目录已存在、路径越界、摘要不匹配、数据超限或任一生成步骤失败时整体失败，不留下部分结果。
