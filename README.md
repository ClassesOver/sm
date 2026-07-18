# Odoo 12 AG-UI 智能助手

本插件在 Odoo 12 中挂载 React AG-UI 聊天运行时，并通过 `agui.odoo.v2`
暴露当前原生 FormController/ListController 状态。Odoo BasicModel 始终是页面状态的
唯一权威来源。

生产环境流量路径如下：

```text
浏览器 -> 同源反向代理 -> AgentOS AG-UI POST/SSE
```

Odoo 提供 `/agui_chat/config`、v2 界面会话、浏览器宿主命令策略，以及仅允许已注册命令的
同步业务命令端点。Odoo 不代理 SSE，也不开放通用 RPC 或 CRUD。

配置 `runtime_url` 后，Odoo 会根据其中的 `/agui` 路径推导对应的 `/config` 握手地址。
部署匹配的 `12.0.8.6.0` 声明后，再启用灰度开关。详情参见
[协议说明](docs/agui_odoo_protocol.md)和[生产部署指南](docs/agui_chat_production.md)。

前端验证：

```bash
cd agui_chat/react_widget
npm run typecheck
npm run test
npm run build
```

按对话隔离的附件、工作区文件和经确认的代码执行，使用
`docker-compose.daytona.yml` 中锁定版本的 Daytona 部署。有关初始化、密钥、API 密钥创建、
备份和许可证要求，请参见[生产部署指南](docs/agui_chat_production.md#isolated-workspaces)。
首次启动前需预创建 `AGUI_SHARED_NETWORK` 指定的外部网络；默认名称为 `hrp_network`。
收藏筛选和当前筛选可在管理员启用 `odoo.business.report.filters` 并配置逐模型读取策略后，
导出到同一对话工作区，再由受控 Pandas 工具分析和生成图表。

集成开发环境可直接启动仓库内的最小 AgentOS 应用：

```bash
uv venv .venv-agent
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements.txt
OPENAI_API_KEY=sk-... .venv-agent/bin/python -m agentos_dev.app
```

新配置默认关闭聊天且不预填运行地址。配置 `/agui` 地址后，Odoo 会自动推导
同路径下的 `/config` 完成 v2 握手。开发智能体默认复用
`/home/junge/pros/agents_app/.env` 中的模型配置。

目前仅支持停靠面板和 WebClient 内浮动窗口两种界面形态。两者移动的是同一个 React DOM
根节点，因此不会中断当前 Odoo 操作。停靠面板支持视口四边；在窄屏上，两种形态都会覆盖
整个视口，而不会压缩 Odoo WebClient。
