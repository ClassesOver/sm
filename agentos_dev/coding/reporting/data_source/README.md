# Report Agent 数据源配置规约

Report Agent 从调用方提供的 `boundary_dir` 到 `start_dir`，按目录层级由远到近查找
`report-data-sources.json`。查找不会越过 `boundary_dir`；配置文件必须是小于等于 1 MiB 的普通文件，
不接受符号链接。

每层配置使用严格 JSON 契约：

```json
{
  "version": "1",
  "defaultSourceIds": ["operations"],
  "sources": [
    {
      "id": "operations",
      "type": "starrocks",
      "name": "运营数据",
      "dsnEnv": "REPORT_OPERATIONS_DSN",
      "database": "reporting",
      "tables": ["reporting.income", "reporting.workload"],
      "periodColumns": {
        "reporting.income": "month",
        "reporting.workload": "month"
      },
      "periodGranularities": {
        "reporting.income": "date",
        "reporting.workload": "date"
      },
      "reportingProfile": "hospital-operations",
      "statementTimeoutSeconds": 30,
      "maxRows": 1000000,
      "maxBytes": 268435456,
      "exactDistinctMaxRows": 1000000,
      "statisticsColumnBatchSize": 24,
      "topValuesMaxColumns": 20,
      "topValuesLimit": 10,
      "profileConcurrency": 4,
      "queryConcurrency": 2
    }
  ]
}
```

覆盖规则：

1. 父目录先加载，越接近 `start_dir` 的配置优先。
2. 相同 `id` 的 source 整项替换，不做字段级深合并。
3. `{"id": "operations", "disabled": true}` 删除继承的数据源；该对象不能包含其他字段。
4. `defaultSourceIds` 仅在当前层显式出现时整项替换；省略表示继承，空数组表示清空。
5. 每层 source ID 不得重复；最终默认 ID 必须指向仍然启用的数据源。
6. 所有未知字段均拒绝。当前仅实现 `starrocks`，其他类型通过注册独立 parser 扩展。

连接信息只能来自 `dsnEnv` 指向的服务端环境变量。请求、公开配置、模型上下文和 Workflow state
不得保存或返回 DSN、host、用户名或密码。StarRocks 的 `database` 必须与 DSN 一致，`tables` 必须使用
同一数据库下的完整限定名。
`periodColumns` 必须逐项覆盖 `tables`，键为完整表名，值为期间字段；`periodGranularities` 可显式为
每张表声明 `date` 或 `year`，省略时使用 `date`。日期模式按完整日期过滤并统计月份覆盖，年度模式按
整数年份过滤并统计年度覆盖；均不得由字段命名猜测。
`reportingProfile` 是可选的服务端 Profile ID，不包含任何 Profile 内容或连接信息。一次运行选择的所有
数据源必须绑定相同 ID；省略时使用内置领域无关 Profile。Profile 规约见
[`../profile/README.md`](../profile/README.md)。

DataShape 统计规约：

1. `exactDistinctMaxRows` 按全表行数决定 distinct 模式；不超过阈值使用精确统计，超过阈值使用
   `APPROX_COUNT_DISTINCT`。
2. `statisticsColumnBatchSize` 控制单条聚合 SQL 包含的字段数，避免超宽表产生过长 SQL。
3. Top-K 不包含期间字段，只选择 `distinctCount <= topValuesLimit` 的低基数字段，并最多统计
   `topValuesMaxColumns` 个字段；设为 `0` 可禁用 Top-K。
4. 空值率和基数率均以期间内行数为分母；精确 distinct 时，`unique` 表示所有非空值唯一，近似
   distinct 时为 `null`，避免把估算结果误报为唯一性结论。
5. 全部查询只返回聚合结果，不读取样本行。任一表、任一统计批次失败，整次 DataShape 采集失败。
6. DataShape 记录 source ID、metadata revision、schema hash、统计版本及实际查询数；表级
   `periodGranularity`、`periodCoverage` 和 `missingPeriods` 精确描述日期或年度覆盖。期间字段必须由
   调用方按完整表名显式配置，不根据字段名猜测。
7. `profileConcurrency` 限制单数据源 DataShape 查询并发数；多数据源运行时以所有源中的
   最小值作为 Workflow 总上限，避免 source/table/batch 多层并发相乘。
8. `queryConcurrency` 限制审核 SQL 物化并发数；同一 source 使用自身上限，整批使用相关
   source 中的最小值作为总上限。查询结果直接写入 staging，全部成功后才原子提交。
