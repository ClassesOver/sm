# Word AI 审阅写操作验收

日期：2026-11-11。固定 GenOffice 源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。属于四格式 AI 共性优先项，不代表完整工具面或所有审阅类型已对齐。

## 已接入行为

Word 原生 Agno 工具新增 `read_review_targets`。用户在已有批注面板选择根批注，通过带 Lucide 图标的“AI 回复批注”“AI 处理批注”进入现有候选面板；简单正文修订列表逐条提供“AI 审阅修订”。入口只授权当前审阅身份，不自动生成、采纳或保存。候选面板可返回正文选区模式。

服务端从实际 DOCX 模型验证 `{sourceId,targetId}` 或 `{blockId,revisionId}`，冻结目标正文及开放能力。必须连续分页完整读取对应目标后，才可调用 `propose_operations`；最终候选与工具登记操作逐项一致。候选经真实引擎预览，用户显式采纳仅更新草稿，保存仍生成新修订。复用现有取消、任务和 SSE，工具进度显示中文。

支持根批注 `replyComment`、`resolveComment(done=true|false)`，以及简单插入/删除修订 `resolveTextRevision(action=accept|reject)`。回复作者 `AI Assistant`、UTC 秒级日期与 clientId 由服务端在任务选区快照中一次生成，模型不能冒用或修改；来源 hash 同样由服务端核验恢复。

批注与修订选区不混合，普通正文授权不隐含审阅权限；每轮只处理一种操作 family，每个目标最多一次操作。不兼容的已有草稿要求先保存重开。根线程状态操作会同步根及其回复的状态；模型仅读取所选根批注文字，不宣称读过回复或全线程。复杂/嵌套修订与嵌套回复仍未开放。

## 定向证据

- 核心实际 DOCX、Agno、权限、schema、分页、真实三类写入 7 项通过；后续状态快照、缺失身份与原生 UTF-16 长度边界 4 项通过。原普通 Word 能力回归 12 项通过。
- 服务层 9 项通过：三 family 实际 preview → accept → patch → inspect，原件不变；伪造身份、混选和不兼容草稿拒绝；取消后迟到结果不发布；生产工厂实际 Agno 工具调用及真实 toolCallId。
- 前端相关既有及新增链 53 项通过，评论/修订入口追加两项、候选决策展示四项窄测通过。未重复完整项目测试。
- 真实 provider 首轮暴露最终操作平铺格式与 schema 的歧义：已给 `propose_operations` 回执增加可原样返回的 `proposal`（包含 `kind + arguments`），并明确最终格式。未静默接受格式错误，最终候选一致性校验保留。回执可直接验证成最终 schema 的定向测试通过。

完整 `npm run build` 的类型阶段失败，日志 `/tmp/word-ai-review-build-20261111.log`：包括 docx-view 测试缺少 active、vendor IPC 缺包/类型、工作簿保护测试 bandedRows、workbook-main 参数类型与 sparklines 变量使用顺序。本轮未以宽松类型或预算上调掩盖这些问题。

单独 Vite 构建 47.64 秒成功，日志 `/tmp/word-ai-review-vite-20261111.log`。预算检查失败：workbook-engine 439.1 KiB 超 428 KiB、workbook-main 263.0 KiB 超 253 KiB，见 `/tmp/word-ai-review-budget-20261111.log`。不声明当前整个前端构建和预算通过。

浏览器首轮及第一次复验均因脚本把编辑助手与阅读助手的进度列表混选而停在候选阶段，未计通过。修正为精确 `AI 编辑选区` region 后复验；失败目录原样保留。

后续浏览器脚本还修复了两项证据问题：ZIP 新增空目录不计为实际部件修改；共享构建期间 manifest 变化则不计完整资产验收。现复制实际生产资产到独立只读验收目录，HTML 入口和静态资源均从同一快照提供，并逐份核对 HTTP 内容 SHA。冻结资产首轮三链及 125 份 JS 已通过，但 root 事后核对发现轮询重生成同名 DOCX 会因 ZIP 时间戳改变而覆盖先前证据，故其旧文件身份不计最终通过；验收服务改按文件内容 SHA 命名保留每个产物，独立最终复验另记。以上仅修验收脚本，不降低产品校验或修改来源文件。

## 真实模型

当前 reporting 工厂 `deepseek-v4.1-flash` 经真实 Agno 执行三项。首轮均失败，原证据 `/tmp/word-ai-review-write-real-provider-20261111.json` 保留：回复与接受修订返回平铺最终操作，线程重开最终操作未与工具登记一致。修复回执格式后，每个失败项仅复验一次，见 `/tmp/word-ai-review-write-real-provider-20261111-final.json`，耗时 115.25 秒。

最终三项均验证指定审阅身份、实际读取/提案工具、唯一登记操作、真实 DOCX 写入及原件不变：回复保留“已核实收入42”且作者为服务端 `AI Assistant`；重开根线程及直接回复；接受指定插入保留插入文字和相邻删除修订。root 独立核对全部源/候选 SHA、候选与登记一致、ZIP/XML 可读及实际改变的包部件。

重开线程探针曾错误要求回复 done 不变。按照已有引擎线程语义，仅从同次保存的源/候选 ZIP 校准断言，没有再调 provider；错误断言版 `-final.wrong-assertion.json`、校准脚本及记录均保留。

实际 provider 仍多次重复提案，被重复身份保护拒绝，最终仅一条候选登记成功；回执、失败工具事件均保留。后续指令已明确成功登记后立即返回 proposal，但尚未重新调用模型证明重复调用消失，不能标记执行效率问题已解决。此验证不含生产数据库或桌面 Word。

## 最终浏览器复验

`/tmp/word-ai-review-20261111-immutable-final/summary.json` 的 `ok=true`，Chromium `140.0.7339.16` 真实完成三链：中文带图标目标入口 → 明确输入要求 → Agno 原生工具及 SSE → 真实引擎候选预览 → 显式采纳 → 本地草稿与画布刷新。生成候选前后草稿不变，只有采纳后增加当前目标的一项操作；未发送 save/export，原件 SHA 不变。

125 份实际加载 JS HTTP 内容与冻结磁盘资产 SHA 全部匹配，manifest `eeb712aacbd867023a226b2e06c794188a0026a014b9403aea1698a1e85b947d`；页面、控制台和 HTTP 错误均为空。root 独立重新核对 manifest、全部资源、三份保留 DOCX 文件 SHA/ZIP 及来源 SHA，确认产物未被后续轮询覆盖，并目视修订采纳画布截图。回复实际新增评论和真实父关系；线程状态仅改变 commentsExtended；接受插入仅改变 document.xml 并保留删除修订。

浏览器使用 ScriptedModel 经真实 Agno，不冒称真实 provider；真实 provider 证据单独见上节。鉴权使用实际 grant/cookie/workspace 与有作用域内存 revision repository，不冒称生产数据库或桌面 Office。冻结资产验证不等于共享目录此后构建资产仍完全一致，也不使完整 types/预算门禁变为通过。

完整四格式目标继续开放，未改发布签发链，未提交、推送或部署。
