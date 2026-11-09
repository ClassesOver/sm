# 标准图诊断关联冻结输入身份

研究 PR #197 建议把单位、期间和来源文件身份保留在同一证据中。本补丁从 `28649e9c56b1aa7e96f0c363e8eec8accd0175b7` 独立建立，不包含 PR #198 的编译优化。

## 实际缺口与补丁

`standard_plan_diagnostics` 原先只返回 `sourceIndex/source/columns/columnMeta`。同列名来源遇到缺单位或期间错配时，诊断虽有错误码和来源索引，却没有冻结输入的文件身份，无法仅凭该诊断核对输入版本。

现在每个通过既有路径/SHA 核验且解析为 JSON 对象的来源附带 `inputFile: {path, size, sha256}`。大小从实际字节计算，摘要从宿主读取的内容计算，不读取 JSON 内自称的身份，不复制可能过时的登记 size。索引继续按绑定 entries 的顺序生成，不依赖 files 的枚举顺序。

原诊断码、元数据、bindingCorrectionAllowed 和规划纠错规则维持原行为。缺失文件、SHA 不匹配、坏 JSON 和非对象 JSON 不作为可信来源附在诊断中。这仅补足标准图规划纠错诊断的身份线索，不能当作业务语义正确、完整派生链归档或发布验收通过。

## 验证

- 新增缺单位、期间错配两个案例，在旧实现因缺失 `inputFile` 失败，补丁后通过；同时检查同列名/文件顺序打乱、错误登记大小、JSON 自述伪造身份和保留期间元数据。
- 负例覆盖缺失文件、旧 SHA、坏 JSON、非对象 JSON；可信来源列表保持为空。
- 定向回归 `81 passed`，仅有既有 `imghdr` 弃用警告；Ruff 与 `git diff --check` 通过。

```bash
python -m pytest -q \
  smart_reporting/reporting/tests/test_visualization_route_repairs.py \
  smart_reporting/reporting/tests/test_standard_chart_contract.py \
  smart_reporting/reporting/tests/test_standard_visualization_diagnostics.py \
  smart_reporting/reporting/tests/test_publication_nonblocking.py
```

Python 使用项目已有虚拟环境。没有运行全套测试、调用真实模型或访问真实业务数据。本补丁未修改发布/签发链路，不新增其故障步骤；也不实现中文布局检测、分页 revision 失效或四格式联动。不报告速度、命中率或正确率提升。
# 与先行 PR 的集成核对

#195 收紧了文件自动修正规则：已登记文件不得自动改指另一业务文件，未知文件才允许同分析下的唯一精确路径修正。原有绑定测试据此扩展为已登记/未知文件、同分析/跨分析、完整/子集字段八组对照，保留精确表索引与字段断言，没有放宽生产规则。集成后的来源诊断、绑定和 P1 语义回归共 52 项通过；独立复核确认与 #195 契约一致。
