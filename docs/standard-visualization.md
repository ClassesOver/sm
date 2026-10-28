# 标准可视化

章节作图在授权 chart-input 物化后优先预检标准静态模板；整组均支持才进入标准路径，任一图不支持则整组走原 Coding 路线。失败日志为 `report_standard_visualization_fallback`，成功日志为 `report_standard_visualization_completed`。

支持 visualForm 为 line/折线图、bar/柱状图、barh/横向条形图。每图只能绑定一个已校验来源，列必须恰为 period/value 或 label/value；最多60行，标签唯一，数值有限且无缺失。复杂比较、多系列、单位混合和其他数据形状继续走 Coding。benchmark 路径保持原配置。

模板读入时再次核验 chart-input SHA256，沿用原始行序和数值，不聚合、不裁剪、不填零。仅输出 Matplotlib PNG/JPEG。模板执行复用 ReportingCodeModeToolkit 的写入、执行、独立视觉审查、提交与当前回执重验；看图仍可能调用视觉模型，不能宣称零模型或线上提速已验证。

PR146 审查定向回归168项通过；标准出图及工作流218项通过，另补5项执行门禁测试；发布非阻断契约86项通过。实际模板执行验证三种PNG输出及输入篡改拒绝。三个运行时模块mypy、Ruff和diff检查通过。尚未进行生产模型端到端报告验收。
