# 原生 PPTX 图表单点配色验收

2026-11-11。固定 GenOffice 提交：
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。
参考 `apps/slides/src/renderer/components/FormatPane.tsx` 的
`paneFormatChartPoints`、`CHART_PALETTE` 和 `onChartPointColor`，
`apps/slides/src/renderer/App.tsx` 的颜色编辑回调，以及
`packages/pptx-engine/src/index.ts` 的 `editChartElement` 单点覆盖与转置逻辑。

## 范围与实现

图表设计新增“单点配色”，按系列和类别提供原生颜色输入及“恢复系列配色”。
从实际来源覆盖与待保存草稿合并回填；颜色变化、重置作为一次确认事务，
未改变、取消或回填同一颜色不产生新patch。复用既有来源/选区/草稿快照检查、
撤销重做、刷新恢复和保存链路。采用宿主弹窗，不声称完整复刻源FormatPane外观。

`chartEdits[].pointColors` 为稀疏映射：系列索引→类别索引→`#RRGGBB`或`null`。
索引为规范ASCII十进制字符串，拒绝前导零、负数、越界与空映射/空行；
颜色严格使用六位HEX，`null` 显式删除对应点覆盖，恢复原生系列/类别默认配色。
Python先验证20系列、100类别协议上界，前端草稿及桥接再核对最终实际数据维度。
修改数据使已有颜色patch越界时拒绝该次修改、保留原草稿，不静默错绑颜色。

映射始终采用用户最终看到的行列，与既有显式categories/series协议一致。
宿主交换时同步转置颜色patch；保存桥接在原生交换前反投影颜色坐标，
再委托原生引擎一起转置来源覆盖和新增覆盖。因此“先设色再交换”和
“交换后设色”结果一致，双次交换还原坐标。多次点编辑逐行合并，不能用
后一小片覆盖吞掉前一片。inspect新增 `chartPointColors` 和 `chartSeriesColors`，
不改变既有数据或六字段样式对象。

仍使用 `chartEditSafe` 来源限制。12种现有图库类型的单点HEX写入可回读；
固定源scatter构建器不写dPt，本轮显式禁用散点图入口，并在草稿/桥接校验
拒绝有效类型为scatter的pointColors patch，不改writer来掩盖源能力限制。
未修改vendored引擎、发布门禁或下载签发链路。

## 定向测试

证据根目录：`/tmp/pptx-chart-points-20261111/`。未运行完整测试集。

- RED：`protocol-red.log`、`bridge-red.log`、`frontend-red.log`、
  `integration-red.log`确认新字段、弹窗、按钮及合并流程尚未接入。
- Python：70个不同用例分批通过：`python-green.log` 的68项含新增单点专项
  16项、配色方案28项、交换9项与原生编辑契约15项。另补2项Unicode数字索引
  一致性用例，先在 `index-red.log` 复现Python的 `\d` 接受非ASCII数字、
  桥接拒绝的不一致，再改为显式ASCII数字；仅这2项复验通过，见
  `index-green.log`。实际PPTX经python-pptx/XML独立读取，
  交换后新颜色在正确系列；null移除dPt，数据及无关ZIP部件保留。
- 桥接：15个不同用例分批通过，见 `bridge-green.log`（9）和
  `bridge-regression.log`（6）。覆盖12种支持类型、来源覆盖保留、反投影与
  清除、颜色/索引/散点拒绝且archive不变，以及原数据/样式/交换契约。
- 前端：64个不同用例分批通过。`frontend-green.log` 63项，另见
  `frontend-points-final.log` 的3个单点用例（2个复验、1个新增）。新增循环
  方案预览测试先在 `palette-cycle-red.log` 失败，再修正超出方案色数时
  按系列循环取色；同批补验取消。覆盖逐点合并、reset、双次交换、来源回填、
  撤销重做、刷新恢复及保存请求，未重复完整测试。
- Ruff、Python编译和smoke脚本语法检查通过。

## 独立构建及类型检查

临时Vite配置输出到独立static，关闭会写共享static的PDF资源复制插件，
其他配置保持。构建退出0（45.16秒），见 `build.log`。
370个JS chunk通过既有预算，未改阈值；slides-main为244852字节，见 `budget.log`。

桥接及新增测试的strict ESNext/Bundler定向类型检查退出0，见 `bridge-tsc.log`。
全局 `tsc --noEmit` 仍退出2，唯一诊断为未涉及的
`src/docx-ruler.test.tsx(25,54)`：`extendedIndents`不属于`Options`，见 `tsc.log`。
不声称全工作区类型检查通过。

- manifest SHA256：`81a3d6fadaf58be5b9e9f383bb97f3d5ec7d0b8eeeea6441dab487c9c41daacc`。
- 独立edit桥：`6d4c127b39ac6ae5a89c5fe9f3683a02ba830024d86ae53ba90db68137497f60`。
- 独立render桥：`05f1574d88f1ec43e4f3af778c7bb2f3557101831ef404a71d4859c3bb8db918`。

## 实际浏览器、下载与重开

复用 `frontend/smoke/pptx-parallel-edit-smoke.mjs`，新增
`PPTX_SMOKE_CHART_POINTS=1` 并组合既有SWAP/DESIGN模式，在上述独立
构建和桥上运行。退出0、`ok=true`，见 `browser.log`、
`browser/evidence.json`。实际执行Python/Node inspect、patch、render及
python-pptx/XML文件读回。API授权/CSRF是显式route fixture，不声称覆盖
生产认证、数据库、部署；有效PDF attachment placeholder不验证PDF转换。

浏览器实际验证：

1. 先修改数据和六类元素、交换行列，再应用暖色与粗柱预设。
2. 单点弹窗无变化确认不产生历史。通过真实原生color input的值与input事件
   为两个系列的数据点设色；不涉及操作系统颜色选择器自动化。
3. 确认两点patch、单笔撤销/重做。双次交换同步投影颜色并恢复；清除第二点
   保留第一点，随后清除第一点但取消，原草稿不变。
4. 连同文字与图片修改刷新恢复、保存，从界面签发链接下载实际PPTX。
   独立读取类型为水平条形图、类别Revenue、One=99/Two=20；原系列方案
   ED7D31/FFC000不变，实际单点覆盖仅One的第0点为123ABC，Two没有dPt。
   未涉及的母版/版式/主题部件身份保留。
5. 打开修订2，颜色控件回填One为123ABC、Two为系列默认FFC000；不改确认
   保持空草稿。清除One的已保存来源覆盖产生显式null，撤销恢复空草稿。

117份实际网络JS响应逐个匹配冻结磁盘文件，manifest前后一致；page、console、
route和HTTP失败列表为空。已目视 `chart-points-dialog.png`：两系列、颜色、
恢复按钮及确认/取消均完整可见。`revision-2.png`中One蓝色条与Two黄色条
可见，标题、轴标题和网格线保留。综合夹具图片仍在原定位置并与图表区重叠，
本轮未调整该布局。图例保留系列颜色，单点覆盖改变对应条形颜色。

另以openpyxl独立读取实际下载文件内嵌工作簿，精确得到
`[["", "One", "Two"], ["Revenue", 99, 20]]`，见
`browser/independent-workbook.json`。实际下载47758字节：

- 下载 SHA256：`dd7560580af1ccd49ed96250ed75845e2c5e82f41c205797b587389659810557`。
- 来源 SHA256：`9c1cf3d9f124aca806b76b482ae254d80acf1c553e0ebf5842d723f14d0b064f`，验收后不变。

## 剩余范围

真实源界面的缩略图样式图库和配色色卡后续已接入，见
[缩略图库专项](NATIVE_PPTX_CHART_GALLERY_ACCEPTANCE.md)。图表数据点颜色侧栏后续已接入，
见[格式侧栏专项](NATIVE_PPTX_CHART_FORMAT_PANE_ACCEPTANCE.md)。完整FormatPane其他分组与布局仍未对齐。
任意柱间距输入和圆环孔径控制仍未暴露于宿主：经源码核对，它们主要是源
引擎API能力，不应将独立数值输入一概标记为源现有界面缺口。
散点图单点颜色写入仍是固定源限制。外部/复杂图表安全边界未放宽。
本专项不代表Chart Design或PPTX全面对齐；未提交、推送或部署。
