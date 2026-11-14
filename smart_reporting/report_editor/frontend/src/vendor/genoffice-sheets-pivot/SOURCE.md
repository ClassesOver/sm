# 固定源数据透视字段窗格

来源：GenOffice，固定提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

原始路径：

- `apps/sheets/src/renderer/PivotFieldPane.tsx`
- `apps/sheets/src/renderer/pivot-field-model.ts`
- `packages/xlsx-gateway/src/domain/pivot-value-modes.ts`
- `calendar-date-pattern.ts` 摘取 `apps/sheets/src/renderer/numfmt-fix.ts` 的日期格式识别闭包；默认归区遵循 `apps/sheets/src/renderer/pivot-actions.ts` 的 `columnIsNumeric`（数值文本与日历日期归入行）。
- 中文词条：`apps/sheets/src/renderer/i18n/dialogs/zh.ts`
- 宿主 CSS `../../workbook-pivot-pane.css` 源自 `apps/sheets/src/renderer/styles.css` 的透视窗格样式。

本地适配：模块路径复用现有 Dropdown 与模态焦点 hook；中文词条只保留组件使用项；保留数字格式及报告筛选多选元数据；pointercancel 取消拖动，菜单 Escape 返回触发按钮焦点。2026-11-14 已补齐固定源全部十一种聚合；普通值与十四种 ShowAs 及基字段／基项已支持，外部缓存投影／旧格式继承的明确限制见最新专项，自定义值标题已在后续专项贯通保存／导入／刷新。真实源窗格内容由 `../../workbook-pivot-pane.tsx` 接入既有来源/目标模态框，计算和文件写入仍委托现有引擎。

许可证与版权声明复用同一固定源已有的 [Apache-2.0 LICENSE](../genoffice-sheets-format/LICENSE) 和 [NOTICE](../genoffice-sheets-format/NOTICE)。

2026-11-14 六种额外聚合的完整计算／保存／导入／刷新路径及浏览器下载证据见 [专项验收](../../../../NATIVE_XLSX_PIVOT_AGGREGATIONS_ACCEPTANCE_20261114.md)。Pane 当前身份登记于 `LOCAL-ADAPTATIONS-SHA256.json`；原始来源提交与许可保持不变。

2026-11-14 [自定义值标题专项](../../../../NATIVE_XLSX_PIVOT_CAPTIONS_ACCEPTANCE_20261114.md)启用原输入框，补宿主配置／布局／写入／读取的 name 传递；ShowAs 剩余选项仍禁用。Pane 当前哈希已更新，前一聚合专项的冻结 artifact 绑定保留其当时字节身份。

2026-11-14 [父级百分比／指数专项](../../../../NATIVE_XLSX_PIVOT_PARENT_INDEX_ACCEPTANCE_20261114.md)启用 percentOfParentRow/Col、index，保留其余八种基字段模式禁用。父级百分比保存采用微软文档的 x14 扩展，未照搬固定源非法 core enum 写法。

2026-11-14 后续 [基字段／基项专项](../../../../NATIVE_XLSX_PIVOT_BASE_MODES_ACCEPTANCE_20261114.md)补齐剩余八种模式和参数映射，全部十五个显示选项（含普通值）可用。宿主保留外部成员显示顺序，分组基项选择使用 typed groupValue 和文件日期纪元；显式 General 输出 id0。原始源边界、raw foreign d/e cache 与未指定格式的限制仍明确保留，前面批次的“禁用”描述只代表当时状态。
