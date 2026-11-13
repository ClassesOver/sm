# PDF 与固定 GenOffice 的对齐状态

2026-11-11；来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
整体状态：**未完成，不可将当前 PR 视作 PDF 全功能对齐或上线验收通过**。

PR 隔离组合的依赖范围、专项结果与未通过门禁见 `NATIVE_PDF_PR_INTEGRATION.md`。下述各批次验收记录属于原开发树，不等同于隔离 PR 的浏览器或宿主重验。

用户范围决定（2026-11-11）：不需要 OCR，OCR/自动 OCR 不再作为本次交付缺口；存量兼容代码不因本次范围调整删除。其余功能继续推进，外部证书依赖如实记录。

这是功能族映射，不是穷尽所有子组件的命令数量统计。对固定 App.tsx
（Git blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`）做 TypeScript AST
回调清点得到206个带 onClick/onChange/onSubmit 的 JSX 节点，其中63个位于
主 Ribbon 源码区域；这些数包含对话框、重复布局及动态组件，不能充当
已完成比例的分母。原始记录在证据包的 `source-census.json`，委托子组件
仍须逐个核对。禁用按钮和“文件能打开”不计作功能已完成。

| 来源功能族 | 当前原生状态 | 明确剩余差异 |
| --- | --- | --- |
| 文件/保存/另存 | 导入、来源身份、不可变修订、幂等保存、下载与重开有分层证据 | 桌面路径/文件监听/全部入口及部署宿主等价性未完成 |
| Home/Annotate 四类文字标注 | 高亮、下划线、波浪线、删除线按多行文字选区写入；可切换草稿及安全来源的已保存标注 | 关联回复/弹窗/结构、签名及复杂源标注只读，尚非完整源切换语义 |
| 标注颜色 | 固定源默认色，只有高亮接受自定义颜色；下载验证 RGB | 完整源颜色弹层/上下文工具与现有批注编辑未全部对齐 |
| 文字编辑 | 新增原位改字 Ctrl/Cmd+Enter 快捷提交、普通 Enter 换行和 IME/禁用隔离，实际唯一对象改字与选区样式保存见 NATIVE_PDF_TEXT_EDIT_SHORTCUT_ACCEPTANCE.md；水平既有文字整对象替换、静态插入支持三类字体、粗斜体、字号/颜色、手动多行与左/中/右对齐；新增UTF-16选区样式、焦点/选区保持和输入后范围重定位；混排实际字体/advance与真实浏览器保存下载重开通过（NATIVE_PDF_TEXT_SELECTION_ACCEPTANCE.md）；整对象样式与选区覆盖联动、统一/混合/继承状态和键盘焦点方向见NATIVE_PDF_TEXT_SELECTION_CONTROLS_ACCEPTANCE.md；新增受限样式改字与新增文字标注同批路径，原操作索引和实际字节保留，专项证据见NATIVE_PDF_TEXT_MARKUP_MIXED_ACCEPTANCE.md；样式改字与新增矩形/椭圆、箭头/多边形/手绘及文字标注同批，实际下载/AP/原索引核验见NATIVE_PDF_TEXT_DRAWING_MIXED_ACCEPTANCE.md、NATIVE_PDF_TEXT_VECTOR_MIXED_ACCEPTANCE.md；后者补变换矩阵与旧AP资源闭包复核；再增安全RGB/RGBA PNG与样式改字/文字标注/矢量交错，真实像素/透明通道及下载重开见NATIVE_PDF_TEXT_PNG_MIXED_ACCEPTANCE.md；再增安全外链/mailto/内部页跳转与样式改字同批，严格目标与来源边界见NATIVE_PDF_TEXT_LINK_MIXED_ACCEPTANCE.md；测量线/caret与样式改字同存、成功测量逐项软告警及实际斜线标签渲染见NATIVE_PDF_TEXT_MEASURE_CARET_MIXED_ACCEPTANCE.md | 任意编辑种类混合、页面内完整游标、自动段落/跨对象reflow未接；测量标签Rect/AP BBox已按正式字体与实际Tm扩展并通过独立渲染（NATIVE_PDF_MEASURE_LABEL_BOUNDS_ACCEPTANCE.md），本地草稿已按实际Tm/闭合caret三角映射（NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md），属于固定源UI/AP差异的本地一致性适配；浏览器字体回退像素与页边CropBox裁切仍开放；新增标注仍用来源坐标，不随改字自动重算；混合来源限无表单/保护及所有受影响页默认单位；旋转/倾斜矩阵不支持样式替换；插入仍有来源限制和功能开关 |
| 便签 | 新增/未保存便签编辑删除、创建时间绑定，安全既有便签及标准平铺叶子回复编辑删除，历史/实际预览/下载重开 | 旧草稿未知创建时间不补造；全文侧栏与定位已接通，安全既有和未保存根线程可追加平铺回复并管理草稿身份/编辑删除联动；含回复根便签正文/整线程删除、嵌套/弹窗/复杂/富文本线程仍未接通 |
| 绘图/测量 | 手绘、标定测量、矩形、椭圆、箭头、多边形、插入符号及固定源颜色/线宽已接；待保存记录支持精确列表选择、平移/删除，七类geometry支持透明stroke画布命中/拖动，image另支持数值等比缩放/四角控制柄（`NATIVE_PDF_SHAPE_CANVAS_ACCEPTANCE.md`）；安全已保存六类绘图支持身份绑定逻辑删除 | 本地measure标签/caret草稿已按实际AP几何随viewport缩放旋转，完整上下文/快捷键及字体回退逐像素保真仍开放；复杂已保存来源只读。源普通线宽固定，saved移动/改样式不是已确认缺失源功能；逻辑删除不等于安全擦除 |
| 安全涂黑 | 涂黑/清除涂黑/应用涂黑已接通：标记区域为可撤销草稿，保存新修订时由固定引擎 `redaction.ts`（PDFium ApplyRedaction）永久移除区域内文字/图像/路径并黑块覆盖，来源修订不变；pypdf 独立回读不可提取（`NATIVE_PDF_REDACTION_ACCEPTANCE.md`） | 涂黑与页面尺寸同批；空白草稿页；跨页共享图像/表单控件及关联批注、共享外观或无法证明安全的引用图由引擎拒绝（fail-closed） |
| 页面旋转/删除/顺序 | 来源页身份、左右/全部旋转、删除、反序/移动、历史与回读通过 | 全部页选区/范围组合和相邻上下文仍有差异 |
| 裁切 | 当前/全部保留页按显示方向百分比；实际页面画布、八方向控制柄、区域移动及数值联动；纯裁切实际写回PDF预览、下载通过（NATIVE_PDF_CROP_HANDLES_ACCEPTANCE.md） | 裁切仍只是隐藏内容；复杂宿主与其他草稿组合的视觉/行为等价未穷尽 |
| 页面尺寸 | 五个固定预设、受限来源、实际输出预览与下载通过 | 自定义/复杂来源及裁切/改字同批混用未接通 |
| 提取/插入/替换 | 空白页插入已接通；页面提取可保留所选页序、生成独立派生文档、授权下载/重开，父修订身份与来源草稿不变（NATIVE_PDF_EXTRACT_UI_ACCEPTANCE.md）；外部PDF插入/替换已在独立交付链路实现，见NATIVE_PDF_DELIVERY_BATCH_ACCEPTANCE.md | 空白页保存前不接受标注/裁切/改字；复杂表单/批注/保护来源和导航重映射有安全限制，完整多文件语义未完成 |
| 页面合并/拆分 | 页面N合1（2–16、横/纵、分隔线）及页面2/4/9拆分：固定引擎、新修订、真实预览与可复现摘要；N合1保留可见批注/表单外观为静态内容；文件级提取及外部页面插入/替换另见NATIVE_PDF_DELIVERY_BATCH_ACCEPTANCE.md | 拆分PDF/合并PDF的多产物语义、表单拆分页字段树/Widget重映射、复杂多来源导航/批注/表单及桌面全任务等价尚未完成 |
| 缩略图/目录/单双页/跳页/夜间模式 | 已接入并有浏览器证据；阅读位置/缩放恢复及侧栏尺寸持久化已接通 | 全文便签侧栏已接通；比较和完整快捷键/布局未穷尽 |
| 附件 | 查看/下载、安全平坦名称树新增/身份绑定移除、草稿历史、实际预览及下载重开通过 | 分层/共享/关联附件、受保护来源、超出预算及原位改字混用未开放；移除目录不能擦除内容 |
| 缩放/适合页面 | 源阶梯/滑块/滚轮/锚点、全保留页独立单双页行适配与持续自适应已接通 | 原生批注卡片位于页下，桌面侧边批注边距及完整宿主布局仍不同；10–800%限制保留 |
| 搜索 | 固定源逐处索引/计数、跨片段、大小写/全词、循环导航、选中框与预览身份映射 | 浮动搜索栏、复杂字形精确几何及全部快捷键未完成；OCR已排除 |
| 打印 | 已保存 PDF 的浏览器整份打印 | 源系统打印机、范围/双面等功能需 Web/宿主等价约定 |
| 填写表单 | 受限 text/checkbox/radio/choice 及字段导航通过 | 静态表单填写、复杂字段、签名字段与完整行为未对齐 |
| Form Design | 新增安全独立单 Widget 画布选中与方向键 1pt/Shift10pt 微调，四旋转方向/CropBox/完整身份与 Undo/Redo 保持，实际 0°/90° 保存见 NATIVE_PDF_FORM_CANVAS_NUDGE_ACCEPTANCE.md（默认 UserUnit、select 模式，拖动/resize/多 Widget 未开放）；text/checkbox/date/choice/radio新建；日期四格式、choice选项、radio原子多控件；安全控件rect/required属性及十一种逐页独立排列（多页选区按页分组，不足页保持，原AP/引用保真见NATIVE_PDF_FORM_MULTIPAGE_ARRANGEMENT_ACCEPTANCE.md）；最多16段ASCII层级名称、父节点复用与冲突校验；已有安全单选组追加未选中Widget并保留旧选择/控件/AP；安全独立文本字段可改多行、最大长度、对齐、字号（NATIVE_PDF_FORM_TEXT_PROPERTIES_ACCEPTANCE.md）；新增Helvetica/Times/Courier三家族12标准字型选择及后续填写保留所选字体，限ASCII现值/单Widget/未保护未签名来源（NATIVE_PDF_FORM_TEXT_FONTS_ACCEPTANCE.md）；安全单Widget已有字段支持同父层级叶子改名、草稿恢复及新名称后续填写，保留值/引用/AP，见NATIVE_PDF_FORM_WIDGET_NAME_ACCEPTANCE.md（用户授权属性增量，固定源名称为generated/not shown）；已有安全单Widget下拉字段支持未选项增删/排列并保持现值/default/AP，恢复草稿及后填值真实链见NATIVE_PDF_FORM_CHOICE_OPTIONS_ACCEPTANCE.md；安全2–64 Widget互斥单选组支持同父叶子改名，整组值/状态/AP/原引用保持及新名后填值见NATIVE_PDF_FORM_RADIO_NAME_ACCEPTANCE.md；新增安全组未选中且非默认单按钮逻辑删除，Kids/Opt/Annots同步且后续幸存值可填写，见NATIVE_PDF_FORM_RADIO_REMOVAL_ACCEPTANCE.md；新增安全完整互斥组“整组必填”切换，Ff仅xor2，值/AP/原引用保持，真实五次保存及恢复草稿见NATIVE_PDF_FORM_RADIO_REQUIRED_ACCEPTANCE.md；其余真实链见NATIVE_PDF_FORM_DESIGN_ENGINE_ACCEPTANCE.md | 单选组拆分、跨页统一坐标排列/控件页迁移、任意复杂多Widget语义、跨父/父节点名称与任意字体编辑、CJK/自定义字体/密码/富文本/日期字段属性编辑、自动检测、XFA、签名/保护来源未开放；窄控件长文本新增标准字体布局宽/高软告警，属性与后续填值均保留实际字节/字体/下载，损坏复核元数据也不阻断，见NATIVE_PDF_FORM_TEXT_OVERFLOW_ACCEPTANCE.md；仍可能裁切，未实现自动适配，完整glyph外伸/下伸边界未覆盖；独立字段删除仍限安全单控件；radio组仅限安全未选中非默认按钮，最后一个不开放删除 |
| 转换导出 | 新增 DOCX 精确 RGB 文字底色（复用原生 Run.shading，保留命名高亮/白色规则），实际 Writer 三底色绘制核验见 NATIVE_PDF_DOCX_EXACT_SHADING_ACCEPTANCE.md；PNG/JPEG ZIP；固定源PDF→PPTX/DOCX/XLSX；Markdown/HTML复用实际派生Word与固定源序列化，图片自包含；PDF已识别下划线/删除线现保留为XLSX原生单元格字体，四种装饰及实际Calc渲染见NATIVE_PDF_XLSX_TEXT_DECORATION_ACCEPTANCE.md；正常页图片保存到XLSX可编辑单元格后的参考区，九图验证见NATIVE_PDF_XLSX_IMAGES_ACCEPTANCE.md；PDF→PPTX多行文本按来源基线间距写入（NATIVE_PDF_PPTX_TEXT_GEOMETRY_ACCEPTANCE.md）；测量文字框现禁用shape autofit，复用既有API消除额外横向漂移（NATIVE_PDF_PPTX_TEXT_POSITION_ACCEPTANCE.md）；单元格内混合字体/粗斜体/下划线/删除线现为可编辑富文本，真实下载及Calc验证见NATIVE_PDF_XLSX_RICH_TEXT_ACCEPTANCE.md；已确认的Chrom Sans PS字体回退及非指数小数打印取整/列宽问题已修复，实际下载Calc与嵌入字体证据见NATIVE_PDF_XLSX_DECIMAL_FONT_ACCEPTANCE.md；货币原小数位及独立货币/百分数列宽见NATIVE_PDF_XLSX_CURRENCY_PRECISION_ACCEPTANCE.md，实际下载单次Calc五组显示完整；新增PPTX文字run安全外链/内部页跳转，含表格/脚注关系，实际下载和单次Impress六条链接核验见NATIVE_PDF_PPTX_TEXT_LINKS_ACCEPTANCE.md；后置故障仍保留实际下载 | 图片参考区不等于原位图文排版；XLSX本批测试小数精度与已确认字体回退已修复，跨槽重复计宽已修，实际同源单次Calc由六页降至四页、表头可见总跨度787.4350→629.1500pt（NATIVE_PDF_XLSX_TABLE_SLOT_WIDTH_ACCEPTANCE.md）；两页来源仍未还原，默认字体/MDW、正文行布局/图片参考区根因见NATIVE_PDF_XLSX_PRINT_LAYOUT_DIAGNOSTIC.md；复杂内容/字体完整保真、任意PPTX等价未完成；本轮fixture的PPTX行距已对齐，横向来源实测基线X已贯穿安全LTR路径，本轮两列host残差降至约+0.003/-0.002pt（NATIVE_PDF_PPTX_TEXT_ORIGIN_ACCEPTANCE.md），首行基线仍约差6.35pt；Impress将表格链接显式来源色#123456显示为主题#0563C1，目标可用但宿主颜色保真未通过；图片/栅格链接未纳入本批文字run适配；跨界JPEG跳过告警；MD/HTML页眉页脚/分页可能变化；OCR排除，编辑入口遵循目标开关 |
| 图片/链接/水印 | 插入图像已接通（PNG/JPEG → 浏览器转 PNG ≤2000px，拖出位置，写为 Stamp 批注）；水印与页眉页脚/页码已接通（固定源 StampDialog + 原样复用 stamps.ts 渲染，覆盖全部页面、页码按当前页序；设置后锁定页面结构直至保存或撤销），编辑链接已接通：拖出区域后填写 http/https/mailto 地址或页码（二选一，与固定源 LinkDialog 一致；不安全协议拒绝），页码按来源页绑定、目标页删除时拒绝，保存后回读 Link 批注（`NATIVE_PDF_DRAW_ACCEPTANCE.md`）；已有图像的裁剪/水平垂直翻转/透明度已接通（固定源 image-bake 烘焙后经 replaceImage 写回，见 NATIVE_PDF_EXISTING_IMAGE_BAKE_ACCEPTANCE.md）；已有图像去除背景已接通（固定源 cutout.ts removeBackground，容差 0–100、默认 30，见 NATIVE_PDF_EXISTING_IMAGE_CUTOUT_ACCEPTANCE.md） | 来源已有图像真实对象移动/缩放已接通，实际预览确认、UndoRedo、下载重开及独立像素/矩阵核验见NATIVE_PDF_EXISTING_IMAGE_ACCEPTANCE.md；来源已有图像的像素替换已接通（编辑图像 ▸ 替换为新图像，保留位置与层级，可同时调整范围；同一图像数据多处引用时拒绝替换），见 NATIVE_PDF_EXISTING_IMAGE_REPLACE_ACCEPTANCE.md；图像 90° 旋转未完成（固定源 ImageBakeOp 亦无旋转烘焙）；去除背景对话框没有固定源的实时预览画布；带旋转/镜像或模板内图像的裁剪翻转被拒绝；已保存图像/链接/水印的编辑删除（待保存图像已可精确移动、等比缩放和删除，链接可删除）；页眉页脚字号与颜色调节（固定源对话框亦未提供） |
| 保护/加密与签名 | 可视手写/键入签名保留；新增AES-256 revision6密码和四项阅读器权限的独立下载，真实浏览器与pypdf解密/权限/源正文核验；密码不入草稿/历史/回执；后置故障告警保留下载 | 已加密来源打开/修改/移除密码、签名字段绑定、已保存签名复用、既有签名验证及证书签名未完成；证书服务为外部依赖 |
| AI 入口/审阅/批注处理 | 已接问答/总结/要点/审阅Agno只读工具及受限批注处理，见NATIVE_PDF_AI_READ_ACCEPTANCE.md、NATIVE_PDF_REVIEW_AI_ACCEPTANCE.md | 只读测试使用ScriptedModel，不能证明外部真实provider；完整编辑/生成与固定源全部任务等价未完成；OCR排除 |

## 当前可复核的交付

最新一批完成文字 Ctrl/Cmd+Enter、表单安全单控件画布微调与 DOCX 精确底色三项限定增量，另修复并发页面渲染重复 overlay 与脱离 DOM 控制器清理。文字和 DOCX 浏览器在 r1 冻结构建通过；表单保留 r1 两次已保存字段，从显式 buildTransitions 续跑 final 构建后三次保存，未重复已通过保存。真实三域各 37 JS 身份核验、错误列表为空；3 项 HTTP/守卫专项通过；实际 DOCX 单次 Writer 三色精确保留，整体保真仍 false。final 376 个 JS 分块预算零超限、PDF main 251288 bytes；49 前端/192 引擎清单/955 bundle inputs、LOCAL187/converter48/固定Git blob69匹配。三次 Vite 包含真实渲染缺陷和生命周期修复迭代，不是重复完整测试；未标全项目类型检查或生产部署通过。

- NATIVE_PDF_SHORTCUT_NUDGE_SHADING_ACCEPTANCE.md
- NATIVE_PDF_TEXT_EDIT_SHORTCUT_ACCEPTANCE.md
- NATIVE_PDF_FORM_CANVAS_NUDGE_ACCEPTANCE.md
- NATIVE_PDF_DOCX_EXACT_SHADING_ACCEPTANCE.md
- NATIVE_PDF_AP_ARRANGE_LINKS_ACCEPTANCE.md
- NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md
- NATIVE_PDF_FORM_MULTIPAGE_ARRANGEMENT_ACCEPTANCE.md
- NATIVE_PDF_PPTX_TEXT_LINKS_ACCEPTANCE.md
- NATIVE_PDF_LABEL_REQUIRED_SLOTS_ACCEPTANCE.md
- NATIVE_PDF_MEASURE_LABEL_BOUNDS_ACCEPTANCE.md
- NATIVE_PDF_FORM_RADIO_REQUIRED_ACCEPTANCE.md
- NATIVE_PDF_XLSX_TABLE_SLOT_WIDTH_ACCEPTANCE.md
- NATIVE_PDF_MEASURE_RADIO_CURRENCY_ACCEPTANCE.md
- NATIVE_PDF_TEXT_MEASURE_CARET_MIXED_ACCEPTANCE.md
- NATIVE_PDF_FORM_RADIO_REMOVAL_ACCEPTANCE.md
- NATIVE_PDF_XLSX_CURRENCY_PRECISION_ACCEPTANCE.md
- NATIVE_PDF_XLSX_PRINT_LAYOUT_DIAGNOSTIC.md
- NATIVE_PDF_LINK_RADIO_DECIMAL_ACCEPTANCE.md
- NATIVE_PDF_TEXT_LINK_MIXED_ACCEPTANCE.md
- NATIVE_PDF_FORM_RADIO_NAME_ACCEPTANCE.md
- NATIVE_PDF_XLSX_DECIMAL_FONT_ACCEPTANCE.md

- NATIVE_PDF_PNG_CHOICE_RICH_TEXT_ACCEPTANCE.md
- NATIVE_PDF_TEXT_PNG_MIXED_ACCEPTANCE.md
- NATIVE_PDF_FORM_CHOICE_OPTIONS_ACCEPTANCE.md
- NATIVE_PDF_XLSX_RICH_TEXT_ACCEPTANCE.md

- NATIVE_PDF_VECTOR_RENAME_CONVERSION_ACCEPTANCE.md
- NATIVE_PDF_TEXT_VECTOR_MIXED_ACCEPTANCE.md
- NATIVE_PDF_FORM_WIDGET_NAME_ACCEPTANCE.md
- NATIVE_PDF_XLSX_TEXT_DECORATION_ACCEPTANCE.md
- NATIVE_PDF_PPTX_BASELINE_DIAGNOSTIC.md

- NATIVE_PDF_DRAWING_OVERFLOW_ORIGIN_ACCEPTANCE.md
- NATIVE_PDF_TEXT_DRAWING_MIXED_ACCEPTANCE.md
- NATIVE_PDF_FORM_TEXT_OVERFLOW_ACCEPTANCE.md
- NATIVE_PDF_PPTX_TEXT_ORIGIN_ACCEPTANCE.md

- NATIVE_PDF_MIXED_FONTS_POSITION_ACCEPTANCE.md
- NATIVE_PDF_SELECTION_IMAGES_HIERARCHY_ACCEPTANCE.md
- NATIVE_PDF_TEXT_CONVERT_FORM_ACCEPTANCE.md
- NATIVE_PDF_PARALLEL_BATCH_ACCEPTANCE.md
- NATIVE_PDF_STATIC_TEXT_ACCEPTANCE.md
- NATIVE_PDF_TEXT_STYLE_ACCEPTANCE.md
- NATIVE_PDF_TEXT_SELECTION_CONTROLS_ACCEPTANCE.md
- NATIVE_PDF_FORM_TEXT_PROPERTIES_ACCEPTANCE.md
- NATIVE_PDF_PPTX_TEXT_GEOMETRY_ACCEPTANCE.md
- NATIVE_PDF_TEXT_MARKUP_MIXED_ACCEPTANCE.md
- NATIVE_PDF_FORM_TEXT_FONTS_ACCEPTANCE.md
- NATIVE_PDF_PPTX_TEXT_POSITION_ACCEPTANCE.md
- NATIVE_PDF_OFFICE_TEXT_CONVERSION_ACCEPTANCE.md
- NATIVE_PDF_CROP_HANDLES_ACCEPTANCE.md
- NATIVE_PDF_EXTRACT_UI_ACCEPTANCE.md
- NATIVE_PDF_FORM_DESIGN_ENGINE_ACCEPTANCE.md
- NATIVE_PDF_DELIVERY_BATCH_ACCEPTANCE.md

- `NATIVE_PDF_ROTATE_ALL_ACCEPTANCE.md`
- `NATIVE_PDF_INSERT_BLANK_ACCEPTANCE.md`
- `NATIVE_PDF_DRAW_ACCEPTANCE.md`（含编辑链接、水印与页眉页脚）
- `NATIVE_PDF_CROP_ACCEPTANCE.md` / `NATIVE_PDF_CROP_ALL_ACCEPTANCE.md`
- `NATIVE_PDF_PAGE_SIZE_ACCEPTANCE.md`
- `NATIVE_PDF_SELECTION_MARKUP_ACCEPTANCE.md`
- `NATIVE_PDF_VIEW_ACCEPTANCE.md`
- `NATIVE_PDF_MARKUP_REMOVAL_ACCEPTANCE.md`
- `NATIVE_PDF_SEARCH_ACCEPTANCE.md`
- `NATIVE_PDF_SAVED_NOTES_ACCEPTANCE.md`
- `NATIVE_PDF_PENDING_NOTES_ACCEPTANCE.md`
- `NATIVE_PDF_NOTE_PREVIEW_ACCEPTANCE.md`
- `NATIVE_PDF_COMMENTS_ACCEPTANCE.md` / `NATIVE_PDF_REPLIES_ACCEPTANCE.md` / `NATIVE_PDF_LOCAL_REPLIES_ACCEPTANCE.md` / `NATIVE_PDF_SAVED_REPLY_EDITS_ACCEPTANCE.md`
- `NATIVE_PDF_ATTACHMENTS_ACCEPTANCE.md` / `NATIVE_PDF_ATTACHMENT_WRITE_ACCEPTANCE.md`
- `NATIVE_PDF_READING_ACCEPTANCE.md`
- `NATIVE_PDF_FIT_ACCEPTANCE.md`
- `NATIVE_PDF_SIDEBAR_ACCEPTANCE.md`

每项分别写出原始材料、固定源行为、浏览器/引擎/服务/SQL/容器的证据
边界、失败迭代及实际下载身份。不把重复运行累计为新检查，也不以
placeholder/stub/disabled control 证明完成。

## 不能凭实现推定通过的外部依赖

固定 `CertSignDialog.tsx`（blob `d1340a75490336d36d00c91122efc91a6a969ded`）
直接依赖系统/文件证书库、inspectCertificate、signWithCertificate 和
releaseCertificate。当前 Native API 没有这些服务，也未提供已授权后端
签名服务或非敏感证书别名。所选管理实例的最新配置观测为 secret bindings、
runtime variables、outbound identities 列表均为空；这不代表企业不存在
签名服务，也不表示进程中没有其他用途的凭据。本次没有扫描密钥文件。
元数据回执保留在 `dependency-readiness.json`。

因此**完整对齐目标中的真实证书签名验收目前被外部服务/证书配置阻塞**。
已向用户请求服务名/接口文档和非敏感证书标识，未请求私钥或密码。
`NATIVE_PDF_SIGNING_WEB_DESIGN.md` 给出具体边界和待接入契约；它是设计提案，
不是已实现的签名功能或安全验收证书。其他表格中列出的普通实现缺口仍然
是未完成的开发工作，不能归因于这个外部阻塞。

完整应用镜像、真实生产身份/权限/网络、桌面视觉兼容仍未验收；既有8GB/vfs
完整构建 ENOSPC 缺口不由 mounted-runtime 结果替代。功能开关保持关闭。
