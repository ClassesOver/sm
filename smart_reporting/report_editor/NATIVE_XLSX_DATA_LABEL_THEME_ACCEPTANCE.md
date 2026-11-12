# XLSX 数值标签主题色验收

日期：2026-11-12；续 PR #222。仅关闭普通 bar/column 的显式数值标签、单一常规 txPr 中无变换 schemeClr 的颜色解析，不关闭完整主题/图表/标签家族。

## 原始依据与实现

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 WorkbookVisuals.tsx::labelTextStyle 使用实际标签颜色；本地此前只接受纯 srgbClr。此次从真实 XLSX 包中的 workbook.xml.rels、主题 clrScheme、chart txPr 入手，复用现有 parseThemePalette、themeSlotIndex、resolveStyleColor；没有新增调色算法，也没有把单元格 tint 算法套用到 DrawingML 变换。

图表读取沿工作簿唯一内部 theme 关系定位部件，支持实际主题移动后保留旧 theme1.xml 的场景。主题需 XML 完整、12 个槽位唯一且可解析，srgbClr/sysClr(lastClr) 无变换。严格模式不使用缺失槽位的 Office 默认值；既有单元格宽松读取不变。普通 accent1–6、tx/bg、链接色通过现有槽位映射取得实际 RGB，传到既有 plot/series/point 逐属性继承和真实字体度量画布。原图表仍保存 schemeClr，而非写死解析后的 RGB。

缺失/不完整/重复主题、外部关系、未知 phClr、标签颜色或主题槽位带变换均保持 unsupported，避免生成错误的默认颜色。非标准主题路径可读取，不代表现有主题菜单支持写入任意路径（菜单仍针对 xl/theme/theme1.xml）。

## 定向验证

- 有效 RED：新 13 项中 7 失败、6 通过，失败均为实际颜色缺失；早先错误使用字符串 API 的无效 fixture 日志不计产品失败证据。
- GREEN：新主题读取/重解析/移动关系/负控/改图保留/series-point 共 **17 项**；相关既有字体、数据标签、表格主题 **30 项**，共 **47 项分批通过**，未重复完整项目测试。
- 引擎两级 tsc 和 bridge bundle 通过；完整前端 tsc/Vite **53.58s**、全部体积预算通过，阈值未修改。产品画布未改，无需重写前端实现镜像测试。

## 实际页面与独立证明

最终证据 `/tmp/workbook-chart-label-theme-browser-20261112-green/summary.json`；冻结产物 `/tmp/workbook-chart-label-theme-static-20261112`，manifest SHA `2d508a9279eb1fa998c9cc9fe9c057370bd7f1403e1592486a8bd1e994376708`。Chromium140.0.7339.16，字体预检通过；169 份实际 JS/CSS 字节 SHA 与冻结磁盘一致，page/console/http/asset 四类错误数组均为空。

实际 NativeEditorService/授权/CSRF/引擎写回/修订登记/下载链路：原文件读取 accent2=#C0504D → 页面布局颜色选择 Ember → #E97132 → Undo 恢复 → Redo → 保存修订4到5 → 授权下载并核 SHA → 明确修订5重开。未注入图表模型或操作，未调用 AI provider；保存一次、plannerCalls=0。重开实际被动画布记录见 theme-reopened-paints.json，包含主题新色和未变的 series/point RGB #90EE90/#FFD700。

独立 openpyxl/lxml/Pillow 从下载 ZIP 与截图复核：数值10/20不变，唯一变更部件为 xl/theme/theme1.xml，所有 chart XML 原字节不变，标签仍引用 accent2。独立读取下载主题得到 #E97132；按该源前景色与蓝条背景的抗锯齿混合线恢复字形，159/166 像素、包围框居中正确。另五场景保留默认字、series/point RGB、未解析 phClr、72pt放不下、红字后备；两个负控均为零标签墨迹。根任务已查看最终完整截图 charts.png；主题切换前截图 before-theme.png 也保留。

原件 SHA `273d0d93d1f9b062b6255bf5e29c9c59093ef418c68abd38df53ee5d88103aec`；下载 SHA `662c7940845efd32d975cdb59760f2627441b87279af9448c6a004ec7df7cc7e`。

首次浏览器运行完成主题/保存/像素检查，但重开缓存返回304，资源身份断言失败；保留 `/tmp/workbook-chart-label-theme-browser-20261112` 失败现场，不计通过。验证器随后在导航前用CDP禁用HTTP缓存，以确保每份实际资源均返回200并核字节；不放宽断言。

## 仍开放

DrawingML 明暗/透明度/其它颜色变换、字体族/斜体等完整样式、复杂富文本、任意标签偏移、完整 sourceLinked 格式、分类/系列/占比内容及复杂图表仍未关闭。当前浏览器仅验收100%缩放；不据此声称全部缩放、全部主题或完整 Office 保真。
