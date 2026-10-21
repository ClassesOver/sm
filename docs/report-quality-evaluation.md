# 报告质量离线评估与回滚核查

此工具整理已存在的真实评估证据，不调用模型、不获取线上数据、不联系审核人员，不影响报告下载或发布。它不证明人工记录真实，也不签发上线许可。当前仓库没有 12 个真实试点任务和 30 个真实独立保留任务的完整证据，真实效果评估尚未执行。

## 可执行入口

在仓库根目录运行：

```sh
MPLCONFIGDIR=/tmp/report-quality-matplotlib .venv/bin/python -m scripts.evaluate_reporting_quality validate /path/to/study.json --output /path/to/plan-validation.json
MPLCONFIGDIR=/tmp/report-quality-matplotlib .venv/bin/python -m scripts.evaluate_reporting_quality evaluate /path/to/study.json --output /path/to/evaluation.json
```

`validate` 只检查方案、分区、样本及配置文件身份；`plan_validated` 不表示报告或审核已经执行。`evaluate` 校验实际报告、双审及计量证据，按任务成对计算基线/候选结果。缺少证据返回 `not_ready`、`acceptanceMet=null` 和具体 issues，退出码 2；证据完整但未达到冻结阈值也退出 2。结构无效返回 `invalid`。完整评估且阈值满足才退出 0，但所有结果的 `rolloutAuthorized` 始终为 false。

`--output` 不得覆盖 study.json 或任何登记的配置、样本、授权、报告、计量、审核及裁决文件；指向这些文件的符号链接和硬链接同样拒绝。

保留原有引用闭环验证入口 `scripts/check_reference_review.py`：其 JUnit 实际执行数、退出码、失败和跳过检查仍用于工程回归。工程回归不代替这里的真实业务评估。

## 收集和冻结

1. 在观察结果前登记 `StudyPlan` 并保存其规范 JSON SHA256；建议将其登记到外部受控审计记录。方案包含两个不同的方案身份、各自配置文件身份（代码版本、模型、提示、规则、运行模式和工具版本）、作者、领域审核人员、验收阈值及全部任务。后续报告审核和计量记录都绑定这个 `planSha256`，修改阈值或分区会使已有记录失配。
2. `tasks` 中至少登记 12 个 pilot 和 30 个 holdout，且各自至少有对应数量的独立 `independenceGroup`。试点与保留集不得共用任务族或相同输入内容哈希。每项输入包括冻结请求/问题、输入数据和业务真值材料；相同公共配置应放在方案配置中，不作为任务独立输入。覆盖领域和代表性仍需业务人员判断，不能靠任意改写 group ID 建立独立性。
3. 真实任务声明 `sampleKind=real`，提供授权凭据文件身份；合成任务可以用于调试，但永远不能建立真实评估就绪。授权凭据的内容、适用范围和实际授权有效性由外部责任人确认，工具只验证文件未被替换。
4. 对每个任务分别执行 baseline 和 candidate，保存最终报告与原始 provider 计量导出。报告分别登记完整 `claimIds`；任务预先登记全部 `requiredConditionIds`。计量 JSON 中的费用、耗时和 token 数来自真实提供方导出，并绑定方案/报告哈希。工具不会将模型估计的费用或合成计量当成真实成本。
5. 对每份报告收集两位不同领域人员的独立盲审；审核人员不能出现在 `authorIds`。将原始签名或认证导出文件保存在外部审核系统，向本工具导入规范记录。两位审核分别确认主张清单完整、未获支持的主张 ID、已完成的条件 ID、严重错误数量及对方案身份盲态。记录使用不同 `blindReviewId`（审核记录身份，不是方案名称）。两份结论不同则必须由第三位领域人员裁决；未裁决保持 not_ready。
6. 保留集只在试点修复完成并冻结候选版本后执行。不得查看保留结果后调阈值、改候选配置或替换任务再沿用原方案哈希；需要重新登记独立保留集。工具可以发现哈希不一致，不能检测未被记录的泄漏、伪造身份或事后“首次登记”。这些必须由外部评估流程约束。

## JSON 契约

完整机器可读 schema：

```sh
MPLCONFIGDIR=/tmp/report-quality-matplotlib .venv/bin/python -c 'import json; from smart_reporting.reporting.workflow.quality_evaluation import StudyEvidence; print(json.dumps(StudyEvidence.model_json_schema(by_alias=True), ensure_ascii=False, indent=2))' > /tmp/report-quality-study.schema.json
```

顶层字段为 `plan` 和 `runs`。所有文件复用 `BenchmarkFileIdentity` 的 `path/size/sha256` 契约，路径相对于 study.json 所在目录。路径必须安全且位于评估目录内；越界路径、指向目录外的符号链接、内容改变及单文件超过 64 MiB 都不用于评估。

`plan`：`version=1`、`studyId`、`baseline`、`candidate`、`baselineConfiguration`、`candidateConfiguration`、`authorIds`、`domainReviewerIds`、`tasks`、`thresholds`。阈值明确填写 `maximumUnsupportedRate`、`minimumAnswerCoverage`、`maximumCriticalErrors`、`maximumCostRatio`，没有暗含“上线可接受”的默认阈值。

每个 task：`taskId`、`partition=pilot|holdout`、`sampleKind=real|synthetic`、`independenceGroup`、`inputs`、`authorization`、`requiredConditionIds`。

每个 run：`taskId`、`variant`（严格匹配 baseline/candidate）、`report`、`claimIds`、`metering`、`reviews`、可选 `adjudication`。每个计量文件是 `StudyMetering` JSON：`planSha256`、`reportSha256`、`taskId`、`variant`、`configurationSha256`、`provenance=provider_export`、`currency`、`totalCost`、`wallSeconds`、`inputTokens`、`outputTokens`。计量必须匹配当前任务、版本和对应配置内容哈希，不能因输出报告内容相同而复用另一任务或版本的费用记录。

每个审核/裁决文件是 `DomainReview` JSON：`planSha256`、`reportSha256`、`taskId`、`reviewerId`、`role=independent|adjudicator`、`blindReviewId`、`claimInventoryComplete`、`blindedToVariant`、`unsupportedClaimIds`、`answeredConditionIds`、`criticalErrorCount`。布尔声明必须是真布尔；主张和条件必须在对应冻结清单内，且不能重复。审核及裁决必须匹配当前任务，不能将针对另一任务背景的结论串用；审核记录不包含版本标签或配置哈希，保留对版本的盲态。工具只接受完整主张清单的审核，不把只审核部分段落算整份报告。

缺少新增任务/版本/配置绑定的历史计量和审核记录仍可解析，但不能建立验收证据；评估返回 `not_ready` 和 `run_evidence_incomplete`，不自动补填或升级旧记录。

## 结果如何解释

分别输出 pilot/holdout 的完整成对任务数、每方案任务平均未支持主张率、回答条件覆盖率、严重错误数、费用和耗时；不会把试点与保留集混合平均。不同计价币种不自动换汇，保持 not_ready。缺失一边的任务不计为改善，整个研究不能满足验收。

配对结果包括未支持率降低、回答覆盖增益的胜/负/平、平均变化及双侧精确符号检验 p 值。平局不进入符号检验分母。统计量用于评估人员理解配对结果，不证明因果，也不替代预登记的统计方案或领域结论。阈值验收使用完整保留集的任务平均率、严重错误总数和平均成本比；基线成本为零时成本比未知，不能自动通过。

均值使用十进制中间值计算，避免有限费用相加溢出后把成本比误算为零。均值或成本比无法有限表示、或正值下溢为零时保持 `not_ready`，不输出 Infinity/NaN 或标记验收通过。

即使所有阈值满足，也只能说这批外部证据的计算满足登记阈值，不能说消除了所有幻觉。必须另外完成独立审核签字、覆盖代表性判断、未发现的遗漏主张检查及部署审核。

## 历史兼容与回滚

当前版本能读取旧事实，但不能把缺省期间语义或缺失全序列计数升级为已知。`test_reporting_rollback_compatibility.py` 固定 pr80@743b7100 的字段清单和旧 `periodAggregation=last|null` 枚举，实际构造旧 reader 验证：新 `periodAggregation=sum` 或 `seriesMissingCount` 会被旧版严格模型拒绝。

该探针测试通过意味着**发现了直接回滚不兼容**，不是“回滚已成功”。不能通过删除新增字段、改 sum 为 null 或重铸 factId 掩盖该问题，这会破坏冻结事实及证明身份。

真正回滚前应先部署支持新旧 schema 的兼容 reader，或按运行版本隔离并路由到对应 reader，保留原文件及其哈希；演练新旧报告的打开、校验、编辑、导出、下载与恢复，验证新版文件不会被旧 worker 消费。当前没有声明这项跨部署演练已完成。

已提供可移植的 pr80 只读事实适配器和独立探针，接入与演练要求见 [冻结事实兼容读取](report-fact-reader-compatibility.md)。它保留原始身份并将语义保持 unknown，不接管新版检查点或质量协议；旧服务接入及真实跨部署演练仍未完成。
