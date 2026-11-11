# Word Insert 页眉、页脚、页码入口调查

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 源语义

- `components/ribbon-insert-tab.tsx:1151–1275`：页眉/页脚按钮各打开菜单“编辑”“删除”；删除提交 `{text:''}`。页码菜单包含顶端/底端各左中右六位置、设置页码格式、移除页码。位置调用源 `hfPageNumberOnly(align)`，移除使用源 `hfHasPageField` / `hfWithoutPageMarks`，该源helper只移PAGE_MARK（legacy首个#），保留NUMPAGES/SECTIONPAGES和文本；不能用本地HF专页strip全部域helper冒充同源行为。
- `components/Ribbon.tsx:4566` 传给 InsertTab 的 `hasDoc` 是 `canEdit`，因此这些修改入口在只读文档中禁用。Home全选的 `hasDoc` 与此不同。
- `App.tsx:7631/7636`：页眉写首节，页脚写末节。变体来自实际页面边缘：`doc-state.ts:94 restingHfAreaVariant`，页眉 titlePg 时取first；页脚单页且titlePg时取first，否则开启奇偶不同且最后逻辑页码为偶数时取even，其余default。
- “编辑”通过 `openHfEditor(kind)` 进入实际首/末页边缘条，对应part，不能不带目标地打开默认header面板。
- “页码格式”调用 `openPgNumModal`，初值及应用目标是光标所在节的 `pageNumberFmt/pageNumberStart`，与页眉首节/页脚末节目标不同。decimal写缺省，起始页码空写缺省，否则非负整数。

## 本地现状

- Insert三个按钮永久disabled；仅有controller按光标activeSection提供HF数据，`DocxHeaderFooterSource` 内部part/variant默认header/default，不能直接复用无参数切tab冒充源目标。
- 现有 `DocxHeaderFooterController` 提供valueOf/onCommit/linked及flushPendingEdits；多节controller可靠地解析继承归属、严格锚点、解除链接和草稿组合。应复用其底层路径并传显式节，而非新增宽松写回协议。
- 现有 `docx-layout-source.tsx` 已有光标节页码格式dialog和严格setSectionLayout，可提取复用同一控件状态/渲染，不应另造第二套校验。Insert六位置及移除应复用源hf-dom helper。
- 本地正文没有常驻的分页布局/最后逻辑页码状态；分页预览通过 `PaginationPreview` 临时测量分页。不能把段落数当页数，也不能把末节页码设置直接当最后页码。完整边缘变体需复用源分页测量/section页码分配事实，这是当前接线的真实前置缺口。

## 空值ZIP实际验证

2026-11-10 使用真实python-docx源文档（页眉Header、页脚Footer、正文Body），经 `inspect_docx` 取得真实部件身份，提交现有 `setHeaderFooter(text='',pageNumber=False)`。`patch_docx` 保存后重新inspect页眉为空、页脚仍Footer；原部件/关系仍存在，正文和页脚字节不变。实际变化为 `word/header1.xml` 和常规保存的 `docProps/core.xml`，日志 `/tmp/word-hf-empty-part-probe.log`。

这证明源“删除页眉”所用空值表达已有协议，不需为按钮专门增加ZIP部件删除。首次探针错断言只变header而因core元数据变化失败；修正边界后通过，未改生产。布局表格/图片等复杂HF空值是否与源一致仍须各自验证，不据普通HF结果推广。

## 最小设计与验收顺序

1. 先复用源分页事实形成明确edgeTarget(part)：首/末节、对应first/even/default、有效继承归属、当前值和能力。目标对象须捕获sectionId/part/variant和来源身份；菜单开后光标节变更不得静默换写目标。无可信分页事实时不能伪造default为已对齐。
2. controller复用现节编辑内部函数，增加显式目标入口；HF面板支持进入指定part/variant，切换前flushPendingEdits。Insert菜单保留源结构和关闭行为。
3. 位置和移除复用源helper；空值删除用已有onCommit。页码格式单独复用光标节dialog。保留危险HF、只读/保存、来源身份和继承保护。
4. RED覆盖三个现disabled入口；后续验证六位置、空值删除和页码移除、格式当前节、实际单页首页/多页奇偶末页、多节继承/节切换、草稿保存重开及非目标部件。不能只靠菜单出现或HF专页已有功能计完成。

本项目前仅调查和真实空值ZIP探针，未改HF生产代码或协议。

## 共享分页前置实现（2026-11-10）

实际源进一步核对：App的edge areaView对header/footer均传同一global titlePg，file-actions从parsed.titlePg初始化；parse.ts使用整个documentXml的xmlFlagOn，并非分别按首末节。本地按节HF已有更精确行为；该差异须在宿主明确选择源兼容或登记本地适配，不能默默把single global当各节事实。

已将Preview原sliceHere机械抽取至vendor `renderer/pagination-snapshot.ts` 的 `slicePaginationSnapshot`；再将原zoom/class中和、measureBlocks/liveSections/assignSections/尾注/浮动溢出前处理抽为 `withMeasuredPaginationSnapshot(input,consume)`。Preview使用同helper，不复制第二套分页。消费者保持测量状态，finally恢复zoom/class。新增3项分页输入GREEN（逻辑页码重启、continuous及first/even），2项测量GREEN（真实DOM重新读取、消费者异常恢复）。

真实Chromium对抽取前静态Preview及抽取后dev Preview取PageCut快照，单节1cut完全相等（`/tmp/word-pagination-before-built.log`、`/tmp/word-pagination-shared-measure-dev.log`），三节fixture含显式分页、continuous和最后节重启12/首页不同/奇偶不同，4cuts逐字段相等（`/tmp/word-pagination-sections-before-built.log`、`/tmp/word-pagination-sections-after-dev.log`），各pageErrors=[]。不是只比较算法源码。

`resolveDocxEdgeHfTarget` 接收真实cuts和可信section锚点，按源visiblePageCount和最后cut.pageNo、restingHfAreaVariant返回首/末节明确身份；4项真实算法及边界GREEN，缺失/无效分页不猜default。

宿主独立 `measureCurrentDocxPagination` 输入共享measurement+slice参数，等待fonts.ready、当前图片decode和RAF；等待前及每次等待后检查pm连接与宿主stillCurrent闭包，完成真实测量后再检。无缓存、无隐藏Preview、无调试global读取。5项定向GREEN覆盖就绪顺序、开始过期、字体等待后文档变化、图片等待后HF变化、帧后host移除；`/tmp/word-measure-current-green.log` 和 `/tmp/word-measure-current-image-stale-green.log`。当前统一tsc退出0（`/tmp/word-measure-current-typecheck.log`）。

三个Insert入口本身的真实Editor/Ribbon RED已落 `src/docx-insert-hf-entry.test.ts` / `/tmp/word-insert-hf-entry-red.log`，仍待controller/菜单主入口集成；上述共享前置不能当HF完整交付。未增加HF写回协议。

## main prepareEdges 接线（2026-11-10）

root将多节controller封装为可信sectionId绑定factory，不移动正文selection；新增 `forSection` 供边缘目标使用。main `prepareEdges` 先flush未提交HF内容，捕获正文doc引用、草稿操作串及activeSection（当前canvas纸张几何随光标节变化），再调用真实on-demand测量。保存/关闭/dispose、正文/布局/HF草稿变化、几何节切换均使仍在等待的请求失效。

测量传当前各节布局与页码草稿，HF高度使用同继承解析器与当前草稿值，global titlePg由当前各节标记any合成以对应源初始whole-document parse行为；源运行时单global toggle与本地按节修改之间仍有语义差异，不声称已验证所有混合节场景。HF面板须保留按节状态，显式边缘target不得静默降为default。

main两项新增定向先RED（prepareEdges缺失），实现后GREEN：固定首末节controller、准备不移动选择/不写草稿、HF变化使assertCurrent拒绝、dispose不迟到提交；`/tmp/word-main-edges-red.log`、`/tmp/word-main-edges-green.log`。另几何节切换失效1项GREEN，`/tmp/word-main-edges-geometry-green.log`。这些main用测量stub只验证接线，真实分页算法及Preview测量由上述独立证据覆盖，未把stub当端到端。最终tsc退出0 `/tmp/word-main-edges-typecheck-final.log`。菜单与最终GUI保存重开验收仍由root集成后执行，不能据此计完整入口交付。

## 菜单集成后的定向验证

root接入Insert源三个dropdown、显式HF面板target和共享页码格式dialog后，独立 `docx-insert-hf-menu.test.tsx` 12项GREEN（`/tmp/word-insert-hf-menu-green.log`）：六位置精确目标/变体、删除提交空值、移除仅PAGE保留NUMPAGES/文字、捕获身份过期拒绝、关闭后异步旧结果不复活、只读禁用。页面格式dialog复用原布局组件的校验，未新增写回协议。

真实dev Chromium/Python保存链：

- `/tmp/word-insert-hf-fields-zip-gui.log`：普通单节三次保存/下载/重开，Insert移除PAGE保留NUMPAGES/文字；footer center覆盖为PAGE；显式编辑footer后通过Insert页码格式设置upperRoman/5并保存；独立lxml验证实际ZIP `instrText` 和 `w:jc`，正文/页眉保留。
- `/tmp/word-insert-hf-title-gui.log`：单页title文档页眉和页脚均命中first，两个真实保存重开。
- `/tmp/word-insert-hf-even-gui.log`：双物理页文档末页footer=even、首header=default，两个保存重开。
- `/tmp/word-insert-hf-multi-zip-gui.log`：多节首末不同内容，光标保留末节，footer正确写末节even/right（逻辑页码12），header仍写首节default/left；页码格式单独只写当前末节，所有非目标HF ZIP部件SHA保持。两次保存/下载/重开。
- `/tmp/word-insert-hf-delete-gui.log`：源菜单依次删除页眉、页脚，空值严格操作，两个保存/重开，非目标正文保留、footer字段清空。

各场景 `pageErrors=[]`。HTTP身份/修订仍为替身；Python patch和ZIP回读实际执行，不据此声称生产HTTP或复杂Office全兼容。复用入口 `smoke/docx-insert-hf-gui-smoke.mjs`（DOCX_INSERT_CASE选择上述分支），built模式具备每个JS200/磁盘SHA检查，尚待最终静态构建后验收。

生命周期review另发现真实BUG：Insert精确边缘target在离开HF时未清除，之后正文换节再手动HF仍编辑旧边缘。真实main/Ribbon新增测试RED（`/tmp/word-hf-target-lifecycle-red.log`），最小修复离开HF先flush、再清target，GREEN（`/tmp/word-hf-target-lifecycle-green.log`），最终tsc退出0（`/tmp/word-hf-lifecycle-typecheck.log`）。Insert直接进入显式目标不变。

生命周期修复另有真实dev多节GUI通过：`/tmp/word-insert-hf-target-lifecycle-gui.log`；离开显式footer后切Home、正文首节，再手动HF正确跟随首节/default，原有两次保存/ZIP非目标部件保留继续通过，pageErrors=[]。仍待统一静态构建验证。

明确剩余分页缺口：当前native Preview/prepareEdges均沿现有colMode:none路径，尚未接入源App脚注/尾注动态布局collector及完整多栏canvas状态；大脚注/尾注/复杂多栏可能改变末页奇偶。这些继续属于全量对齐目标，未通过禁用排除，也未以本批普通/多节夹具结果声称已验证。

下一阶段只读调查、源行号和最小接线/失败探针规格见 `NATIVE_WORD_PAGINATION_COLLECTOR_PLAN.md`，探针尚未执行，不作为通过证据。

## 最终静态构建验收（2026-11-10）

root 统一build完成后，`NATIVE_GUI_PREVIEW=1` 分别运行 `hf-insert` 与 `hf-insert-edge-multi`，均退出0。日志 `/tmp/word-insert-hf-final-built-ordinary.log` 与 `/tmp/word-insert-hf-final-built-multi.log`；两场景各112个实际加载JS均200并与磁盘SHA匹配，`builtChunkIdentityVerified:true`、`pageErrors:[]`。共同main `lazy-docx-main-BZ9sjlxA.js` SHA256 `7ec6a30152ecc227e080078b3ea4b6870ec2b33d7d8f9fe7c7d8034014725c3f`，提取身份 `/tmp/word-insert-hf-final-built-identities.json`。

ordinary覆盖移除PAGE保留NUMPAGES/文字、footer center、显式footer编辑、upperRoman/5三次实际Python保存/下载/重开及ZIP字段；multi覆盖首末节区分、最后逻辑页12/even、格式仅当前末节、非目标HF SHA不变，并执行离开显式footer/切Home/正文首节/手动HF回归首节的生命周期路径。本次未重复未变的select-all整链。脚注尾注/多栏剩余缺口及HTTP替身限制继续成立。

随后root仅调整Vite的Zod叶子chunk以修复另一入口初始化循环，Word行为源码未改；新build做窄初始化/Insert页眉菜单探针，`/tmp/word-hf-cyclefix-init-built.log` 退出0、pageErrors=[]、saveRequests=0，112实际JS均200/SHA与磁盘匹配。新main `lazy-docx-main-7WHzFgdf.js` SHA256 `375ba64df179c7c82a5d0e696ad164ae4827d637d0ad587d3de03ba2204e9d4e`；保留上述旧构建双完整保存链证据，未重复执行。
