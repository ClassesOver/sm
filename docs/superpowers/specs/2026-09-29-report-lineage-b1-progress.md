# Report Editor 数据追溯 B1 进度记录

日期：2026-09-30（更新）。状态：B1 实施与验证清单完成；G1 门禁待真实发布链路联调确认（见下）。

上游：`2026-09-29-report-editor-data-lineage-batched-implementation.md`（B1）、
`2026-09-29-report-lineage-b0-freeze.md`（契约基线）。

## 已完成

| 项 | 实现 | 测试 |
| --- | --- | --- |
| 物化时间（未决#1 关闭） | `DatasetHandle.materialized_at`（ISO8601 UTC；旧 state 无该字段兼容为 null），materialize/register 写入 | `test_report_data_sources.py` 回归 |
| CSV 预览/下载服务 | `reporting/trace/dataset_service.py`：polars lazy scan 分页（禁全文件入内存）、受控列选择、HMAC 签名游标（绑定 **report/revision** + dataset 身份 + sha + 列选择 + limit + TTL，计划 5.3 全项；重放/篡改/参数漂移/跨报告重放拒绝）、单元格 4KiB 截断、1MiB 响应预算（不足一页如实标记）、原始下载权限校验、文件名安全化 | `test_trace_dataset_service.py` 12 例 |
| 发布时 revision 索引 | `reporting/trace/index_builder.py` + `publication.py _write_trace_index`：finalize 时从已验收 handle+lineage 构建 `trace-index-v1.json`（与 manifest 同目录），manifest 新增可选 `traceIndex` 字段登记（`ArtifactFile` 媒体类型扩展 json/csv），checkpoint files 总账并入 | `test_trace_index_builder.py` 5 例 + workflow/artifact 回归 |
| Editor 恢复与 API | `report_editor/trace_sources.py` + service 委托：索引定位=markdownPath 同目录（旧报告无索引 → 200 available=false，不猜测）；read_asset 同模式身份复核（磁盘 size/sha256 不符 → `snapshot_integrity_failed`）；路由 `GET /api/sources`、`GET /api/datasets/{id}/preview`、`GET /api/datasets/{id}/download` | `test_report_editor_trace.py` 13 例（真实 Host workspace + 真实 HTTP） |
| 派生/脱敏导出（B1-7） | `report_editor/trace_exports.py`：`masked_columns` 注册策略（未登记策略 4xx 不进执行器）、polars lazy `sink_csv` 流式生成、后台任务+轮询（复用 export 模式）、并发上限 4、独立短保留期 24h（过期拒绝下载并清理）、任务归属按 report/revision 校验（跨报告查询 `source_missing` 不泄露）、派生文件名带 `-derived`、响应携带 `derived:true` + 独立 sha256；API `POST /datasets/{id}/exports`(202)、`GET /data-exports/{id}`、`GET /data-exports/{id}/download` | `test_report_editor_trace.py` 4 例（掩码正确+身份独立、策略/列反例、share 403、跨报告隔离） |
| 权限矩阵 | `ReportEditorSession.capabilities`（None=完整 editor 会话，向后兼容；`download_original`/`download_derived`/`blocked_columns`）；share 路由签发受限能力；错误码接入 `_editor_error_status`（B0 冻结映射 + `request_invalid`） | HTTP 集成覆盖 owner 全通过 + share 预览 200/下载 403/派生 403 |
| B1-8 验证清单 | 游标跨报告（report-1↔report-2 同名同内容）重放拒绝；双期间（current/yoy periodRoles）双数据集索引与预览；未登记数据集 `source_missing`（磁盘存在同名文件也不放行）；篡改快照 `snapshot_integrity_failed` | 同上 |

### 压测（B1-9，2026-09-30，本机，204 MiB / 330 万行 / 7 列合成 CSV）

| 场景 | 结果 | B0 门槛 |
| --- | --- | --- |
| 预览首页 50 行（完整链路） | p50=3ms | p95 ≤ 1s ✓ |
| 游标翻页 | p50=2ms | — |
| 受控列选择（2 列） | p50=2ms | — |
| 下钻式 group_by sum（20 组） | 0.23s | p95 ≤ 3s ✓ |

验证命令（2026-09-30）：trace/editor/data-sources/artifact/workflow 相关 14 个测试文件全部通过（合计 181 例）。

## G1 门禁自检（对照计划 B1）

| G1 条件 | 状态 |
| --- | --- |
| 授权对象可定位并预览/下载 | ✓（集成测试：索引恢复→身份复核→预览/下载） |
| 非法访问不能泄露内容 | ✓（越权列 403 不回显列名、跨报告/未登记 404 不泄露存在性、错误正文无路径） |
| 分页与资源边界满足固定预算 | ✓（预算常量锁定 + 4KiB/1MiB/50 列/100 行测试；204MiB 压测 p50=3ms） |
| 重启后索引与文件可恢复 | 部分：scope release/resolve 在集成测试模拟 ✓；**真实进程重启与 workspace 重新注册留 B9**（计划 B9 范围） |
| 派生导出身份区分 | ✓（独立 sha256、`derived:true`、文件名标注） |

## 剩余（不阻塞进入 B2，但 G9 前必须闭环）

1. 数据库 CSV（starrocks_materialized）真实端到端：当前索引/预览链路与来源类型无关（身份字段齐全），真实 StarRocks 物化联调随环境在 B2/B9 补。
2. 真实发布链路（managed workflow 全流程）生成索引的联调：单元/集成层已验证 finalize 接入点，全流程冒烟随 B2 事实层一并跑。
3. 真实进程重启恢复（B9）。

## 已知边界（如实记录）

- 预览游标签名密钥未持久化配置时按进程随机：重启后旧游标失效（客户端重拉首页，安全无害）；生产装配可在 `ReportEditorService(trace_cursor_secret=...)` 显式注入。游标绑定 report/revision + 数据集身份，同名同内容跨报告重放被拒绝（测试覆盖）。
- markdown 复制分支（markdown 不在 revision 目录的历史 job）不自动复制 trace-index；正常发布链路索引与正文同目录，不受影响。
- 派生导出任务为进程内状态：重启后任务丢失（文件保留至保留期后由下次清理删除）；跨进程任务队列不属 B1 范围。
