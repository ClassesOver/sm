# AgentOS 开发服务

本仓库提供基于 Agno 和 PostgreSQL 的 Coding 与 Reporting 后端，不包含浏览器聊天接口或 Odoo 宿主模块。

## Docker 部署

根目录 `docker-compose.yml` 部署 AgentOS 和专用 PostgreSQL，`reporting-db` 向宿主机发布
`127.0.0.1:55432`。报告分析、绘图与文档渲染都在 AgentOS 所在主机的本地工作区中执行
（`REPORTING_HOST_WORKSPACE_ROOT`），不再依赖外部沙箱服务。

AgentOS 的持久化数据使用根目录 `data/`。
其中 `data/reporting-workspaces` 存放报告修订的 Markdown 与图片工作区：编辑上下文和下载
授权在 PostgreSQL 中持久化，若工作区文件随容器重建丢失，打开历史修订会报
`report_editor_revision_missing`（404），必须用备份恢复或重新生成报告，不能用空目录继续。
将仓库部署到 `/u01` 后，服务数据会随项目保存在 `/u01` 文件系统。

生成根目录 `.env` 并启动 AgentOS：

```bash
bash scripts/configure_agentos_env.sh .env
docker compose up -d --build
```

`deepseek`、`qwen` 等 OpenAI-compatible 模型不在 tiktoken 的模型映射中，Agno
会回退到 `o200k_base` 估算上下文 token。Compose 使用可写缓存目录，外网环境首次启动
会自动下载并校验该编码，后续启动直接复用。内网部署前，必须在联网机器生成缓存并随
部署文件一起传到宿主机：

```bash
TIKTOKEN_CACHE_DIR="$PWD/data/tiktoken-cache" \
  .venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
sha256sum data/tiktoken-cache/fb374d419588a4632f3f557e76b4b70aebbca790
```

校验值必须为
`446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`。
Compose 默认将 `./data/tiktoken-cache` 挂载为容器内 `/opt/tiktoken-cache`；
仓库不在 `/u01` 时，可在 `.env` 中用 `AGENT_TIKTOKEN_CACHE_DIR` 指向实际宿主目录。

内网机器已提前导入 `AGENTOS_REPORTING_IMAGE` 指定的镜像时，可直接挂载当前仓库中的
`smart_reporting/` 覆盖镜像内源码，无需重新构建：

```bash
docker compose up -d --no-build --force-recreate reporting-os
```

后续只修改 Python 源码时，执行 `docker compose restart reporting-os` 即可加载新代码。
若 `pyproject.toml`、`uv.lock`、基础镜像或系统依赖发生变化，仍需在联网环境重新构建并导入镜像。

本地运行：

```bash
UV_PROJECT_ENVIRONMENT=.venv uv sync --python 3.12 --no-install-project
AGENT_ENV_FILE=.env .venv/bin/python -m smart_reporting.app
```

当前服务使用 Agno 3.1.2，部署时必须连接全新数据库。不要复用 Agno 2.x 的 PostgreSQL
数据库或 `data/postgres` 数据目录；本项目不执行 2.x 历史数据迁移或兼容读取。

AgentOS 的 agent、team 和 workflow 新建 run 请求总大小上限为 32 MiB；multipart
请求最多包含 8 个文件，单文件上限为 24 MiB。run continuation 请求上限为 2 MiB。
超过边界的请求会在模型调用或文件读取前被拒绝。

## 报告准确性与工具协议

- 数值引用绑定具体事实、期间、分组和公式；金额、人次换算与十进制舍入由服务端统一处理。
- 冲突值、无依据的倍数和被大单位舍入成零的非零值需复核；日期数字不会作为事实值。
- Coding harness 校验调用身份与一对一回执，按顺序执行多工具调用；失败或提交后停止后续执行，并保留 custom 输入与 reasoning 回放。
- 业务复核为软告警。已生成且身份可读取的 PDF/Word 即使验收失败，也返回下载链接与失败原因。

相关回归测试（不调用真实模型服务）：

```bash
uv sync --frozen --group dev
.venv/bin/pytest -q smart_reporting/reporting/tests/{test_numeric_text,test_semantic_bindings,test_trace_subject_validate,test_reporting_code_reasoning_replay}.py
```

接口与配置见 [smart_reporting/README.md](smart_reporting/README.md)。
