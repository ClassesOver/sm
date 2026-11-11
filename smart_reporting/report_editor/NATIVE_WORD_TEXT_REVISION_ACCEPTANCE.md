# Word 简单正文修订：core 阶段验收与宿主接入备忘

> 后续状态：宿主、草稿及修订列表已接入，见 [集成验证](NATIVE_WORD_TEXT_REVISION_INTEGRATION_VERIFICATION.md) 与 [built 验收](NATIVE_WORD_TEXT_REVISION_BUILT_ACCEPTANCE.md)。下文保留 core 阶段记录；其中“尚未接入”仅描述当时状态。

日期：2026-11-10。**当前仅完成原始 XML 决策 core 及引擎保存证据；尚未接入 HTTP、草稿 collector、恢复、Undo/Redo 或 Ribbon，未完成 UI 闭环。** 本轮宿主处于冻结构建阶段，本备忘只读调查宿主，没有修改其生产入口、公共 index 或构建产物，没有执行应用 build、完整测试、提交或 push。

## 固定来源与交付文件

- 固定源：`/home/junge/pros/genoffice-source-full`，实际 `git rev-parse HEAD` 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
- 同源工具：固定源 `packages/docx-engine/src/revision-xml.ts` 与本地 `reporting/doc_engine/packages/docx-engine/src/revision-xml.ts`，实际 SHA256 均为 `c992c97b1395c55ba4990bfeb218c16aceaac75e8ebd7304e789024d2e8be6db`。
- 新增实现：`reporting/doc_engine/bridge/docx-revisions.ts`。
- 新增专项测试：`reporting/doc_engine/bridge/tests/docx-revisions.test.ts`。
- 调查基础：`NATIVE_WORD_REVIEW_INVESTIGATION.md`。该文档的 24 次固定源探针属于前轮调查，不计为本轮 core 或宿主验收。

## 已实现 API 与保证

```ts
inspectTextRevisions(block, blockId, protectedDocument = false)
// {reviewTargets: TextRevisionTarget[], revisionReadOnlyReason: string | null}

resolveTextRevisions(block, blockId, operations, protectedDocument = false)
// {xml: string, resolvedRevisionIds: string[]}
```

每条 operation 严格只接受 `{blockId, expectedObjectSha256, revisionId, action:'accept'|'reject'}`。宿主操作的 `kind:'resolveTextRevision'` 尚未实现；未来适配必须剥离 kind 后调用 core，不能直接传额外键。

`revisionId` 为 `SHA256(JSON.stringify([blockId, 原段 XML SHA256, wrapper 序号, wrapper 原 XML]))`，不是原 OOXML `w:id`。目标提供 `originalRevisionId/type/author/date` 作为描述信息；重复甚至完全相同的 wrapper 仍有不同目标身份。blockId 应由宿主以既有 `SHA256(sourceSha256 + ':block:' + docxIndex)` 签发，不由客户端选择。操作只授权原快照里的单个目标，不能传入 XML、路径、filter、作者范围或 all。

core 先校验全部操作及唯一性，再按 XML 位置倒序处理，迟到的无效/陈旧/重复/冲突目标不会返回部分成功 XML。它不修改传入 block，不执行磁盘写入。接受插入保留运行及其格式；拒绝插入删除对应包装及内容；接受删除移除对应包装及内容；拒绝删除恢复运行并由同源工具将 `w:delText` 恢复为 `w:t`。同源工具只收到已验证的目标 wrapper，避免整段执行时的 move marker 清理波及非目标。

范围为顶层正文 p 块中直属的简单 `w:ins/w:del`，包装内仅运行与简单文字/tab/br/cr。普通段落 editable 能力没有被放宽。段内复杂修订或嵌套来源整体只读，避免呈现“接受全部”已完成的假象。

| 来源限制 | 明确 reason |
| --- | --- |
| 非段落块、无原 XML、无有效 blockId | `docx_revision_block_unsupported` |
| 保护文档 | `docx_revision_protected` |
| XML 无效、DTD/注释/处理指令、不支持的片段结构 | `docx_revision_xml_unsupported` |
| 块内声明/重绑 namespace | `docx_revision_namespace_unsupported` |
| move、属性/编号/节/表格修订及冲突/范围修订家族 | `docx_revision_complex_unsupported` |
| ins/del 不直接属于段落或存在嵌套/段落标记修订 | `docx_revision_nested_unsupported` |
| 修订包装缺失原始 w:id | `docx_revision_id_missing` |
| 图像、字段、复杂包装/运行，或属性值含字面 `>` | `docx_revision_payload_unsupported` |
| 目标内字面 `<w:rPr></w:rPr>` / `<w:trPr></w:trPr>` | `docx_revision_empty_properties_unsupported` |

最后两项属于源工具边界：扫描器不能可靠处理属性内字面 `>`；调用末尾会清理字面空 rPr/trPr。首版拒绝授权这些来源，避免损失原属性。自闭合 rPr 不受该清理规则影响。非目标 rsid、未知 XML、运行属性、书签、批注锚点、其它修订及 ZIP 部件在已验向量中保留；没有声称任意复杂 OOXML 均可编辑。

重要调用前提：core 只持有块 XML，不能证明该块位于授权文档顶层，也不能看到继承自 document/body 的 namespace。宿主必须从授权原 DOCX 重新读取块，核验 document/body 的 w 命名空间、顶层归属及保护状态，并传入 `protectedDocument`。默认参数 false 不代表 core 已核验文档保护。

## 实际验证与日志边界

从 `smart_reporting/reporting/doc_engine` 实际执行：

```sh
node --import tsx --test bridge/tests/docx-revisions.test.ts
```

RED 阶段空实现返回 0 个目标，首项断言为 `0 !== 2`；4 项失败。随后完整实现 GREEN。空 rPr 来源另行加入用例时先失败（实际 reason 为 null），再添加明确只读守卫后通过。最终一次专项执行输出摘录如下：

```text
✔ four decisions preserve exact surrounding XML and independently reopen actual ZIP/XML
✔ validates whole snapshot batch before returning XML and rejects stale conflicting or unknown input
✔ unsupported structures have explicit read-only reasons
✔ single quotes and identical wrappers have deterministic source-bound identities
ℹ tests 4
ℹ pass 4
ℹ fail 0
ℹ duration_ms 1186.932195
```

以上为**实际工具输出摘录**，当时没有重定向到日志文件，没有为补日志重复执行测试。测试每个方向使用真实 DOCX ZIP、saveDocx 和 parseDocx 重开，并调用独立 Python zipfile/lxml；其 `/tmp/docx-revision-*` 临时产物由测试 finally 删除，不能引用为仍存在的证据文件。曾执行两新增文件范围的 `git diff --check`，无输出；文件当时未跟踪，该命令不等于完整类型检查或完整 lint。

为补足可审阅的留存文件，另执行一个独立证据探针，未重跑测试套件。持久证据目录：`/tmp/word-text-revision-core-20261110/`。此目录是容器临时证据，不是仓库交付资产或永久存储。

从仓库根实际执行：

```sh
node --import /home/junge/pros/smart_reporting/smart_reporting/reporting/doc_engine/node_modules/tsx/dist/loader.mjs /tmp/word-text-revision-core-20261110/probe.ts > /tmp/word-text-revision-core-20261110/probe.log
.venv/bin/python /tmp/word-text-revision-core-20261110/verify.py > /tmp/word-text-revision-core-20261110/verify.log
```

探针直接调用本轮 core、真实 buildDocx/parseDocx/saveDocx，不经过 bundle、dist、HTTP 或 UI。生成具备批注部件及关系、书签、中文/实体/emoji、插入粗体、删除斜体、相同 w:id 的修订、未知属性及 opaque customXml part 的来源。

| 实际留存路径（均位于该证据目录） | 内容 |
| --- | --- |
| `source.docx`、`source-block.xml`、`targets.json` | 原文件、原段、实际签发目标 |
| `accept-ins.docx`、`reject-ins.docx`、`accept-del.docx`、`reject-del.docx` | 四方向实际 core 保存文件 |
| `accept-ins-expected.xml` 等四个 `*-expected.xml` | core 返回的目标段 XML |
| `manifest.json`、`probe.log` | 操作原文、文件 SHA256/size；真实探针输出 |
| `zip-lxml-evidence.json`、`verify.log` | 独立 ZIP/lxml 回读结果及摘要 |
| `probe.ts`、`verify.py` | 可复现的探针与独立校验脚本 |

`verify.log` 实际内容：

```json
{"verified": 4, "evidence": "/tmp/word-text-revision-core-20261110/zip-lxml-evidence.json"}
```

四文件 ZIP CRC 正常，全部 XML/rels 可独立解析；文件 SHA256 与 manifest 一致；仅 `word/document.xml` 字节发生变化；非目标 ZIP 部件逐项相等；独立 C14N 比对实际首段与 core 预期段一致；rsid、书签/批注锚点、未知 sibling XML、另一条非目标修订与 sibling 段均保留。接受插入保留粗体，拒绝删除恢复斜体及空白/中文/实体。没有验证桌面 Word 视觉或真实 HTTP 下载。

## 下一阶段宿主接入方案（只读拟定，尚未实施）

这里的 core-index 指 `reporting/doc_engine/bridge/edit-docx.ts` 的 `model()` / `indexed` 能力链；没有另一个同名 core-index 文件。以下符号均以当前源码实际位置为准，行号随共享区后续修改可能变化。

### 后端能力、操作与保存

1. `edit-docx.ts` 的 `sourceZip`、`blocks = parsed.blocks.filter(block => !block.hidden)`、`blockId()`、`indexed`：从授权来源 ZIP 核验 w 命名空间的实际 URI（包括 document/body 继承或重绑），只为真实顶层段调用 `inspectTextRevisions(block, blockId(block), !!parsed.protection?.enforced)`。不将客户端 XML/作者/filter 交给 core。
2. `model()` 的 `blocks.map(...)` 注入独立 `reviewTargets` 与 `revisionReadOnlyReason`，可选全局能力 `simpleTextRevisions`。保留现有 `editable/readOnlyReason/paragraphLayoutEditable/deletable` 语义，不用 revision 能力把含修订段变成普通 writer 可写。复杂来源没有可编辑目标时仍显示具体 reason；不能把目标数组为空解释成“文档没有修订”。
3. Python `reporting/delivery/docx_native.py::_OPERATION_KINDS` 加入明确的 `resolveTextRevision`；`patch_docx()`、`_invoke()`、`report_editor/native.py` 现有授权/expectedSha256、输出身份回读继续生效。仅 TypeScript 分支改动会先被 Python allowlist 拒绝。
4. `edit-docx.ts` 的 `blockOperations` / `operations = await Promise.all(...)` 校验处先做 `keys(op, ['kind','blockId','expectedObjectSha256','revisionId','action'])`，用 `indexed` 重定位原块。建议把该类操作按原 blockId 分组，每组剥离 kind 后**一次**调用 `resolveTextRevisions`，在所有普通操作和全部修订组均完成校验之后才进入 `states` 应用。core 已拒绝同目标重复或相反决策，不应 last-write-wins。
5. `states`、`state.saved`、`finalBlocks`：每段只应用一次合并后的 `{kind:'xml', docxIndex, xml}`。不能逐条 core 调用后反复覆盖 state.saved（会丢同段先前决策）；也不能把第一次返回 XML 填回 block 再用原 hash 和原 revisionId 调第二次（快照身份应失效）。合法同段多 target 共用原 expectedObjectSha256，core 在原快照上一次规划，倒序定点写回。
6. `operations` 后现有 `*_batch_conflict` 守卫附近加入修订段冲突检查。首版同段只允许多个互不重复的 resolveTextRevision；与 replaceParagraph、patchParagraphRuns、format/clear/style/link、note body 更新、deleteParagraph，以及同锚点 insertSectionBreak 等结构操作互斥。须同时检查 `finalParagraphs`、`notesPlan.blocks`，不能只扫描 blockOperations（patchParagraphRuns/note 已被提前剥离）。跨段正常操作可保留；插入型/节型操作若影响对应段索引或节边界，首版明确拒绝组合，后续单独扩大。
7. 保存后、最终 `writeFile(...,{flag:'wx'})` 前，仿照 `verifyTableAltTextResult` 所在回读区，从实际输出 parseDocx 查对应 `state.saved` 在 `finalBlocks` 中的位置，核验该段原 XML 等于本组合结果，剩余/非目标目标保持正确；插段使块索引变化，不能直接拿原 docxIndex 作输出数组索引。应有宿主失败注入证明迟到无效不写输出。
8. `operations.every(...)` 的 `docProps/core.xml` 保留分支需要纳入该定点修订类别，避免宿主默认 metadata 更新令已证明的“非目标 ZIP 保持”退化。其它部件应按实际输出逐项验证。

这些错误是**编辑请求输入/身份校验失败**，不要把它们接成报告发布门禁：已生成且身份可核验的 PDF/Word 下载仍遵守 AGENTS.md 的非阻断规则。若改到发布/签发链，必须执行既有对应非阻断回归；本 core 阶段没有触碰该链。

### 前端能力注入、collector 与恢复

- `frontend/src/docx-main.tsx::WordModel`、`createDocxEditorView()` 的 `visible` / `anchors.push({...anchor,docxIndex})`：沿既有来源文件 hash、块 XML hash、blockId 校验注入目标能力；`frontend/src/docx-operations.ts::DocxAnchor` 新增独立修订字段。普通 editable 仍为 false。
- vendor `editor/revisions.ts::RevisionRange` 仅有 from/to/kind/author/date 等，没有服务端 revisionId 或 OOXML w:id；`collectRevisions()` 产生 PM 范围，不能直接按作者、文本、w:id 或返回数组顺序映射服务端 XML wrapper。相邻同属性 wrapper 可能成为同一 PM mark 范围，跨 run 范围也可能拆分，当前 core 目标模型本身没有提供 PM 映射。这是下一阶段必须补齐的映射契约，不是已有 UI 能力。
- 建议新增明确的“原 XML wrapper → PM 源片段”映射及投影校验：从已验证 source block，按 wrapper/run 的真实贡献范围产生精确片段，以服务端 revisionId 绑定；同源 `applyRevisions()` 仅作受信目标的预览执行。不唯一映射时显示只读理由；不能把两个 wrapper 因 PM 合并就隐式接受两条。
- 建议新增纯 `docx-text-revisions` 投影/规范化模块，在 PM doc 或段落 attrs 存 `nativeTextRevisionOperations` 一类历史意图，并注册 rendered:false 的明确属性。意图须与预览变化处于同一历史事务；复用 vendor `TRACK_IGNORE`，避免接受/拒绝动作本身被 Track Changes 再记为新修订。不得只把决策存进脱离 PM history 的可变数组。
- `docx-main.tsx::collectOperations`、`Guard.filterTransaction`、`onUpdate`：在普通 diff 前规范化修订投影，校验当前节点严格等于“基线 + 已授权目标决策”的投影，将普通 diff 中该段还原为基线并附加独立 resolveTextRevision 操作。这样 Guard 不会因原段只读阻止合法预览，也不会把意图伪装成 replaceParagraph。普通 diff 的 notes/normalizePlainDocxRuns 两条 fallback 均不能绕过该校验。
- `docx-operations.ts::docxOperations()` 的早期 same 判断、缺失节点/delete 检查及普通段落分支均须兼容“合法修订投影”；原段删除最后文本不等于 deleteParagraph，仍应保留空段身份。无动作时意图为空，不能写草稿/历史。
- `docx-operations.ts::replayDocxOperations()` 及 `docx-main.tsx` 的 refresh 草稿重放链：先严格校验整批原目标、重复/冲突和互斥，再由原基线一次重放同段目标，校验结果，恢复对应意图。不能将每条操作轮流套到“已修改基线”并以原 snapshot 权限授权。现有 note / patchParagraphRuns 过滤不应吞掉修订操作。
- `setSaving()`、Guard、draft.saving/draft.closed/context.editingEnabled 继续锁定动作。Ribbon 上首版只开放明确目标的接受/拒绝，未实现全篇/作者/范围/其它 story 就保持只读并给原因，不显示“全部修订已处理”。

## 下一阶段仍须实际验收

宿主 request allowlist、文档 namespace/保护、重复/陈旧/越权和批内迟到失败不写输出；同段双目标合并和同段普通操作互斥；PM 映射在重复 ID、相邻同属性 wrapper、重复文字、多 run、emoji 下不扩大目标；真实浏览器决策→Undo/Redo→草稿恢复→未离焦保存→HTTP 下载→明确新修订重开。四方向实际输出及非目标保真必须继续独立核验。当前文档及证据不替代上述宿主和 UI 验收，不据此移除整族 Word 审阅缺口。
