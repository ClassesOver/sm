# Odoo ReportAssemblyInput 清单与配置

## 数据集清单

路径必须是 `报表/原始数据/<dataset-uuid>/数据集.json`，版本为 `agui.report.dataset.v1`。清单包含：

- `datasetId`、`model`、`fields`、`rowCount`、`columnCount`
- `fragments[].path/size/sha256`、`totalSize`
- `scope`、`selectedCount`、`timezone`、`generatedAt`、`scopeFingerprint`

清单不得包含 domain、context、selected IDs 或记录值。分片必须位于同一数据集的 `分片/数据-NNNN.jsonl`，最多 16 个，每个最多 8 MiB，总计最多 100 MiB。不要通过文本读取工具打开分片。

## 最终报表配置

必须调用 `pandas_create_report_config` 创建配置，不要手工选择 UUID 或路径。配置版本为 `agui.report.config.v1`，结构如下：

```json
{
  "version": "agui.report.config.v1",
  "reportId": "<report-uuid>",
  "manifestPath": "报表/原始数据/<dataset-uuid>/数据集.json",
  "datasetHash": "<detail 返回的 manifest SHA-256>",
  "title": "区域销售分析",
  "analysis": {
    "dimensions": ["region"],
    "metrics": [
      {"field": "amount", "aggregation": "sum", "label": "销售额"}
    ],
    "notes": ["按当前列表范围统计，不做隐式汇率换算。"]
  },
  "chart": {
    "type": "bar",
    "metric": "amount:sum",
    "title": "各区域销售额"
  },
  "presentation": {
    "purpose": "比较区域销售表现并识别差异。",
    "sections": ["overview", "notes", "chart", "analysis"]
  }
}
```

- 维度 1 至 2 个，指标 1 至 5 个。
- 聚合只允许 `count`、`sum`、`avg`、`min`、`max`；`sum`/`avg` 仅用于数值字段。
- 最终图表只允许 `bar`、`line`、`pie`，图表指标必须是配置中的数值聚合结果。
- 分析说明最多 10 条，每条最多 500 字符，不得放入原始行、ID 或查询条件。
- `purpose` 是根据用户当前需求提炼的报告目的，最多 500 字符，不得包含原始行或查询条件。
- `sections` 按输出顺序选择 `overview`、`notes`、`chart`、`analysis`，至少一项且不得重复。未选择 `chart` 时不生成临时图表。
- 最终配置和 PDF 不包含原始行样例。`pandas_sample_dataset` 的有界结果只用于 Agent 内部核对，不得复制到配置或分析说明。

脚本从配置路径推导唯一 PDF 输出路径，不接受自定义输出目录。图表 PNG 只作为 PDF 渲染期间的临时资源；失败时不会留下部分输出目录。脚本操作和 JSON 信封见 `report-protocol.md`。
