# 冻结事实的 pr80 兼容读取与回滚演练

适用目标为 `pr80@743b7100` 的严格事实模型。本工具提供**只读事实适配和独立探针**，不表示旧服务已接入、不支持恢复新版工作流、不复用语义证明，也不授权切换部署。

## 已实现的读取边界

`smart_reporting/reporting/compat/fact_reader.py` 仅依赖标准库和 Pydantic，可单独复制到旧运行环境。它接收旧环境自己的 `DeterministicMetricFact` 和 `DeterministicAnalysisBundle`，以 Pydantic `create_model` 构造独立适配类型，不修改原类型。只补充已知的四个兼容点：

- `periodAggregation` 接受 `sum`、`last` 或空值。
- `seriesMissingCount` 接受非负整数或空值。
- `groupPopulation` 使用旧模型的严格结构化分组类型，最多 2000 组或空值。
- `cumulativePolicy` 可省略或为空；非空时仅接受版本 `1`、`reset=calendar_year_zero`、`observation=closed_month_end`、`changes=signed_snapshot_delta` 的严格声明。后三项必须显式提供，不能据此推断原始数据已通过累计语义验证。

旧模型的字段约束、别名、数组预算和 `extra=forbid` 继续执行；未知字段、未知期间枚举、未来文件版本、重复事实 ID、重复 JSON 键及非有限数值均拒绝。读取上限为 64 MiB，失败只表示该事实不能由此读取层使用。

调用者必须从已授权并已核验的索引／manifest 提供原文件 SHA256 和字节数，不能把文件自身的声明作为信任根。适配器不写文件、不重铸事实 ID、不删字段、不重序列化成替代快照；`raw` 是原始字节，`document` 每次返回独立视图。省略的历史字段保持省略，历史空期间语义不升级为可加。

读取结果固定为 `semanticStatus=unknown`、`semanticSupportReused=false`、`workflowResumeSupported=false`。适配成功只说明原始事实可按已知 schema 读取；新版质量文件、断言结果、渲染回执、编辑事务、索引和 CAS 检查点都不在这个适配范围内。

非空累计声明会登记 `requiredFeatures` 中的 `cumulative_snapshot_policy`；未知重置方式、未知变动语义、未来版本或额外策略字段仍拒绝。省略或空值不增加所需特性，也不向模型序列化结果补写空策略；经核验的原始文件继续保留其原有省略／空值形式。

## 在旧环境执行只读探针

先从经过审核的候选发布包取得 `fact_reader.py`，保留独立路径。在旧服务的 Python 环境执行，例如：

```bash
PYTHONPATH=/path/to/pr80 /path/to/pr80/.venv/bin/python /path/to/approved/fact_reader.py \
  --legacy-module smart_reporting.reporting.hospital_operation.deterministic_analysis \
  --fact-file /path/to/frozen-facts.json \
  --expected-sha256 "$REGISTERED_FACT_SHA256" \
  --expected-size "$REGISTERED_FACT_SIZE"
```

两个 `REGISTERED_` 参数必须来自授权登记，不能现场以待检文件自算的值替代。模块参数应指向旧环境已安装的可信模型模块。探针只输出兼容状态、原文件哈希及所需特性，不输出源数据单元格内容。

退出码 0 表示本文件可兼容读取；退出码 1 表示无法核验身份、模型不是已支持目标、文件损坏或 schema 不兼容。两种结果都返回 `rollbackReady=false`。不要将探针接入 PDF/Word 下载门禁，不要将适配类型全局替换到旧工作流生成或证明执行器。

## 接入与跨部署演练的剩余步骤

1. 为旧版本的只读事实查看接口显式接入 `read_compatible_snapshot`；保留原授权、资源 ID 解析和 manifest 身份校验。未知的新断言不能通过旧校验器获得绿标。
2. 按运行／修订所属版本隔离路由。新版检查点、质量文件、渲染回执及编辑事务继续交给支持这些协议的 worker；本适配器不能迁移或恢复它们。缺版本路由证据时，不让旧 worker 接管新版运行。
3. 在隔离的实际旧／新服务部署中演练历史报告和新版报告的打开、当前校验、编辑、导出、下载及工作流恢复。只读适配不能替代这些端到端场景。
4. 核对原始文件、登记哈希、事实 ID 和期间语义未改；新语义未知时不显示通过。对已生成且身份可读取的 PDF/Word 保留下载，来源不可用只降级对应证据。
5. 保存实际部署版本、路由配置、逐场景结果及回切证据，再评估是否允许切换。当前仓库的模型子进程测试不满足这一部署验收。

## 本地验证证据

`test_fact_reader_compatibility.py` 使用从 pr80 原文件 AST 固定的模型声明，记录原文件 SHA256；不借用当前事实类来模拟旧模型。独立子进程只复制这些旧声明和适配器，验证新旧事实读取、身份保留及数据不泄露。

本地回归覆盖原旧 reader 拒绝新字段、适配后仍拒绝未知字段、原始字节及 ID 不变、历史缺失语义不升级、消费者修改视图不改变证据、模型字符串数值转换后的 NaN/Infinity，以及新版引擎继续读取原证据。累计策略另外覆盖严格字段校验、空值不补写、所需特性登记及独立旧模型子进程读取；读取成功仍不复用该策略的业务证明。以上是代码和模型隔离测试，未部署旧服务或执行真实业务回切。
