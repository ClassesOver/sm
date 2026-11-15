# 原生 PPTX AI 表格与图表验收记录

日期：2026-11-11。

本轮已有表格单元格文字、已有安全图表数据与类型的 AI 候选链已通过定向前端测试、两项真实 provider 服务探针及两条冻结生产资产浏览器验收。完整类型检查及构建体积门禁仍有失败，不能称全部检查通过。

## 授权与产品范围

- 当前对象范围使用编辑器真实 `selectedObjects`，支持明确多选；没有选中对象时不回退首个对象、当前页或整稿。当前页和整稿只收集实际支持的对象。
- 表格从引擎 `tableCells: (string | null)[][]` 读取真实内容；仅字符串格可写，合并占位 `null` 不视为可写格。本轮只支持已有表格单格文字，不包括结构、样式及合并拆分。
- 图表必须有 `chartEditSafe === true`，使用实际 `chartKind`、`chartCategories`、`chartSeries`。候选采用原生 `chartEdits`，不把不可安全编辑的外部来源图表伪装为支持。
- 预览前值来自当前完整草稿的 `tableCells` / `chartEdits` 投影。相关表格结构、对象组合、版式、重置版式或页面尺寸变化时要求先保存，避免使用旧投影。
- 候选预览以中文显示表格页号、名称、行列与原值 → 新值，以及图表类型、类别、序列的差异。现有预览、明确采纳、草稿、撤销和保存链复用；生成候选不等于保存。
- 图片、母版、动画不在本轮 AI 修改范围；现有文字和布局能力保留。未新增 Plotly 或交互图代码。

## 前端定向验证

本轮已执行且通过，不在文档复核阶段重复运行：

- `slides-native-ai.test.ts`：9 项，包括表格/图表中文差异、Lucide SVG、明确采纳、取消及草稿冲突。
- `slides-native-ai-context.test.ts`：4 项，包括真实选区、未选不扩大授权、安全能力、当前草稿投影及结构变化拒绝。

合计 13 项通过；root 另完成 `slideSize` 防双缩放窄回归 1 项通过。最终 scoped Ruff（含 reporting/tests 路径）通过。产品代码本轮文档阶段未修改。

## 真实 provider：完整原生服务链

模型：`deepseek-v4.1-flash`，使用现有生产 `production_model` 工厂。两项各首次调用，无失败后重试。总耗时 17.08 秒；表格 9.15 秒、图表 7.18 秒。

实际链路：`create_native_slides_ai_service(model, RealEditor)` → `start_edit` → 真实 Agno `get_presentation_context` / `read_slide` / `propose_operations` → 引擎 `patch_office` 与 `inspect_office` 预览 → `accept_edit` → 实际候选 PPTX → python-pptx 独立回读。RealEditor 使用实际文件和引擎预览；未连接生产文档库或修改生产文档。

| 用例 | 实际文件结果 | 范围与只读保证 |
| --- | --- | --- |
| 选中 2×2 表格 | 零基 `(1,1)` 收入金额 `42` → `84`；其余三格不变 | 未选图表仍为收入 42、费用 17；未选文字保留 |
| 选中安全图表 | 收入 42 → 84、费用保持 17；类别“收入/费用”、系列“本期”、图表类型保留 | 未选表格金额仍为 42；未选文字保留 |

两项真实工具调用全部成功，工具回执 `requiresAcceptance: true`；秘密文字未进入实际 `read_slide` 返回内容，实际文件中仍保留。候选仅包含对应授权对象操作；原件 SHA 不变。

证据：

- `/tmp/pptx-ai-objects-real-provider-20261111.py`
- `/tmp/pptx-ai-objects-real-provider-20261111.json`
- `/tmp/pptx-ai-objects-real-provider-20261111.log`
- `/tmp/pptx-ai-objects-real-provider-20261111.independent-readback.json`

文档阶段重新从保存文件计算 SHA 并用 python-pptx 回读，10 项独立断言均通过；没有重新调用模型或重跑测试。

| 已保存文件 | SHA-256 |
| --- | --- |
| `pptx-ai-objects-real-provider-20261111.source.pptx` | `c10dd64a2436860a612b80ebee66435e19696e018b993c7a1d08bf9be410dc0f` |
| `pptx-ai-objects-real-provider-20261111.table.candidate.pptx` | `8ba0dc85c4a10f0f62069a1716cec37fdb9f3e49edc0290abd5d9dac03c2f467` |
| `pptx-ai-objects-real-provider-20261111.chart.candidate.pptx` | `374af3140da3c2cdc4f75e92681358a6a541a9be8be2b0ab61c73a26eb558507` |

三份文件均在 `/tmp/`，摘要与首次 provider 证据一致。

## 冻结生产资产浏览器验收

最终证据：`/tmp/pptx-ai-objects-20261111-verified/summary.json`。Chromium `140.0.7339.16`；表格、图表两条链通过，真实 DOM 选中对象后生成、中文预览、明确采纳到本地草稿。root 已独立核验源/候选摘要及实际表格、图表结果，并目视图表候选截图。

- 实际加载的 113 份 JS 资产 SHA 已核验。
- 冻结 manifest SHA-256：`906221925dfc66230da119e975cf4b58d2f99c3d7ee4c4c32ed617b6709bcc90`。
- 页面异常、控制台错误及 HTTP 错误均为 `[]`。
- 首轮浏览器脚本因预期正则的空格与实际中文文案不符而失败；修正验收脚本后复验通过，期间产品代码未修改。首轮不作为产品通过证据，最终证据目录与其分开保存。

浏览器验收与真实 provider 探针为两组证据；不将浏览器本地验收冒称额外真实 provider 调用。

## 尚未通过与剩余范围

- 当前完整类型检查失败位置涉及 `slides-clipboard-link-main.test` 和 `workbook-main` 的其他改动；本轮未据此宣称完整类型检查通过。
- 最终生产构建已成功，但冻结构建的体积门禁有三项失败，未提高上限：`docx-render` 764.8 KiB > 710 KiB、`xlsx-engine` 443.1 KiB > 428 KiB、`workbook-main` 266.1 KiB > 253 KiB。
- 本轮新增能力验证聚焦已有表格文字与安全图表数据；没有声称支持所有 PPTX 外部图表来源、表格结构、图片、母版或动画 AI 修改。
- 未重复运行完整测试；本文档阶段仅复核已保存产物与证据。
