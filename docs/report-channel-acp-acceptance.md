# 私有报告频道 ACP 验收

宿主通过现有邀请兑换与身份校验绑定单份报告。若启用 ACP，客户端使用兑换回执中的 `acpMessagesPath` 提交 `message_id` 和 `text`。Word 候选走回执中的 `wordTasksPath`，使用同一次报告授权。设定 `prepare_with_acp: true` 时，宿主先让原版 DSH 整理操作说明，再委派 Word 候选。编辑器会话由报告宿主签发，候选由编辑者采纳并保存。

## 接入顺序

1. 从受信宿主读取邀请页面的接入说明。原始链接的片段不会随 GET 请求发送。
2. 通过宿主提供的认证流程取得连接身份，再将邀请片段作为 `reference` 提交给接入说明所列的兑换接口。报告和会话范围由服务端确定。
3. 使用兑换回执提供的相对路径发消息或提交候选任务。遇到网络重试时保留原消息 ID 和正文。收到 `report_channel_acp_outcome_unknown` 时应提示用户结果未确认，避免改用新 ID 自动重发。
4. 用候选回执中的任务 ID 查进度，通过审阅链接进入报告宿主的正常编辑授权流程。用户在 Office 助手采纳并保存，再打开新修订确认结果。

## 本地复跑

使用锁定依赖和构建好的 Office 助手静态资源。配置项目已有的合成 PostgreSQL 夹具与浏览器测试环境。以下参数只用于测试：

- `REPORT_ACP_TEST_DSH_BIN` 指向原版 DSH 的 Node 入口。本次使用 DSH 0.2.2-rc.1。
- `REPORT_ACP_TEST_NODE` 可选，指向符合所用 DSH 版本要求的 Node。该版本要求 24.9 或更新版本。
- `WORD_CHANNEL_VIDEO_DIR` 指向新的录制目录。验收用例会遮罩一次性邀请。
- `WORD_ACCEPTANCE_CHROMIUM` 和 `PLAYWRIGHT_NODEJS_PATH` 可用来指定用于回归的浏览器及其 Node 运行时。

```sh
pytest -q smart_reporting/tests/test_report_acp_client.py smart_reporting/tests/test_report_acp_dsh.py
pytest -q -m integration smart_reporting/reporting/tests/test_native_word_task_chain_docx.py -k "test_channel_invitation_delegates and acp-http"
```

本机联合验收启用了 PostgreSQL 持久模式，确认报告授权绑定了 ACP 会话，并通过了 Word 候选预览、显式采纳、保存、打开新修订及 DOCX 独立回读。本地 JUnit 及 WebM 位于工作区的 `acp-dsh-word-durable-browser.junit.xml` 和 `acp-dsh-word-durable-browser/`，没有纳入源码提交。

联合验收使用原版 DSH 进程、真实 DOCX、合成数据及本地模型替身。真实模型的双 Agent 对话与桌面聊天粘贴链接自动绑定仍待验收。当前接口仅供私有试验。

## DSH 桌面入口核对

核对时本机安装的是 DSH Desktop `0.2.2-rc.3`。上游源码固定在 `39163dd30f703a79079e2d2446545cff3c453738`。

- [桌面协议处理器](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/apps/desktop/src/main.ts) 接收 `dsh://open` 或 `dsh://open/` 后聚焦窗口，没有报告邀请参数。
- [标准预设](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/standard.patch.yml) 给子 Agent 工具配置的是 `spawn` 和 `fork`。[ACP 子 Agent](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/subagent/subagent-acp/README.md) 需要在宿主中显式挂载并配置子进程命令；每次委派启动一个子进程并返回最终文本。
- [ACP 自动化入口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/acp-app/README.md) 通过 `dsh --profile acp` 提供 stdio，由启动它的客户端建立或恢复会话。本地 Word 联合验收使用这条入口。

要验收桌面原生对话，DSH 需要提供受支持的方式，让现有桌面会话识别报告邀请并连接经授权的报告通道。

私有宿主可在完成频道表初始化后用 `ReportChannelAcp(..., durable=True)` 将会话绑定与回执保存在 PostgreSQL。重启后的 DSH 工厂需继续使用同一个私有 DSH 会话目录。存储层与 HTTP 重建测试位于 `smart_reporting/tests/test_report_acp_persistence.py`，使用隔离的合成数据库和 ACP 对端替身。两个宿主同时请求同一会话时，后到请求收到 `report_channel_acp_turn_in_progress`，可稍候以原消息 ID 重试。

在支持 psycopg 异步连接和 ACP 子进程的测试环境中，运行 `pytest -q -m integration smart_reporting/tests/test_report_acp_dsh.py smart_reporting/tests/test_report_acp_persistence.py`。其中原版 DSH 用例通过实际 PostgreSQL 做邀请兑换，重建 HTTP 宿主后复用回执，再继续原 DSH 会话。模型端为本地替身。

如需验证真实模型的 ACP 会话恢复，令 `REPORT_ACP_LIVE_DSH_HOME` 指向已通过 DSH 正常流程配置模型的独立测试目录，再运行 `pytest -q smart_reporting/tests/test_report_acp_dsh.py -k live_model`。测试仅发送随机合成编号，会创建并恢复一个测试会话。凭据从该配置或已有受信环境进入 DSH，无需放入命令行、仓库或聊天。

## 2026-11-15 审查修复回归

本轮修复以 PR #246 的 `d74b34d4` 为起点，随后合入 `code` 的 `9b23f895`，解决前端助手、API 类型、控制器测试及原生候选采纳的五处合并冲突。保留主分支的会话/来源/候选身份复核，同时保留频道任务跟随和独立取消清理语义：旧任务清理失败可重试，但不拖住新任务取消，也不把旧任务的失败算作新任务取消失败。

- 持久化 ACP 使用与内存模式相同的执行中授权监视，撤销后取消当前调用并关闭本地 ACP 子进程；不重放结果未知的原消息。清理异常不会覆盖撤销异常。
- Word 生成期间监视原 grant；每次 MCP 工具调用在数据库、编辑会话和来源读取前后复核该 grant，候选提交及结果返回前也复核。取消被依赖吞掉时仍拒绝迟到候选。
- 统一 DOCX 候选把已校验的宿主草稿快照及原 grant 传入 Word 服务。选区、操作及嵌套样式在首次授权 await 前深拷贝，避免二次解析换成另一组选区；新 grant 不接管旧请求。

合并后的本地验证（均选择 asyncio）：

```sh
python -m pytest -q -o addopts='' -k 'not trio' \
  smart_reporting/reporting/tests/test_regular_accept_authority.py \
  smart_reporting/reporting/tests/test_native_word_task_prepare_api.py \
  smart_reporting/reporting/tests/test_native_word_task_dispatcher.py \
  smart_reporting/tests/test_report_acp_client.py \
  smart_reporting/tests/test_document_candidate_word_adapter.py \
  tests/test_report_channel_api.py
# 83 passed

python -m pytest -q -o addopts='' -k 'not trio' \
  smart_reporting/reporting/tests/test_native_ai.py \
  smart_reporting/reporting/tests/test_native_ai_requests.py \
  smart_reporting/reporting/tests/test_native_ai_cancel_terminal.py \
  smart_reporting/reporting/tests/test_native_ai_shutdown_terminal.py
# 41 passed

# 在 smart_reporting/report_editor/frontend 中：
npx tsc --noEmit
npx vitest run src/native-ai.test.ts src/office-assistant-controller.test.ts src/report-channel-share.test.ts
# 类型检查通过；45 passed
```

修改的 Python 模块及测试通过 Ruff，合并差异通过 `git diff --check`。初次回归因隔离工作区缺少 Office 引擎依赖而出现初始化错误；按锁文件安装依赖后，上述 Word/PDF 用例全部通过。复用旧前端依赖曾产生 XLSX 类型版本不一致，改用本次检出的锁定依赖后完整类型检查通过。Python 仍有既有 `imghdr` 弃用告警。

本轮没有可用的隔离 PostgreSQL 或原版 DSH/真实模型配置，对应 5 项测试跳过；未重跑前文的 Chromium 保存/重开联合验收。新增子进程测试使用合成 ACP 对端，Word/PDF 回归使用真实格式引擎。它们不能替代真实 DSH 桌面、多宿主 PostgreSQL 或浏览器联合验收。PR 继续保持 Draft，不合并、不部署。
