# 幻灯片格式刷来源与边界

参考 GenOffice 提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`（Apache-2.0），本地来源 `/home/junge/pros/genoffice-source-full`。许可证沿用 `vendor/genoffice/LICENSE`；本模块没有复制来源的正文重建逻辑。

- `format-brush.ts` 54–100 行的捕获、119–135 行的字段交集和 144–200 行的应用逻辑用于行为参考。该来源文件 SHA-256：`26d2e950ec040d0ec63d267b6f91639599ee4e7c1b43b888bf81b53926557a02`。
- `clipboard-actions.ts` 299–359 行与 `RibbonHomeTab.tsx` 354–357 行定义单次/连续模式及单击/双击入口；`App.tsx` 1660–1667 行保留来源选择；`keyboard-actions.ts` 235–239 行以 Esc 退出。模式、生命周期和历史提交由 `slides-main.ts` 集成负责。

## 本地实现

`slides-format-brush.ts` 是纯捕获/应用规划器。`captureSlidesBrush` 结合后端明确摘要与当前草稿，`planSlidesBrushApply` 返回完整候选草稿、是否变化及原因；调用方仅在变化时提交一次历史。返回类型 `T & BrushDraft` 保留调用方扩展字段并公开新增格式补丁。它复用 `slides-paragraph.ts` 的段落投影与统一值判断，按当前待提交正文决定是否能应用文字格式。

后端 `reporting/slides_engine/bridge/pptx-brush-source.ts` 仅读取已解析对象，对所有非空文字 run 逐字段确认统一值。只暴露可明确表示的字号、字体、六位 RGB、粗体、斜体、简单下划线、段落对齐、简单填充与实线描边；不把解析器的默认黑色、隐式字体/字号/布尔值、缺省下划线当作明确来源。字体不读取显示用途的 `fontFamily`，仅当全部非空 run 的原始 `latinFont`、`eaFont`、`csFont` 三槽为同一个非主题实际字体且跨 run 一致时，才允许折叠为可回写的单字段字体；Latin-only、混合文字体系和缺省继承均省略。允许引擎生成的标准 creationId 扩展；未知扩展、域、超链接和复杂内容保守拒绝。

与来源相比，本实现不采用首 run 作为混合样式代表，不重建正文，不复制图片描边，不涉及几何、列表、间距、阴影、动画等属性。已删除对象/页面及本页待提交组合操作拒绝处理；文本、段落和形状补丁上限采用现有 500 项限制，超限整体不提交。所有未涉及的草稿字段保留。

验证见 `slides-format-brush.test.ts` 与 `reporting/slides_engine/bridge/tests/pptx-brush-source.test.ts`，覆盖明确 false、混合格式、pending 覆盖、空正文、原子合并、限制拒绝、来源隐式值、标准 identity 扩展和真实 PPTX 保存再读。
