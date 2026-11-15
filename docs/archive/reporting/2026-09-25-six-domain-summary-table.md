# 2026-09-25 六域真实 CLI 验证 · 汇总表

串行 6 跑，60 分钟/跑上限，模型 deepseek-v4-flash-0731。**总结果：5/6 通过（83%），topic5 超时。**
总跨度 16:59:34 → 20:27:07（3h27m）。详见 `docs/2026-09-25-six-domain-cli-verification.md`。

| # | 主题 | 耗时 | 结局 | PDF | 代码生成 | no_output_write | declared_missing | exec_failed | edit_invalid | generic_helper | rounds_exhausted | binding_autocorr | source_invalid | reasoningTokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 门诊/住院服务量与均次费用 | 33m43s | ✅ exit 0 | 11 页 | 7 | 10 | 11 | 0 | 8 | 3 | 3 | 0 | 0 | 122k |
| 2 | 药品/卫生材料收入结构 | 50m09s | ✅ exit 0 | 11 页 | 10 | 16 | 28 | 0 | 15 | 5 | 3 | 1 | 0 | 239k |
| 3 | 临床科室绩效对比 | 18m59s | ✅ exit 0 | 9 页 | 6 | 0 | 0 | 0 | 3 | 0 | 3 | 4 | 0 | 47k |
| 4 | 各院区收入分布 | 25m11s | ✅ exit 0 | 9 页 | 5 | 0 | 0 | 0 | 13 | 0 | 0 | 7 | 0 | 104k |
| 5 | **异常波动诊断** | **59m29s** | ❌ **timeout** | 无 | 6+1在飞 | 7 | 34 | **36** | 2 | 6 | 3 | 2 | 2 | 296k |
| 6 | 门诊/住院结算结构 | 18m32s | ✅ exit 0 | 15 页 | 6 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 50k |

**口径说明**

- `rounds_exhausted`：视觉收敛闸门按设计降级（连续 3 轮软告警放行），非失败。
- `source_invalid`：语法护栏触发次数，6 跑仅 topic5 有 2 次。
- topic5 的 exec_failed 拒收细分：`mode_execution_failed=36`、`declared_output_missing=34`、`no_output_write=4`、`edit_not_found=4`、`generic_data_helper=4`、`source_path_invalid=2`、`edit_unchanged=2`、`edit_invalid=2`。
- 代码版本：topic1–5 跑 pre-PR#3（1591f18），topic6 跑 post-PR#3（17ae770，PR#3 于当日 19:57 合入）——topic6 结果含主题难度混杂因素。
- 通过跑中位耗时 25m11s（区间 18m32s–50m09s）。
