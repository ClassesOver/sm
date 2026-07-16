# AG-UI Chat for Odoo 12

This addon mounts one React AG-UI chat runtime inside Odoo 12 and exposes the
current native FormController/ListController state through `agui.odoo.v2`.
Odoo BasicModel remains the only page-state authority.

Production traffic is:

```text
browser -> same-origin reverse proxy -> AgentOS AG-UI POST/SSE
```

Odoo serves `/agui_chat/config`, v2 UI sessions, browser host-command policy,
and a registry-only synchronous business-command endpoint. It does not proxy
SSE and does not expose generic RPC or CRUD.

Configure `runtime_url`; Odoo derives the matching `/config` handshake URL
from its `/agui` path. Deploy matching `12.0.7.0.0` declarations, then enable
the rollout kill switches. See [protocol](docs/agui_odoo_protocol.md) and
[production deployment](docs/agui_chat_production.md).

Frontend verification:

```bash
cd agui_chat/react_widget
npm run typecheck
npm run test
npm run build
```

集成开发环境可直接启动仓库内的最小 AgentOS 应用：

```bash
uv venv .venv-agent
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements.txt
OPENAI_API_KEY=sk-... .venv-agent/bin/python -m agentos_dev.app
```

Odoo 默认使用 `http://127.0.0.1:7777/agui`，并自动从该地址推导
`http://127.0.0.1:7777/config` 完成 v2 握手。开发智能体默认复用
`/home/junge/pros/agents_app/.env` 中的模型配置。

The only supported surfaces are Dock and an in-WebClient floating window.
They move the same React DOM root and keep the current Odoo action alive. Dock
supports all four viewport edges; on narrow screens both surfaces cover the
viewport without shrinking the Odoo WebClient.
