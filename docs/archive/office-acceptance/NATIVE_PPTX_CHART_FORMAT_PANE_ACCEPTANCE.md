# 原生 PPTX 图表格式侧栏数据点分组验收

2026-11-11。固定参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
本专项把源 FormatPane 的图表数据点颜色分组接入右侧对象面板，保留先前弹窗。
不代表完整通用 FormatPane 或 PPTX 全面对齐。

## 固定源与宿主适配

源码核对位置：`apps/slides/src/renderer/components/FormatPane.tsx` 的
chartData / onChartPointColor、数据点分组、CHART_PALETTE 与200ms防抖；
`components/ColorWell.tsx` 的色块、下拉、共享颜色图库与原生输入保持挂载。

以下三文件按字节原样复制，没有重写调色板或键盘导航：

- `packages/ui/src/color-picker.tsx` → 前端 vendor `genoffice-slides/ui/color-picker.tsx`，
  SHA256 `8cb984120287510d9d3d17a0b55aa0c8a14c666f8829dc54f7f6e1bf1eaf70e1`。
- 同路径 `color-picker.css`，SHA256
  `54d11716b518384edc6a2d8d352eaf62fe219e05d96ab143743030884d75a88a`。
- `apps/slides/src/renderer/color-input.ts` → 同 vendor 根目录，SHA256
  `5c8a5c74472e487203ddcaab9cf58f2e00d7f18a53d0246bfdfd8b7a70b93c86`。

上游 FormatPane、ColorWell、中文 pane 文案与这三个本地文件的身份登记在
`vendor/genoffice-slides/SOURCE-SHA256.json`，验收副本为 `source-identity.json`；
同目录 `SOURCE.md` 说明适配边界，现有引擎 LICENSE/NOTICE 保留。
FormatPane/ColorWell 是行为和样式参考，不宣称宿主适配器逐字复制。

`slides-chart-format-pane.tsx` 只承载图表的数据点颜色分组：多系列分组、类别名、
74×26色块、主题色及色阶、标准色，共70个色块，以及“更多颜色…”原生输入。
中文文案沿固定源；源布局度量加宿主作用域与主题绑定，采用源正文左右14px内边距。
沿用已有“恢复”操作，清除来源覆盖写显式null。选中图表时隐藏无用途的禁用文字框，
其他对象的文字框和既有几何/页面控件保留。

来源及待保存覆盖经既有 `nativeChartPointColors`、`nativeChartData` 合并，
含交换行列后的最终坐标；配色方案按既有宿主逻辑回填。饼图、三维饼图和圆环图
沿用已验收弹窗的按类别回退方式。对具有可读元数据的散点图或不安全来源，
只显示具体原因、不开放写入；没有可读图表元数据时不展示分组。
本轮没有修改 Python、bridge、wire、图表 writer 或安全来源判定。

宿主新增的状态保护：

- 200ms内连续变化及不同点合并为一个稀疏patch，单笔历史；重选当前覆盖不写草稿。
- 切目标、多选、外部回填、撤销/重做、锁定、销毁使旧代次与待提交定时器失效。
- 保存及打开旧图表弹窗前先flush。提交失败展示具体原因并保留重试机会，
  不吞掉输入；这是编辑状态校验，不改变发布门禁与签发规则。
- 自定义颜色在同一目标的颜色回填后保持同一原生input挂载，避免防抖提交时拆掉
  尚未关闭的原生选色对话框。锁定后解锁不会自动重开旧浮层。
- 浮层进入原生 manual popover top-layer，视口内夹紧，支持Escape与外部点击；
  页面实际位移/resize后关闭，不因打开前延迟送达的滚动事件误关。没有blur关闭。

## 定向测试与失败记录

证据根目录：`/tmp/pptx-chart-pane-20261111/`。未运行或重复完整测试集。

新增6项分组组件用例和1项主编辑器集成用例，另复验2项关联用例，共9个不同
用例分批通过：

- `frontend-red.log`：入口未实现时模块加载失败；`integration-red.log`：
  新集成用例明确因侧栏控件不存在而失败。
- `frontend-initial.log`：3项通过、2项自定义输入模拟失败。测试改用原生value
  setter与input事件以触发React受控输入，并在重复打开前明确关闭旧菜单，
  未改变应用的颜色回调来迁就测试；这2项通过见 `custom-green.log`。
- 新增锁定/解锁不重开浮层的回归先失败，见 `lock-red.log`；补锁定时清理open
  状态后通过，见 `lock-green.log`。
- 锁定修复后，来源图库/键盘、恢复/失败重试、饼图/只读这3项窄回归再通过，
  见 `frontend-final.log`；没有重复整个组件或工作区测试集。
- `integration-green.log`：新侧栏集成、既有缩略图库集成、既有单点/交换集成
  共3项通过。覆盖200ms合并、多点、来源颜色、显式null、无变化、失败重试、
  原生input身份、陈旧控件、只读、散点、交换坐标、历史、保存前flush及刷新回填。
- `tsc-focused-final.log`：新分组、主入口、关联Ribbon与集成测试定向TypeScript
  检查退出0。smoke脚本语法和定向diff检查通过。未重跑全局类型检查，不能将
  上轮已记录的 `docx-ruler.test.tsx` 全局诊断视为本轮已修复。

组件/主入口联动先通过，首轮实际浏览器保存链路也通过，记录保留在
`browser-before-gutter/`、`browser-before-gutter.log`。截图检查随后发现宿主分组
缺少源左右内边距、恢复按钮仍用浏览器默认样式；只修这两处本地CSS后重新构建、
验收。首轮证据不替代下述最终构建身份，未重复前端全套测试。

## 最终构建与实际下载验收

最终独立Vite构建退出0，42.91秒，见 `build.log`。临时配置只关闭会写入共享
static的PDF资源复制插件，不覆盖共享前端或引擎dist。新增一个格式分组模块
chunk边界，未调高预算；373个JS chunk检查无失败，见 `budget.log`：

- `lazy-slides-main-DaoBH5Aq.js`：254333字节，仍低于250KiB。
- `lazy-native-pptx-chart-format-Bcudprvf.js`：9458字节。
- manifest SHA256：`459687438d09a5004eb3355d48bd055e585b1bc0288c278f57148250907b63b4`。
- 独立edit桥：`6d4c127b39ac6ae5a89c5fe9f3683a02ba830024d86ae53ba90db68137497f60`。
- 独立render桥：`05f1574d88f1ec43e4f3af778c7bb2f3557101831ef404a71d4859c3bb8db918`。

本轮桥未改，独立runtime复用此前已验收的相同身份桥，没有重跑Python/bridge
全套。以下浏览器链路实际调用Python/Node inspect、patch、render。

扩展已有 `frontend/smoke/pptx-parallel-edit-smoke.mjs`，启用
`PPTX_SMOKE_CHART_PANE=1`，并保留SWAP/DESIGN/POINTS/GALLERY四个专项开关。
最终退出0、`ok=true`，见 `browser.log` 与 `browser/evidence.json`。

1. 保留此前交换行列、图库、配色、单点弹窗及历史校验。侧栏显示两系列和源覆盖，
   原生top-layer中70个色块可用；主题色选择、撤销/重做、恢复默认与Escape正确。
2. 自定义颜色先设为556677，防抖提交后检查仍是同一个input；620×900视口
   打开侧栏图库并等待延迟事件处理，浮层仍完整位于视口内。
3. 连同图片、文字修改刷新恢复。最后在同一JavaScript执行中输入123ABC并
   点击保存，不等待200ms；验证实际保存请求包括这最后一次输入。
4. 从界面签发的链接下载真实PPTX；独立python-pptx/XML/ZIP读取水平条形、
   类别Revenue、One=99/Two=20、暖色ED7D31/FFC000、间距50，且只有One第0点
   覆盖123ABC。未涉及的母版、版式、主题部件字节不变。
5. 打开修订2，侧栏读回蓝色单点及黄色默认系列；重复来源色不产生草稿。
   既有数据、元素、单点弹窗及来源粗柱标记继续正确，最终撤销回空草稿。

119份实际网络JS响应逐一匹配冻结磁盘文件，manifest前后一致；page、console、
route、HTTP错误列表为空。目视 `chart-format-pane.png`、`chart-format-narrow.png`
及 `revision-2.png`：源颜色矩阵可见，窄屏浮层无裁切，最终侧栏保留左右内边距、
主题恢复按钮和正确的蓝/黄颜色。综合夹具图片仍保留原位置并与图表区域重叠，
本轮未调整该布局。

另用python-pptx/XML、openpyxl独立回读最终下载，见 `independent-final.log`、
`browser/independent-final.json`、`browser/independent-workbook.json`。
工作簿精确为 `[["", "One", "Two"], ["Revenue", 99, 20]]`，下载47758字节。

- 来源 SHA256：`568e6c50de8f5c92361bdf34a3df8e9c5de603fbc85136d0239099f7fb1ba65d`，验收后不变。
- 下载 SHA256：`3fe5b8f68336ff30fff9ed3ddcb60dd2f23c3ad8f8fc12eb4c82032b9483a622`。

## 边界与剩余范围

浏览器授权/CSRF采用显式API route fixture，不覆盖生产鉴权、数据库或部署。
原生颜色输入通过真实DOM value/input事件验证，不声称自动操作了操作系统
选色对话框。辅助PDF是有效attachment placeholder，不验证PDF转换或原生PDF插件。
本轮未改变报告发布门禁、非阻断签发或下载契约，未提交、推送、部署。

本专项关闭“图表数据点颜色只有弹窗、没有侧栏入口”的缺口。完整FormatPane的
通用填充/线条、效果、大小属性和文本框分组、各对象交互与整体布局仍未完整对齐。
大小属性中的厘米输入、纵横比与位置参考点随后单独补齐，详见
[大小与位置专项](NATIVE_PPTX_GEOMETRY_PANE_ACCEPTANCE.md)；旋转与百分比缩放仍开放。
任意柱间距、圆环孔径仍未提供宿主输入，不能将源引擎API能力一概视为源既有
独立数值UI缺口；散点单点写入与外部/复杂图表限制保留。
