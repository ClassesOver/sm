# 新版原生报告选项验收

2026-10-23：适配 dingyi-agno 0.5.5 与 Console 提交 `b009d31` 的类型化输入和表单样式。

报告工具使用 `prepare_user_input_tools`，由 `Annotated` / `Field` 声明中文标题、日期和选项，沿用 Console 原生表单。Console 的 `frontend/src/shared/chat/renderer.tsx` 仅将续跑表单标题 `report_workflow_start` 显示为“确认报告需求”，不改变工具身份或续跑协议。Agno Toolkit 绑定方法时会移除 `Annotated` 元数据，业务工具注册后恢复原始注解再交给 SDK。

上下文提取由模型填入工具参数；Agno 在暂停前预填，用户确认后启动工作流。确认值通过 `requestOptions` 传递，期间与指标覆盖规划器输出，篇幅和维度写入后续规划目标。原始消息保存在当前 run 绑定的状态中，供暂停续跑读取。

## 复跑

先在 Console frontend 目录启动 `npm run dev`，再在本项目根目录执行（端口按实际服务调整）：

```bash
.venv/bin/python scripts/check_report_options_console_e2e.py --frontend http://127.0.0.1:5174
```

脚本默认使用 `~/pros/agno-admin-console` 的 gateway 与前端，以及本项目安装的正式 SDK。结果位于 `/tmp/report-options-console-055/`，包含 `report.json`、`01-desktop.png` 和 `02-mobile.png`。

已验证表单标题为“确认报告需求”且不暴露工具名、日期和中文多选预填、确认前不启动、移动端无横向溢出、编辑值经过新版 gateway 与 Agno 续跑后保留。报告选项、请求归一化、审核契约共 31 项定向测试通过；前端类型检查、Ruff、锁文件检查通过。

浏览器使用固定模型响应及报告生成边界夹具，实际运行 Console Renderer、SDK 协议和 Agno 暂停续跑。不覆盖真实模型上下文抽取准确率、Console 登录与完整 API 路由或 PDF/Word 导出。
