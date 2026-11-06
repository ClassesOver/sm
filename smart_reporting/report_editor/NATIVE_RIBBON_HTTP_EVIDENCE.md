# PR #190 原生功能区 HTTP 证据审计

日期：2026-11-05。基线：`0017ff7a22cb7931eb8dc387b0eb98b14601d933`；工作树含本轮 PPTX 自定义尺寸校验修改，尚未提交。本文只审计现有四格式 HTTP 回路及其依赖边界，不是生产授权或完整系统验收证书。

## 原始材料与检查方法

直接读取以下实现和测试，而不以 PR 描述作为验证依据：

- `reporting/tests/test_native_ribbon_http_roundtrip.py`（四格式实际回路和文件读回断言）。
- `report_editor/native_import_api.py`、`native_api.py`、`native.py`（能力凭据、会话、CSRF、作用域与文件身份检查）。
- `report_editor/native_publication.py`、`native_repository.py`（请求摘要、修订预约、恢复回执与下载签发）。
- `frontend/src/native-draft.ts`（本地草稿身份、请求重试和历史状态）。
- 测试中引入的 `test_native_editor_api.Repository`、`test_native_publication_nonblocking.Repository/create_publication`（替身具体行为）。

方法：逐步追踪测试实际调用的入口与断言，标记执行真实实现/替身的分界；核对负向安全用例所在层级；仅运行当前四个参数化回路，不跑完整测试套件。

## 四例实际能够证明什么

`test_native_ribbon_http_roundtrip.py:139–193` 创建实际 FastAPI 中间件/路由，通过 `httpx.ASGITransport` 在进程内发送 HTTP 请求。这执行 HTTP 请求模型、cookie、重定向、路由、中间件和响应流；**不经过 TCP、TLS、反向代理或真实浏览器 cookie 策略**。

| 链路 | 实际实现与断言 | 证据边界 |
| --- | --- | --- |
| 上传身份 | `require_workspace_capability` 核验合法测试凭据；multipart 上传经 `NativeImportService` | 这四例只用合法身份，不含伪造/过期/跨线程拒绝样本 |
| grant 与 session | 实际 `ReportEditorGrantService` 生成/交换凭据；重定向后设置 cookie 并读取 context | 编辑授权仓储是内存实现；`cookie_secure=False`，不能证明生产 HTTPS cookie 行为 |
| 写入 CSRF | preview/save 带合法 `Origin` 和 context 下发的 token，执行 `_csrf` | 正向通过不证明缺失、伪造 Origin/token 均被拒绝 |
| 文件编辑 | 实际 DOCX、PDF、XLSX、PPTX 引擎生成文件 | 请求操作由测试直接构造；不执行前端功能区命令和用户输入 |
| 非阻断验收 | validator 用 `AsyncMock` 强制抛异常；返回 `validation.ok=False`、`native_validation_failed`，仍成功下载 | 证明“验收执行异常”这一故障分支；不证明内容/版式验收算法正确，也不覆盖所有发布故障 |
| 下载身份 | 请求签发 URL 得到字节，计算 SHA256 与返回身份一致 | 下载授权和产物仓储为内存替身；未验证生产持久化/重启后的 grant |
| 产物读回 | python-docx 验证正文/段落/分栏；pypdf 验证页序/尺寸；openpyxl 验证值/公式/格式/合并；python-pptx 验证文字/尺寸/位置 | 这些库从下载字节断言目标语义，强于仅检查请求或成功状态；不等于 Office 桌面版或视觉保真认证 |
| 幂等 | 相同保存请求再次发送，revision 仍为 2，下载 SHA 不变 | 串行同进程重试；不是进程崩溃、跨进程竞争或生产事务约束验证 |
| 源与重开 | 原修订 `/file` 等于原上传字节；新修订 `/file` 等于下载字节 | 证明此测试内文件不可变和版本关系；不执行浏览器重开画布和编辑 |

## 替身对结论的影响

`create_publication` 使用真实临时目录 `ReportingWorkspaceRegistry/Router`、实际发布/下载服务，但注入内存 download grants、artifact records、editor grants，以及测试 `Repository`。四格式测试进一步组合两个仓储替身。

修订替身 `test_native_publication_nonblocking.Repository.reserve_revision` 按 `request_id` 存 dict，以 `len(rows)+2` 分配修订，重试检查摘要与父修订。生产 `NativeDocumentRepository.reserve_revision` 则先按完整作用域查文档并 `SELECT … FOR UPDATE`，按 document/request 检查冲突，再验证父修订和分配 next_revision。四例不执行生产 SQL，因此不能证明作用域 SQL、行锁、唯一约束、事务回滚或并发预约正确。替身没有与生产相同的跨文档 request_id 隔离、note 冲突与并发模型。

`NativeDraft` 当前实现把 database/company/user/thread/document/revision/source SHA 全部写入存储键，失败保留 pending request，修改或 undo/redo 清除旧 pending，保存登记后关闭旧草稿。这是源码检查结果；四例没有加载此 TypeScript 模块，不能用它们证明刷新恢复、撤销历史或浏览器失败重试行为。

## 已存在但不能混为四格式全链路的负向证据

以下在本轮分别执行，结果见末节；它们的测试边界仍须保留：

- `test_native_import_api.py::test_import_real_middleware_verifies_capability_before_consuming_upload`：真实中间件拒绝 capability/thread 不一致，断言 401 且不再调用 importer；importer 是 `AsyncMock`。
- `test_native_editor_api.py::test_save_route_passes_validated_snapshot_note_and_requires_csrf`：实际路由缺失 CSRF 返回 403，错误 revision 返回 403；publication 是 `AsyncMock`。
- `test_native_editor_api.py::test_native_scope_revision_and_capability_mismatches_are_rejected`：scope/format/native_editor capability 错配被服务层拒绝；不是 HTTP 测试，也不执行生产 repository。

这些是有用的分层防线；不能直接拼接成“伪造授权经过真实四格式文件引擎和生产数据库被拒绝”的证据。

## 仍缺什么及通过条件

1. **生产仓储作用域与竞争**：使用隔离测试数据库加载真实 schema，两个独立连接/进程并发保存同一 request 和不同 request；断言修订唯一、冲突不覆盖、完整作用域隔离、重启后的同请求恢复，保存 SQL 结果与产物身份。
2. **部署边界**：在干净镜像通过真实网络入口验证 cookie Secure/Path/SameSite、反向代理 Origin、同源静态资源、原生引擎可用性和下载。对断网要求，记录镜像身份及网络隔离条件。
3. **真实用户行为**：浏览器操作真实后端上传→编辑→保存→下载→新修订重开；保留输入事件、请求摘要、下载 SHA 与独立解析结果，不能用路由替身代替。
4. **负向全链路**：在上述真实后端环境变更用户/公司/线程/文档/修订、CSRF、源 SHA，并检查拒绝后没有创建修订或修改文件。已有服务层/路由测试可减少重复，但不能消除这层环境验证。

本审计没有确认生产实现中的可复现安全缺陷；上述项是证据缺口，不能据此声称已经发生越权。

## 本轮执行记录

初次 pytest 在收集阶段依次被缺失的 app 启动配置阻断：`AGENT_WORKSPACE_HMAC_SECRET` 长度不足、`AGENT_REPORT_PUBLIC_BASE_URL` 未设置；尚未执行任何格式用例。命令级采用 `smart_reporting/tests/conftest.py` 已有的公开 test-only 默认值后才执行测试；未读取或替换任何真实凭据。

可复现命令（工作目录仓库根）：

```bash
AGENT_WORKSPACE_HMAC_SECRET=test-only-workspace-secret-0123456789 \
AGENT_REPORT_PUBLIC_BASE_URL=https://reports.test.invalid \
.venv/bin/python -m pytest smart_reporting/reporting/tests/test_native_ribbon_http_roundtrip.py -q --tb=short
```

首次实际执行：**3 passed、1 failed，11.80s**。DOCX/XLSX/PPTX 均完成完整断言；PDF 在上传阶段返回 `503 native_engine_unavailable`，尚未执行 PDF 保存回路。检查到源码引擎所需 `pdf_engine/node_modules/.bin/tsx` 缺失，且没有可用打包桥接；属于本地运行依赖未安装，不能归为 PDF 编辑逻辑失败。

恢复步骤仅在 `smart_reporting/reporting/pdf_engine` 执行 `npm ci --no-audit --no-fund`（15 packages，7s），不修改锁文件或产品源码；之后只重跑失败的 `[pdf]` 参数，避免重复三个已通过回路。

负向分层用例按上一节列出的三个具体 node ID 单独执行：**3 passed，6.49s**。结果证明跨线程 capability 在实际中间件被 401 拒绝；缺失 CSRF 和错误修订在真实路由被 403 拒绝；scope/format/native_editor 错配在服务层被拒绝。下游 importer/publication/repository 的替身边界不变。

本地执行日志分别为 `/tmp/pr190-http-evidence-test.log`、`/tmp/pr190-http-pdf-evidence-test.log`、`/tmp/pr190-http-negative-evidence.log`；这些是当前工作区诊断文件，未作为长期托管证书。测试断言计算并比较实际文件 SHA，但不输出每次生成文件的 SHA，因而本文不伪造持久产物身份清单。

首次四格式及分层负向审计的源码身份（SHA256；后续自定义尺寸测试改动另列于下节）：

| 文件 | SHA256 |
| --- | --- |
| 四格式回路测试 | `d927c74d54c6be9fafbac682fd0c3b050ec38b21d4049229967afe0a2f2a1215` |
| native_api.py | `f7b24a751484260568451c7211ab00bc97d1eea3ee5b212443109ca600cb7bde` |
| native_repository.py | `8e1bdd4951c6a51d697c38745d6c3c5ec33e1f644827162240405d48823fb0da` |
| native_publication.py | `0fcea1e1086316a8cc1ab5a1094fde1ff2dc31613533ab86f939794c8dcbdc50` |

PDF 失败项恢复依赖后复验：**1 passed，17.55s**。因此本轮四格式各自的实际 HTTP 回路均已通过（3 项首轮通过 + 1 项环境恢复后通过），另有 3 项分层负向用例通过；没有重复完整套件。运行均仅有既有 Python `imghdr` 弃用警告。这个结果关闭本地 PDF 引擎缺依赖导致的失败，不关闭生产数据库、部署网络或真实浏览器验收缺口。


## PPTX 自定义尺寸的 HTTP 补证

四格式测试的 PPTX 分支现改为同一条 `editSlides` 同时提交文字修改和自定义尺寸 **9000000 × 7200000 EMU（25 × 20 cm）**，取代此前固定 16:9 预设。其他三个格式分支未改变，未重复执行。

下载后使用 `python-pptx.Presentation(BytesIO(downloaded.content))` 独立读取，断言实际 `slide_width/slide_height` 为目标值、文字修改保留，并验证文本框 `left/top/width/height = 900000/960000/2700000/960000 EMU`。这组几何预期由原样本 10 × 7.5 in、文本框 1/1/3/1 in 分别按目标宽高比例计算，不复用产品引擎的转换函数。

此补证继续执行原有 capability/session/CSRF、验收异常仍下载、下载 SHA、相同请求重试仍为修订 2、源字节不变和新修订重新授权读文件的全部断言。它证明后端接受自定义尺寸并生成正确文件，**不验证浏览器输入事件或 NativeDraft UI**。

复现命令（仅 PPTX）：

```bash
AGENT_WORKSPACE_HMAC_SECRET=test-only-workspace-secret-0123456789 \
AGENT_REPORT_PUBLIC_BASE_URL=https://reports.test.invalid \
.venv/bin/python -m pytest 'smart_reporting/reporting/tests/test_native_ribbon_http_roundtrip.py::test_ribbon_operations_use_real_http_save_download_and_reopen[pptx]' -q --tb=short
```

修改后测试文件 SHA256：`c7b3e85becdda73666e9ae822b51ce575e1ff4a12a00044361c2813af7ab1a2d`。执行日志：`/tmp/pr190-http-custom-pptx-evidence-test.log`。结果：**1 passed，10.84s**（只有既有 imghdr 弃用警告）。


## Real native-repository PostgreSQL boundary (2026-11-06)

The previous in-memory repository evidence remains historical. New opt-in
`test_native_repository_postgres_integration.py` cases reuse the four existing
HTTP roundtrip flows with actual PostgreSQL 18 and independent SQL checks: one
document, two saved revisions, next revision 3, persisted failed validation,
idempotent retry and second-engine readback. All four formats passed. PPTX now
combines ordered list/indent/direction and spacing with independent file checks.
Artifact/download/editor grant stores are still test doubles and HTTP is still
in-process ASGI. This closes the exercised native SQL persistence boundary, not
production authorization or deployed network behavior. Exact isolation, run
counts and reproduction are in `NATIVE_POSTGRES_ACCEPTANCE.md`.


## Word table structural adapter HTTP continuation

The DOCX fixture now combines column insertion with body/link/spacing/section
changes. ASGI upload/save/download/SHA/retry/reopen and independent python-docx
checks passed locally and in a production-packed Node22 read-only/network-none
container (final adapter: 1 passed, 7.18s). Native/artifact/grant repositories remain doubles in
this selection; the earlier PostgreSQL counts are not evidence for this new
flow against SQL. Source preservation, protocol and remaining UI/desktop gaps
are recorded in `NATIVE_WORD_TABLE_ACCEPTANCE.md`.
