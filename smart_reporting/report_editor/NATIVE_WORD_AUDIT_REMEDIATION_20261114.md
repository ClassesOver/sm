# Word完整审计整改进度

固定源：`f8c17004fb730df11f0f743164ffd8b4281bb38c`。基准为[全入口审计](NATIVE_WORD_EXHAUSTIVE_GAPS_20261114.md)。这是实施增量，不是844行全部关闭声明；原审计保留当时源码证据，下面的范围及[增量索引](word-parity-audit-20261114/remediation-index.json)覆盖同ID旧状态。

完整逐行当前结论可直接读取[机械合并台账](word-parity-audit-20261114/current-command-index.json)，不用手工交叉索引。原始行字段完整保留，新增 `baselineStatus/effectiveStatus/scope/evidence`；局部整改不关闭未声明的目标/组合，第三至五批已按下文限定构建/场景验收，第六批亦按下文普通表格场景完成限定验收，未声明的命令与组合不据此关闭。

## 第一批已落地

| 能力 | 具体变化与范围 | 剩余边界 |
|---|---|---|
| Home格式 | 折叠光标使用stored marks，不再重写整段；只有随后键入文字带新格式。A+/A-复用固定源中文/日文/西文阶梯，字号输入及桥接支持1–1638pt。 | 子编辑器、复杂目标、未保存富段落另批；未宣称源连续点击合并渲染优化全等价。 |
| 视图 | Web版式、阅读/退出、深色页面偏好、源滚轮/触控缩放分类；阅读时锁主编辑器、嵌套输入与内容事务，退出仍尊重原保护/权限。 | 多页编辑、分屏、完整状态/GoTo仍缺。 |
| 偏好与自动更正 | 五单位选择与持久化、六规则开关和重置，复用已有存储；自动列表同事务保留来源段落属性并绑定真实编号定义，支持Undo/Backspace。 | 复杂来源/受保护目标维持明确门禁。 |
| 表格样式 | 无样式、五预设、文档样式、六look选项、选择状态/UndoRedo；setTableStyle校验来源与原XML，仅改指定表格，独立保存。 | 合并/嵌套/grid-gap/修订表仍只读；与其他编辑需分别保存。 |
| 域 | 选中DATE/TIME/PAGE/NUMPAGES/FILENAME可编辑指令和刷新缓存；限定安全MERGEFORMAT开关；所选/全部代码显示与Alt+F9不写文档。 | 不接受任意危险/嵌套/复杂指令，完整字段种类与正文右键菜单仍另批。 |
| 邮件合并 | 逐记录ZIP、Avery/自定义格标签DOCX、信封ZIP；会话授权、CSRF、已登记CSV独立回读，输出SHA/尺寸独立核验后下载；不创建正文修订。单文档支持平面IF/NEXT/SKIPIF和拆分/simple域。 | 仍仅登记UTF-8 CSV；嵌套/跨段/NEXTIF、多节模板不支持；NEXT/SKIPIF在逐条/标签/信封模式明确拒绝；复杂标签内容拒绝而非静默丢弃。 |

## 定向验证

- Home三条新行为先RED后GREEN；相关前端五文件96测试通过，`/tmp/word-remediation-front-related.log`。新增下载身份校验2测试通过。环境有既有JSDOM Canvas提示，不把提示写成产品失败。
- preferences14、view14、field frontend8+bridge7、table-style frontend9+bridge3专项通过；邮件合并bridge13、Python16、前端15专项通过。上述数字含交叉执行，不相加冒充唯一总数。
- 原生宿主字体与表格样式12测试通过，`/tmp/word-remediation-table-font-host.log`。其中第二张相同表格定位及210pt真实OOXML写回先RED后GREEN。
- 评论来源模块只有扩展名导入/never类型修复，类型检查通过；其14测试使用仅替换缺失绝对Python路径的临时副本通过，原测试文件未改，不冒充原命令直接全绿。
- 完整TypeScript+Vite构建通过，`/tmp/word-remediation-batch1-build`；492个JS分包通过原预算，Word主分包240002字节<256000。重用独立懒加载边界，未提高阈值。两条生产bridge入口均已打包。
- 独立审查未发现可确认的新增Important；不等于全面功能或格式保真认证。

## 真实浏览器、HTTP与文件证据

`/tmp/word-remediation-table-field-20261114/result.json`：真实表格BlueHeader保存修订2，再PAGE→DATE保存修订3，恰好两次成功保存。首次verifier误把“无shd”当“auto”失败后，只重开已下载最终文件，无重复保存。186资源身份一致，浏览器异常为空。独立lxml/python-docx验证仅目标改变、其他ZIP部件/页眉页脚/邻文保全。

- 表格修订SHA：`a4300f85f7be29d3679b8d4f5da1f5b10f2224ad9c5469da820c3e56d26049e6`。
- 域修订SHA：`cd472aebf5fd17ce2853da350e4b6ae0d009bc6fed21761e136cf2f0ff1a613f`。

`/tmp/word-remediation-view-mail-20261114-run3/result.json`：实际Home不改旧字、Web/深色/滚轮/阅读退出、单位/自动更正；实际CSV上传与三种输出下载，187资源SHA一致，0保存/0修订/0页面异常。独立回读Ada/Grace、邻文、标签表格与信封尺寸。先前两次为styled-label/filechooser定位错误，不计产品失败或重复输出验收。

`/tmp/word-remediation-view-mail-20261114-protected/result.json`：真实受保护来源进入并退出阅读，仍不可编辑，输入不改变正文；186资源身份匹配。

这些服务测试使用真实FastAPI授权/工作区/发布与下载链，仓储为限定内存fixture；不认证生产仓储或模型质量。浏览器使用绝对FONTCONFIG_FILE指向既有canvas-fontconfig.conf。两次修订仍携带native_source_review_pending，已核验产物照常签发下载，不标业务验收通过。

## 第二批：布局与首次保存前富段落

已落地 `docx-page-setup.ts`、`docx-margin-dialog.tsx`、`docx-new-rich-paragraph.ts` 和同名 bridge：适中/镜像/Office 2003/最近自定义页边距、镜像开关与内外侧标签；自定义纸张宽高 144–31680 twips、当前节/全文范围，页边距保留最小正文区域。`insertRichParagraph` 校验新增普通段落/标题/列表的来源邻接身份、已绑定样式/编号、受支持 runs 与段落属性；保留加粗等 marks、居中等段落格式、Shift+Enter 与空段落待输入格式，不再笼统拒绝新增段落富格式。Enter 不复制来源段落身份，公式目标元数据不随 split 复制。

范围仍小于源：只支持白名单字体/文字/段落属性及已有可信样式/编号；每段最多 1000 runs / 20000 字符；任意新建链接、域、图片/其他内联对象、图片项目符号与未知属性仍拒绝；第三批另为Enter/插图分割已有可信来源段落建立 typed source-run 引用路径，以保留继承的链接/域/原始格式，不能据此推论任意新建对象均可写入。普通单元格富格式、新段落的每一种工具栏/对话框入口、HF/文本框等活动子编辑器接线未因新增 writer 自动全部完成。

真实验收 `/tmp/word-remediation-layout-rich-20261114/result.json` 为 `ok:true`：镜像页边距修订2与新增加粗居中段落修订3，**累计恰好两次成功保存**；恢复既有镜像结果后本次只保存富段落，不重复保存镜像。独立 lxml/python-docx 回读确认镜像设置、边距、新段落加粗/居中以及页眉页脚、表格和原段落保全。资源身份清单 SHA `a31658c1cb092082456e0a28006890a3519203deeb73d5f4fb631a9a662a913a`，页面异常为空。

- 镜像修订：`9a1ecf2bb98373b7b4f0f8d1e060919c2428d0460e5fa41138b56ade0ae13bd8`。
- 富段落修订：`47748049684f794c81178207aa3918970514f067d97a91ba1fb49ea685ef848e`。

该真实场景只证明镜像与新增加粗居中段落的保存/下载/重开；不代替所有预设、字段边界及跨节组合矩阵。两修订业务核验均仍为 `native_source_review_pending`，下载签发保留，不标业务验收通过。

## 第三批：正文右键与图片文件拖放

当前源码已接通 `docx-context-menu.ts` → `docx-context-actions.ts` → `docx-main.tsx`。鼠标右键保留指针内已有选区、选中实际图片或移动到指针位置；ContextMenu/Shift+F10 在光标处打开；冻结 doc/selection/目标并复核只读、保存、IME、异步读取与目标变化，提供焦点恢复和完整销毁。嵌套 `.ProseMirror` / `.doc-nested-table` 不认领正文菜单，保留浏览器原行为。

已接原生回调：剪切/复制/两种粘贴、字体/段落、五类可信域编辑/更新与代码显示、编号重新开始/继续/指定值、已支持表格命令与属性、图片本地查看/保存、可信超链接、批注新建/删除/根线程回复、正文修订接受/拒绝/开关及选择段落翻译。每项沿用原生来源门禁；接受/拒绝明确标为“受支持的正文修订”，翻译明确整段/整格授权并须采纳，**不是源全部 story/任意选区语义已对齐**。

第三批当时未接整表删除/拆分；第五批已按下述限定范围接通。第六批另已按下述安全来源范围接通插入/删除单元格对话框；当前右键仍禁用的真实缺口：调整列表缩进与逐级菜单；同义词、隐藏/取消隐藏；图片环绕与层级的右键回调；解决批注右键回调。底层已有环绕、批注解决等其他入口，不重复称为整个功能不存在。桌面拼写建议/忽略/加入词典/字典语言 IPC 未接，浏览器拼写开关不等于这些回调。超链接打开仅走原生安全目标策略；完整源书签/TOC跳转不据此关闭。

`docx-image-drop.ts` 已接 OS 图片文件坐标拖放：PNG/JPEG/**GIF**（仅空 MIME 时扩展名回退），按来源顺序复用原生插图/解码/校验/保存链；8MB 上限。写为**独立正文图片块**，不是源内联图片等价实现。仅可信顶层正文段落目标；表格、嵌套编辑器/其他 story、未支持原生来源和同时操作仍有门禁；批次可部分成功，失败需明确反馈，不承诺原子多图导入或动画/GIF全矩阵保真。

18项菜单 Editor+DOM 定向测试通过，包括嵌套编辑器隔离、选区冻结、只读、IME、焦点、图片 DOM 命中与原生范围说明。异步剪贴板目标复核58项、NativeSplit12项、typed source-run前端7/bridge7/native2项，以及插入顺序修复相关前端74项与混合/边界/table-tail15项定向验证通过；这些是有交叉的专项，不相加冒充唯一总数。独立审查无确认的Important，不等于全面认证。

真实来源暴露并修复了两个边界：Enter/插图分割继承的 `rawRPr` 及域/链接必须经可信来源引用保留，不能因白名单误拒绝或直接接受任意客户端XML；同来源区间内图片、新段落和尾随表格必须共享插入顺序，不能各按对象类型排序。修复采用公共插入区间/顺序辅助及 table-tail 混合优先级。最终 TypeScript+Vite 构建 `/tmp/word-remediation-batch3-order-build` 通过，496个分包，Word主包248347字节，原有预算全部通过，未提高阈值。

### 第三批真实浏览器与独立文件验收

`/tmp/word-remediation-context-drop-corrected-20261114/result.json` 为 `ok:true`：复用已经成功保存的所选域结果，再从该精确字节重新导入、签发新grant后执行修正的GIF拖放流程；不重做所选域修改。191个资源与最终构建身份匹配，资源清单SHA `cfa8505ce257f4f75e3e8b6e45a969ca893b7ee32611f602fdb42c547f8bd54b`，页面异常为空。Enter/Undo及阅读模式打开图片后Esc保持阅读模式也通过。

`independent.json` 独立回读确认：只更新选定NUMPAGES缓存为1，旁边PAGE缓存7未动；GIF媒体字节完全保留；插图分割前后的文字和pPr/style保留；无关ZIP部件与HF保全。此结果不代替全右键回调、所有图像来源、动画呈现、内联/表格/story目标及组合保存矩阵。

- 原先所选域成功保存SHA：`48aa97a027f9c41062ce41a75cd89aaab71a6e5d31b0f5a2032629b7b99dc1be`。
- **错误排序产物保留，验收不通过**：`cbdb812a00a118738f5b7357cc76ec55ae4137460218bedefa982a4d9ea46112`；原证据在 `/tmp/word-remediation-context-drop-20261114`，不能把HTTP成功当文件验收通过。
- 必要修正后GIF保存SHA：`836eaf8aec440e3674ad28a40449f39c4bd8dffc5f9869cdbf8c7349994f6d2f`。其receipt为**重新导入上下文的revision2、parentRevision1**；fixture文件名 `drop-r3` 不是全局修订3。

第三批跨原流程与必要修正累计**3次成功HTTP保存**：所选域1次、错误GIF1次、修正GIF1次。修正流程本次新增恰好1次保存；错误GIF只计保存行为，不计通过验收。已生成产物照常保留下载，成功与错误产物的业务验收标识分开，`native_source_review_pending` 不冒充业务事实与完整版式核验通过。

## 第四批：New / Save As 的独立文件范围

`native_word_file_actions.py`、`native_api.py` 和 `native-api.ts` 已实现授权/CSRF/来源SHA绑定的新建与另存为 API。新建复用固定源 blank builder；另存为复制**已保存来源修订的原始字节**，通过原生导入链创建独立文档，不覆盖旧修订。文件名只接受合法 `.docx` basename；不接受磁盘路径。请求与来源身份绑定，复用既有幂等和导入检查。

这不等于桌面 Save As 的任意磁盘目标、加密保存或把内存草稿隐式并入副本。当前 `docx-file-actions.ts` 已由 `docx-main.tsx` 懒加载并接入文件页的新建/保存/另存为；另存为在有未保存修改时明确禁用，提交前flush并再验，创建后只提供同源校验过的“打开新文档”链接，保留当前文档与草稿。新文档displayName已接 FILENAME 域、导出标题和原始下载文件名。这里确认源码接线，不把API或按钮存在当成真实浏览器验收。第四批真实浏览器 `/tmp/word-file-actions-20261114-run2/result.json` 为 `ok:true`：新建空白后首次输入、保存/下载/重开，再以 Unicode 文件名“独立烟测副本.docx”另存为独立文档并重开；副本 ID 独立，字节与已保存修订完全一致，脏草稿时另存为禁用，最初来源文件未变。累计**恰好1次成功保存**，恢复验证时重建限定内存fixture并重新签发grant，没有重复修改或保存；187个资源身份匹配，页面异常为空。

- 新建后保存与另存为副本同SHA：`4e73ace0ccad5a1d8818c93212e5027dd27c35a82e84ca2f9465ea69f5e75404`。
- 原始来源SHA：`7749d878bbd497ded2f066aaf99277a329aff9799d1561d9786f820051a69602`。
- 资源清单SHA：`1d0de47336716ea76457979b6faa87dd9e2a9ddaf2820e9dadf57f7117b34223`。

该浏览器证据服务的是冻结 `/tmp/word-remediation-batch3-build`；**不覆盖随后 `docx-file-actions.ts` 文件名160字符/校验的窄修订**。窄修订25项专项与最终构建通过，不能替换相应浏览器场景。首次harness尝试未发保存请求、无保存receipt；恢复只补验证。仓储仍为限定内存fixture，不认证生产仓储；已保存修订仍携带 `native_source_review_pending`，下载保留，不标业务验收通过。New/SaveAs仍按已保存修订/独立文件范围记为 `partial`，不升级整个桌面文件族为 `aligned`。

## 第五批：整表删除与拆分表格（普通顶层表格限定范围已验收）

`docx-table-lifecycle.ts` 与同名 bridge 已实现独立保存的 `deleteTable` / `splitTable`，操作绑定可信 `blockId` 与原始表格 SHA；只接受普通顶层矩形表格。拆分行索引为 `1..rows-1`，不接受首行或越界。前端删除复用 PM `deleteTable`，拆分复用新纳入的固定源原始 `table-ops.ts`（及 `toast-bus.ts` 依赖）；下表重置来源身份与替代文字，两表间插入空段落。删除文档唯一表格时留下 schema 必需的空段落。输出复用原始表格 XML；auto/pct/fixed 宽度只通过校验投影放行，不把投影写回来源宽度。

Ribbon、正文右键及编辑器内 Ctrl/Meta+Shift+Enter 已接同一受限控制器。快捷键仅认领主编辑器的顶层表格目标，不认领嵌套编辑器、输入框/对话框或 IME。只读/保护、修订模式、已有未保存修改、保存中与待处理批注（包括根线程回复）均阻止操作；事务支持 Undo/Redo，归一化从不可变来源回放并拒绝混合操作或伪造下表身份。底层仍拒绝合并/嵌套、批注/修订标记及未知 shell 等复杂来源，**不是固定源所有表格的完整等价实现**；第五批当时尚缺单元格位移与插入/删除单元格对话框，第六批另按下述限定范围实现。

前端生命周期13项与批注待处理getter11项（含本次新增1项根线程回复锁回归）共24项通过；另相关48项通过。bridge9项与真实 native Python4项通过，原生回读确认所有非 `document.xml` 部件字节完全相同。不同专项范围有交叉，不相加冒充全套测试。独立审查发现的待处理批注锁缺口已修复，复审无确认的Important。

最终 TypeScript/Vite 构建 `/tmp/word-table-lifecycle-build` 已通过；497个JS分包、Word主分包249547字节，原预算全部通过（`/tmp/word-table-lifecycle-budget.json`），未提高阈值。两个新增vendor文件的来源/本地SHA登记一致，保留固定源原始行为。真实浏览器 `/tmp/word-table-lifecycle-20261114/result.json` 为 `ok:true`、errors为空：待处理批注锁、首行拆分禁用、拆分Undo/Redo、Ribbon拆分与右键整表删除，以及两次保存/下载/重开通过。192个实际资源身份与该最终构建一致，manifest SHA `72bf08253f08d3de0bdbd3bd1b7f61e5377f3bab5ef74f93a8cd7f0f0a5d5fab`。独立 `independent.json` 核验原始rows/cell/pPr/rPr XML、grid与auto宽度/样式保留，下表替代文字清除，相同邻表及所有非 `document.xml` ZIP部件/页眉页脚完全保留。

- 拆分revision2（parent1）SHA：`69bc1b3a845805d30e313dabbd60cf60f9576156a4fda8e552b2a34e0ebb1ed1`。
- 删除revision3（parent2）SHA：`d7f41e6080c84f4929bb6c374ddf03db50b07cd668d32985dea63ae6747c14fe`。

原始流程累计**恰好2次成功HTTP保存**。首次独立verifier因继承namespace上下文比较不对称失败；仅修正harness两侧对称归一化后从原始receipt/下载恢复只读验证，最终 `savesThisRun:[]`，未重做任何编辑或保存。原失败证据与两份实际产物保留，不当作产品写回失败。此真实FastAPI/原生发布链使用限定内存fixture，不认证生产数据库；两份修订仍为 `native_source_review_pending`，保留下载，不标业务事实/完整版式验收通过。浏览器只证明此普通表格场景，不能替代全部宽度/来源/快捷键/only-table和复杂组合矩阵。`OBJ-TBL-DELETE`、`OBJ-TBL-SPLIT-TABLE`、`OBJ-CONTEXT-DELETE-TABLE`、`OBJ-CONTEXT-SPLIT-TABLE` 当前均只覆盖上述范围，状态为 `partial`。

## 第六批：插入/删除单元格对话框（安全普通表格限定场景已验收）

新增独立保存的 `editTableCells` 操作，绑定原表 `blockId` / SHA 与选区矩形意图，由可信来源回放推导实际几何，不接受客户端XML。Ribbon和正文右键共用原生UI适配器：Insert Cells按固定源的四方向与数量1–100插入**完整行或列**；Delete Cells提供shiftLeft、shiftUp、整行、整列四模式。共享纯PM核心复用已固定的AI/table-ops行列原语与 `fixTables`，不新增vendor文件或改变既有hash。已vendor的固定源文件保持逐字节一致；本批共享核心中的部分逻辑按源语义重写/适配，原始XML保留writer为本地定制实现，不声称全部代码直接复制。对话框复用固定源选项语义，未声称整份 `TableDialogs.tsx` 原样移植。

仅普通安全正文顶层表格，支持经校验的auto/pct/fixed宽度；上限100行/30列/1000格，操作结果也受预算约束。已有gridGap、合并/嵌套、批注/修订或未知shell仍明确拒绝。shiftLeft产生的 `gridAfter` 可读取/下载/重开，不承诺其可继续执行非普通表格结构编辑。操作仍受只读/保护、修订模式、脏稿/保存中、待处理批注、IME/过期选区等门禁，支持Undo/Redo；只允许单操作保存。

存活段落与rPr XML保持原样；新增行/列的空格只复制源定义的视觉单元格属性，使用默认空段落属性；shiftUp补空格沿用原第一段pPr。专项发现居中单元格的旧generator `jc` 继承偏差，已以带正确空段落属性的richParas修复，新增回归先RED后GREEN。不把新增格误写为存活段落全文继承，也不把修复扩大为任意复杂单元格保真声明。

前端adapter14/core10/lifecycle13共37项通过，bridge10项通过；真实native Python12项覆盖所有模式、only-table与malformed拒绝，相关4文件102项通过。上述专项有交叉，不相加充当全套测试；未重跑全套。根线程检查与独立审查无其他确认的Important。完整TypeScript/Vite通过，498个JS分包、Word250168字节，`/tmp/word-table-cells-budget.json` 原预算failures为空，未提高阈值。

真实浏览器 `/tmp/word-table-cells-20261114/result.json` 为 `ok:true`、errors为空，193个实际资源身份匹配最终构建，manifest SHA `09792cc876047559f52759da0b0174530e865400e13e86e7226cded6433a3742`。待批注输入保留、取消/无效数量不改变正文、行数预算拒绝、过期选区禁用、保存前HTTP请求数0与精确Undo/Redo通过；实际insertRight数量2→shiftUp→shiftLeft依次完成保存/下载/重开，共**恰好3次成功HTTP200保存**，来源SHA逐修订衔接，未重放已成功动作。

- 插入revision2（parent1）：`29a104cfd1bc0b5c2dfe93eb1e273b01b50ecd2197078986c53bdbc9434cd1ac`。
- shiftUp revision3（parent2）：`57f9955b2df6807d195eb8e8be7e643c92e3f37c0dd6b8d2a64f3cdaa310124a`。
- shiftLeft revision4（parent3）：`8a0b45768c02d252af5e13cb34e33761afbb29143dd65bc9181ad95cf8c71d26`。

独立 `independent.json` 确认存活paragraph/run XML、空段落/补格继承、shiftUp/Left文字与gridAfter、拟合grid/cell宽度、相同邻表/正文及非目标ZIP部件/页眉页脚保全。最终shiftLeft文件可重开；进一步编辑带grid gaps来源仍不在支持范围。真实FastAPI原生发布链使用限定内存仓储，不认证生产数据库。三份修订仍携带 `native_source_review_pending`，保留下载，不标业务事实或完整版式验收通过。该浏览器矩阵只覆盖上述三个模式场景，其余方向/数量/行列整删由专项测试提供证据，不冒充全部真实浏览器组合通过。`OBJ-TBL-INSERT-CELLS`、`OBJ-TBL-DELETE-CELLS`、`OBJ-CONTEXT-INSERT-CELLS`、`OBJ-CONTEXT-DELETE-CELLS` 均只按上述安全来源范围记为 `partial`；复杂表格、保存后的grid gaps、混合操作与未覆盖组合继续开放。

## 当前仍开放的优先缺口（与844行历史证据对应）

1. **跨编辑上下文的写回范围**：普通单元格 runs 格式、活动 HF/文本框的 Home 接线、既有文本框富内容与复杂来源；新增正文 writer 不覆盖这些。优先核对 `TXT-T04/T07/T08`、`TXT-FD01–FD21` / `TXT-PD01–PD18` 的目标差异及对象编辑行；`TXT-T06` 注释纯文本编辑源自身同样是PromptModal，不新增“富注释Home编辑缺失”。
2. **表格操作剩余范围**：`OBJ-TBL-INSERT-CELLS`、`OBJ-TBL-DELETE-CELLS` 已有第六批安全来源对话框与独立保存writer，上述普通表格场景已通过；保存后带grid gaps的来源不承诺继续结构编辑。`OBJ-TBL-DELETE`、`OBJ-TBL-SPLIT-TABLE` 已有第五批独立保存 writer，复杂合并/嵌套/批注/修订/未知shell与混合操作仍不支持，构建与上述普通表格浏览器场景已通过，未覆盖复杂目标。已有增删/合并/样式的复杂目标范围也未关闭。
3. **既有对象完整编辑与图片语义**：保存后的形状/文本框/艺术字内容和几何编辑、图片前后层级、内联及复杂图片目标；正文块图片拖放仅关闭入口空缺的一部分。对应 `OBJ-SHAPE-FMT-*`（剔除下述源限制项）、`OBJ-SHAPE-DRAG-RESIZE`、`OBJ-CONTEXT-OBJECT-*`、`OBJ-PIC-FMT-*`。
4. **引用与审阅深层能力**：Zotero/来源管理/书目、XE索引；复杂 move/属性/对象/跨 story 修订、富批注/图片；保护模式 comments/trackedChanges/forms 的差异语义。当前统一保护只读仍保留。对应 `REF-007–REF-026` 中明确未接项目、`REV-PANE`、复杂修订/富批注行及 `REV-PROTECT-TRACKEDCHANGES/COMMENTS/FORMS`；并非该ID区间全部缺失。
5. **文件与视图族**：DOC/DOT、ODT/OTT、HWP/HWPX 导入、密码生命周期、页面图片导出和完整打印；最近文档/AI命名；多页编辑、分屏、Go To/状态栏与完整 App级快捷键。New/SaveAs只按本批限定范围覆盖；第五批Ctrl/Meta+Shift+Enter仅覆盖主编辑器安全顶层表格拆分，不关闭完整快捷键目录。对应 `WV-F03–F06/F10/F16–F17/F21–F23`、`WV-V09/V15`、`WV-N06`、`WV-S01–S05`、`WV-K01–K07` 中尚未对齐部分。
6. **AI与组合验证**：完整源工具/apply_ops、附件/知识库及上下文协议逐项映射仍开放；显式授权/采纳不是缺陷。尚未覆盖的第三批命令/目标组合、第四批窄文件名修订浏览器覆盖、第五批未覆盖来源/组合验证、第六批未覆盖模式/来源组合和全来源/组合保存矩阵属于证据欠缺，不冒充已发现文件损坏。

源限制不纳入整改欠账：`SRC-001–SRC-013`（源未提供完整Word构建块/字段分类、脚注编号配置、完整引文样式管理、复杂页设置等）；`OBJ-SHAPE-FMT-FLIP-HORIZONTAL/VERTICAL`、`OBJ-SHAPE-SOURCE-EFFECTS`、`OBJ-CHART-EDIT-TYPE-CHANGE`、`OBJ-CHART-EDIT-ADD-DELETE-CATEGORY-SERIES` 按固定源实际限制保留；`AI-HIDDEN-UI-OPS` 不是源模型可调用工具；`WV-F25/F26` 文档属性/版本历史也非本次源移植要求。所有源限制项以结构化索引的 `source-limited` 为准，不为了“穷尽”凭空扩展标准。

原始844行是命令/字段审计单元，不是独立缺陷计数。本增量只覆盖明确ID或非Ribbon分组，未列入增量的旧行继续有效；不按按钮数宣布完成比例。


## 机械台账再生成

在仓库根目录执行：

```sh
python smart_reporting/report_editor/word-parity-audit-20261114/merge-current-index.py
```

脚本相对自身目录读取 `command-index.json` 与 `remediation-index.json`，保留每个原始字段，追加当前限定范围并记录两个输入SHA；断言844个唯一ID、整改ID全部存在、原始字段不变及源限制状态未被覆盖。脚本不运行产品测试，不按行数给完成比例。
