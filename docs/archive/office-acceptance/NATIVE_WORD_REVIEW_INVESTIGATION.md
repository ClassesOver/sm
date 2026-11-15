# Word 审阅下一缺口：固定源真实保存调查

日期：2026-11-10。仅调查，不表示本地交付。固定源 `/home/junge/pros/genoffice-source-full`，只读核对 HEAD=`f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只新增此文档和 `/tmp/word-review-gap/` 探针，不改生产、公共配置或既有验收，不运行应用 build、完整测试、浏览器或桌面 Word，不提交/push。

## 结论供下一轮选择

**建议下一项：顶层简单正文 `w:ins/w:del` 的定点接受/拒绝。** 固定源有真实 Ribbon 回调、PM 执行和保存；本地已有同版 revision 模型/执行器和原始 XML 修订工具，但尚无严格授权操作。不能只启用按钮后把普通 replaceParagraph 当作修订保存。

最小迁移可复用既有 engine `applyTrackedChangesXml`，限定服务端核验的简单修订目标，保留原 XML，再交 `saveDocx(kind:'xml')`。本次已实际验证该适配方式的接受/拒绝及作者过滤，保留段落 rsid、批注、格式与非目标 parts。它是**已有源工具的宿主适配方案**，不是固定源正文 Ribbon 当前采用的 PM 保存路径，也不是本地已交付功能。

更小的备选：已有批注纯文字编辑（固定源同段数量可 patch 的情形）。真实源保存仅改变 `word/comments.xml`，正文完全不动；可先补批注面板和单一 `editCommentText` 协议。新建、删除、回复必须同时处理正文锚点，不能与改文字算同一工作量。

**不能整族照搬后称完成。** 源无 paraId 的旧批注存在回复/解决关联失效；源正文 PM 全段生成丢失原始 `w:p/@w:rsidR`。下文区分源码闭环、实际执行、边界和建议协议。

## 固定源真实链路

路径均相对于固定源根，不以翻译标签作为实现证据。

| 功能 | Ribbon / 宿主入口 | 实际执行 | 保存落点 |
| --- | --- | --- | --- |
| 接受/拒绝 | `apps/docs/src/renderer/components/ribbon-tabs.tsx` `ReviewTab` / `revisionMenu`，约880–904、1221–1252；scope 为 next/all/shown/selection/{author}；`components/Ribbon.tsx` 4667–4668 传 props；`App.tsx` 7655–7656 接 `handleRevision` | `review-actions.ts` 341 `handleRevision`，按 scope 收集/过滤，all 先处理 story 再正文；413 `handleRevisionRange` 再从 live doc 定位；`editor/revisions.ts` 519 `applyRevisions`、917/921 accept/reject all；事务设 `TRACK_IGNORE` 避免决策自身再记修订 | `file-actions.ts` 839 `pmDocToSavePlan` →907 `saveDocx`；`packages/docx-engine/src/patch.ts` 746 `saveDocx`；保存字节再由 `file-actions.ts` 1171/1206/1211/1227 的 desktop save APIs 写文件 |
| 新建/删除批注 | `ribbon-tabs.tsx` ReviewTab new/delete callbacks，App 7644–7647；插入页也有 new comment callback | `review-actions.ts` 193 submit、274 delete、302 deleteAll；`editor/comments.ts` add/remove 标记；删除父批注会带 replies | 同一 SavePlan 更新正文锚点；`file-actions.ts` 928 `comments: ctx.commentsDirty ? ctx.comments : undefined`；`patch.ts` 1445+ 更新 comments、rels、types |
| 批注编辑/回复/解决 | `App.tsx` 3263–3279 callbacks、8698+ `CommentsPanel` 真接线；不是每个动作都由 Ribbon 直接触发 | `review-actions.ts` 236 reply、257 edit、265 resolve；reply 共用父锚范围；resolve 改全线程 done | `patch.ts` 2774 `buildCommentsXml` 保留或 patch 已有 comment XML；2855附近 `buildCommentsExtendedXml` 写 paraId/parent/done |
| 非正文修订 | `handleRevision` 调 `applyStoryRevisions`；`editor/story-revisions.ts` 405 `resolveNotes`、431 `resolveHfValue` 累计 revisionsResolved | engine `revision-xml.ts` `applyTrackedChangesXml` / `applyRevisionResolutions`，处理原始 XML | `notes.ts` 297 和 `patch.ts` 2532 把决策回放到原注释/HF XML；本次没有对脚注、页眉页脚、文本框进行 GUI/文件专项验收 |

Track Changes 设置自身也有 `file-actions.ts` 925 `trackRevisions` 设置保存；这不等于所有编辑操作都已正确产生修订，也不等于本次对 recorder 做过专项验收。比较/翻译/保护不在本次交付候选证据范围，不能按审阅 tab 一并计完成。

## 本地核验：保留/显示不等于可编辑

- `frontend/src/docx-ribbon.ts` `pendingGroups.review`（47）列出批注/修订；renderPending（360附近）对无 action 映射的按钮以 migrating 原因禁用，无可执行接线。
- `frontend/src/docx-insert-source.tsx` 409 的 new comment 明确 `disabled={true}`。
- `frontend/src/docx-main.tsx` 193 使用 vendor `editorExtensions`；326 把 parsed.comments 交给显示层。vendor `editor/extensions.ts` 已有 comment/ins/del marks、修订 attrs，并在7362注册 TrackChangesExtension。不能误报为“完全没有解析或模型”。
- `frontend/src/docx-operations.ts` 没有批注/修订语义 intent 到严格 operation 的收集；`reporting/doc_engine/bridge/edit-docx.ts` 没有对应操作分支，1355落 operation_unsupported。
- 同 bridge 的 `simpleParagraphXml`（398）只允许 p/r/t/tab/br/cr/hyperlink 等标签；含 commentRange、ins/del 的段落不取得普通 editableParagraph 权限（438）。editableTable（458）也拒绝 ins/del 等。不能为迁移审阅直接放宽普通段落/表格写回能力。
- 本地 `reporting/doc_engine/packages/docx-engine/src/revision-xml.ts` 与固定源同文件 SHA256 均为 `c992c97b1395c55ba4990bfeb218c16aceaac75e8ebd7304e789024d2e8be6db`。这说明可复用工具已在 vendor engine，并不说明本地 HTTP/草稿/授权闭环已有。

## 已执行探针与独立证据

全部代码和输出在 `/tmp/word-review-gap/`，最终权威样本分为 `modern/` 和 `legacy/`；根目录早期样本是探索版本，未计入下表。现代样本已有 `w14:paraId=ABCDEF01`，旧样本没有 paraId；正文使用合法 `xml:space="preserve"` 的 `KEPT `、Ann 的粗体插入 NEW、Bob 的删除 OLD、已有批注1、独立 sibling 段和 opaque customXml part。

`probe.ts` 直接导入**固定源** parseDocx/buildDocx/blocksToPmDoc/pmDocToSavePlan/applyRevisions/comments helpers/saveDocx。使用真实 PM Schema/EditorState，按源 converter 产出的所有 attrs/marks 建立无 DOM 的最小 schema；view 仅 dispatch 到 state。没有 stub engine 或伪造保存输出。UI 依赖仅将 `@genoffice/ui` 指向 wordart preset 的窄转出，探针未调用该UI。本次用 esbuild 只打包 `/tmp` 探针，**没有运行应用 build**。

每类来源12次实际 engine 保存，共24个最终输出 DOCX：8个 PM/批注路径、4个 raw adapter 路径。这里实际执行到的是源执行器和源保存器；Ribbon/App callback 链是静态追踪证据，未声称点击过源 Ribbon、执行完整 React 宿主状态或 desktop save API。

| 向量（每项modern/legacy各一次） | ZIP + lxml / 源 parseDocx 结果 |
| --- | --- |
| accept / reject | 主段为 `KEPT NEW` / `KEPT OLD`；ins=del=0；接受保留NEW粗体；原批注与锚点保留 |
| accept-ann / reject-bob | 仅 Ann ins 消失，Bob del 保留 / 仅 Bob del 消失，Ann ins 保留；说明非目标修订不会一律清空 |
| comment-edit | 批注为 `Edited & <review>`，实体正确回读；原斜体、正文及rsid、ins/del、锚点均保留；仅 comments.xml 字节变化 |
| comment-reply-resolve | modern 源重开准确恢复 parentId=1 与父/子 done=true；legacy **不成立**，见下文源边界 |
| comment-delete | comments无条目、正文无commentRangeStart/End/Reference；ins/del保留 |
| comment-add | 2条批注，新增id2锚点存在；旧批注与ins/del保留；只证明简单文字范围，不代表复杂跨段/跨故事 |
| raw-accept / raw-reject / raw-accept-ann / raw-reject-bob | 用源 engine `applyTrackedChangesXml` 修改原主段XML → saveDocx的xml块；文本/剩余ins/del与对应PM向量一致，额外保留主段rsid及原批注part字节 |

所有24次输出 ZIP `testzip()==None`，所有 XML/rels 独立 lxml 解析成功；所有 sibling段结构与 opaque customXml part 不变。保存文件SHA256、变化parts、修订计数、锚点、comment paraId和extended XML全文在：

- `modern/results.jsonl`、`legacy/results.jsonl`：源解析/PM执行/SavePlan/源重开。
- `modern/zip-lxml-evidence.json`、`legacy/zip-lxml-evidence.json`：独立 ZIP+lxml 回读及文件SHA256。
- `modern/verify.log`、`legacy/verify.log`：最终独立校验输出。
- `probe.ts`、`build-probe.mjs`、`verify.py`：可复现源探针。命令：`node /tmp/word-review-gap/build-probe.mjs`，`node /tmp/word-review-gap/probe.mjs`（modern），`REVIEW_LEGACY=1 node /tmp/word-review-gap/probe.mjs`；仓库 `.venv/bin/python /tmp/word-review-gap/verify.py`（modern），`REVIEW_CASE=legacy .venv/bin/python /tmp/word-review-gap/verify.py`。

## 观察到的源边界与保真风险

1. **旧批注的回复/解决失去关联，不能称源完整支持。** `patch.ts` 1454+为没有paraId的内存comment分配新键，但 `buildCommentsXml` 遇文字未变优先返回 orig.xml；因此旧父批注仍无w14:paraId，commentsExtended却指向虚构父键。legacy 的 commentsExtended 写父 `10001112`、子 `10002224` 和 done=1，但 comments.xml 只有子的paraId；源parseDocx重开：父没有done，子虽done=true却无parentId。`parse-package.ts` 183–192只能按真实paraId关联。modern已有父键可正常恢复。回复前必须补齐/核验真实关联键，或明确不开放该来源；不能把XML存在当语义成功。
2. **正文 PM 全段重建丢原段属性。** 所有改变正文的PM向量SavePlan为generated，原 `w:p/@w:rsidR=AABBCCDD` 消失；keepNext及NEW粗体保留，sibling不变。原XML不变的comment-edit走original，rsid保留。未证明其它任意段落属性/扩展都丢失，但已足以否定“全量保真”。raw adapter四向量保留该rsid，不需要复制整个PM生成路径。
3. **复杂修订不是简单ins/del。** source RevisionRange 包括 move、段落标记、rPr/pPr、编号/节、表行/格及属性变化；move成对、删除段落合并、行格结构等会跨目标影响。all范围还包括story。首版只读保留这些，显示明确原因；不要用当前段两个mark的逻辑执行“全篇全部”。
4. **批注复杂内容需分能力。** 源buildCommentsXml同段数量文字patch可保留富格式；patch失败则重建，段数量变化不能凭本次单段斜体样本宣称保真。图片、超链接、跨段锚点、reference-only、同范围重叠、回复级联、commentsExtensible/people等modern parts本次未验收。删除/新建/回复会改正文，不同于只改已有comment文本。
5. 原始XML修订工具是扫描型实现（revision-xml.ts），以w前缀和特定OOXML结构为边界。必须服务端限制/核验受支持的命名空间和目标，不能接受客户端任意XML、part路径或filter，从而变成任意文档修改接口。非目标raw parts保留；受保护文档、身份不符只拒绝编辑对应目标，不影响已生成PDF/Word下载非阻断契约。

## 最小严格协议与验收建议（尚未实现）

### 推荐：简单正文修订决策

1. 解析阶段新增独立 `reviewTargets`，不提升原普通editableParagraph：服务端生成稳定targetId、blockId、expectedObjectSha256、原XML内类型/修订id/作者/日期、能力与readOnlyReason。仅顶层简单段、没有move/段落标记/属性修订/表格/嵌套/含糊重叠/复杂包装，首版可先更窄。
2. 操作为 `resolveTextRevision {targetId, blockId, expectedObjectSha256, action:'accept'|'reject'}`；作用域固定单个服务端签发目标。范围/author/all是UI收集成目标列表，不直接接受任意作者filter或part路径。服务端重读授权修订的原DOCX，校验块hash和目标身份唯一；映射到既有`applyTrackedChangesXml`的精确受信id/filter；不得只按作者匹配整块其它修订。同操作批内序列在工作副本校验后原子保存，未执行/失效不冒充成功。
3. 前端可复用source collect/applyRevisions做预览，但草稿必须记录独立决策intent；Undo/Redo及恢复必须同步撤销/回放intent。保存后从实际文件重解析确认文本、剩余修订和非目标内容，签发新修订、下载并明确重开；本次未写任何该协议。
4. 不能让普通`replaceParagraph`代替修订接受拒绝；拒绝删除要恢复旧文字，接受插入要保留其格式，修订标记及其它修订需精确处理。首次不开放“接受全部”，除非所有受支持目标及不支持数量都准确说明，避免“全部”实际只处理可见正文。

### 较小备选：已有批注文本编辑

`editCommentText {commentId, expectedCommentSha256, text}`。身份由服务端原始comments.xml对应comment XML hash产生，定位唯一且不接受客户端author/date/relationships/XML；无正文选区要求。仅开放已验证可原位文字patch的结构，保留author/date/initials/paraId/锚点/图片/外部关系与其它批注。文本改变段数导致无法保真时明确拒绝该编辑；可在后续单独扩展。解决/重开需要commentsExtended及真实paraId关联验证，回复/增删还需正文锚点协议，不隐式塞进此操作。

### 必须验证的成功条件

- 新协议单测覆盖身份陈旧、重复id、缺失id、越权、重复/冲突目标、不能编辑的复杂修订；失败不产生半份修改。
- 接受/拒绝四个基本方向（accept ins、accept del、reject ins、reject del）、选择性非目标保留、格式、实体/中文/UTF16和合法空白；独立ZIP+lxml看实际输出XML，不能只看源parseDocx或PM状态。
- 对非目标parts字节、目标段rsid/书签/批注锚点/链接/字段/图像等做保真检查；首版不支持的复杂来源必须只读且保持下载可用。
- 真浏览器新建草稿→决策→Undo/Redo→恢复→未离焦保存→HTTP下载字节→明确新修订重开，验证动作和实际文件一致；readonly/saving锁生效；无动作不会写草稿/历史。
- 若迁移批注reply/resolve，modern与legacy无paraId样本都必须通过独立键关联和源重开，不能只检查commentsExtended存在。
- 修改导出/签发链时遵守AGENTS.md既有非阻断回归契约；不能以“审阅验收未过”停发身份已可核验的实际PDF/Word。

本次24次源/adapter保存是引擎级调查证据，不是本地功能验收、浏览器验收、桌面Word视觉或生产鉴权验收。不会更新CURRENT_GAPS把审阅族移除。
