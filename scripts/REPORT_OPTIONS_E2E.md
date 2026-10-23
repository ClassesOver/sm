# 报告选项 Console 浏览器回归

验证日期：2026-10-23。

## 运行

先在 `~/pros/agno-admin-console/frontend` 启动 `npm run dev -- --host 127.0.0.1`，再在 smart_reporting 根目录执行：

```bash
.venv/bin/python scripts/check_report_options_console_e2e.py
```

可通过 `--console-root`、`--frontend`、`--port`、`--output` 指定环境。脚本会优先导入指定 Console 的本地 Python SDK。

## 已通过的场景

- 桌面：期间、收入及工作量、简要版、院区和科室已预填，确认前工作流启动次数为零。
- 修改结束日期、篇幅、指标和维度后，通过 Console 原生 continuation 映射和 Agno HITL 续跑；确认值覆盖规划器的冲突输出，且只启动一次。
- 移动端（390×844）：缺少期间时显示必填提示，不启动工作流；补齐后保留预算、默认简要版和空的可选维度，无横向溢出。
- 表单运行期间未出现浏览器异常。

结果和截图默认保存到 `/tmp/report-options-console-e2e/`：`report.json`、`01-prefilled-desktop.png`、`02-missing-period-mobile.png`。

## 测试边界

使用真实 Console Renderer、dingyi-agno 表单协议、Agno 暂停/续跑和报告请求归一化。模型响应与最终报告生成边界使用固定夹具；没有验证真实模型的上下文抽取准确率、完整 Console 登录/API 链路或 PDF/Word 导出。

本次同时通过报告请求相关 21 项、合并冲突处规划预算 3 项、SDK 表单 schema 2 项回归，以及 Console 前端 TypeScript 类型检查。额外执行的 Console 协议测试文件在输出 24 个通过后停滞并被中止，因此不计为整文件通过。

## 部署依赖

表单的日期 `format` 与数组枚举映射在 Console 仓库 `sdk/python/src/dingyi_agno/chat/protocol.py` 中（随本功能一起修改，PyPI 上的 dingyi-agno 0.5.4 尚无此能力，多选会退化为单选字符串导致提交校验失败）。Console 后端镜像按 `pip install --no-deps ./sdk/python` 从仓库源码安装 SDK，因此：

- 生产部署顺序的唯一硬要求是 Console 后端镜像（含协议改动）先于或同批于本后端上线；Console 前端已提交版本即支持 `items.enum` 多选渲染，未提交的改动仅为枚举值中文化；
- smart_reporting 运行时不调用 `tool_requirement_block`，仅发射 wire 字段，旧协议消费方忽略不崩；
- 发布 dingyi-agno 0.5.5（Console 仓库已 bump）并升级本仓库 pin 后，`test_console_protocol_maps_report_options_to_form_schema` 自动启用——它只影响本仓库测试链路，不阻塞上线。
