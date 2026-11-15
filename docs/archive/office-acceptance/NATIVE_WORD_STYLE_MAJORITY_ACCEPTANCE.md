# 普通段落Ribbon样式的多数直接格式规则

本项A对齐固定源f8c17004的Ribbon/Styles Pane样式应用；正文/notes与样式组合B仍未开放，AI旧无flag入口保持pStyle-only语义。源Ribbon的 `ribbon-tabs.tsx:193–251 shedMajorityDirectFormatting` 原函数精确复用到本地docx-style-majority.ts（Apache-2.0）：按UTF16文本总长度计算，覆盖严格超过一半的bold/italic/underline/strike和docTextStyle color/sizeHalfPoints/font/fontAscii整段移除；恰好一半或更少保留。

首次持久化实际Editor RED保存在 `/tmp/word-style-majority-persistent-red.log`，证明原控件整段bold仍保留。源原文及临时对比证据见 `NATIVE_WORD_STYLE_COMPOSITION_INVESTIGATION.md`。

Ribbon控件同一transaction更新styleId并运行源函数，重复应用相同styleId也执行；本地NativeRibbonStyle段落意图扩展支持草稿/重复应用，docx-main仅注册该扩展，收集/replay接口不变。前端完整段必须等于可信来源规则投影，才发一条受限setParagraphStyle/ribbon:true。不存在客户端raw XML、runs或任意attrs透传。缺省ribbon保持旧样式行为，显式false/null/number/string均拒绝；原安全style catalog/hash/capability/保护/focus-time目标核验保留。

保存不能复用通用fontFamily:null，后者扩清所有字体槽；本flag后端按可信parsed Run（与源runsToInline的八项PM属性同口径）统计majority，针对来源w:r内部rawRPr定点移除实际产生被移除mark的属性，再合成pStyle。pPr/段落mark rPr不动，非目标raw子节点和空白保留；fontAscii只移literal ascii/hAnsi槽，eastAsia/cs/字体theme属性保留，不以目标style修改来源styles.xml。font主显示项可在重开后由保留的eastAsia/theme重新派生，这是保留这些非目标槽的结果。源已有独立字体槽不被通用清空，未声称所有重开PM字段恒null。

保真审查额外RED发现：少数run的w:b val=0被全段组删除误伤；`/tmp/word-style-majority-off-red.log`保留失败证据。最小修复保留显式b/i/strike off、u none/no-val及color auto/no-val这些没有源mark的节点。修后定向1项GREEN（`/tmp/word-style-majority-off-green.log`）。

前端新增4项及受影响style10项共14项GREEN（`/tmp/word-style-majority-front-regression.log`）；后续重复op拒绝变更再次运行新增4项GREEN（`/tmp/word-style-majority-front-final.log`）。覆盖source真实Editor、strict >50%阈值、少数强调、四项字体字段、rawRPr、重复同style、完整段等价、正文伪造、flag类型、undo/redo和草稿replay。首次tsc只发现新测试union类型问题，修后退出0（`/tmp/word-style-majority-tsc2.log`），最终统一tsc由root执行。

新/受影响ZIP首批25项GREEN（`/tmp/word-style-majority-zip-regression.log`），后补逐属性及pPr/全包保真4项GREEN和1项目录entry比较失败（`/tmp/word-style-majority-zip-preservation.log`）；该失败只因JSZip自动新增目录entry，非目标实际文件和pPr已保持，修为只比较实际文件，连同重复flag拒绝2项GREEN（`/tmp/word-style-majority-zip-final.log`）。再加显式off修复1项GREEN。独立新增22个场景、既有style10个场景按需要分段验证，未重复完整测试。

普通段落source inline若含noteRef、hardBreak等，Ribbon选取拒绝；source的未知inline/保护/危险style/伪造hash/客户端额外字段继续拒绝，style与任意正文/format/layout/notes同批也拒绝，未借本批开放B。

独立dev GUI入口 `smoke/docx-style-majority-gui-smoke.mjs`：真实源DOCX三字符bold、四项直接字体格式覆盖3/4，少数D italic。实际Ribbon选择样式后多数格式移除、少数保留；真实点击正文后撤销/重做、刷新草稿、Python patch保存下载ZIP回读、重开重复相同style再保存重开，两个新修订通过、非目标部件SHA不变、pageErrors=[]，4194释放。成功日志 `/tmp/word-style-majority-gui2.log`。第一轮Ctrl+z仍在select焦点未触发编辑器撤销的测试失败保留于 `/tmp/word-style-majority-gui.log`，修为真实点击正文再快捷键，未改产品撤销逻辑。

未自行build/static/commit/push；源码归属补充于vendor/genoffice-docs/SOURCE.md，LOCAL-SHA256.json同步该文件身份。

2026-11-10 环境恢复后，旧 `/tmp` 日志已消失；前述记录保留为之前运行结果，不冒称旧日志仍可读取。root重新最终构建通过（39.49秒，预算及预算contract均退出0），随后使用 `NATIVE_GUI_PREVIEW=1 DOCX_SMOKE_PORT=4194 node smoke/docx-style-majority-gui-smoke.mjs` 对当前静态产物验收，退出0。当前日志 `/tmp/word-style-majority-built-restored.log`，精简身份 `/tmp/word-style-majority-built-identities.json`。实际112个JS响应均200且与磁盘SHA相同；`lazy-docx-main-D7AvIywF.js` SHA256为 `1791d2afd5a2d0c1ce11127bf35b240e0f47eeeaf5e018a49825c31e07f4bfb5`；真实Python保存使用当前 `dist/edit-docx.mjs`（SHA256 `f9676a8457dab851b8e4bca762b4d282f06226ee3b663e803d0014225b98670c`）。

本次built完整覆盖真实Ribbon样式应用、点击正文后撤销重做、刷新草稿、第一次Python写回/下载ZIP回读、修订2重复应用同样式、第二次保存/下载及修订3重开；每次提交只有一条 `setParagraphStyle/ribbon:true`，多数格式清除、少数italic和非目标部件保留，`pageErrors=[]`。身份/修订HTTP使用替身路由，未把该结果当生产HTTP或桌面Office全面兼容验收。全量Word/XLSX仍有其他缺口。

本地生产SHA256（该文档记录时）：

- `smart_reporting/report_editor/frontend/src/docx-style-majority.ts`：`68894421703869cbc28d58b5e0420d580ba85ddbedc164c6b23151084e271131`

- `smart_reporting/report_editor/frontend/src/docx-styles.ts`：`ae900b9506a7630635bd13f1e63f50c46b92f5b29602932fdc910ccb3683793d`

- `smart_reporting/report_editor/frontend/src/docx-operations.ts`：`8b2a714ac417acd5cdef2ae9c5bd1338893bcc35bc94eb426323c71acbb85158`

- `smart_reporting/report_editor/frontend/src/docx-main.tsx`：`e0e35b92beea7359a8bec87bc59eeb3f7f13f808b54a33e408ed608599045073`

- `smart_reporting/reporting/slides_engine/bridge/edit-docx.ts`：`3320e866951a50a93b35feb6ae85c5c16b40f5b06e9271b8d93f504123605577`
