# Word 已有批注文字编辑：独立 core 专项验收

日期：2026-11-11。仅交付独立 core，不表示宿主、HTTP、UI或完整批注族已完成。按 [批注调查](NATIVE_WORD_COMMENTS_INVESTIGATION.md) 的首步范围推进，不更新原调查，不启用Ribbon按钮。

## 交付与接口

仅新增：

- `smart_reporting/reporting/doc_engine/bridge/docx-comments.ts`：纯字符串core，不IO、不写ZIP。
- `smart_reporting/reporting/doc_engine/bridge/tests/docx-comments.test.ts`：8组定向测试，含实际DOCX及独立ZIP/lxml。
- 本文。探针、日志及产物在 `/tmp/word-comments-gap/` 和 `/tmp/word-comments-core-*.log`。

```ts
interface CommentTextSource {
  sourceId: string
  commentsXml: string
  protectedDocument: boolean
}
inspectCommentText(source)
// => {commentTargets: CommentTextTarget[], commentReadOnlyReason: string|null}
resolveCommentText(source, operations)
// => {xml: string}，仅返回comments.xml替换结果，不修改source
```

单一操作严格keys：

```ts
{
  kind: 'editCommentText', sourceId, targetId,
  expectedCommentsSha256, expectedObjectSha256, text
}
```

`sourceId`由未来宿主绑定授权文档/版本/批注part/正文锚点来源，不是OOXML id，不是core自己证明过的权限。targetId由 `[sourceId, hash(完整原comments.xml), comment序位, 原comment XML]` 派生；每目标另带comment XML hash，不能凭w:id、paraId、作者或客户端PM范围命中。完整part任意变化均使旧目标失效。返回的originalCommentId、ordinal、author/date/initials及relationshipIds是宿主显示/核对材料，不接受客户端覆盖作者和关系。

来源级非法XML、未知实体、非法Unicode/数值引用、错误w命名空间、重复/缺失/非规范非负int32批注id、重复paraId、明确保护状态拒绝全部授权并给只读原因。目标级复杂结构保留原XML但只读，其它安全目标仍可签发。单条目标内部/跨条目重复paraId均拒绝，不假装按paraId可唯一识别。

首版允许comment→paragraph→run及inline hyperlink，保留pPr/rPr中明确列出的简单叶属性；其它结构、未知命名空间、局部xmlns重绑定、图片/字段/修订/制表符元素/未知属性结构、无成对w:t文字锚均只读。root与非目标兄弟中的未知扩展保留，不能因为它们“看不懂”重建或删除。已有多段可以编辑，但段数必须不变；w:t内已有CR/LF或其字符引用只读，避免与段落分隔混淆。新文本可含实体对应字符、中文、emoji、tab及合法空白；拒绝新增/删除段落、CR、孤立代理字符、XML非法字符。新文本限65536 UTF-16代码单元，批次限200个目标，源XML限4MiB；都在调用文字patch前校验。

resolve先整批验证身份、keys、目标唯一、文字/结构及段数，再复用同固定源版本的 `packages/docx-engine/src/text-patch.ts::patchParagraphTexts`。不写新XML生成器，不走源comments全清单fallback。发生迟到非法操作不返回部分XML，不改变source。无变化操作返回完全相同XML；多目标按原始位置从后向前替换，目标外raw字节不变。

## 宿主必须完成的边界（本轮未做）

core只知道传入的原XML和宿主声明的保护状态，**没有核验**用户/项目/文档版本权限、真实part位置及唯一comments关系、ZIP路径身份、实际文档保护、正文锚点、外部超链接关系。未来桥必须从授权原文件重读并验证这些条件，不能接受客户端source对象/保护状态/XML/关系作为证据。`relationshipIds`可帮助宿主在comments自身rels中核验hyperlink，不能替代该核验。

推荐最小接入方式：在现有授权保存入口整批规划；不传 `saveDocx(options.comments)`；其它保存完成后，仅将core返回XML写入已核验的comments part。不要更新commentsExtended、commentsIds、commentsExtensible、people或作者属性，不放宽普通editableParagraph。未知复杂来源只读，不应阻止已生成且实际身份可读取的PDF/Word链接。

源 `loadDocxZip`可复用加载/限额工具，但会做OOXML规范化与重复style refs清理。宿主若要求raw part保真，必须比较工具加载的part与授权原包原字节；检测到规范化差异时不能冒充原始comments XML签发身份。本轮固定源生成的规范OOXML样本没有此差异。core本身不调用loadDocxZip或saveDocx，不会隐式规范化整个文件。

未接入 `edit-docx.ts`、公共parse、frontend、delivery或dist。UI草稿/Undo/Redo、未blur flush、保护锁与HTTP下载重开留待下一阶段；回复/新建/删除/解决/重开不在本轮交付。

## TDD及实际文件证据

先写测试并确认缺模块失败：`/tmp/word-comments-core-red.log`。实现首轮6组通过后，新增未知实体用例确认失败：`/tmp/word-comments-core-entities-red.log`，补字符/实体校验；新增w:t内嵌换行用例确认失败：`/tmp/word-comments-core-line-red.log`，补只读边界。最终8组全部通过：

```sh
smart_reporting/reporting/doc_engine/node_modules/.bin/tsx --test \
  smart_reporting/reporting/doc_engine/bridge/tests/docx-comments.test.ts
```

最终日志：`/tmp/word-comments-core-green.log`。覆盖来源绑定、确定性目标、非目标part改变使身份失效、批内迟到invalid/重复/冲突、strict keys、保护、重复id/paraId、未知prefix/局部重绑定、富文本结构只读、实体/emoji/空值/多段段数/内嵌换行、实际DOCX保全。实际DOCX测试使用源buildDocx及loadDocxZip；lxml独立解析全部XML/rels，并逐part字节比较，验证只有comments.xml变化、目标外未知siblings及hyperlink/斜体仍存在。

另有保留的core实际输出，复用调查时固定源ref `f8c17004fb730df11f0f743164ffd8b4281bb38c` 生成的modern来源。不是手工修改“期望输出”冒充core：

- 输入：`/tmp/word-comments-gap/rich-edit-source.docx`，SHA256 `a7085fc4bcbd112c7896808817f92ea6478d0f9dc8e55da5904ab6a74df78ccb`。
- 执行：`/tmp/word-comments-gap/core-probe.mts`，真实调用inspect/resolve并将返回值写入源ZIP。
- 输出：`/tmp/word-comments-gap/core-edit.docx`，SHA256 `28013912bd7777a96e1eaf70615edaf8f4f9859704543d9573b810a3e7abfb1f`。
- 模型与操作：`/tmp/word-comments-gap/core-evidence.json`。
- 独立校验：`.venv/bin/python /tmp/word-comments-gap/verify-core.py`；证据 `core-zip-lxml-evidence.json`、`verify-core.log`。

独立ZIP/lxml确认所有XML/rels合法，目标文字=`Core 😀 & <中文>`；斜体及超链接保留，**仅word/comments.xml变化**。正文锚点、rsid、comments.xml.rels、document.xml.rels、commentsExtended未知扩展、commentsIds/Extensible/people全保留原字节。此证据只证明纯文字局部编辑不会触碰关联parts，不证明这些parts的所有语义或桌面Word视觉行为。

未运行产品build、全图tsc或完整测试；未commit/push。没有因core独立测试通过而宣称Word批注族完成。
