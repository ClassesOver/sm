# 标准可视化

章节作图在授权 chart-input 物化后优先预检标准静态模板；整组均支持才进入标准路径，任一图不支持则整组走原 Coding 路线。失败日志为 `report_standard_visualization_fallback`，成功日志为 `report_standard_visualization_completed`。

支持 visualForm 为 line/折线图/多系列折线图、bar/柱状图/分组柱状图、barh/横向条形图、stacked-bar/堆叠柱状图、stacked-area/堆叠面积图。每图绑定一个已校验来源，最多60个标签、8个系列、480行。

输入支持 period 或 label 标签列加一个或多个数值列，以及 period×分类×value 长表。宽表多系列要求各列显式登记相同单位和比例尺度；趋势和堆叠图还要求列期间元数据一致。分组对比允许本期/基期分别保留各列冻结期间。长表重复期间/分类组合拒绝；缺少组合仅折线允许并展示断点，其余图不填零。堆叠图拒绝负值。非有限值、混合单位、复杂双轴、多来源拼接及其他数据形状继续走 Coding。benchmark 路径保持原配置。

模板读入时再次核验 chart-input SHA256，沿用原始行序和数值，不聚合、不裁剪、不填零。仅输出 Matplotlib PNG/JPEG。模板执行复用 ReportingCodeModeToolkit 的写入、执行、独立视觉审查、提交与当前回执重验；看图仍可能调用视觉模型，不能宣称零模型或线上提速已验证。

显示层从冻结 columnMeta 读取坐标单位；unit=% 且 isPercent=false 时将小数按百分数显示。最新增强的作图、投影与工作流242项回归通过，实际断点及百分比柱高有数值断言。新增复杂模板真实执行覆盖宽表/长表的五类图形。

## 冻结产物覆盖回放

2026-10-28 使用用户上传 revision-2 产物包的9张图、11份chart-input离线回放。图表身份按trace-index登记的size/SHA256核验，不修改原始文件。新增唯一文本标签识别及 `standardValueFields` 显式数值列选择；选择必须是绑定表内现有数值列，未选择时仍核验全部数值列，不静默丢弃混合单位辅助列。

同一输入、相同回放候选枚举下，优化前1/9图可覆盖，优化后6/9可覆盖；命中候选均实际生成PNG。剩余两张为多来源绑定、一张为无标签单行预算总览。该包未保存原可视化计划，因此这是离线模板候选覆盖率，不能当作原始在线路由命中率、整体报告数值正确率或模型性能结论。245项作图/投影/工作流回归通过。

可复现入口：`PYTHONPATH=. python scripts/replay_standard_visualization.py ARCHIVE --output OUTPUT`。Python 3.14以下读取zstd ZIP需要zstandard。报告保存在OUTPUT/replay.json，包含逐图覆盖、明确列选择、输入摘要与实际PNG路径；不向线上发送请求。

PR146 审查定向回归168项通过；标准出图及工作流218项通过，另补5项执行门禁测试；发布非阻断契约86项通过。实际模板执行验证三种PNG输出及输入篡改拒绝。三个运行时模块mypy、Ruff和diff检查通过。尚未进行生产模型端到端报告验收。
