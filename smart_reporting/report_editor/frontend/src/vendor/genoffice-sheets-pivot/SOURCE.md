# 固定源数据透视字段窗格

来源：GenOffice，固定提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

原始路径：

- `apps/sheets/src/renderer/PivotFieldPane.tsx`
- `apps/sheets/src/renderer/pivot-field-model.ts`
- `packages/xlsx-gateway/src/domain/pivot-value-modes.ts`
- `calendar-date-pattern.ts` 摘取 `apps/sheets/src/renderer/numfmt-fix.ts` 的日期格式识别闭包；默认归区遵循 `apps/sheets/src/renderer/pivot-actions.ts` 的 `columnIsNumeric`（数值文本与日历日期归入行）。
- 中文词条：`apps/sheets/src/renderer/i18n/dialogs/zh.ts`
- 宿主 CSS `../../workbook-pivot-pane.css` 源自 `apps/sheets/src/renderer/styles.css` 的透视窗格样式。

本地适配：模块路径复用现有 Dropdown 与模态焦点 hook；中文词条只保留组件使用项；保留数字格式及报告筛选多选元数据；pointercancel 取消拖动，菜单 Escape 返回触发按钮焦点。现有引擎只支持五种聚合及普通值/三种百分比，其余源选项禁用，自定义值标题禁用。真实源窗格内容由 `../../workbook-pivot-pane.tsx` 接入既有来源/目标模态框，计算和文件写入仍委托现有引擎。

许可证与版权声明复用同一固定源已有的 [Apache-2.0 LICENSE](../genoffice-sheets-format/LICENSE) 和 [NOTICE](../genoffice-sheets-format/NOTICE)。
