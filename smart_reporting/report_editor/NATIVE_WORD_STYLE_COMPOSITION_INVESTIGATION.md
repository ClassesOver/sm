# Word 样式语义与最终正文组合调查（仅设计）

2026-11-10。本轮只读生产取证，全部探针写在/tmp；未修改生产、永久测试、static或构建。结论需拆成两项顺序工作：先修本地Ribbon应用样式的源语义，再接最终runs+pStyle与notes组合。不能把本地现有“保留全部直接格式”当成完整固定源Ribbon语义。

## 当前明确缺口

| 操作 | 本地拒绝点与原因 |
| --- | --- |
| 普通段落style+正文/局部格式 | docx-operations.ts:476要求仅styleId变化，:478立即continue；normalizer不能提取正文 |
| style+现有layout/decor | 同一style-only比较拒绝，replay:670以及backend:1214要求style独占；decor自身也不允许style |
| notes来源仅改style或style+正文 | paragraphStyleEditable:680只接受simpleParagraphXml；noteRef来源capability=false，样式控件disabled；normalize noteParagraphLayout白名单未含style |
| style+finalruns | finalParagraphs从普通operations剥离，所以backend:1214不是唯一阻碍；:1253 note_body_batch_conflict也拒绝style |
| pageBreak+正文/格式/layout/decor/style | docx-operations.ts:506只接受pageBreakBefore单独变化，replay:689有同段互斥；backend:1225同段除锚定插入外均冲突 |
| notes+pageBreak | notes属性投影白名单未含pageBreak；backend先遇普通editable限制，notes并未获独立pageBreak能力 |

本轮只建议前两项顺序工作，不实施pageBreak或所有pPr任意组合。

## 固定源语义必须区分入口

固定源HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`，工作树干净。

1. Ribbon/Styles Pane：`apps/docs/src/renderer/components/Ribbon.tsx:1737` 调用 `applyGalleryStyle`；`components/ribbon-tabs.tsx:305`普通段落样式进入 `applyParagraphStyleId(:256)`，修改styleId后`:293`调用`shedMajorityDirectFormatting(:203)`。以整段文本UTF16长度为分母；bold/italic/underline/strike，以及docTextStyle的color/sizeHalfPoints/font/fontAscii，任一属性覆盖严格超过一半文本，则整段移除此属性。恰好一半或较少保留；计算只计text，marker不计。直接段落attrs仍保留，字符样式入口另行设置mark。此为源Ribbon语义。
2. AI applyStyle：`ai/style-ops.ts:354–418`遍历目标段落，只以`setNodeMarkup`应用styleId/必要节点类型，不调用majority shedding。不能为共享AI入口无条件增加Ribbon规则。
3. 本地`docx-styles.ts:97`仅改styleId，tooltip宣称“保留直接格式”。现有clear-all-formatting代码有相关多数覆盖行为，但不是同一操作：不得直接调用整套清除格式而额外清掉段落attrs或少数强调。

固定源SHA256：ribbon-tabs.tsx `d475b39d10a2b8dacfcf6a5293ec87f15e0a2d00b9d22d46f8e35ebb39e1cff2`；ai/style-ops.ts `373546e248a075774f01e9598f7b67ae905eb38d25dfffa96f4090b71b2d3fad`；packages/docx-engine/src/generate.ts `a339c97330a1551f3ca657f96b5abfd6d41473f9bdabddade3d62208be74e624`。

## 临时真实反例

`/tmp/word-style-composition.probe.test.ts`使用实际Tiptap Editor、完整pinned schema和本地真实样式select。普通Body键入新增，再select Custom，DOM文档确有新文本和新styleId，docxOperations拒绝“段落样式修改请先保存；同段文字和格式不能混用”；notes来源select实际disabled，强制设置attrs后normalizer拒绝。日志 `/tmp/word-style-composition-editor-probe.log`，一项探针通过表示成功观察既有拒绝，不表示缺口修好。

`/tmp/word-style-composition-docx-probe.py`用python-docx创建源内ProbeCustom普通段落样式，来源style-only实际成功并独立回读；style+finalruns报`docx_note_body_batch_conflict`，style+replaceParagraph报`docx_paragraph_style_batch_conflict`；先真实insertNote后，paragraphStyleEditable=false，style-only及style+body均报`docx_paragraph_style_unsupported`。完整错误与能力证据 `/tmp/word-style-composition-docx-probe-full.log`。

另用实际Editor比较本地select与固定源函数原文抽取：`/tmp/word-source-style-shedding.ts`逐字抽取源DIRECT_MARKS/DIRECT_TEXT_STYLE_ATTRS/shedMajorityDirectFormatting（该临时文件SHA256 `cccba8c86fa2c61473b3d42379552c38d925f2bacafbcb34319e41a1aaae495a`）。整段Body均bold，源函数应用Custom后去掉bold，本地select仍bold；RED日志 `/tmp/word-style-majority-red.log`。临时config为 `/tmp/word-style-composition.probe.config.ts`；没有把临时测试加入build/tsc。

## 顺序方案 A：先补Ribbon应用样式语义

保持现有源内普通paragraph style白名单（拒绝heading/numbered/循环/缺父/危险display）、来源hash、独立capability、保护和focus时目标身份。仅本地Ribbon样式select调用精确复用/归属记录的source majority shedding函数，styleId+shedding必须同一transaction，保留少数强调、opaque rawRPr、直接pPr和未选段。AI入口不改。不能把本项扩大成notes/layout/decor/pageBreak组合。

这项必须能独立保存，不能只让PM显示改对：样式提取要接受可由源majority规则证明的格式移除，输出既有`setParagraphStyle`和严格`patchParagraphRuns`（无正文变化）即可；后端仅对这类同段finalruns+pStyle开通最小组合。若使用专门本地意图标记验证majority来源，应只在草稿/前端持久化，不新增客户端raw XML。先测试51%/50%/少数、font/color/size各槽、未知raw保留、重复/撤销/草稿、保存重开，明确AI行为仍不同。

## 顺序方案 B：再补style+body/notes最终组合

复用方案A已核验的样式提取和最终runs+pStyle合成，扩展为有正文差分和注释生命周期；优先仅开该具名组合，style+layout/decor/pageBreak仍明确拒绝，避免一次解除所有pPr互斥。

- frontend source-only style catalog必须传入normalizer。当前noteParagraphLayout调用docxOperations没传styles，直接把style加白名单会在safeParagraphStyle(undefined, id)失败；需从main parsed.styles参数贯穿（共享main调用改动须root协调），plain adapter同样处理。仅抽离styleId，不吞其他attrs差分；paragraphStyleEditable仍独立检查。
- notes来源独立style capability须在notesPlanner可用、editableNoteReferenceBlock通过、源和目标普通段落style均safe时允许，保留全局editable=false；同一note的kind/id/hash/referenceIndex与finalruns生命周期仍由既有链路验证。禁止借此允许未知inline、损坏notes、保护、伪造样式或越界原XML。
- replay先恢复pStyle，随后从可信源恢复最终runs并canonical复验；分清来源paragraph attrs基线和当前已应用style attrs，不能对带新style投影当原来源hash。
- backend现有state.styleId晚期把`state.saved`重置为基于原XML的style补丁（:1432），放宽冲突会直接覆盖最终runs。改为若state.saved是generated，则对`<w:p>${generated.rawPPr}</w:p>`应用原paragraphStyleXml并回填当前rawPPr，同时设置generated.styleId；其余style-only XML路径保留。源generate.ts:2279遇rawPPr直接透传，因此仅改generated.styleId无效。无新wire协议、无二次parse/保存。
- metadata恢复分支:1652目前ordinary operations只有style时恢复core；finalParagraphs在另一集合。body+style真保存的core语义需显式测试，与style-only不触碰metadata区分，不能沿用“所有非notes部件逐字节不变”错误断言。
- 定向验收脚注/尾注增改删、普通正文、source marker原格式/唯一引用、同批删除保留文字、source styles.xml不改、直接pPr/非目标段落保持、style-only兼容、两方向/undo/draft/save/reopen；只按需要运行新增/受影响检查，最后root统一build。

本文件为交叉review输入；未声称已实现A或B，也不以调查探针计作通过的新功能验收。
