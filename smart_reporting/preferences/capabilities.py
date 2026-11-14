"""明确未消费的格式偏好能力；兼容读取不代表允许新增修改或验收通过。"""


def unsupported_preference_reason(format, path):
    local = path.removeprefix(format + '.')
    if format == 'md' and local in {'common.font', 'common.accentColor', 'common.generatedByLabel'}:
        return 'Markdown 纯文本生成器不消费此视觉/生成标识配置。'
    if format == 'pptx':
        if local.startswith(('typography.h2.', 'typography.h3.')):
            return '正式演示文稿输入没有二/三级标题角色。'
        if local == 'tables.splitRows':
            return '演示文稿表格按完整行续页，不采用 Word 表格跨页断行开关。'
        if local == 'charts.keepWithCaption':
            return '演示文稿保留上游静态图片；未实现 DPI 重采样或文档分页开关。'
        if local == 'common.generatedByLabel':
            return '正式演示文稿桥接尚未消费此字段。'
    if format == 'xlsx':
        if local.startswith(('body.', 'header.', 'signature.')) and local.rsplit('.', 1)[-1] in {
            'lineHeight', 'spaceBefore', 'spaceAfter', 'indent', 'dateGap'}:
            return '工作簿单元格/独立说明页尚未消费此段落属性。'
        if local == 'header.color':
            return '表头文字使用主题色自动对比色，未消费单独表头文字颜色。'
        if local.startswith('print.headerFooter.style.') and local.rsplit('.', 1)[-1] not in {'font', 'size', 'color', 'bold'}:
            return '工作簿打印页眉页脚支持原生字体、整磅字号、颜色和加粗，不支持段落间距或缩进。'
        if local == 'print.headerFooter.divider':
            return '工作簿打印页眉页脚尚未实现分隔线。'
        if local == 'common.generatedByLabel':
            return '工作簿未消费生成标识。'
    return None
