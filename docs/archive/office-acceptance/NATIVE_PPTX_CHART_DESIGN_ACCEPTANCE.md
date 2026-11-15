# 原生 PPTX 图表配色与命名样式验收

2026-11-11。固定 GenOffice 参考提交：
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。
对照 `apps/slides/src/renderer/components/Ribbon.tsx` 的
`CHART_STYLE_PRESETS`、配色与样式入口，以及
`apps/slides/src/main/slides-main.ts` 的 `deckAccents`、
`chartColorSchemes` 和旧版 `CHART_COLOR_SCHEMES`。

## 范围与协议

Chart Design 新增“图表配色与样式”入口，采用命名选择器和配色色块预览。
这关闭配色及预设参数的编辑缺口，但没有复制源 Ribbon 的缩略图样式图库。
主题完整时有9种主题配色，并兼容4个旧配色键；10个样式预设的参数与固定源一致。

- 主题配色：`default`、`colorful`、`colorful2`、`mono-accent1..6`。
  与固定源一样，使用第一页继承链的主题强调色；少于3色或读取失败时使用
  固定源默认强调色。只有3至5色的主题只提供实际可用的单色方案。
- 旧配色：`blue`、`warm`、`cool`、`mono`，保留固定源完整颜色数组。
- 预设：`classic`、`grid`、`labeled`、`detail`、`minimal`、
  `minimal-labeled`、`bold`、`slim`、`legend-top`、`legend-right`。
  设置图例、数据标签、网格线和柱间距；粗柱为50、细柱为300，其余为150。
  标题和数据继续保留，间距仅在原生柱形/条形家族生效。

沿用 `chartEdits`：新增可选严格枚举 `colorScheme` 和0至500的整数
`gapWidthPct`，拒绝布尔值、浮点数、原始颜色数组和未知方案。
桥接根据实际来源解析方案，调用既有 `editChartElement`，没有新增writer或
修改vendored引擎。`default` 显式传空数组，清除系列显式颜色以恢复主题默认，
不能因空数组而省略请求。已有单点颜色继续覆盖系列配色，这是固定源行为。

inspect新增独立的 `chartColorSchemes`、`chartGapWidthPct`；原六字段
`chartStyle` 结构不变。配色键和预设ID不写入PPTX元数据，文件保存实际参数；
重开保留实际颜色和间距，选择器默认“保留当前配色/样式”，不猜测历史方案ID。
待保存草稿仍可回填方案键。相同预设、未选择及取消不产生新patch。

复用现有原子校验、草稿恢复、撤销重做、过期弹窗防护、保存与下载链路；
配色、样式、数据、类型与交换行列合并同一目标，单次确认是一笔历史。
仅允许既有 `chartEditSafe` 来源，外部/共享/复杂图表安全边界不变。
本轮未修改发布或签发链路。

## 定向验证

证据根目录：`/tmp/pptx-chart-design-20261111/`。未运行完整测试集。

- RED：`protocol-red.log`、`bridge-red.log`、`frontend-red.log`保留
  新字段、来源配色及入口未接入时的失败。
- Python：68项通过，含新增28项和既有交换、六类元素、原生编辑契约，
  见 `python-green.log`。独立python-pptx/XML确认暖色系列、间距50、
  数据与其他ZIP部件保留；恢复默认确实移除系列显式颜色。
- 桥接：12项通过，见 `bridge-green.log`。覆盖13种类型的实际文件读写、
  数据和可保留的单点颜色，主题强调色 `#123456` 及其单色渐变，非法输入
  拒绝且archive不变。scatter构建器不写单点颜色是既有源限制，未扩展它。
- 前端：59个不同用例分批通过，见 `frontend-green.log` 和
  `frontend-design-final.log`。覆盖13种配色、10个预设、取消/无变化、
  宿主拒绝、来源方案可用性，以及与交换、历史、刷新和保存合并。
  初批58通过、1失败：测试把来源已开启的 `gridlines=true` 误列为新增patch；
  修正为仅提交变化字段后，只重跑该集成用例及新增来源方案断言，两项通过。
- Ruff、Python编译及smoke脚本语法检查通过。

## 独立构建与类型检查

临时Vite配置输出到证据目录的独立 `static/`，仅关闭写共享static的PDF
资源复制插件，其余配置保留。构建退出0（43.40秒），见 `build.log`。
370个JS chunk通过既有预算，未调整阈值；slides-main为243795字节，
见 `budget.log`。

桥接及新增测试沿ESNext/Bundler、strict配置定向类型检查退出0，见
`bridge-tsc.log`。全局 `tsc --noEmit` 退出2，唯一诊断仍是未涉及的
`src/docx-ruler.test.tsx(25,54)`：`extendedIndents`不属于`Options`，
见 `tsc.log`；不能声称工作区全局类型检查通过。

- manifest SHA256：`cdee947d65d13fbdf1971c8391b4ce7877627fe5ad64e2d53b4760349fe17ef8`。
- 独立edit桥：`7b546238d32dbc99c07ee2de051cf35469b37c9308b7a88094ce31be44223ce0`。
- 独立render桥：`05f1574d88f1ec43e4f3af778c7bb2f3557101831ef404a71d4859c3bb8db918`。

## 实际浏览器保存、下载与重开

扩展已有 `frontend/smoke/pptx-parallel-edit-smoke.mjs` 及独立Python
文件检查器。以 `PPTX_SMOKE_CHART_SWAP=1`、
`PPTX_SMOKE_CHART_DESIGN=1` 运行于上述独立构建和桥，退出0、
`ok=true`，见 `browser.log`、`browser/evidence.json`。
inspect、patch和render实际执行Python/Node原生链路；API授权/CSRF为
显式route fixture，不声称覆盖生产认证、数据库或部署。PDF是有效attachment
placeholder，本专项不验证PDF转换。

浏览器实际验证：

1. 编辑数据、类型和六类元素后交换行列，再把系列One改为99。
2. 切换水平条形类型，检查13种可用配色、10个预设；不选择直接确认和取消
   均保留原草稿。选择暖色与粗柱，5色色块可见；撤销/重做为单笔事务。
3. 重开待保存弹窗回填暖色；显式恢复主题默认后撤销，回到暖色及间距50。
   连同图片和文字修改刷新恢复、实际保存，并从界面签发链接下载PPTX。
4. 独立python-pptx/XML读取水平条形图、类别Revenue、系列One=99/Two=20、
   系列颜色ED7D31/FFC000、间距50，以及原有标题、轴标题和预设图例/网格线。
   未涉及的母版、版式和主题部件身份保持一致。
5. 打开修订2，数据和元素弹窗读回正确值、来源间距50；再次选择粗柱确认
   不产生草稿，避免把来源已保存的间距误判成新增修改。

117份实际网络JS响应逐一匹配冻结磁盘文件，manifest前后一致；page、console、
route和HTTP失败列表为空。已目视 `chart-design-dialog.png` 与 `revision-2.png`：
选择器、色块和确认按钮完整可见，重开后橙黄粗条、网格、标题和图例可见。
综合夹具图片保留原定位置并与图表区重叠，本轮未调整该布局。

另以openpyxl独立读取实际下载文件的内嵌工作簿，得到
`[["", "One", "Two"], ["Revenue", 99, 20]]`，见
`browser/independent-workbook.json`。实际下载47729字节：

- 下载 SHA256：`c82feefbc85d8874fc4b39e64b497e55a135a362833d7625086cb8fdb7249088`。
- 来源 SHA256：`ce44d842e49eba82bc584e1742c4a750bd28206d5685e6cd0cb4e141687583c3`，验收后不变。

## 验收边界与剩余缺口

后续单点配色已接入，见[单点配色专项](NATIVE_PPTX_CHART_POINTS_ACCEPTANCE.md)。
源缩略图图库和配色色卡后续已接入，见[缩略图库专项](NATIVE_PPTX_CHART_GALLERY_ACCEPTANCE.md)。
图表数据点颜色侧栏后续已接入，见[格式侧栏专项](NATIVE_PPTX_CHART_FORMAT_PANE_ACCEPTANCE.md)。
完整FormatPane其他分组与布局仍未对齐。任意柱间距输入、圆环孔径控制
仍未暴露于宿主；源码复核表明独立数值输入主要属于引擎API扩展范围，不能
一概视为源现有界面缺口。本专项只接入命名样式50/150/300间距及0至500协议，
不将协议支持视为任意间距UI已完成。不能标记完整Chart Design或PPTX全面对齐。
本轮未提交、推送或部署。
