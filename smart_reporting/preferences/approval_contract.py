"""版本化偏好批准合同；静态能力登记与无 I/O 的同绑定证据覆盖判定。

本合同不会开放应用入口。旧 405 字段台账与明确拒绝原因保持独立；
消费者登记只说明实现，不表示当前草稿已取得原生、视觉和生命周期验收。
"""
from __future__ import annotations

import re
from copy import deepcopy

from ..management.configuration_store import configuration_hash
from .models import CommonPreferences, FormatPreferences, resolve_format_preferences

# 静态兼容登记：模型增加或删除字段必须显式更新登记并产生新合同摘要。
_REGISTERED_PATHS = {
    'md': """
        common.signer common.generatedByLabel common.dateFormat common.font common.accentColor
        signature.description sectionHeadingLevel toc tableStyle listMarker
        codeFence imageCaptions references
    """.split(),
    'xlsx': """
        common.signer common.generatedByLabel common.dateFormat common.font common.accentColor
        signature.description signature.font signature.size signature.color signature.bold
        signature.lineHeight signature.spaceBefore signature.spaceAfter signature.indent signature.align
        signature.dateGap body.font body.size body.color body.bold
        body.lineHeight body.spaceBefore body.spaceAfter body.indent header.font
        header.size header.color header.bold header.lineHeight header.spaceBefore
        header.spaceAfter header.indent alignment wrapText rowHeight
        columnWidth borders striped freezeHeader autoFilter
        numbers.decimalPlaces numbers.thousandsSeparator numbers.percentPlaces numbers.negativeStyle numbers.dateFormat
        print.page.paper print.page.orientation print.page.margins.top print.page.margins.right print.page.margins.bottom
        print.page.margins.left print.headerFooter.enabled print.headerFooter.header.left print.headerFooter.header.center print.headerFooter.header.right
        print.headerFooter.footer.left print.headerFooter.footer.center print.headerFooter.footer.right print.headerFooter.style.font print.headerFooter.style.size
        print.headerFooter.style.color print.headerFooter.style.bold print.headerFooter.style.lineHeight print.headerFooter.style.spaceBefore print.headerFooter.style.spaceAfter
        print.headerFooter.style.indent print.headerFooter.headerDistance print.headerFooter.footerDistance print.headerFooter.divider print.fitToWidth
        print.fitToHeight print.scalePercent print.repeatTitleRows
    """.split(),
    'pptx': """
        common.signer common.generatedByLabel common.dateFormat common.font common.accentColor
        signature.description signature.font signature.size signature.color signature.bold
        signature.lineHeight signature.spaceBefore signature.spaceAfter signature.indent signature.align
        signature.dateGap aspectRatio theme typography.body.font typography.body.size
        typography.body.color typography.body.bold typography.body.lineHeight typography.body.spaceBefore typography.body.spaceAfter
        typography.body.indent typography.h1.font typography.h1.size typography.h1.color typography.h1.bold
        typography.h1.lineHeight typography.h1.spaceBefore typography.h1.spaceAfter typography.h1.indent typography.h2.font
        typography.h2.size typography.h2.color typography.h2.bold typography.h2.lineHeight typography.h2.spaceBefore
        typography.h2.spaceAfter typography.h2.indent typography.h3.font typography.h3.size typography.h3.color
        typography.h3.bold typography.h3.lineHeight typography.h3.spaceBefore typography.h3.spaceAfter typography.h3.indent
        typography.table.font typography.table.size typography.table.color typography.table.bold typography.table.lineHeight
        typography.table.spaceBefore typography.table.spaceAfter typography.table.indent typography.caption.font typography.caption.size
        typography.caption.color typography.caption.bold typography.caption.lineHeight typography.caption.spaceBefore typography.caption.spaceAfter
        typography.caption.indent density layout tables.repeatHeader tables.splitRows
        tables.borders tables.striped tables.captionNumbering charts.captionNumbering charts.imageDpi
        charts.keepWithCaption footer.left footer.center footer.right footerStyle.font
        footerStyle.size footerStyle.color footerStyle.bold footerStyle.lineHeight footerStyle.spaceBefore
        footerStyle.spaceAfter footerStyle.indent hideTitleSlideFooter
    """.split(),
    'pdf': """
        common.signer common.generatedByLabel common.dateFormat common.font common.accentColor
        signature.description signature.font signature.size signature.color signature.bold
        signature.lineHeight signature.spaceBefore signature.spaceAfter signature.indent signature.align
        signature.dateGap page.paper page.orientation page.margins.top page.margins.right
        page.margins.bottom page.margins.left typography.body.font typography.body.size typography.body.color
        typography.body.bold typography.body.lineHeight typography.body.spaceBefore typography.body.spaceAfter typography.body.indent
        typography.h1.font typography.h1.size typography.h1.color typography.h1.bold typography.h1.lineHeight
        typography.h1.spaceBefore typography.h1.spaceAfter typography.h1.indent typography.h2.font typography.h2.size
        typography.h2.color typography.h2.bold typography.h2.lineHeight typography.h2.spaceBefore typography.h2.spaceAfter
        typography.h2.indent typography.h3.font typography.h3.size typography.h3.color typography.h3.bold
        typography.h3.lineHeight typography.h3.spaceBefore typography.h3.spaceAfter typography.h3.indent typography.table.font
        typography.table.size typography.table.color typography.table.bold typography.table.lineHeight typography.table.spaceBefore
        typography.table.spaceAfter typography.table.indent typography.caption.font typography.caption.size typography.caption.color
        typography.caption.bold typography.caption.lineHeight typography.caption.spaceBefore typography.caption.spaceAfter typography.caption.indent
        headerFooter.enabled headerFooter.header.left headerFooter.header.center headerFooter.header.right headerFooter.footer.left
        headerFooter.footer.center headerFooter.footer.right headerFooter.style.font headerFooter.style.size headerFooter.style.color
        headerFooter.style.bold headerFooter.style.lineHeight headerFooter.style.spaceBefore headerFooter.style.spaceAfter headerFooter.style.indent
        headerFooter.headerDistance headerFooter.footerDistance headerFooter.divider headerFooter.firstPageDifferent headerFooter.oddEvenDifferent
        headerFooter.firstHeader.left headerFooter.firstHeader.center headerFooter.firstHeader.right headerFooter.firstFooter.left headerFooter.firstFooter.center
        headerFooter.firstFooter.right headerFooter.evenHeader headerFooter.evenFooter headerFooter.pageNumbers headerFooter.pageNumberStart
        tables.repeatHeader tables.splitRows tables.borders tables.striped tables.captionNumbering
        charts.captionNumbering charts.imageDpi charts.keepWithCaption watermark.enabled watermark.text
        watermark.opacity cover toc sources bookmarks
        embedFonts imageQuality
    """.split(),
    'word': """
        common.signer common.generatedByLabel common.dateFormat common.font common.accentColor
        signature.description signature.font signature.size signature.color signature.bold
        signature.lineHeight signature.spaceBefore signature.spaceAfter signature.indent signature.align
        signature.dateGap page.paper page.orientation page.margins.top page.margins.right
        page.margins.bottom page.margins.left typography.body.font typography.body.size typography.body.color
        typography.body.bold typography.body.lineHeight typography.body.spaceBefore typography.body.spaceAfter typography.body.indent
        typography.h1.font typography.h1.size typography.h1.color typography.h1.bold typography.h1.lineHeight
        typography.h1.spaceBefore typography.h1.spaceAfter typography.h1.indent typography.h2.font typography.h2.size
        typography.h2.color typography.h2.bold typography.h2.lineHeight typography.h2.spaceBefore typography.h2.spaceAfter
        typography.h2.indent typography.h3.font typography.h3.size typography.h3.color typography.h3.bold
        typography.h3.lineHeight typography.h3.spaceBefore typography.h3.spaceAfter typography.h3.indent typography.table.font
        typography.table.size typography.table.color typography.table.bold typography.table.lineHeight typography.table.spaceBefore
        typography.table.spaceAfter typography.table.indent typography.caption.font typography.caption.size typography.caption.color
        typography.caption.bold typography.caption.lineHeight typography.caption.spaceBefore typography.caption.spaceAfter typography.caption.indent
        headerFooter.enabled headerFooter.header.left headerFooter.header.center headerFooter.header.right headerFooter.footer.left
        headerFooter.footer.center headerFooter.footer.right headerFooter.style.font headerFooter.style.size headerFooter.style.color
        headerFooter.style.bold headerFooter.style.lineHeight headerFooter.style.spaceBefore headerFooter.style.spaceAfter headerFooter.style.indent
        headerFooter.headerDistance headerFooter.footerDistance headerFooter.divider headerFooter.firstPageDifferent headerFooter.oddEvenDifferent
        headerFooter.firstHeader.left headerFooter.firstHeader.center headerFooter.firstHeader.right headerFooter.firstFooter.left headerFooter.firstFooter.center
        headerFooter.firstFooter.right headerFooter.evenHeader headerFooter.evenFooter headerFooter.pageNumbers headerFooter.pageNumberStart
        tables.repeatHeader tables.splitRows tables.borders tables.striped tables.captionNumbering
        charts.captionNumbering charts.imageDpi charts.keepWithCaption watermark.enabled watermark.text
        watermark.opacity cover toc sources
    """.split(),
}

# 原 65 项拒绝只作历史分类，不据此倒推其余字段受支持。
_LEGACY_UNSUPPORTED = {
    'md.common.generatedByLabel': 'Markdown 纯文本生成器不消费此视觉/生成标识配置。',
    'md.common.font': 'Markdown 纯文本生成器不消费此视觉/生成标识配置。',
    'md.common.accentColor': 'Markdown 纯文本生成器不消费此视觉/生成标识配置。',
    'xlsx.common.generatedByLabel': '工作簿未消费生成标识。',
    'xlsx.signature.lineHeight': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.signature.spaceBefore': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.signature.spaceAfter': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.signature.indent': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.signature.dateGap': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.body.lineHeight': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.body.spaceBefore': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.body.spaceAfter': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.body.indent': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.header.color': '表头文字使用主题色自动对比色，未消费单独表头文字颜色。',
    'xlsx.header.lineHeight': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.header.spaceBefore': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.header.spaceAfter': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.header.indent': '工作簿单元格/独立说明页尚未消费此段落属性。',
    'xlsx.print.headerFooter.style.lineHeight': '工作簿打印页眉页脚支持原生字体、整磅字号、颜色和加粗，不支持段落间距或缩进。',
    'xlsx.print.headerFooter.style.spaceBefore': '工作簿打印页眉页脚支持原生字体、整磅字号、颜色和加粗，不支持段落间距或缩进。',
    'xlsx.print.headerFooter.style.spaceAfter': '工作簿打印页眉页脚支持原生字体、整磅字号、颜色和加粗，不支持段落间距或缩进。',
    'xlsx.print.headerFooter.style.indent': '工作簿打印页眉页脚支持原生字体、整磅字号、颜色和加粗，不支持段落间距或缩进。',
    'xlsx.print.headerFooter.divider': '工作簿打印页眉页脚尚未实现分隔线。',
    'pptx.common.generatedByLabel': '正式演示文稿桥接尚未消费此字段。',
    'pptx.signature.spaceBefore': '正式演示文稿桥接尚未消费此字段。',
    'pptx.signature.indent': '正式演示文稿桥接尚未消费此字段。',
    'pptx.typography.body.indent': '演示文稿桥接尚未消费段落缩进。',
    'pptx.typography.h1.indent': '演示文稿桥接尚未消费段落缩进。',
    'pptx.typography.h2.font': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h2.size': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h2.color': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h2.bold': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h2.lineHeight': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h2.spaceBefore': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h2.spaceAfter': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h2.indent': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h3.font': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h3.size': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h3.color': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h3.bold': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h3.lineHeight': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h3.spaceBefore': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h3.spaceAfter': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.h3.indent': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.table.font': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.table.size': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.table.color': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.table.bold': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.table.lineHeight': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.table.spaceBefore': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.table.spaceAfter': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.table.indent': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.typography.caption.indent': '演示文稿桥接尚未消费段落缩进。',
    'pptx.tables.repeatHeader': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.tables.splitRows': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.tables.borders': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.tables.striped': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.tables.captionNumbering': '正式演示文稿输入没有原生表格或二/三级标题角色。',
    'pptx.charts.imageDpi': '演示文稿保留上游静态图片；未实现 DPI 重采样或文档分页开关。',
    'pptx.charts.keepWithCaption': '演示文稿保留上游静态图片；未实现 DPI 重采样或文档分页开关。',
    'pptx.footerStyle.indent': '演示文稿桥接尚未消费段落缩进。',
    'pdf.tables.captionNumbering': '正式文档适配器尚未将此字段映射到可核验的原生产物。',
    'pdf.charts.imageDpi': '正式文档适配器尚未将此字段映射到可核验的原生产物。',
    'word.tables.captionNumbering': '正式文档适配器尚未将此字段映射到可核验的原生产物。',
    'word.charts.imageDpi': '正式文档适配器尚未将此字段映射到可核验的原生产物。',
}

# 冻结原设计的规范章节；不纳入文件尾部持续追加的工程进度记录。
_SPEC_SOURCES = {
    '已确认要求': '文本报告的“章节起始级别”仅维护一个选择：二级（默认）、三级、四级。报告总标题保持一级，服务端登记的章节和两层小节按同一层级差顺延，最大六级；手写未登记标题、引用块和代码示例保持原样。Word/PDF使用原始语义层级，目录仍按层级关系生成。旧快照缺少该字段时维持二级起始，不改写历史冻结值。\n\nXLSX页面区增加数据对齐、自动换行及可清空的行高/列宽，文字排版按数据/表头角色折叠维护；只开放引擎已有消费的字体、字号、加粗和数据文字颜色。表头文字颜色随主题自动选择黑白，不增加无效的颜色输入。单元格明确样式优先，原值、公式和缓存保持不变；独立落款已完成长内容打印专项：不继承业务行列尺寸和关闭换行，按字体及纸张测量，必要时缩字并软告警；署名与日期保持同页及一致字号。任意业务长表极端组合仍待验收。\n\nWord/PDF文字排版维护已增加正文、三级标题、表格文字及图注角色选择；默认折叠，段落间距进一步按需展开，复用既有原生适配。校验定位展开后，修正输入保留展开状态。窄屏目录限制自身最小宽度，允许目录内部横向滚动，不撑开整页。\n\n文字文档/PDF的导出区已接通封面、目录与来源附录维护；各格式独立保存与真实预览，Word目录保留原生域。来源附录预览仅使用明确标注的固定样例登记，不注入正式报告。\n\n增量验收映射见 output/system-config-preferences/verification.md。MD目录已接通正式组装、草稿维护与真实下载，Word/PDF投影移除MD目录避免重复；表格写法已接通可逆HTML/标准表格、原生Word/PDF与来源/改表读取；图片说明已接通正式组装、草稿维护与跨格式投影，连续保存后预览已通过短流程及完整原生产物浏览器复验；引用编号已接通登记来源、显示开关、悬停名称及任务冻结，隐藏显示仍保留来源绑定，Word/PDF使用各自的来源设置；章节起始级别已接通二至四级维护、真实组装、预览及任务冻结。其他Office适配、模板语义和完整应用验收继续推进，完整目标保持实现中。\n\n- 两个独立一级菜单：「系统配置」「偏好管理」。现有「数据源」保持置顶。\n- 偏好采用全局默认，由管理员维护；首版不增加个人覆盖或组织管理。\n- 偏好按 MD、XLSX、PPTX、PDF、Word 区分，Word 对应 DOCX 输出。页面名称依次使用“文本报告 / 电子表格 / 演示文稿 / PDF / 文字文档”，扩展名在辅助提示中说明；接口键与历史快照标识不变。\n- 必须有可设计的落款，页眉页脚及常规 Office 偏好纳入同一设计。\n- 延续低学习成本、列表与表单区分明显、横向方角页签、减少纵向堆叠的界面规则。',
    '菜单与页面': '系统配置采用左侧分类目录、右侧设置表单。页面分类为模型与服务、报告运行、编辑与导出。日常页面保留12项维护设置，执行协议、调试、追踪与访问日志由部署配置维护。中文名称为主，环境变量名作为辅助说明；支持常用项搜索、修改差异、版本和实际生效状态。\n\n系统配置仅呈现日常维护项；移除高级参数入口，搜索不再带回底层协议参数，部署路径、监听地址等继续由部署配置维护。去掉空分类和逐项重复的重启说明，来源及环境变量在标签提示中查看。正文面板最大 908px、表单最大 720px，随内容自然高度展示，不用空白或冗余参数撑满页面；顶部五格式方角页签仍横向占满。\n\n偏好管理顶部为横向占满的 MD / XLSX / PPTX / PDF / Word 五个格式页签；不再增加五个一级菜单。各格式内按「常用」「页面与排版」「页眉页脚」「落款」「表格与图表」「导出」切换设置区域，仅显示该格式有意义的分区。根据用户关于冗余配置与页面被撑开的最新反馈，主区统一采用设置/预览视图切换，各屏宽均不常驻并排；内容面板最大 908px，表单最大 720px，按内容自然高度展示，不纵向堆叠。预览按需读取已保存草稿，修改中明确标注样例未包含当前输入，保存版本变化清除旧样例；切换视图保留表单，校验错误返回设置视图。版本历史按需打开，不常驻堆叠在表单下面。\n\n「通用偏好」作为偏好页面内的独立入口，维护跨格式共用的署名、日期格式、字体和主题色。格式页显示「沿用通用」或「已单独设置」，提供恢复沿用。切换页签保留未保存输入；保存前显示本次涉及的格式和公共项，错误定位到对应页签和字段。',
    '落款设计（必备）': '落款内容为默认维护区，四种 Office 格式的字体、字号、颜色、对齐、加粗收进默认折叠的「落款样式」；校验错误自动展开定位，不把低频样式纵向铺开。Markdown仅维护内容。\n\n落款为独立的内容与样式模块，页脚、水印、封面中的署名不能代替正文或交付物末尾的落款。\n\n| 类别 | 配置内容 |\n|---|---|\n| 内容 | 署名、生成日期、可选附加说明；署名为普通文本，不新增组织对象或人员目录 |\n| 日期 | 默认使用本次报告修订的生成日期，选择日期显示格式；同一修订的预览和重复下载不改变日期 |\n| 排版 | 字体、字号、颜色、行距、署名与日期间距、与前文的间距、对齐方式 |\n| 位置 | 按格式选择合法落点；默认遵循下表，不开放任意绝对坐标作为普通维护操作 |\n| 内容复用 | 共用一份署名与日期来源，各格式可独立调整样式；从当前有效署名配置初始化，不用登录用户名或示例名称猜测落款 |\n| 预览与校验 | 预览展示完整落款，长署名自动换行；检查遮挡、溢出、重复添加和与正文分离的问题 |\n\n| 格式 | 默认落款落点 |\n|---|---|\n| MD | 正文末尾独立的 Markdown 段落，署名与日期分行；不依赖仅个别阅读器支持的对齐 HTML |\n| XLSX | 说明工作表末尾的原生单元格区域，不把落款混入业务数据表体；说明页同时进入打印范围 |\n| PPTX | 最后一页的原生可编辑落款文本区域；空间不足时使用结束页，保持正文与落款均可读 |\n| PDF | 正文结束后的独立右对齐落款块；署名和日期保持在一起，布局与页脚互不覆盖 |\n| Word | 正文结束后的原生段落，默认右对齐；使用段落分页属性保持落款整体，支持后续编辑 |\n\n落款默认必备，不提供跨格式总开关将其整体移除。新偏好应用前必须有有效署名；已完成任务保持其冻结的落款身份。已有模板明确的落款位置优先复用并绑定本次内容，不能追加重复落款或沿用模板示例署名、日期。附录不再重复添加落款。',
    '页眉页脚与常规 Office 偏好': 'Word/PDF/XLSX 的页边距先选择常规、窄、宽或自定义；仅自定义展开四边毫米数值，至少保留20毫米可打印宽高，错误直接定位对应字段。\n\n页眉页脚使用表单选择左/中/右区域、文本样式、位置及分隔线；动态内容通过「插入字段」选择报告标题、分析期间、生成日期、文件名、页码/总页数等受支持字段。每种格式只显示自身支持的字段。所有页码使用真实页码字段或导出引擎分页结果，不能手写页码。\n\n| 格式 | 纳入设计的设置 |\n|---|---|\n| MD | 标题级别、列表与表格写法、目录、代码块、图片说明、引用和末尾落款；不存在物理分页页眉页脚，不显示其设置 |\n| XLSX | 默认字体、字号、对齐、自动换行、行高/列宽；表头、边框与条纹；小数位、千分位、百分比、日期和负数显示；冻结表头、自动筛选；打印纸张、方向、边距、打印区域、重复标题行、缩放与分页；左/中/右打印页眉页脚、页码；说明页落款 |\n| PPTX | 页面比例、主题色与字体、标题/正文/注释样式、内容密度、图文布局、图表和表格风格；日期、页脚、幻灯片编号及标题页隐藏规则；末页落款。页眉类信息进入标题或版式区，不照搬 Word 分页语义 |\n| PDF | 纸张、方向、边距、封面与目录；正文/标题/图注样式；页眉页脚、首页差异、奇偶页差异、页码起点；表格跨页、图表与落款分页；书签、固定字体嵌入与图像输出质量 |\n| Word | 纸张、方向、边距；字体、字号、标题样式、段前段后、行距、首行缩进；封面、原生目录、页码；页眉页脚、首页不同、奇偶页不同、页码起点；表头重复、表格跨页、图表标题与编号；独立落款段落 |\n\nPDF/UA交付始终嵌入字体，不提供无效的关闭开关；历史embedFonts=false快照保留读取兼容并返回具体提示，文件继续生成。字体选择限定为实际渲染环境具备的字体；缺失字体明确显示替代情况。数值格式仅控制显示，不改变原始数据、公式结果、统计口径或精度。Office 文件保留原生可编辑段落、表格、文本框和工作表，不以整页图片代替。\n\n公共署名、日期、主题等只维护一个默认来源；PDF 与 Word 可以继承同一默认排版，再分别配置差异。页眉、页脚、水印、封面署名、正文落款各自有清楚名称和预览位置，避免同一个内容在多个入口竞争。',
    '系统环境变量纳管边界': '建立项目配置清单，只纳入代码明确声明和读取的变量，不枚举并公开全部进程环境。每项登记类型、单位、校验、默认来源、敏感性、依赖条件和真实生效方式。\n\n- 报告模型、运行限额、业务功能开关等按实际读取链路提供可维护设置；能按任务初始化的配置在下一任务生效，进程初始化项标明重启后生效。\n- 系统数据库连接、加密主密钥、监听端口、构建镜像和引擎路径等部署基础项首版只展示脱敏状态及维护说明；不提供修改后可能使管理入口自身失效的普通表单。\n- 密码和令牌复用既有凭据加密与引用机制，只显示配置状态，允许明确替换；不回显或写入审计明文。\n  - 已接通模型服务凭据替换：复用 CredentialVault 加密，独立 system_credentials 不可变记录，草稿/发布版本仅存引用；发布并重启后消费，历史恢复保留旧凭据。元数据服务令牌同样支持服务端替换，不新增日常表单参数。缺密钥时明确告警并回退部署启动值，不误报管理版本已生效。\n- 署名、页眉页脚、水印等已有环境变量归属「偏好管理」，系统配置只显示其来源与跳转入口，避免两处独立编辑。\n- 展示已保存版本、当前有效版本及生效时间。管理配置、部署初值与内置默认的来源明确可见，不通过直接修改全局 os.environ 实现运行时更新。',
    '版本、运行与兼容原则': '编辑器导出与预览按格式冻结默认叠加明确修改差异，避免将PDF完整默认写成Word的通用覆盖；Word单格式编辑采用Word基线。实际双格式字体、导出提交及重启回读已有专项证据；历史恢复已接通各格式默认、页面和落款上下文的来源修订继承，缺失旧字段不会残留新版值；预览、导出提交及重启回读已有证据。另已通过真实数据库快照、重启读取、派生修订继承及五格式实际生成的代表性配置验证；这不替代所有正式入口、历史编辑和重复下载的完整冻结审计。\n\n分别维护系统配置和全局偏好的草稿及有效版本，沿用现有保存、应用/发布、差异、CAS 并发保护和回读机制。恢复旧版本产生新版本，不覆盖历史记录。\n\n全局偏好作为新任务默认值。明确的单次任务要求、上传模板布局和报告编辑器中已经确认的设计优先于全局默认；落款缺失时补齐，模板示例内容必须重新绑定。业务事实、安全边界和发布契约不能被外观偏好覆盖。\n\n任务创建时冻结所用系统配置版本、偏好版本及解析后的有效值；运行中修改只影响后续任务。已有修订的预览、恢复和再次下载不因为全局偏好更新而变样。当前浏览器本地导出选项只作为单次编辑意图，不升级为共享全局默认。\n\n已有部署配置作为首次纳管初值；首轮上线维持现有效果，不自动重写历史报告。服务端渲染、编辑器预览和各格式导出读取同一份有效配置。落款缺失、排版或预览校验失败必须返回具体原因，但已生成且身份可核验的产物仍按项目非阻断签发契约保留下载。',
    '实现依据与需补齐能力': '当前已有：`runtime/settings.py` 的运行参数；`delivery/settings.py` 的署名、水印、左右页眉页脚；`delivery/report_runtime/report_design.py` 的封面落款、字体、标题、图注和导出选项；编辑器设计草稿与冲突保护；Word/PDF 正文末尾落款渲染。\n\n需补齐：两个管理菜单、配置清单与全局版本服务、统一的格式偏好解析和任务快照；独立落款内容/样式模型；页眉页脚与纸张布局扩展；XLSX/PPTX/MD 的格式适配及实际预览。已有 A4 封面坐标约束不能仅增加纸张选择框，必须同步布局换算和输出验证。\n\n目标设置只有接入实际生成、预览和导出执行器并通过验证后才开放编辑。未接入项明确列为待实现能力，不提供可以保存但不生效的空壳配置。',
    '验收重点': '1. 两个菜单独立可访问、数据源仍置顶；五格式页签、设置分区、未保存提示和移动端切换正确，页面不呈现工作表式配置网格。\n2. 配置脱敏、类型与单位校验、配置来源、实际生效状态、并发冲突、响应丢失回读、恢复默认和历史版本恢复均有定向验证。\n3. 每种格式生成实际样例；检查署名、日期、落款位置、页眉页脚、真实页码，以及原生可编辑结构，不能仅检查 JSON 保存成功。\n4. 长署名、多行说明、跨页表格、首页/奇偶页、横向纸张、长表头、打印缩放、幻灯片末页空间不足均验证不遮挡、不重复、不丢失正文。\n5. 模板与全局默认冲突时，优先级和最终来源可见；不携带旧模板的示例落款或日期；编辑器预览与实际产物一致。\n6. 修改全局设置不影响运行中任务、历史修订和重复下载；落款/排版验收失败不阻断已生成产物的下载。若改动导出签发，保持 AGENTS.md 指定的非阻断回归通过。\n7. 遵守项目要求，只运行受影响定向测试，不重复完整测试；实际预览与试用结论分别记录。',
}


def approval_contract_hash(contract: dict) -> str:
    """运行绑定单独冻结；其余合同内容全部参与稳定的规范 JSON 摘要。"""
    return configuration_hash({key: value for key, value in contract.items() if key != 'expectedBinding'})


def _paths(value, prefix):
    result = set()
    for key, nested in value.items():
        path = f'{prefix}.{key}'
        result.update(_paths(nested, path) if isinstance(nested, dict) else {path})
    return result


def _requirement_id(format, local):
    if local.startswith('signature.') or local in {'common.signer', 'common.dateFormat'}:
        return 'signature-content-and-layout'
    if format == 'md':
        return 'markdown-semantic-transform'
    if format == 'pptx':
        return 'slides-native-content-and-style'
    if format == 'xlsx':
        return 'workbook-print-layout' if local.startswith('print.') else 'workbook-display-invariants'
    if local.startswith(('page.', 'headerFooter.')) or local in {'cover', 'toc'}:
        return 'paged-header-footer-and-numbering'
    if format == 'pdf' and local in {'embedFonts', 'bookmarks', 'imageQuality'}:
        return 'pdf-accessible-quality'
    return 'native-editable-role-style'


def _consumer(format, local):
    """显式消费者白名单；未列入的字段保持 missing，绝不按拒绝清单取补集。"""
    if local in {'common.signer', 'common.dateFormat'}:
        return f'preferences/{ {"md": "markdown", "xlsx": "workbook", "pptx": "slides"}.get(format, "document") }_adapter.py', 'frozen signer/date -> terminal signature'
    if format == 'md' and local in {'signature.description', 'sectionHeadingLevel', 'toc', 'tableStyle',
        'listMarker', 'codeFence', 'imageCaptions', 'references'}:
        return 'preferences/markdown_adapter.py', 'registered Markdown nodes/signature paragraphs'
    if format in {'word', 'pdf'}:
        if local == 'tables.captionNumbering':
            return 'reporting/delivery/report_runtime/table_captions.py', 'registered current-revision captions -> native adjacent Caption/bookmark or PDF caption paragraphs'
        if local == 'charts.imageDpi':
            return f'reporting/delivery/report_runtime/{"docx" if format == "word" else "pdf"}.py', 'verified chart image identity -> controlled static PNG/JPEG derivative -> native media pixels and drawing extent / PDF image resource and draw matrix readback'
        allowed_groups = {'signature', 'page', 'typography', 'headerFooter', 'tables', 'watermark'}
        if local.split('.')[0] in allowed_groups or local in {'common.font', 'common.accentColor',
            'cover', 'toc', 'sources', 'charts.captionNumbering', 'charts.keepWithCaption', 'bookmarks', 'imageQuality'}:
            return f'reporting/delivery/report_runtime/{"docx" if format == "word" else "pdf"}.py', {
                'signature': 'native terminal signature paragraphs / spacing / pagination',
                'page': 'section page size/orientation/margins',
                'typography': 'native text-role font/paragraph properties',
                'headerFooter': 'native header/footer variants, fields and page numbering',
                'tables': 'native table header/row-break/border/stripe properties',
                'watermark': 'watermark text/opacity',
            }.get(local.split('.')[0], 'ReportDesign options / static figure caption / PDF output properties')
    if format == 'xlsx':
        allowed = {'alignment', 'wrapText', 'rowHeight', 'columnWidth', 'borders', 'striped',
            'freezeHeader', 'autoFilter', 'common.font', 'common.accentColor'}
        if (local in allowed or local.startswith(('numbers.', 'print.page.'))
            or local in {f'{role}.{prop}' for role in ('body', 'header', 'signature')
                for prop in ('font', 'size', 'bold', 'color') if not (role == 'header' and prop == 'color')}
            or local in {'signature.align', 'signature.description'}
            or local in {f'print.headerFooter.style.{prop}' for prop in ('font', 'size', 'color', 'bold')}
            or local in {'print.fitToWidth', 'print.fitToHeight', 'print.scalePercent', 'print.repeatTitleRows',
                'print.headerFooter.enabled', 'print.headerFooter.headerDistance', 'print.headerFooter.footerDistance'}
            or local in {f'print.headerFooter.{kind}.{side}' for kind in ('header', 'footer') for side in ('left', 'center', 'right')}):
            return 'preferences/workbook_adapter.py', 'native workbook cell/display/worksheet print properties through build_workbook'
    if format == 'pptx':
        if local == 'charts.imageDpi':
            return 'reporting/delivery/pptx.py', 'registered chart image objects -> controlled static PNG/JPEG media derivative -> source and embedded media identity, slide extent and effective DPI readback'
        if local in {'signature.indent', 'footerStyle.indent', 'typography.body.indent',
            'typography.h1.indent', 'typography.table.indent', 'typography.caption.indent'}:
            return 'reporting/slides_engine/bridge/build-pptx.ts', 'all native role paragraphs: first-line indent in physical points -> layoutText and Paragraph indent EMU'
        if local == 'signature.spaceBefore':
            return 'reporting/slides_engine/bridge/build-pptx.ts', 'every signature slide: heading text-box bottom -> first signature text-box top, in physical points'
        if (local in {'tables.repeatHeader', 'tables.borders', 'tables.striped', 'tables.captionNumbering'}
            or local in {f'typography.table.{prop}' for prop in (
                'font', 'size', 'color', 'bold', 'lineHeight', 'spaceBefore', 'spaceAfter')}):
            return 'reporting/slides_engine/bridge/build-pptx.ts', 'native table continuation header / border / stripe / caption and cell text properties'
        if (local in {'aspectRatio', 'theme', 'density', 'layout', 'common.font', 'common.accentColor',
            'hideTitleSlideFooter', 'charts.captionNumbering'}
            or local in {f'typography.{role}.{prop}' for role in ('body', 'h1', 'caption')
                for prop in ('font', 'size', 'color', 'bold', 'lineHeight', 'spaceBefore', 'spaceAfter')}
            or local in {f'footerStyle.{prop}' for prop in ('font', 'size', 'color', 'bold', 'lineHeight', 'spaceBefore', 'spaceAfter')}
            or local in {'footer.left', 'footer.center', 'footer.right'}
            or local in {f'signature.{prop}' for prop in ('font', 'size', 'color', 'bold', 'lineHeight', 'spaceAfter', 'align', 'dateGap', 'description')}):
            return 'preferences/slides_adapter.py', 'native slide text boxes / paragraph style / slide-number fields through assemble_slides'
    return None, None


def _field(format, local):
    path = f'{format}.{local}'
    legacy = _LEGACY_UNSUPPORTED.get(path)
    consumer, native = _consumer(format, local)
    reason = None
    if format == 'md' and local in {'common.font', 'common.accentColor'}:
        support, reason = 'not_applicable', 'Markdown 纯文本没有字体或主题色原生属性；不能记为已验证。'
    elif format == 'pptx' and local.startswith(('typography.h2.', 'typography.h3.')):
        support, reason = 'not_applicable', '复用模型的二/三级标题不是原设计承诺的幻灯片角色；标题/正文/注释要求仍保留。'
    elif format == 'xlsx' and local.startswith(('body.', 'header.', 'signature.')) and local.rsplit('.', 1)[-1] in {
        'lineHeight', 'spaceBefore', 'spaceAfter', 'indent', 'dateGap'}:
        support, reason = 'not_applicable', '原生单元格没有 Word 段落属性；落款可读间距、同页和打印要求仍由完整 R 验收。'
    elif format == 'xlsx' and local.startswith('print.headerFooter.style.') and local.rsplit('.', 1)[-1] in {
        'lineHeight', 'spaceBefore', 'spaceAfter', 'indent'}:
        support, reason = 'not_applicable', '原生打印页眉页脚没有 Word 段落属性；字体、字号、颜色、位置与实际打印可读性要求仍由完整 R 验收。'
    elif format == 'xlsx' and local == 'header.color':
        support, reason = 'compatibility_only', '原设计要求表头文字随主题自动选择黑白，不开放独立文字颜色输入。'
    elif format == 'pptx' and local in {'tables.splitRows', 'charts.keepWithCaption'}:
        support, reason = 'not_applicable', '幻灯片不采用 Word 表格跨页/图文分页开关；表格风格和内容完整性要求仍保留。'
    elif local in {'common.generatedByLabel', 'embedFonts'}:
        support, reason = 'compatibility_only', ('PDF/UA 始终嵌入字体，历史 false 只兼容读取并提示。'
            if local == 'embedFonts' else '保留历史生成标识，不作为正文落款或可编辑能力。')
    elif local == 'charts.imageDpi' and consumer:
        support = 'implemented'
    elif format == 'pptx' and (local.startswith(('tables.', 'typography.table.')) or local in {
        'signature.spaceBefore', 'signature.indent', 'footerStyle.indent', 'typography.body.indent',
        'typography.h1.indent', 'typography.caption.indent'}) and consumer:
        support = 'implemented'
    elif format in {'word', 'pdf'} and local == 'tables.captionNumbering' and consumer:
        support = 'implemented'
    elif legacy or not consumer:
        support, reason = 'missing', legacy or '尚未完成此语义字段的正式末端消费者登记。'
        consumer, native = None, None
    else:
        support = 'implemented'
    role = ('terminal_signature' if local.startswith('signature.') or local in {'common.signer', 'common.dateFormat'}
        else local.split('.')[1] if local.startswith('typography.') else local.split('.')[0])
    raw = [path]
    if local.startswith('common.'):
        raw.append(local)
    if local.endswith('.font') and not local.startswith('common.'):
        raw.extend([f'{format}.common.font', 'common.font'])
    if local.endswith('.color') and local.startswith(('typography.h1.', 'typography.h2.', 'typography.h3.')):
        raw.extend([f'{format}.common.accentColor', 'common.accentColor'])
    return {'path': path, 'rawWritePaths': raw, 'semanticRole': role, 'support': support,
        'editable': support == 'implemented', 'requirementIds': [_requirement_id(format, local)],
        'consumer': consumer, 'nativeProperty': native, 'evidenceDimensions': ['native'],
        'notApplicableReason': reason, 'legacyUnsupportedReason': legacy}


def _checks(formats, role, scenarios, dimensions=('native', 'visual')):
    return [{'format': format, 'role': role, 'scenario': scenario, 'dimensions': list(dimensions)}
        for format in formats for scenario in scenarios]


def _requirements():
    """R 保留原文、完整场景及实现缺口，不由 UI 或现有 reader 推导。"""
    entries = [
        ('signature-content-and-layout', ['落款设计（必备）'], 'partial',
            '完整模板落点、任意业务极端组合及五格式完整分页/重复落款处理仍待实现或验收。',
            _checks(_REGISTERED_PATHS, 'terminal_signature', ['normal', 'long_name', 'multiline_description',
                'empty_description', 'no_duplicate', 'together_or_continuation', 'no_overlap'])),
        ('template-binding-and-precedence', ['落款设计（必备）', '版本、运行与兼容原则'], 'missing',
            '模板专属验收、无标记语义消歧、模板示例身份替换及明确单次/编辑器来源优先级未闭合。',
            _checks(_REGISTERED_PATHS, 'template', ['declared_signature_slot', 'unmarked_semantic_disambiguation',
                'replace_example_identity', 'preserve_unregistered_content', 'task_template_editor_precedence', 'visible_source'])),
        ('markdown-semantic-transform', ['已确认要求', '页眉页脚与常规 Office 偏好'], 'implemented', None,
            _checks(['md'], 'registered_markdown', ['heading_2_3_4', 'toc', 'list_fence', 'reversible_table',
                'image_caption', 'citation_binding', 'preserve_unregistered_and_code'])),
        ('native-editable-role-style', ['页眉页脚与常规 Office 偏好'], 'implemented', None,
            _checks(['word', 'xlsx', 'pptx'], 'native_content', ['editable_native_objects'])
            + _checks(['word', 'pdf', 'xlsx', 'pptx'], 'native_content', ['all_text_roles', 'available_fonts_and_substitution'])),
        ('paged-header-footer-and-numbering', ['页眉页脚与常规 Office 偏好'], 'implemented', None,
            _checks(['word', 'pdf'], 'paged_document', ['regular_first_even_pages', 'position_divider',
                'real_page_number_start', 'paper_orientation_margins', 'cover_toc', 'no_body_signature_overlap'])),
        ('workbook-display-invariants', ['已确认要求', '页眉页脚与常规 Office 偏好'], 'implemented', None,
            _checks(['xlsx'], 'worksheet', ['value_formula_cache_precision', 'registered_percent_date',
                'explicit_style_precedence', 'header_stripe_freeze_filter', 'legal_row_column_dimensions'])),
        ('workbook-print-layout', ['页眉页脚与常规 Office 偏好', '已确认要求'], 'partial',
            '打印区域/分页的维护语义尚需明确需求解释和实现；任意长业务表、长表头与长落款极端组合未闭合。',
            _checks(['xlsx'], 'print_layout', ['actual_print_range', 'repeat_rows_fit_scale', 'print_range_pagination_semantics',
                'signature_sheet_in_print', 'arbitrary_long_table_header_signature'])),
        ('slides-native-content-and-style', ['页眉页脚与常规 Office 偏好'], 'partial',
            '原生表格风格正式末端消费尚未完成，不能因界面隐藏而移除要求。',
            _checks(['pptx'], 'slide', ['aspect_theme_roles', 'density_layout_static_chart', 'native_table_style',
                'footer_real_number_title_hide', 'last_slide_overflow_preserves_body'])),
        ('pdf-accessible-quality', ['页眉页脚与常规 Office 偏好'], 'implemented', None,
            _checks(['pdf'], 'pdf_output', ['embedded_fonts', 'bookmarks', 'image_quality_actual_layout',
                'legacy_embed_false_warning'])),
        ('freeze-history-and-download', ['版本、运行与兼容原则'], 'partial',
            '全入口历史恢复、运行中、重启、派生修订和重复下载的冻结生命周期尚未完整闭合。',
            _checks(_REGISTERED_PATHS, 'revision', ['new_task_only', 'running_task', 'historical_restore',
                'derived_revision', 'restart', 'repeated_download_frozen_date'], ('lifecycle',))),
        ('authorization-and-integrity', ['版本、运行与兼容原则', '验收重点'], 'partial',
            '跨状态库可变来源未获得原子身份保证；耐久批准的撤权/重放防护仍需接入。',
            _checks(_REGISTERED_PATHS, 'authorization', ['admin_and_full_editor', 'revision_context_workspace_material',
                'revoke_replay', 'cookie_session_scope', 'immutable_revision_input'], ('lifecycle',))),
        ('nonblocking-artifact-delivery', ['版本、运行与兼容原则', '验收重点'], 'implemented', None,
            _checks(_REGISTERED_PATHS, 'delivery', ['validation_failure', 'gate_failure', 'audit_evidence_failure',
                'actual_artifact_identity_and_specific_reasons'], ('lifecycle',))),
        ('maintenance-and-version-workflow', ['菜单与页面', '版本、运行与兼容原则', '实现依据与需补齐能力', '验收重点'], 'partial',
            '正式批准应用、完整证据汇总与批准后的完整生命周期验收仍未完成。',
            _checks(_REGISTERED_PATHS, 'management', ['menus_datasource_first', 'five_formats_sections', 'common_inherit_restore',
                'unsaved_inputs_preview_invalidation', 'draft_effective_diff_source', 'save_readback_cas_lost_response',
                'restore_new_version', 'error_focus_mobile', 'edit_only_consumed_and_verified', 'apply_only_approved'], ('lifecycle',))),
        ('system-configuration-boundary', ['系统环境变量纳管边界', '菜单与页面', '版本、运行与兼容原则'], 'implemented', None,
            _checks(['system'], 'configuration', ['declared_catalog_only', 'twelve_daily_settings', 'secret_reference_redaction',
                'deployment_only_status', 'next_task_or_restart_source', 'preferences_single_source',
                'initial_values_no_history_rewrite'], ('lifecycle',))),
    ]
    return [{'id': id, 'sourceSections': sections,
        'sourceText': '\n\n'.join(_SPEC_SOURCES[section] for section in sections),
        'implementation': implementation, 'missingImplementationReasons': [reason] if reason else [], 'checks': checks}
        for id, sections, implementation, reason, checks in entries]


def approval_contract() -> dict:
    document = FormatPreferences(common=CommonPreferences(signer='合同登记'))
    registered = {f'{format}.{local}' for format, locals in _REGISTERED_PATHS.items() for local in locals}
    if len(registered) != sum(len(locals) for locals in _REGISTERED_PATHS.values()):
        raise ValueError('偏好合同字段登记重复；每个格式叶子必须唯一。')
    actual = set().union(*(_paths(resolve_format_preferences(document, format), format) for format in _REGISTERED_PATHS))
    if registered != actual:
        raise ValueError(f'偏好合同字段登记不完整：新增={sorted(actual - registered)}；缺失={sorted(registered - actual)}')
    fields = [_field(format, local) for format, locals in _REGISTERED_PATHS.items() for local in locals]
    editable = {}
    for field in fields:
        if field['editable']:
            for raw in field['rawWritePaths']:
                editable.setdefault(raw, []).append(field['path'])
    requirements = _requirements()
    by_id = {item['id']: item for item in requirements}
    # 每个可维护已支持字段均需完整原生证据，不能只测某个代表字段。
    for field in fields:
        if field['editable']:
            by_id[field['requirementIds'][0]]['checks'].append({'format': field['path'].split('.')[0],
                'role': field['semanticRole'], 'scenario': 'configured_field', 'path': field['path'],
                'dimensions': field['evidenceDimensions'][:]})
    return {'contractVersion': 1, 'requirementsVersion': 1, 'preferenceSchemaVersion': 1,
        'specDigest': configuration_hash(_SPEC_SOURCES), 'specSources': deepcopy(_SPEC_SOURCES),
        'fields': fields, 'editablePaths': [{'path': raw, 'resolvedPaths': sorted(paths)} for raw, paths in sorted(editable.items())],
        'requirements': requirements}


def _valid_digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _valid_binding(value):
    return (isinstance(value, dict) and type(value.get('draftVersion')) is int and value['draftVersion'] > 0
        and all(_valid_digest(value.get(key)) for key in ('draftHash', 'contractHash', 'executorManifestHash')))


def _valid_artifact(value):
    return (isinstance(value, dict) and _valid_digest(value.get('sha256'))
        and type(value.get('sizeBytes')) is int and value['sizeBytes'] > 0)


def evaluate_required_coverage(contract: dict, evidence: list[dict]) -> list[dict]:
    """仅接受服务端核验后的证据；授权/实际文件回读由上游可信边界负责。

    V 每项携带 binding、requirementId、format、role、scenario、dimension、
    status=passed/failed、objectScope=complete、authorized=True、
    artifact={sha256,sizeBytes}。字段检查还需 path 精确匹配。
    sample/partial/not_exercised 不能补 complete，更不能从 native 推断 visual。
    """
    gaps = []
    requirements = {item['id']: item for item in contract['requirements']}
    binding = contract.get('expectedBinding')
    if not _valid_binding(binding):
        gaps.append({'requirementId': 'authorization-and-integrity', 'reason': 'missing_binding',
            'missingDimensions': [], 'message': '缺少服务端精确草稿、合同和执行器绑定。'})
    elif binding['contractHash'] != approval_contract_hash(contract):
        gaps.append({'requirementId': 'authorization-and-integrity', 'reason': 'contract_hash_mismatch',
            'missingDimensions': [], 'message': '合同内容与绑定的合同摘要不一致。'})
    for field in contract.get('fields', []):
        if field.get('support') == 'missing':
            for id in field.get('requirementIds', []):
                gaps.append({'requirementId': id, 'format': field['path'].split('.')[0],
                    'role': field['semanticRole'], 'path': field['path'], 'reason': 'implementation_missing',
                    'missingDimensions': [], 'message': field.get('notApplicableReason') or '要求字段缺少正式消费者。'})
    usable = []
    for row in evidence:
        id = row.get('requirementId')
        scope = {key: row[key] for key in ('format', 'role', 'scenario', 'path') if key in row}
        gap = {'requirementId': id, **scope, 'missingDimensions': []}
        if id not in requirements:
            gaps.append({**gap, 'reason': 'unknown_requirement', 'message': '证据引用未登记要求。'})
            continue
        if not _valid_binding(binding) or row.get('binding') != binding:
            gaps.append({**gap, 'reason': 'binding_mismatch', 'message': '证据草稿、合同或执行器绑定不一致。'})
            continue
        if row.get('authorized') is not True:
            gaps.append({**gap, 'reason': 'unauthorized_evidence', 'message': '证据未通过服务端当前授权校验。'})
            continue
        if row.get('status') == 'failed':
            gaps.append({**gap, 'reason': 'check_failed', 'message': row.get('message') or '该场景存在实际失败检查。'})
        if (row.get('status') == 'passed' and row.get('objectScope') == 'complete'
            and _valid_artifact(row.get('artifact'))):
            usable.append(row)
    for requirement in requirements.values():
        id = requirement['id']
        if requirement.get('implementation') != 'implemented':
            gaps.append({'requirementId': id, 'reason': 'implementation_missing', 'missingDimensions': [],
                'message': '；'.join(requirement.get('missingImplementationReasons', [])) or '要求的实现尚未完成。'})
        for check in requirement['checks']:
            dimensions = set()
            for row in usable:
                if row['requirementId'] == id and all(row.get(key) == check.get(key)
                    for key in ('format', 'role', 'scenario', 'path')):
                    dimensions.add(row.get('dimension'))
            missing = sorted(set(check['dimensions']) - dimensions)
            if missing:
                gaps.append({'requirementId': id, **{key: check[key] for key in ('format', 'role', 'scenario', 'path') if key in check},
                    'reason': 'coverage_missing', 'missingDimensions': missing,
                    'message': '缺少同草稿授权场景的全部对象完整证据；采样、未执行和原生读取不能代替视觉验收。'})
    return sorted({configuration_hash(gap): gap for gap in gaps}.values(),
        key=lambda gap: tuple(str(gap.get(key, '')) for key in ('requirementId', 'format', 'role', 'scenario', 'path', 'reason', 'missingDimensions', 'message')))


def editable_change_reason(path: str, before: dict, after: dict) -> str | None:
    """独立合同分类接口；不改变既有草稿保存策略或历史兼容读取。"""
    missing = object()
    def value(document):
        current = document
        for component in path.split('.'):
            if not isinstance(current, dict) or component not in current:
                return missing
            current = current[component]
        return current
    if value(before) == value(after):
        return None
    contract = approval_contract()
    if path in {item['path'] for item in contract['editablePaths']}:
        return None
    return _LEGACY_UNSUPPORTED.get(path) or '此路径没有已登记的可维护正式消费者；保留历史读取，不允许新增修改。'
