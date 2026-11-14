# GenOffice Docs 浏览器接入源码

- 上游：https://github.com/genspark-ai/genoffice
- 固定版本：`f8c17004fb730df11f0f743164ffd8b4281bb38c`
- 完整源码核对位置：`/home/junge/pros/genoffice-source-full`（仅开发环境路径）
- 许可证：见同目录 `LICENSE`、`NOTICE`。
- `SOURCE-SHA256.json` 记录原始上游文件的 SHA-256；`LOCAL-SHA256.json` 记录当前本地文件身份。原始清单并非修改后文件哈希。

本目录保留上游相对目录结构，提取真实 Docs Tiptap 扩展、OOXML → ProseMirror 转换、Worker 解析、文档样式、字体解析、分页测量与 PaginationPreview 的依赖闭包；DOCX引擎与共享 redact/zip 包通过项目 Vite/TypeScript 别名复用 `reporting/slides_engine/packages` 的同版本源码。未引入 Electron 桌面启动、IPC 注册或上游 AI 调用链。

浏览器适配：

1. `editor/extensions.ts` 的图片复制委托 ProseMirror 标准 HTML 剪贴板，删除桌面 `copyImageToClipboard` 分支。浏览器没有伪造成功的桌面桥。
2. `font-resolve.ts` 的指标 provider 默认为空，使用文档嵌入字体和上游静态字体指标/替代链，不访问系统字体 IPC。
3. `i18n/locale.tsx` 保留 React locale context，去掉桌面语言广播订阅。
4. `ai/style-ops.ts` 的 `AgentToolDef` 类型直接取自纯 `agent-core/types`，避免引入桌面 IPC 类型图。此处仅为编辑器扩展依赖，不开放上游 AI 执行。
5. `packages/font-metrics/src/browser.ts` 仅提取上游 `FaceVerticalMetrics` 接口；`packages/ui/src/browser.ts` 仅导出所需纯函数与字体/WordArt常量。未引入 Node 字体扫描器。
6. `scoped.css` 用 PostCSS 将原 `styles.css` 选择器加 `.docx-native` 前缀（`:root` 替换成该根节点，保留关键帧规则），防止上游桌面样式覆盖报告外壳。

2026-11-05 Word Ribbon 首批裁剪：`docx-home-source.tsx` 对应固定上游 `apps/docs/src/renderer/components/Ribbon.tsx` 的 Home 分支，保留原控件组顺序；控件回调由本地 Native DOCX 操作适配。图标复用上游 `components/icons.tsx`，中文 Home 标签只提取 `i18n/ribbon/zh.ts` 中实际使用的词条到 `home-zh.ts`。完整 Ribbon 依赖 Docs App closures、编辑服务和 `@genoffice/ui`，没有将这些桌面/宿主依赖带入；文件及图标 SHA 在 `SOURCE-SHA256.json`，本地裁剪词条和源文件身份在 `LOCAL-SHA256.json` 与 Task 2 brief 登记。

接入层 `docx-main.tsx` 保留真实 GenOffice 编辑器与分页预览；源文件及对象锚点均与服务端逐一核验，只有服务端支持的段落文字、整段基础样式、简单表格文字和段落插删映射为保存操作，其余修改显示原因并拒绝本次事务。原生草稿保存、发布、下载由本项目服务负责。分页预览是浏览器快照，完整桌面 Word 的版式一致性仍需独立验收。

2026-11-05 Word Insert 追加迁移：`docx-insert-source.tsx` 从同版本 `ribbon-insert-tab.tsx` 的 InsertTab JSX 提取页面、表格、插图、文本、链接、批注、页眉页脚和符号八组；保留原 SVG 图标与中文标签。Symbols 保留原 50 个符号、原面板结构和 Tiptap 文字插入回调，经现有 Native 文字操作保存；其他结构命令禁用并说明写回协议缺口，不导入尚不可持久化的弹窗/调色板。`insert-zh.ts` 仅提取对应实际使用词条。真实 Playwright smoke 已验证 Home 格式、段落增删、Insert 符号写入、浏览器下载、独立 DOCX 回读及修订 2 重开，原修订字节不变；授权与修订登记仍由 smoke mock，不代表真实 HTTP 发布验收。

2026-11-05 追加同步：上游今天新增六提交；本闭包交集仅 `editor/hf-dom.ts`，同步原生 PAGE 字段 helper `hfPageNumberOnly`。未导入桌面 ribbon/App。七个共享服务端包在上一基线至当前提交之间无变更。

2026-11-05 增量核对上游最新 `f8c17004fb730df11f0f743164ffd8b4281bb38c`：该增量中与 Docs 相关的三个文件为 `App.tsx`、`ribbon-insert-tab.tsx`、`editor/hf-dom.ts`，本依赖闭包仅包含最后一个；已升级该文件（新增 PAGE 单段页码 helper），其余两个由本系统宿主替代，未复制。未变更文件保留原版本SHA；单文件版本在原始清单明确标记。

2026-11-05 Ribbon increment: Home paragraph alignment maps the source `setSelectionAlign` behavior into an anchored `setParagraphAlignment` operation. The DOCX bridge changes only `w:jc`, preserves other paragraph properties, and rejects alignment edits on new unsaved paragraphs until a stable source anchor exists. Left/center/right/justify plus RTL, combined style edits, save/download/reopen and source preservation are covered by the DOCX brief and smoke.

2026-11-06 Word Home 行距菜单补齐关闭行为：原样迁入固定版本 `packages/ui/src/popover-dismiss.ts`，仅依赖 React；接入其 `useDismissablePopover`，由本菜单容器 ref 提供 inside guard，并启用 Escape。外部 capture-phase pointerdown、窗口 blur 和已有可选 shell 通知均复用上游实现，不新增事件系统或桌面依赖。原始与本地文件哈希均已登记，独立 Home 测试覆盖外点关闭、Escape、失焦、菜单内部点击和触发器切换。

2026-11-09 Home 大小写菜单迁入固定版本 `editor/case-transform.ts`（原样）；宿主仅开放同一来源正文段落内的选中文字，并要求整段字符格式统一、无链接及复杂内联对象，保证 replaceParagraph 变长转换的格式写回一致。菜单七项和关闭行为复用上游标签与 popover helper。

2026-11-10 普通段落Ribbon样式：本地 `src/docx-style-majority.ts` 精确复用固定源 `components/ribbon-tabs.tsx:193–251` 的八项多数直接格式移除函数（上游文件SHA256 `d475b39d10a2b8dacfcf6a5293ec87f15e0a2d00b9d22d46f8e35ebb39e1cff2`）。本地扩展仅记录来源Ribbon样式意图，完整来源段投影验证后以受限 `setParagraphStyle/ribbon:true` 保存；旧无flag/AI样式入口不调用多数规则。桥接来源XML仅移除命中的direct属性，保留少数强调、显式关闭、pPr及字体非目标槽/主题。该本地适配文件位于vendor树外，源码身份和验证记录在 `report_editor/NATIVE_WORD_STYLE_MAJORITY_ACCEPTANCE.md`，vendor文件身份仍由本LOCAL清单登记。

2026-11-10 Home全选源入口：固定源 `components/Ribbon.tsx:4534–4544` 的直接“全选”按钮接入本地Home，复用 `IconSelectAll` 和 `ribbonSelectAll/Tip`，命令仍为 `editor.chain().focus().selectAll().run()`；只读文档可选，不增加文件操作或草稿。宿主适配位于vendor树外的 `docx-home-source.tsx` / `docx-ribbon.ts`，定向记录见 `NATIVE_WORD_SELECT_ALL_INVESTIGATION.md`。

2026-11-10 分页快照机械抽取：PaginationPreview 内原 sliceHere 算法移至同renderer/pagination-snapshot.ts，Preview调用同一实现；未引入第二套分页算法。三项真实分页输入定向测试及Preview前后probe验证见NATIVE_WORD_INSERT_HF_INVESTIGATION.md。该抽取为首末页HF入口目标前置，不代表三入口已完成。文件身份由LOCAL-SHA256.json登记。

2026-11-10 共享测量前处理：同一pagination-snapshot.ts继续机械抽取Preview原zoom=1、列/垂直对齐中和、measureBlocks/liveSections/assignSections、尾注及浮动溢出计算；Preview消费者在同测量状态内完成克隆逻辑，finally恢复zoom/class。宿主按需等待当前字体、图片和一帧后调用同实现；正文/页面/HF身份在异步等待后需仍相同。真实Preview在单节及三节（连续节/重启逻辑页码12）抽取前后PageCut完全一致，详见HF调查记录。

2026-11-10 单栏跨节差宽接线：共享measurement的measuring-columns中和条件增加页宽/左右边距跨节差异，与源App measureSingleFlow对跨节width通道保持一致；保持colMode:none的单栏分页事实，宿主复用sectionWidthSpecs/pageDx和共享最大纸宽，避免正文/Preview/边缘测量叠加视觉transform。定向及真实ZIP验收见NATIVE_WORD_PAGINATION_COLLECTOR_PLAN.md。

2026-11-10 镜像边距宿主接线：共享measurement显式接收mirrorMargins，单栏同宽也中和source mirrorMarginSpecs视觉transform；Preview和宿主首末页测量均传同一parsed标记。宿主复用固定源mirrorMarginSpecs与pageMargins，按PageCut.pageNo（含重启逻辑页号）叠加位移与gap inset，保持colMode:none及来源HF身份。真实正文/保存证据见NATIVE_WORD_PAGINATION_COLLECTOR_PLAN.md。

2026-11-10 浏览器已加载字体指标：`renderer/font-resolve.ts` 仅新增 `setBrowserFontMetrics` 独立登记表，并在现有 installed 查询前读取命中项；未命中继续原有 undefined/static snapshot 回退，不启用或替换桌面 provider。宿主 `docx-bundled-fonts.ts` 仅对实际加载成功的两份原始 Noto CJK SC 资产登记由fontTools提取的真实指标，每次加载替换登记列表；文档 embedded 优先级与 resolve 算法保持来源实现。真实 `runFaceDecls` RED→GREEN、其他snapshot face前后相等、加载失败清理和文档嵌入优先验证见 `NATIVE_WORD_FONT_SCRIPT_SLOTS.md`。

2026-11-10 重复标题行：宿主vendor树外 `docx-tables.ts` 精确复用固定源 `apps/docs/src/renderer/editor/table-properties.ts:131` 的首行前缀toggle及active语义（原文件SHA256 `bbff51fa2da6198df69fb290b8dd5624c00c87713c381b32713d9cf36fd0001f`），不整体迁入桌面表格属性模块。只修改目标前缀repeatHeader/repeatHeaderEdited，保留其他attrs；严格Native操作setTableRepeatHeaders验证来源table hash、原行数和编辑前缀，直接XML补丁仅改tblHeader。普通和合并表均不依赖structureEditable；嵌套表独立anchor仍未接入。源码适配、32项窄测和真实Python保存证据见 `NATIVE_WORD_TABLE_HEADERS_PLAN.md`；未改本vendor算法文件。

2026-11-10 中文字体本地扩展：宿主内置三款 OFL 网页字体（LXGW WenKai、Ma Shan Zheng、ZCOOL XiaoWei），后两者补入 renderer/font-list.ts 和 text-layout/face-info.ts 的东亚名称判定，保证实时选择、布局与桥接脚本槽一致；不改上游原始身份清单。资产来源及授权见宿主 src/assets/docx-cjk/provenance.json。

中文字体度量补充：站酷小薇原始 OS/2.ulCodePageRange1 未设置中文位，但 cmap 含常用中文。宿主仅对已核验并实际加载的内置 CJK 资产向 setBrowserFontMetrics 显式传入 eastAsian:true；保留原始表指标及未传标记的默认推断行为。

2026-11-10 嵌套表文字本地适配：editor/extensions.ts 的 DocNestedTable 新增可选 canEditCell/validateParagraphs/onCommitError 宿主能力，默认无回调保留源入口；宿主仅开放已签发一层简单叶格。commit 使用段落数组逐项比较，保存锁和事务拒绝不静默丢字；transaction 更新输入能力。共享原 tdParas 机械移至无依赖 editor/table-input-paragraphs.ts，并抽取数组比较、提交回读比较和宿主输入岛 Ctrl+A（限定当前格）到同模块；vite 单独 native-docx-table-input chunk，不提高原render预算。源DOM段落读取逻辑未改变。独立嵌套来源清单、diff/replay、来源XML补丁均在vendor外，范围及证据见 NATIVE_WORD_NESTED_TABLE_BRIDGE.md 和 NATIVE_WORD_NESTED_TABLE_ANCHOR_INVESTIGATION.md。

2026-11-10 合并/拆分纯核心：从固定源 `apps/docs/src/renderer/editor/table-ops.ts:113–374` 精确摘录 GridCell 至 splitCellsInto 闭包为 `editor/table-cell-shape-source.ts`，只加 PM 类型/命令 imports 与来源注释，不迁入 UI/修订/桌面依赖；算法本体逐字保持。宿主 vendor 树外 `docx-table-cell-shape-core.ts` 严格验证矩形/步骤/每次网格预算，复用 PM mergeCells 和此 splitCellsInto，每个独立格拆分后将整数 twip 余数优先分配前列再投影 colwidth/colWidthsPct。段落 attrs/marks 原样沿用，新增空段清 docxIndex，bridge 以该属性存服务端来源 token；源规定的格式化空段跳过语义不变。SOURCE 清单记录完整上游文件身份（本文件为其精确片段而非完整副本），LOCAL 清单记录实际摘录文件身份。

2026-11-10 列宽纯fit迁入：`editor/table-column-width-source.ts` 精确摘录固定源 `editor/table-sizing.ts` 的 MIN_TABLE_COLUMN_PX、finiteWidth、fitColumnWidths 闭包，算法逐字保持，无UI依赖。宿主 `docx-table-column-width-core.ts`复用fit规则，从可信整数twip投影 `/15`，set按来源UI取整像素，均分未触floor/fit时保留原整数总宽，再按最大余数（同余前列）量化；受约束时量化源fit结果。bridge只改tblGrid/gridCol、tblW、各物理tcW的宽度属性值，不重建原段落/格属性；复杂continue内容原样保留。源码清单记录完整上游文件身份，本地清单记录精确片段。


2026-11-10 九宫格对齐编辑区继承修复（本地适配，固定来源 ref f8c17004 不改）：
`editor/extensions.ts` 的 editable tableCellSpec 将 td/th 的 CSS 对齐基线固定为逻辑
`text-align:start`，不再将 `cell.align` 的首段兼容投影作为全格可继承对齐。原 cell
attrs、转换与保存均保留。每个 PM 段落/list 已由 fromPmNode 绘制自身 align 或 tblPara
有效表格样式；空 align 表示其自身方向的 start，不能继承另一段落的旧 center/right。
这是修复固定来源渲染继承缺陷的本地差异，并非声称上游已实现。正文、明确段落对齐和
表格样式有效对齐不变；只改编辑单元格渲染，不改 read-only table renderer。
失败 built HTML 显示首格 th center、第1/2/3/5 RTL段落空 align 错继承center；实际
Chromium旧HTML最小修正证明这四段变start（RTL视觉right），其余段保right。
`docx-table-cell-alignment-render.test.ts` 首2例真实RED，扩展后5例GREEN，覆盖cell/header、
旧center/right、LTR/显式/推断RTL、明确center/right、tableStyle与固定converter重开基线，
并保cell attrs/正文。证据 `/tmp/cell-alignment-render-{red,green}.log`、
`/tmp/cell-alignment-render-browser.json`；本子任务未build，最终built复验由root统一执行。

2026-11-11 Word 新建文字批注宿主增量（vendor 文件不改）：
docx-comment-create.ts 复用固定 ref f8c17004fb730df11f0f743164ffd8b4281bb38c 的
review-actions.ts:169–232 和 editor/comments.ts:26–76 精确 UTF16 选区/空光标词范围、
取消、新根线程作者与 UTC 秒时间语义；docx-ribbon.ts 与 docx-insert-source.tsx 两入口
共用创建控制器及固定 IconComment。不将部分选区替换为全文段落，跨 run/跨段及内部普通
空段保持源范围。新增 createComment 走授权原 bytes core/薄桥，同 NativeDraft 历史恢复，
不调用 saveDocx(options.comments) 重建现代批注族；完整源码 SHA、RED/GREEN、真实 HTTP、
独立 ZIP/lxml 证据和当前复杂锚点边界见 NATIVE_WORD_NEW_COMMENT_ACCEPTANCE.md。
最终冻结构建已完成独立 Chromium 140.0.7339.16 闭环（API route 明确为 fixture，保存调用真实生产 Python/Node bridge）；证据 /tmp/word-comment-create-browser-final-20261111/evidence.json，ok=true。manifest SHA256 e13de64ff923e7fb122a0e0b053331d7de3729247c7526f1f32d859c3868b210；bridge SHA256 abe54d7c7306eb05a136e6b8caf7255f80e870ee3eee88fa154fb7245b30fd71；实际 lazy-docx-main-CQiXXdsv.js 为 188811 bytes、SHA256 e52351683defe418ad0cc0b6a8cfe950205ef815c1f495c8879a4ebe3ba5f8c9。122 个加载 JS response 原始字节与磁盘身份一致；取消、Undo/Redo、恢复、两条重叠部分文字范围、未失焦保存、实际下载与新修订重开通过，源文件不变，ZIP/lxml 确认仅 document.xml/comments.xml 改动且 XML 合法，四张截图已目视，浏览器错误列表均为空。真实 HTTP 鉴权专项、完整资产身份及当前复杂锚点只读边界见专属验收记录；跨段/普通空段/表格由各自 core/前端专项覆盖，不冒称本浏览器均重测。

2026-11-11 final2 入口连续性补验：PDF 修复后 root 最终 manifest 为 e2faddb5fb62f0db91b90b3248be4b8355ab5979d0b110eaa92dfde27dfe4daa，Word 生产源码/bridge 未再改。/tmp/word-comment-create-entry-final2-20261111/evidence.json 记录实际 native→docx-main 加载、中文批注双入口可见可用、源 IconComment 两条 SVG path 精确一致、122 个 JS response SHA 与当前磁盘一致、两图已目视且无浏览器错误。该分支零编辑/save/export，仅 fixture context/file 与空 operations preview；bridge 仅 inspect。docx-main 及 bridge 身份与前段相同；新 unified-main-Clb0faQN 为 SHA256 d0286a4a6e49c7f7aeac4cb40b903cb3c59c0d1c982ca049b4978504e690571a，native-main-CoBCbb8k 为 SHA256 5e89f510fe441d829ea9695e9673bd3048eab98c7df903acdead05e5a0c2c6a7。完整交互仍为 e13 构建证据，final2 只补最终入口与资产，不冒称再次完整保存验收。

2026-11-11 Word 已有批注回复宿主增量（vendor 原文件不改）：固定 ref f8c17004fb730df11f0f743164ffd8b4281bb38c 的 review-actions.ts:235–252 / editor/comments.ts:116–137 以新 ID 共享父真实文字范围，CommentInfo 必须带 parentId；parse-package.ts:155–201 与 patch.ts:2837–2860 通过最后段 w14:paraId / commentsExtended 的 w15:paraIdParent 保存真实父子关系。本地 docx-comment-reply.ts 前后端专属模块复用授权原 bytes、原批注目标 SHA、现有精确锚点与 NativeDraft/PM 历史/保存宿主；只给既有唯一根线程创建回复，不用普通根批注伪造回复。已有现代扩展只追加必需记录，原记录/people/未知 XML 保留；歧义/未知 schema 和复杂范围只读报因。源码 SHA、RED/GREEN、真实 HTTP/ZIP-lxml 与当前边界见 NATIVE_WORD_COMMENT_REPLY_ACCEPTANCE.md；统一 built-browser 结果待最终 manifest 后独立追加，不沿用此前新建根批注的交互资产验收。

2026-11-11 回复完整 built-browser：manifest 8c3baa3ed28283fb6e443e22b4590ee3ab82c38fd1f592a0bbcb06076c300a9c，实际 docx-main-HIBoZObN.js 196687 bytes/SHA256 e2c30f13d5a4ceb0145b9754e272fc85d077891e8a125161edec24140e143288，bridge 900ece6a48c11b43682cb9f9284cee1f5c3fa1aa64fabea52fdff81679fd8897。/tmp/word-comment-reply-browser-final-20261111/evidence.json 记录单次完整回复 smoke exit0、122JS响应SHA匹配、取消/历史恢复/未blur保存/真实父关联/下载/revision2重开、旧源拒绝，四图已目视、无浏览器错误；API route 为fixture，真实HTTP另有独立专项。目视发现回复状态行在解除瞬时锁后可能陈旧显示只读提示，已报告并新增严格RED，不把功能成功冒称零UI缺陷；修复与后续资产验收待追加。

8c3 回复状态提示缺陷已获 root 确认并做受限修复：持久 message 与瞬时 blocked 分离，锁解除后恢复正常提示；严格 controller RED→GREEN，4 passed（/tmp/word-comment-reply-status-{red,green}-20261111.log）。回复身份/OOXML/保存语义未变。最终新构建只做恢复草稿/锁解除/中文入口/逐JS SHA的status-only补验、零save/export，不重复完整回复保存整链；待新manifest后追加结果。

回复 final2 状态补验完成：最终 manifest 971b7a2a8eb3461e2cee46a38af23f544631c519c786902ac9d52e9106b646d9；实际 docx-main-_Yy5wQuN.js 196771 bytes/SHA256 dcaaeb6ad6fe701daf7ca2efa028197318d69055cd1ebf82ab92aaa8876ea8fa。/tmp/word-comment-reply-status-final2-20261111/evidence.json 记录 122JS 原始响应大小/SHA 匹配、中文回复入口/本地合法草稿恢复/真实editor锁解除后输入可用和正常提示、PM/草稿不变，0save/export、bridge仅inspect、无浏览器错误、两张截图已目视。bridge保持900ece6a48c11b43682cb9f9284cee1f5c3fa1aa64fabea52fdff81679fd8897。完整保存/真实父关联/下载/修订2重开仍归属8c3完整专项；final2只补状态修复和最终资产，不冒称再次完整保存验收。


2026-11-11 浏览器字体与 Word 行距身份分离（纠正 11-10 指标登记语义）：浏览器内置
woff2 加载成功仅证明可绘制，不再经 font-resolve 的 installed 回调冒充 Word 原生已安装字体。
browserFontFace 保留真实 ascent/descent/hheaTotal，cssFontFamily 仅对已加载且未被文档嵌入
字体覆盖的精确 family 保留实际绘制头；Word resolver、缺失字体替代和 lineFactorOf 的 1.3
规则保持固定源语义。fontChainMetricsPct 的真实字形盒测量不变。复杂报告同 SHA 的 BODY101
此前 4 行高 175.375px、行高 43.8381px，来自 Noto Serif 1.437×1.3 的误登记因子 1.8681；
源应用为 113.015625px、拉丁行高 27.5029px。专项 8 项 RED→GREEN，保留自选字体直接绘制、
拉丁槽、嵌入优先、加载失败清理和非登记字体快照。此处未运行公共 build，最终浏览器复验由 root 统筹。


2026-11-11 浏览器 CJK 绘制补齐 Word 拉丁槽：同一 browser-render 分支继续使用源
latinSlotTarget/latinSlotHead 前缀，使缺失 Noto 声明的 ASCII 走 KR Theme Latin GO，
而中文继续使用已加载的真实 Noto 资产；显式 ASCII 选择和 EA-only 继承槽不变。
仅迁移源 fonts.css 的 KR Theme Latin GO 原块，复用既有 Caladea-Regular.ttf，未扩迁其他字体。
adapter 专项先 3 项失败再 9 项通过。CDP 确认原应用 BODY101 实际命中 Caladea 318 glyph
与系统 Noto Serif CJK SC 7 glyph；去掉 Grid Strut 的单变量对照仍为 113.015625px，
本样本无增加 PUA Blank 的必要证据，故未引入。公共构建与最终宿主 CDP 由 root 统筹。

2026-11-11 隐藏页眉页脚测量作用域适配：固定源 hf-dom.ts 原默认仍将 probe 放在 document.body；新增显式 bindHfProbeParent 容器绑定，供宿主将探针置于 .docx-native 动态文档样式祖先内。绑定栈支持乱序释放、还原原有外部 parent；切换时更新测量缓存 epoch。宿主独立 docx-hf-probe-scope adapter 接线，无绑定的固定源码 app 行为不变。同 SHA7f4e32… 样本 header 保留高度30.1875→65.6875、effective canvasTop75.6→95.9541667，首页切点963.5568→905.7963833333333，与固定源同值。见 NATIVE_WORD_COMPLEX_PAGINATION_ACCEPTANCE.md。


## PDF text exports (2026-11-11)

The browser PDF export adapter uses the existing Docs parse/render pipeline and
these fixed-ref upstream serializers: renderer/export-markdown.ts and
renderer/html-export.ts. Ten previously absent relative-import source modules
were added without replacing existing local adaptations. SOURCE-SHA256.json
records their original source hashes. shared/ipc.ts is a local narrow extract
of the unchanged upstream MarkdownImage and MARKDOWN_MEDIA_DIR_TOKEN definitions,
plus a type-only AgentToolDef re-export from the existing shared source package;
it excludes unrelated desktop/AI protocol declarations. LOCAL-SHA256.json
records the resulting local files. Markdown images are replaced with their
verified parser-provided data URLs by the local browser adapter; no temporary
media folder is exposed. HTML is attachment-only. OCR is not enabled, and
content/layout/font fidelity remains pending manual review.

2026-11-11 标尺：原封迁入固定 f8c17004 的 components/Ruler.tsx、use-measurement.ts、units.ts；宿主 docx-ruler.tsx 仅开放可信单段右缩进及当前节左右边距，tabs/左缩进/首行/悬挂明确只读。导航页面使用既有同源分页快照及本地 continuous PM 呈现适配，不声称直接迁入依赖 live gap 的 NavPageThumbs。


2026-11-13 多级列表源增量：原样迁移 `list-presets.ts`、`components/ListDialogs.tsx`、`LengthInput.tsx`、`modal-keys.ts`、`system-fonts.ts` 与共享 `dropdown.tsx/.css`，固定提交不变。仅启用八套九级预设及 DefineMultilevelDialog；普通项目符号/编号库和设置编号值未因此开放。宿主 `docx-list-gallery` 管理来源快照、保存锁与 IME，并为窄屏限定局部滚动布局；原始文件 SHA 与当前本地 SHA 分别登记。详见 `NATIVE_WORD_MULTILEVEL_ACCEPTANCE.md`。

2026-11-14 审阅预设与比较：从固定 f8c17004 原样迁入 components/translate-langs.ts（22语言）及 editor/compare.ts（段落 LCS / 预览文本规则），原始和本地摘要均登记。适配位于 vendor 外的 docx-review-presets.ts / docx-compare.ts。预设沿用 Native AI 候选/显式采纳，整篇授权受可核验对象和100目标上限限制；比较为浏览器选本地 DOCX，复用源文本差异算法，不创建合并修订文档。复杂对象、story与保护范围不因入口接线放开。

2026-11-14 audit remediation: renderer/font-sizes.ts copied byte-for-byte from fixed f8c17004; native Home uses its language-specific size ladder and valid 1–1638pt range.

2026-11-14 table lifecycle: editor/table-ops.ts and components/toast-bus.ts copied byte-for-byte from fixed f8c17004. Native adapter uses the original splitTableAtSelection and PM deleteTable with source-bound, isolated save operations; unknown/complex tables remain unavailable.
