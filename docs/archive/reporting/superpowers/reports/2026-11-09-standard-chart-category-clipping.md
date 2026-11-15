# 中文分类标签画布裁切修复

本补丁独立基于 `28649e9c56b1aa7e96f0c363e8eec8accd0175b7`，延续研究 PR #197 的渲染后几何验证建议，不包含 PR #198/#199。

## 已复现的缺陷

`finish_standard_layout` 已检查图例、标注是否越画布，并检查分类标签是否互相重叠，但没有检查分类标签自身是否被画布裁掉。一个分类标签不会与其他标签重叠，仍可严重越界并保存为 PNG。

合成输入只有一个中文分类和数值 `-12 人次`。固定 `4×3` 英寸、150 DPI、manual 布局、默认边距、labelWrap=40、关闭数值标注。原实现正常保存 600×450 PNG，实际 Agg 文字边界如下（像素，x/y/width/height）：

| 形式 | 分类标签边界 | 结果 |
|---|---|---|
| bar | `[-17.95, -280.62, 335.95, 335.95]` | 左侧与底部被裁切，原实现无诊断 |
| barh | `[-400.67, 227.82, 456.00, 19.11]` | 大部分中文在画布左侧，原实现无诊断 |

旧 barh PNG 已人工查看确认文字裁切；这是开发者自查，不是独立视觉裁决。新测试中的同一输入可重现该缺陷。

## 最小生产补丁

在既有分类标签重叠检查后，使用最终 renderer 检查可见且非空标签的 bbox。仅当 `crop=canvas` 且标签超出画布时返回既有 `standard_chart_layout_unresolved` 诊断。auto 画布由原重试机制有界扩容；fixed 画布不被偷偷修改。`crop=tight` 保持允许导出边界扩大。

补丁不自动修复所有排版，不改写标签、数据、单位、顺序、期间或边距，不新增图种。几何成功不证明无缺字、文本相互遮挡或业务映射正确；两名盲法视觉审阅仍未完成。

## 验证

- TDD：bar/barh 两个裁切拒绝案例在旧实现均失败（未抛出布局诊断），补丁后通过。
- 两个 tight 正例实际导出 PNG，断言完整中文标签、负值和原输入不变，导出边界可扩大。
- 定向 `420 passed`，用时 111.99 秒。告警为第三方 `imghdr` 弃用及一个 Sankey 边界样例的 Matplotlib tight-layout 提示；没有测试失败。未运行全套。
- 独立只读代码审查未报告缺陷；Ruff 与 `git diff --check` 通过。

```bash
python -m pytest -q \
  smart_reporting/reporting/tests/test_standard_chart_category_clipping.py \
  smart_reporting/reporting/tests/test_standard_chart_presentation.py \
  smart_reporting/reporting/tests/test_standard_chart_domains.py \
  smart_reporting/reporting/tests/test_standard_chart_combinations.py \
  smart_reporting/reporting/tests/test_standard_chart_encoding.py \
  smart_reporting/reporting/tests/test_standard_chart_families.py \
  smart_reporting/reporting/tests/test_standard_chart_proof.py \
  smart_reporting/reporting/tests/test_standard_render_proof_signing.py \
  smart_reporting/reporting/tests/test_standard_chart_routing.py \
  smart_reporting/reporting/tests/test_standard_chart_direct_execution.py \
  smart_reporting/reporting/tests/test_publication_nonblocking.py
```

Python 使用项目已有虚拟环境。不访问真实业务数据、不调用真实模型、不启动生产服务。未修改发布或签发链路；已有布局诊断不能阻止签发身份可读取的 PDF/Word。没有引入新的签发步骤，也不将本补丁解释为分页修订或四格式联动已完成。
