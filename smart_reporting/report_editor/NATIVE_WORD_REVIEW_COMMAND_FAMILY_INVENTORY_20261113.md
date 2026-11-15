# Word Review 命令族盘点

日期：2026-11-13。固定源为 `/home/junge/pros/genoffice-source-full`，核验 HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本文对照固定源 Review Ribbon 与当前本地 DOCX host；命令出现、可点击或已有局部验收均不等于 Review 命令族完整对齐。

2026-11-14 续批：下表为历史调查。Editor／22语言翻译、Compare、保护、简单正文修订范围菜单及限定story修订已补；只读摘要为提示预填，仍须用户发起读取；批注AI批量改写、完整Review Pane和复杂修订仍未对齐。详见[本批验收](NATIVE_WORD_GENOFFICE_ALIGNMENT_20261114.md)。

## 命令映射

| 命令族 | 固定源 Review 行为 | 本地实现与边界 |
| --- | --- | --- |
| 校对与语言 | Editor 对选区或全文发起 AI 改写；键入时拼写检查开关；Translate 提供多语言预设，全文改写前有一次性确认。 | 拼写检查已由 `createDocxSpellcheckControl` 接入。本地 Review Ribbon 的“编辑器”和“翻译”仍是 `pendingGroups.review` 命令，禁用并显示迁移中；不能以其他 AI 面板能力替代源的这些 Review 回调。 |
| 批注 Ribbon | 新建批注；删除当前锚点批注、已解决批注或全部批注；上一条/下一条；显示批注面板；对未解决批注发起 AI 审阅。新建/删除入口受文档保护和 comments-only 限制控制。 | Ribbon 已接新建、当前光标批注删除、前后导航和显示批注；续补可信已解决/全部根线程批量删除，级联回复、projected 状态、整批权限、确认及撤销/重做，见[本批验收](NATIVE_PARITY_NEXT_BATCH_ACCEPTANCE_20261113.md)。存在批注文字草稿时先保留输入，再要求独立保存；本地 fixture+真实 bridge 的一次保存/下载/重开已验，不冒充生产 HTTP 授权验收。Ribbon AI 批注命令仍为缺口。复杂线程、复杂锚点和受保护 comments-only 仍有边界。 |
| 跟踪与标记显示 | Track Changes 开关；Simple/All/None/Original 显示模式；插入删除、格式和作者过滤；修订/批注/行内气泡模式；Track Changes Options 对话框。 | 跟踪开关已接入 `w:trackRevisions` 来源绑定操作，设置专项有 bridge、host 和冻结浏览器保存回读证据。续批已接四种显示模式、插入删除/格式筛选及 Specific People，作者集合含正文、页眉页脚、文本框和脚注尾注；复用源 Original 装饰、作者 ink/CSS 与正文 changed-line 标记，并投影到分页输入。相关 61 项定向测试通过，实际冻结浏览器证据须按[续批记录](NATIVE_REVIEW_IMAGES_SCATTER_ACCEPTANCE_20261113.md)逐项判断。气泡与高级修订选项继续明确禁用；Original 是固定源近似投影，不代表完整复杂格式原稿重建。展示模式不等于所有编辑自动记录修订。 |
| 接受/拒绝与导航 | 菜单范围为 Next、All、Shown、Selection、按作者；Shown 使用当前标记过滤。Next 按当前位置处理可见修订。接受/拒绝还处理固定源能发现的非正文 story 修订；Review Pane 供逐项浏览/决策，另有 AI Review Revisions。受保护文档或强制跟踪限制接受/拒绝，强制跟踪也锁定开关。 | 自定义“正文修订列表”、前后导航和批量接受/拒绝仅作用于服务端明确授权的顶层简单正文插入/删除目标；批量操作全批校验、单事务。没有源的 Shown、Selection、By Author 范围，也不覆盖 story 修订、复杂/嵌套/move/属性修订。列表中的 AI 单条修订回调不是源 Review Pane 的完整等价。已完成的跟踪和正文修订专项分别见 [跟踪修订设置验收](NATIVE_WORD_TRACK_REVISIONS_ACCEPTANCE_20261113.md) 与 [正文修订 built 验收](NATIVE_WORD_TEXT_REVISION_BUILT_ACCEPTANCE.md)；它们不是完整 Review 验收。 |
| 比较与保护 | Compare 回调打开文档比较；Protect Document 打开保护配置，保护状态影响正文编辑、修订决策及批注可用性。 | `pendingGroups.review` 中“比较”“保护文档”无本地 action 映射，禁用迁移中。固定源有回调和保护门禁不证明其保存落点与本地能力；本地尚无这两个 Review 命令闭环。 |

## 核验依据与解释

- 固定源 `apps/docs/src/renderer/components/ribbon-tabs.tsx`：`ReviewTabProps` 声明各回调与保护状态；ReviewTab 渲染各组命令及禁用条件，尤其 `revisionMenu` 的范围项、标记过滤、批注入口和 `isProtected` / `commentsAllowed` / `trackChangesForced` 门禁。
- 固定源 `apps/docs/src/renderer/review-actions.ts`：`handleRevision` 实际按 next/all/shown/selection/author 选择目标，`all` 先处理 story 修订；`handleRevisionRange` 对实时目标重新定位。Ribbon scope 不能简化成“全部正文修订”。
- 本地 `frontend/src/docx-ribbon.ts`：`pendingGroups.review` 定义源命令入口；明确映射的批注（含当前和批量线程删除）、拼写检查与自定义受支持正文修订控件除外，其余未映射命令经迁移状态禁用。`frontend/src/docx-main.tsx` 接入跟踪设置及批注控制；`frontend/src/docx-comment-controls.ts` 将当前光标目标绑定到已核验线程并过滤已投影删除目标；`frontend/src/docx-text-revision-controls.ts` 限定简单正文目标并保留复杂目标。
- 已有新建批注、评论文字/线程及修订专项只证明各自列明的范围。源侧调查 [Review 真实保存调查](NATIVE_WORD_REVIEW_INVESTIGATION.md) 只证明其探针所覆盖的固定源链路/样本；不能扩展为 UI 全量点击或本地 Review 等价性。

## 结论

本地已存在可验收的批注子能力（含当前光标和可信已解决/全部线程删除）、拼写检查、跟踪设置以及简单正文修订处理，但 Ribbon 命令族仍缺翻译与 Editor、批注 AI 入口、完整标记选项、源范围菜单、story 修订、Review Pane 等价、Compare 和保护。批量删除的精确证据及独立保存边界见[本批记录](NATIVE_PARITY_NEXT_BATCH_ACCEPTANCE_20261113.md)。后续应按各命令的目标范围和保存协议分别验收，不按 Review tab 标签或按钮可见性汇总完成。

## 当前批注删除证据边界

本节归档短名均相对于 `/home/junge/codex-evidence/smart_reporting/office-parity-review-print-20261113/`；原始运行目录另以 `/tmp/` 完整路径列出。

- 初始隔离构建：`/tmp/word-current-comment-delete-build-MaBTbY/.vite/manifest.json`，文件时间 `2026-11-13 17:33:15.589680526 +0800`，manifest SHA-256 `20775ab0532b3bd27e19a2bc64857d498e171007d3fbf1d2a20ae0cfefb0f00b`。首次浏览器运行在 `/tmp/word-current-comment-delete-browser-20261113/` 保存一次修订（`revision-2.docx`）；`failure.json` 时间 `17:35:55.409037201 +0800`，只记录 Snap Chromium 的 `download.saveAs` 临时文件 `ENOENT`，不否定页面内下载 URL 的实际字节。
- 首次 smoke 的 recovery 目录 `/tmp/word-current-comment-delete-recovery-20261113/` 保留了失败后诊断文件；最终 recovery `/tmp/word-current-comment-delete-recovery-final-20261113/` 使用同一已保存 revision 1/2，保存请求数为 0。页面内 fetch 的下载状态为 200，`Content-Disposition` 文件名为 `comment-deleted.docx`，下载 SHA 与 `revision-2.docx` 均为 `56b13a440903e29817b8254661983d7768310f9b57e0f0f17e3722311dec20d0`；独立 ZIP/lxml 回读仅 `word/document.xml` 与 `word/comments.xml` 变化，正文 `Anchor text` 保留，批注目标为 0，重开后删除按钮禁用。该 smoke 使用 `page.route` fixture 和真实 Python/Node DOCX bridge，证明的是本地 host 与文件处理链，不是生产 HTTP 授权/签发验收。
- final 隔离构建：`/tmp/word-current-comment-delete-build-final/.vite/manifest.json`，文件时间 `2026-11-13 17:52:26.495851031 +0800`，manifest SHA-256 `ec1eb4fa2c5966a0710c71d93c2d33ebab32fedac717cd08c7df8dfb49025e92`。构建 final 已包含按钮短显示文案，但在后续控制器 dirty-input / 重复删除 / catch 修复前完成；这些修复的源文件修改时间分别约为 `17:55:16`（定向测试）、`17:57:02`（控制器最终 catch），因此没有把 final build 或 recovery 结果冒充为这些修复之后的浏览器构建验收。没有重复保存或重跑浏览器。
- 定向测试原始结果：执行 `npx vitest run src/docx-comment-controls.test.ts src/docx-ribbon.test.ts`，退出码 0，最终 `18 tests` 与 `47 tests` 合计 `65 tests` 通过；仅有既有 Canvas `getContext()` stderr warning。该终端原输出未另存日志文件，以上数字来自终端原输出，不虚构日志路径。`node --check smoke/docx-comment-current-delete-smoke.mjs` 与受影响文件 `git diff --check` 退出 0。203 个 `licenses/`、`pdfjs/` sidecar 的逐文件对照使用共享 static 与 `/tmp/word-current-comment-delete-build-final/`，isolated 副本 203/203 SHA 相同；本段不据此推断本次构建前后 shared static 的写入或未写入状态。
- root随后使用包含脏输入/projected-thread/catch修复的新构建 `/tmp/pdf-replace-text-thumbnail-20261113-final/static`，manifest `db769c2bae077ccf325f3fb7ed233c64e7ace1138127f65fbe613923121bc384`，运行 `/tmp/word-current-comment-delete-current-build-root-20261113`。同一修订下载/重开再次通过，保存0，175资源SHA匹配；独立ZIP回读与下载身份仍一致，短文案截图目视确认。该运行只验证新构建加载与已保存修订重开，不冒称在浏览器重做了脏输入/删除/保存场景；这几项由上述65项定向测试覆盖。静态资源与运行记录分别归档 `pdf-replace-thumbnail-first-final-static/`、`word-current-comment-delete-current-build/`。
