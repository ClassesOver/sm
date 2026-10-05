# Report Editor 数据追溯 B7 进度记录（第一增量）

日期：2026-09-30。状态：**B7 / G7 已完成**。核心契约、规划投影、快照计算、发布声明、Editor API、前端交互、全算法矩阵、接近 200 MiB 规模基准、B6 revision 生命周期及真实 StarRocks 快照闭环均已验收。

上游：计划 B7、B1/B2/B4/B6 进度记录。

## 已完成

| 项 | 实现 | 验证 |
| --- | --- | --- |
| 冻结能力声明 | `DrilldownMetricV1`/`DrilldownDimensionV1`：指标、数据集、算法、实际字段、固定范围、期间、允许维度、对账值与 fact 身份进入 revision 索引；索引校验数据集归属与重复身份 | contracts/index 定向回归 |
| 安全能力生成 | `drilldown_builder.py` 从冻结 facts、Effective Profile 和实际快照列生成声明；歧义、缺字段、无 `additiveAcross`、非行保留 AVG/COUNT/COUNT DISTINCT 均关闭能力；ratio 只使用同快照、同范围、同期间且共同可加维度 | `test_trace_drilldown_builder.py` 3 项 |
| 规划期投影 | 单表 requirement 将全部相关 measure 共同声明可加的 Profile 维度加入 `dimensionColumns`/`grainColumns`；不处理跨表、不超过 30 列契约，无法安全投影时保持不可用 | planner 定向用例 1 项 |
| 受限计算服务 | `drilldown_service.py` 使用 polars lazy scan；请求只能选择登记 dimension code，固定 scope/期间不可覆盖；支持 sum、ratio、average、count、count distinct、`semi_additive_last`；空值组、稳定排序、签名分页、1 MiB 响应预算 | `test_trace_drilldown_service.py` 8 项 |
| 聚合语义与对账 | ratio 用总分子/总分母；average、去重独立计算总体；时点值所有分组使用同一个最新快照期间；返回 expected/observed/difference/passed，不用分组值求和冒充总体 | 手算 fixture 覆盖正确例与拒绝例 |
| Editor API/权限 | `POST /api/sources/{subject_id}/drilldown` 与 `POST /api/drilldowns/{metric_code}`；全局登记指标不依赖正文 subject，dataset/metric/dimension 全部复核；分享会话默认 `drilldown:false`，blocked columns 不展示且拒绝执行 | `test_report_editor_trace.py` 直接服务与真实 ASGI HTTP 用例 |
| 前端 | 来源面板新增“下钻”页签，只展示登记维度；结果表格、分页、单位与对账状态；展示计算说明和冻结快照身份；无权限/不可用使用稳定错误文案 | `trace-panel.test.ts` 14 passed；生产 build 通过 |
| G7 联合算法矩阵 | 同一份行保留冻结快照贯穿声明生成和服务执行，覆盖负数、空值组、固定 scope/期间，以及金额、比率、平均值、普通计数、去重计数、半可加时点值；独立答案全部对账通过 | `test_g7_capability_and_algorithm_matrix_uses_one_frozen_snapshot` |
| 缺输入关闭能力 | 从同一 fixture 移除 `row_preserving_dataset_ids` 后，AVG/COUNT/COUNT DISTINCT 不再签发，保存聚合答案不冒充原始输入 | 同一 G7 联合用例 |
| 大快照执行 | Polars 使用 streaming collect；分组总数、分页和可合并总体值合并为一次分组计划，只有跨组不可合并的 COUNT DISTINCT 保留独立总体扫描 | 191,036,507 字节、550 万行实测 |
| 权限字段 | 下钻依赖任一字段进入 `blocked_columns` 时，来源清单不展示该能力，直接请求也返回 `dataset_access_denied` | Editor 服务定向用例 |
| 并发与超时 | 小快照实测 8 请求峰值为 4 worker；基于 182 MiB 内存基准，≥64 MiB 快照改走单并发 limiter，实测 8 请求峰值为 1；超时保持 `resource_limit_exceeded` | API/服务定向用例 |
| Revision 继承 | revision-1 冻结 CSV/facts 复制到 revision-2 后资源 ID 正确重绑定，下钻声明保持不变；两个 revision 分别执行得到相同快照 hash 与对账答案 | B6/B7 联合定向用例 |
| N+1 事务导出 | revision-1 下钻声明随注册 lineage 原子重绑定到 revision-2；成功导出后可立即执行并对账。渲染、durable commit、下载授权、Editor 授权失败路径分别验证清理/持久化边界 | B6/B7 联合参数化用例 5 项 |
| 历史恢复 | revision-2 恢复 revision-1 正文后，来源上下文指回 revision-1 且下钻可直接执行；随后导出 revision-3 时复制历史冻结 CSV、重绑定资源 ID 并保持 3,600 对账答案 | B6/B7 联合用例 2 项 |
| 真实语义接线 | 规划投影和发布声明均改为读取人工确认后的最终 `SourceSchemaSnapshot.measureSemantics`，不再误读静态 Profile；同时修复多 requirement 时 Profile 维度变量被首项覆盖的问题 | planner/publication 定向回归 |
| 重新分析隔离 | revision-2 使用独立 CSV、datasetId、hash 与 4,000 对账值；执行前后 revision-1 仍返回原 3,600 与原 hash，证明新快照不覆盖旧 revision | Editor trace 定向用例 |

## 本轮验证

- 后端 B7/契约/索引/Editor/HTTP 发布/revision 继承/规划投影受影响回归：223 passed，5 skipped。
- 前端来源面板定向：14 passed。
- 前端生产构建：通过；保留既有大 chunk 警告。
- `git diff --check`：通过。
- 遵守“禁止重复完整测试”，本增量未运行完整后端或完整前端套件。

## 第二增量验证

- 同一冻结快照的 G7 声明/算法联合用例通过；B7 builder/service/Editor 下钻定向回归合计：21 passed。
- 191,036,507 字节（约 182 MiB）、5,500,000 行 CSV，三分组金额下钻连续 5 次：p50 约 226 ms，样本 p95 上界约 250 ms；结果 272,250,000 与独立求和一致。
- 单次执行经一次扫描合并后约 222 ms，峰值 RSS 约 822 MiB；连续 5 次进程峰值约 1.1 GiB。相较初始实现单次约 677 ms、峰值约 1.03 GiB 已显著下降，但 Polars 分配器在重复执行后保留内存，仍列为 G7 资源收尾项，不能标记完全通过。
- 并发门禁实测：8 个小快照请求最多进入 4 个计算 worker，8 个大快照请求最多进入 1 个计算 worker；10 秒超时错误契约保持稳定。
- 修改文件完整 Ruff 检查（service/builder test）与相关文件 F/I、`git diff --check` 通过。
- 当前 `ruijin` Profile 通过真实 registry/extends/source binding 加载；25/25 个生产指标在合法 `SourceSchemaSnapshot.measureSemantics` 与对应表维度齐备时均生成声明。删除任一指标语义后只剩 24 项，证明缺输入不会猜测签发。
- N+1 导出成功及四类失败注入共 5 项通过；已持久化 revision-2 的继承声明可直接执行，结果 3,600 与原冻结答案一致。
- 历史恢复后直接下钻、历史恢复后导出 revision-3 并再次下钻均通过。
- 最终受影响回归分两组执行：B7 builder/service/Editor 24 passed；规划、N+1 与历史恢复联合测试 8 passed。
- 重新分析版本隔离用例通过；旧 revision 在新索引注册前后返回完全相同 payload，新 revision 使用不同快照 hash 和答案。

## 真实源库闭环（G7 最终验收）

- 通过仓库 `.env` 的 `REPORT_STARROCKS_DSN`（验证过程不输出连接信息）只读连接 `rj`，实时 catalog 成功校验 Profile 引用的 6 张表。
- 使用 `ruijin` Profile 的 `actual_medical_income` 和 `dwd_income_budget_view` 最新期间 `2025-12-01`：最终 `SourceSchemaSnapshot.measureSemantics` 将 `data_date`、`area` 声明为可加维度，requirement 投影确实加入 `area`。
- StarRocks 物化冻结快照 1,169 行、31,601 字节，SHA-256 前缀 `aeeeb8dd1521`；服务端生成 facts、下钻声明和 revision trace index，并由 Editor 来源 API 发现该能力。
- Editor 按院区下钻得到 5 个分组；结果与源库独立 `SUM` / `GROUP BY` 答案逐组核对通过，总体 reconciliation 为通过。验证输出不记录业务数值。
- 临时快照和工作区均在探针结束时清理；没有修改源库，也没有保存连接串或明细数据。

## 当前部署 Profile 清单

- `deploy/agentos/reporting/reporting_profiles/hospitals/ruijin.json` 当前登记 25 个指标，静态聚合类型全部为 `sum`；monthly-operation、budget-execution、finance 和 ruijin-north 只继承该指标集，没有额外指标覆盖。该结论现由真实 registry 解析和 25/25 声明测试固定，不再只是人工盘点。
- 因此当前部署 Profile 的直接指标能力范围是金额/工作量等 SUM；是否签发维度仍由每次真实 SourceSchemaSnapshot 的 `measureSemantics.additiveAcross` 和实际 CSV 投影共同决定。
- 比率来自运行时 derived facts；AVG、COUNT、COUNT DISTINCT、半可加时点值的通用能力已由联合 fixture 验证，但当前静态 Profile 没有对应直接指标，不能伪称已完成生产数据跑批。

## G7 完成审计

1. 真实源库闭环已证明 Profile → 最终 SourceSchemaSnapshot → requirement 投影 → CSV → facts → trace index → Editor 下钻；生产 Profile 25 个 SUM 指标的静态映射由 registry 测试固定，缺任一语义时不签发。
2. 191,036,507 字节规模下钻 p95 样本上界约 250 ms，低于 B0 的 3 秒门槛；实现使用 lazy streaming scan。服务基线约 335 MiB，单次峰值约 822 MiB、连续执行进程峰值约 1.1 GiB；≥64 MiB 请求单并发，避免四倍放大。B0 未冻结数值内存上限，实测值完整披露。
3. 金额、比率、平均值、普通计数、去重计数、半可加时点值均有独立正确答案；缺行保留输入、缺字段、零分母或不可加维度均按契约关闭或返回空值。
4. 空值组、负数、重复标识、非法维度、跨 revision 游标、快照篡改、blocked columns、超时、小/大快照并发及响应预算均有服务或 API 级验证。
5. 普通 revision 继承、N+1 成功/失败事务、历史恢复/再导出和重新分析新快照隔离均已验证，旧 revision 的声明、hash 与答案不被覆盖。

## 设计决定

2026-09-30 B6 历史图片/AI 来源保护增量后，B7 builder/service 定向回归 15 passed；未重复完整测试、真实源库探针或大快照基准。G7 既有验收结论不变，总计划 B7 勾选同步本记录。

- 下钻不接受字段名、过滤条件或算法，只接受索引登记的 metric/dataset/dimension 组合。
- 聚合快照没有权重或原始标识时，不为 average/count/count distinct 签发能力；保存了一个聚合数不等于可重新聚合。
- 半可加指标以 `sum` measure 的 `additiveAcross` 未包含期间字段为判据；所有分组统一使用快照内同一最新期间，期间维度不出现在可选项中。
- 语义或输入缺失按项目规则表现为能力不可用；越权、跨 subject、跨 revision 游标和文件完整性失败硬拒绝。
