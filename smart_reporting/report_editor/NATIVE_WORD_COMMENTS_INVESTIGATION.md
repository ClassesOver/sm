# Word 完整批注编辑缺口：来源绑定与固定源保存调查

日期：2026-11-10。固定源 `/home/junge/pros/genoffice-source-full` HEAD=`f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮仅新增本文与 `/tmp/word-comments-gap/`，不改生产、main、Ribbon、桥或 dist；不运行产品 build、完整测试，不 commit/push。本文不是本地功能验收，不宣称完整批注族交付。

## 本轮结论与严格范围

已有 [审阅调查](NATIVE_WORD_REVIEW_INVESTIGATION.md) 的24次源保存足够证明简单新建、编辑、删除及 modern 回复/解决链路，不重复跑。简单正文修订决策已另行交付，本轮只收敛批注下一步。

**下一项仅实施“已有批注正文的原位纯文字编辑”**，无新建、回复、删除、解决/重开，不扩普通正文编辑权限。前提是服务端从授权原DOCX签发唯一目标、源文字工具可保真 patch，保存仅替换目标批注片段。沿用源 `saveDocx({comments: fullList})` 不够：即便纯改文字，也会重建 commentsExtended 并丢未知扩展。新增10次保存（9次固定源原路径、1次源工具宿主适配）已提供实际文件证据。

允许显示所有能解析的批注，不等于授权所有批注编辑。富文本、超链接、作者、日期、initials、锚点、paraId、其它批注及关系必须保留；首版拒绝段数量变化和无法 patch 的来源。图片、字段、嵌套文本框、AlternateContent、修订内容、未知内嵌结构先只读，后续各自验收后再放开。只读/验收失败不影响已核验身份的现有PDF/Word下载。

## 固定源与本地可复用链路

以下源路径相对于固定源根；对应本地引擎前缀为 `smart_reporting/reporting/doc_engine/packages/docx-engine/`。

| 部位 | 已有能力 | 本地差距/注意 |
| --- | --- | --- |
| `apps/docs/src/renderer/review-actions.ts:193–313` | submit/addCommentAt、reply、edit、resolve、delete/deleteAll真实回调；edit保留作者日期；resolve处理父及直接replies；delete父级联直接replies | 是源宿主状态逻辑，不能直接认为本地草稿/HTTP已接入；首版不导入全族 |
| `editor/comments.ts` | nextCommentId、选区/词定位、marks的重叠IDs、remove同时清跨段block attrs、commentAnchors | 本地vendor同文件SHA256一致：`9bd8ef6b1d065e7aceafc27c2b56a9a016adb4ccd09d42bfaad2296bbad89e40`。可复用辅助，不把PM位置当服务端授权身份 |
| `packages/docx-engine/src/parse-package.ts:156–199` | comments及最终段paraId、commentsExtended parent/done回读 | 不校验重复id/paraId；按paraId建Map覆盖前项；未解释commentsIds/Extensible/people的语义 |
| `patch.ts:1445–1566,2774–2876` | comments全文清单保存、同段数文字patch、图片和关系、paraId、extended写入 | 未变批注优先原XML；换段数fallback重建；extended整part重建；不能盲用fullList保存 |
| `text-patch.ts:19` | `patchParagraphTexts`原段、run、链接保留；段数变化或无文字锚返回null，输出文字自检 | 直接相对模块导入，非index公开导出；不要复制算法或实现另一个文字patch器 |
| 本地 `bridge/edit-docx.ts:691,1792,1808` | 授权原文件、loadDocxZip、严格keys/hash/操作批校验、源saveDocx、已有保存后ZIP修补模式 | 当前没有批注写操作、来源comments target或comments选项；可加专用小helper，保持桥原有身份和保存入口 |
| 本地 `frontend/src/docx-main.tsx:178,237,277–285,341` | 原comments交显示层；修订intent已有PM持久属性、严格baseline投影、草稿恢复模式 | 不能修改parsed.comments数组假装草稿；当前批注只显示未形成保存协议；纯metadata编辑没有正文PM步骤，需专门history carrier |

源和本地 `patch.ts` / `text-patch.ts` / `parse-package.ts` SHA256分别完全一致：`42a30f34525620c3700d08883a47954111aceeaaf682ffd5f2ec5f1c4ba9a218` / `76dd463040080c6fead49d3cfaea66ead177b7b5a9179da62668297e82ee8a56` / `4fc4c90c043602cbd8fdda623d896d2a232c8d74f0d46f0c04ead1e0e82b6147`。这是复用证据，不是本地批注功能完成证据。

## 本轮真实保存与独立核验

`/tmp/word-comments-gap/probe.ts` 复用既有 `/tmp/word-review-gap/build-probe.mjs` 打包方式，直接导入固定源 buildDocx/parseDocx、PM converter、comments helper和saveDocx。最小PM schema由真实converter attrs/marks生成；仅用内存view dispatch，无DOM/React宿主。esbuild只生成/tmp探针，不是产品build。作者Alice、日期、initials、正文rsid、批注斜体+外部超链接、现代附属parts及extended未知扩展均作为哨兵。

| 真实源保存样本 | 独立ZIP/lxml及源重开结果 |
| --- | --- |
| `rich-edit` | `Edited & 中文`正确；斜体、超链接和rId保留；author/date/initials/paraId保留；正文不变。**commentsExtended未知属性x:keep及x:opaque被删除** |
| `rich-newline` | 同一批注改为两段后触发重建，文字正确、作者日期/paraId保留，但斜体/超链接消失；原comments.xml.rels仍保留，即剩余关系未再被使用 |
| `resolve-modern` / `reopen-modern` | 唯一真实paraId下，源重开done=true / false（false未显式返回done字段），正文不变；extended未知扩展仍丢失 |
| `duplicate-id-edit` | 两个`w:comment w:id=1`源条目均被编辑，最终两条均复制后项paraId=ABCDEF02；源不拒绝身份含糊来源。**不得按客户端commentId直接授权** |
| `duplicate-paraId-resolve` | 两个不同id共用ABCDEF01；输出两个同paraId commentEx，重开只有后项done=true；**不能把paraId单独当唯一身份** |
| `cross-reply` | 合法跨段父锚点保存在block的commentStarts/Ends，源`addReplyToCommentRange`只扫描文字mark，返回false；父批注保留，无reply创建。探针仍调用saveDocx用于观察保存，但真实reply callback会提前return |
| `cross-delete` | 清掉两个段的跨段端点、reference和批注条目；两个段均generated，原rsid丢失；commentsIds/Extensible仍原字节保留，可能残留已删除目标，**保留字节不等于关联正确** |
| `cross-add` | 从Alpha中部选到Beta中部，helper返回true；新id2在每段分别生成start/end/reference，合计各两个，非单一跨段锚；不把这种输出宣称完整跨段新建支持 |

9个输出ZIP均`testzip()==None`，每个XML/rels均独立lxml解析；所有输出的commentsIds.xml、commentsExtensible.xml、people.xml、comments.xml.rels及document.xml.rels与各自输入字节一致。所有9次传comments列表均使既有commentsExtended重建并丢未知扩展。它们只证明本次样本，不泛化到所有modern parts或Word客户端行为。

第10次 `adapter.ts` 宿主适配：源saveDocx保存原正文块（排除hidden结构块，沿用本地桥行为），**不传comments**；用源loadDocxZip及patchParagraphTexts将唯一目标comment原XML片段替换回comments.xml。独立校验只有 `word/comments.xml` 变化，所有其它parts逐字节保留，斜体/超链接、extended未知扩展和modern附属parts完整保留；源重开文字为`Adapter & 中文`；同工具对新增换行返回null。产物SHA256=`c230193b751b05a73005715a640d3ed59bc045f9f8dfb24543d332779069c56e`。这只验证适配保存可行性，不是生产身份校验实现。

证据与复现：

- `/tmp/word-comments-gap/results.jsonl`：9条源执行、PM、save plan、源重开结果。
- `/tmp/word-comments-gap/zip-lxml-evidence.json`：9个DOCX的SHA256、变化parts、批注元数据、锚点与实际XML。
- `/tmp/word-comments-gap/adapter-result.json`、`adapter-zip-evidence.json`：最小适配保存与独立保全结果。
- `node /tmp/word-comments-gap/build-probe.mjs`；`node /tmp/word-comments-gap/probe.mjs > /tmp/word-comments-gap/results.jsonl`；`.venv/bin/python /tmp/word-comments-gap/verify.py`。
- `node /tmp/word-comments-gap/build-adapter.mjs`；`node /tmp/word-comments-gap/adapter.mjs`；`.venv/bin/python /tmp/word-comments-gap/verify-adapter.py`。

未执行源Ribbon点击、本地浏览器、HTTP、桌面Word或生产鉴权；未验收图片/字段/跨故事复杂锚点；不复跑已有24次简单保存。

## 最小服务端来源绑定协议（下一步实施规格）

### 来源清单

服务端从**现有授权文档版本原字节**读取comments及正文锚点和parts relationships，不从客户端PM/comment数组推断。建立独立`commentTargets`，每项至少：

```ts
{
  targetId, // 服务端生成：绑定文档版本、comments part身份、XML序位、原comment XML hash
  expectedObjectSha256, // 原comment XML UTF-8 hash
  originalCommentId, author, date, initials, text,
  editableText, readOnlyReason,
  // anchor摘要只用于显示/将来能力；不扩大普通editableParagraph
  anchors: [{blockId, expectedObjectSha256, kind: 'range'|'crossParagraph'|'referenceOnly'}]
}
```

不把w:id、paraId、作者名或“所选文字”作为targetId。原文件SHA、revision和项目作用域继续沿用当前宿主授权，不能只靠target hash跨文档查找。虽然ordinal可使重复id在XML上定位唯一，首版仍拒绝重复comment id和重复paraId来源，避免显示层Map与锚点关联含糊；缺失id、孤儿/损坏relationship、未知命名空间绑定、受保护文档按明确原因只读。旧批注没有paraId，**纯文字编辑无需自动补paraId**，只要唯一原目标且patch能力明确即可；reply/resolve另行处理旧来源。

### 唯一新增操作

```ts
{ kind: 'editCommentText', targetId, expectedObjectSha256, text }
```

严格keys，不接受XML、part路径、comment list、author/date/initials、paraId、parentId、done或PM range。已有目标纯改文字不需要正文range；不能要求或信任客户端凭正文当前位置证明权限。同来源目标编辑最终归并成一条；text恢复baseline则删除intent；同操作重复target、冲突或未知target全部先拒绝，禁止后项覆盖前项掩盖错误。

整批先从授权原文件校验target及hash、目标唯一、保护、文本类型/大小/XML合法字符、支持结构。每个目标调用原`patchParagraphTexts`，返回null即拒绝该编辑，不走源fallback重建。匹配/定位用已有结构扫描工具，不能照抄探针简化正则为生产授权解析器。所有目标计划完成后，按原快照非重叠XML切片替换。保存时只把目标替换后的comments.xml放入当前输出ZIP，**不传options.comments**；非目标comment片段、root attrs、extended和关系原样保全。不因纯改文字创建或更新paraId/modern keys。

首版可仅允许一条批注编辑操作与其它正文/表格/节/notes/修订操作分开保存，减少组合授权风险；以后组合必须明确检查保存后来源仍一致。存量结构不受信时仅该目标只读，不能放宽普通replaceParagraph去覆盖带批注的正文。真正不支持的编辑请求可失败且不产生半份修改；此编辑校验失败不能迁移为发布验收失败时阻止现有文件签发。

保存后重开实际输出并独立核对：目标文字、author/date/initials/paraId、非目标comment片段、所有正文anchors和relationships、modern附属parts不变。首次真实HTTP验收必须核验下载字节；模型text变化不算成功。

## 完整批注族后续边界：每次一个缺口

| 下一独立缺口 | 最小授权op/target/range | 开放前必须解决 |
| --- | --- | --- |
| 已有批注纯文字编辑 | 本文editCommentText，唯一原comment target，无正文range | 本轮建议首先实施；严格patch与附属part保全、草稿/Undo/真实HTTP |
| 解决/重开 | `setCommentThreadResolved {threadTargetId, expectedObjectSha256, done}`；服务端签发线程成员与extended关联快照 | 唯一paraId/父子关系；旧无paraId不能沿用虚构键；原位更改done同时保留未知扩展，commentsIds/Extensible语义单独调查；reply级入口应先映射父线程 |
| 回复 | `replyToComment {threadTargetId, expectedObjectSha256, clientId, text}`；range由服务端父线程签发，客户端不可自定锚 | 新ID/paraId及作者时间由服务端分配；旧键修复；跨段父reply helper不可直接复用；线程附属modern parts一致性 |
| 删除回复/线程 | 分开的`deleteComment`/`deleteCommentThread`，目标签发明确受影响成员、完整anchor端点与各part身份 | 子级联必须明确scope；原XML局部删除保留段属性；现代keys清理；reference-only/跨段/重叠/重复ID不能静默扫全篇同id |
| 新建 | `addComment {clientId, rangeTargetId, expectedObjectSha256, from, to, text}`；首版仅单顶层简单段、来源UTF16文字范围 | 服务端块hash+文字hash+UTF16边界（不可切代理对）；PM mark/叶节点/修订影响映射，禁止跨段；书签/超链接/run边界保真；跨段新建另行协议，不能复用当前逐段重复id输出 |

作者是审计属性：编辑已有内容保留原作者日期；新建/回复作者与日期由可信宿主决定，不能让任意客户端覆盖。前端clientId仅用于临时草稿目标映射和幂等，不是OOXML id；服务端分配的正式id应随新版本重开返回。表格、notes、HF、文本框故事要分别有来源part/容器身份，不能用正文blockId假装通用range。

## UI草稿、Undo/Redo与恢复难点

源`editComment`和`resolveComment`仅改React comments数组；新建/删除/回复分别改PM mark和comments数组，两份状态并非天然同一Undo单元。直接搬源callbacks会出现Undo撤锚但批注仍在、恢复正文却漏metadata、保存未离焦输入丢失等问题。

首步文字编辑应把规范化的comment intent挂到**可进入PM历史的专用doc属性/事务**（复用本地notes/修订intent思路），面板内容由baseline comments+intent投影，不能双持可变parsed.comments。该事务不更改普通正文内容，不触发track changes录制。collector必须同时验证正文严格等于允许projection，新增属性不能被普通段落diff吞掉或变成replaceParagraph。编辑提交用closeHistory分隔，输入时机和撤销粒度明确；无变化不记历史、不写草稿。Undo/Redo读取同一intent载体并同步面板；恢复草稿先验证原目标身份，再重放投影，失效不能显示已保存成功。

切换目标、关闭面板、点击保存前必须flush尚未blur的文本；saving/readonly/closed期间禁止提交；异步面板打开期间保留target及原hash，来源变化即丢弃陈旧提交。后续新建/删除/回复需把正文锚变化与metadata intent放在同一个PM事务，并在恢复时从baseline重算；先不要以独立外部数组实现临时历史。

## 首步验收清单

只运行新增定向测试及必要相关契约，禁止完整套件重复运行。

1. 服务端身份：错文档/版本/hash、缺失/重复id、重复paraId、损坏/越界relation、受保护、未知target、重复/冲突操作拒绝；批内后项失败不产生半保存。
2. 纯文字：中文、emoji、实体、合法空白、空文本、同段多run/链接、既有多段不变段数；换段数量、无文字锚、未知/复杂结构明确只读或拒绝；作者日期initials/paraId不变。
3. 独立ZIP/lxml：实际HTTP产物仅comments.xml按授权片段变化；非目标comment XML、正文、commentsExtended未知扩展、Ids/Extensible/people、所有rels保持；所有XML有效。不能仅检查parseDocx结果。
4. 真实浏览器：面板改文字→Undo/Redo→草稿关闭恢复→未blur保存→HTTP下载→新版本明确重开；readonly/saving、无动作不记历史、陈旧面板提交、多个目标切换均有证据。
5. 若触及导出/签发，按AGENTS.md非阻断契约运行相关定向回归；任何批注验收失败不得扣留已生成且身份可读的PDF/Word链接。

以上是下一步实施规格及固定源调查证据；本轮没有新增生产操作或宣称批注族完成。
