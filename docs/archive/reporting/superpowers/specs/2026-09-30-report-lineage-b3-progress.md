# Report Editor 数据追溯 B3 进度记录（第二增量）

日期：2026-09-30。状态：B3 计划实施项（B3-1~B3-4）主体落地；多系列映射提取与真实跑批随 B5/G9。

上游：计划 B3、`2026-09-29-report-lineage-b0-freeze.md`。

## 已完成

| 项 | 实现 | 测试 |
| --- | --- | --- |
| 作图数据身份进入提交链路 | `_materialize_chart` entry 增 `size`/`sha256`；`submit` 闭包把 chart-input 文件身份按 chartId 上报；`submit_visualization_charts` 新参数 `plot_data_files`——服务端逐文件 `ahash_file` 重验（磁盘与提交身份不一致即拒绝），重验后写入 durable `visualizationSections[sectionCode].plotDataFiles`，提交冲突检查覆盖 | `test_replay_visualization_task.py` 回归 + 模块导入验证 |
| AnalysisChart 冻结作图数据 | `plotDataFiles`（FileIdentity ≤50，JSON 校验、路径去重）+ `plotDataKind`；`_analysis_chart_from_registration` 从 durable 带入；旧图无字段兼容（空 = 来源不足，读取层降级） | 回归覆盖 |
| 归档与索引登记 | finalize 把 chart-input 文件与图片一起归档进 revision 目录（`chart-XXX--N.chart-input.json`，不进交付 manifest）；`ChartTraceV1` 构造（image=归档图、plotData=归档 chart-input、datasetIds=citation→dataset 映射）；`build_csv_trace_index` 增 `chart_trace_files`/`chart_traces`，图表 trace 引用全部落在已登记文件上（契约全局校验） | `test_trace_index_builder.py` 7 例（媒体类型、未登记文件拒绝） |
| 确定性转换规则 | `trace/chart_transform.py`：排序、Top N/其他项合并、缺值语义（Top 内缺值保持 None；「其他」缺值按 0 计入、全缺值则 None）、单位换算、负数参与排序；非法请求 4xx | `test_trace_chart_transform.py` 5 例——逐值核对 `chart_expected.json` 手算答案（B 2400/A 1200/C 600/其他 350；万元 0.24/0.12/0.06/0.035；C 费用 missing；D -100 入其他） |

验证：B3 受影响面 23 个测试文件 367 passed（2026-09-30，含 `test_replay_visualization_task.py` 可视化回放）。

## 第二增量：图表来源读取服务、Editor API 与联合验收强化（2026-09-30 完成）

| 项 | 实现 | 测试 |
| --- | --- | --- |
| 路径安全 | `chart_input_root_for` 公共化（analysis.py 物化入口与提交工具共用推导，防口径漂移）；`submit_visualization_charts` 校验作图数据文件必须落在当前 Task 的 chart-input 签发目录内（防任意工作区路径伪造身份） | 既有提交回归 |
| 静态图数值级联合验收（软） | `verify_static_chart_inputs_referenced`：静态图（matplotlib）脚本必须引用预物化 chart-input（path 或文件名 stem），未引用记 loguru 软告警（哈希不能证明柱高，深核依赖视觉审查——计划 4.4-4 的诚实边界）；Plotly 图沿用 `verify_plotly_chart_inputs` 数值核对 | `test_replay_visualization_task.py` 72 例回归 |
| 图表来源读取服务 | `trace_sources.charts()`（有 trace 的图表清单）、`chart_source()`（图片/作图数据身份 + transformNotes + 作图表有界预览：解析 chart-input/v1 JSON，columns + offset/limit 分页 rows，1~100 行/页，逐文件复核登记 sha256，不返回工作区路径）；未知 chartId 一律 `source_missing`（404） | `test_report_editor_trace.py` 19 例 |
| Editor API | `GET /api/charts`、`GET /api/charts/{chart_id}/source`（limit/offset 参数、非法 limit 400 `request_invalid`） | 同上（HTTP 全链路） |

验证：B3 受影响面 23 个测试文件 370 passed（2026-09-30）。

## G3 对照（计划 B3）

| G3 条件 | 状态 |
| --- | --- |
| 现有静态图类型能定位实际绘图输入 | 服务端物化路径（chart-input/v1）已全程登记：身份链 entry→submit 重验→durable→AnalysisChart→归档→ChartTraceV1；转换规则以独立答案验证 |
| 直接数据图与分析结果图两条链路 | 直接数据图（chart-input→CSV 溯源）与引用 facts 的物化图均可定位；分析结果图到 ComputationRecord 的深链随 B4 |
| 未受控旧图显示来源不足，不伪造绘图数据 | plotDataFiles 空的图不构造 trace、读取层如实降级 ✓ |

## B3 剩余（随 B5/G9 闭环）

1. **多系列/多面板映射**：ChartSeriesV1 从 chart-input 内容自动提取进 ChartTraceV1（当前 transformNotes 为固定说明）。
2. **真实跑批验证**：完整工作流真实报告的图表来源端到端（当前单测/集成级）。
3. **前端入口**：图下"查看图表来源"（B5 Editor 交互批次）。

## 设计决定（如实记录）

- chart-input 归档文件不进交付 manifest（非渲染产物，`_accepted_artifacts_match_manifest` 的图片白名单不破坏），只进追溯索引——权威 manifest 的 `traceIndex` 字段是唯一登记入口。
- ChartTraceV1 的 datasetIds 来自 chart.citation_ids → citation_bindings 映射；无可映射数据集或无作图数据的图不构造 trace（不伪造，计划 G3"来源不足不伪造绘图数据"）。
- 缺值语义与 B0 边界 fixtures 一致：Top 内缺值如实保留，合并组缺值按 0 计入合计。
- transform_notes 第一版为固定说明；dataPath 级转换说明随多系列映射增量补。
