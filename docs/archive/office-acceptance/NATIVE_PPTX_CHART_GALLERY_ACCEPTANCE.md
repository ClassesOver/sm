# 原生 PPTX 图表样式缩略图库验收

2026-11-11。固定参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
本轮补齐图表设计中的源样式缩略图库和配色色卡下拉，不代表 PPTX 全面对齐。

## 来源与实现范围

从固定源 `apps/slides/src/renderer/components/Ribbon.tsx` 提取
`chartPresetActive`、`ChartStyleThumb` 到前端 vendor 的
`components/chart-style-preview.tsx`。两个函数体、64×40 SVG、样例数据与颜色
保持原样；只适配导出、独立类型导入和接口的 `StringKey` → `string`。
缩略图是源的样式示意，不是当前图表实际数据的实时预览。

- 源 Ribbon SHA256：`6a261cf18bbdbf2b39fa51add3d30383a10ded4a072303e0012cb7e5cde00aba`。
- 源 styles SHA256：`4c223aa7cad2fc20d714444fb65f85f2c3f0f01ae64b054686ad0528632a5d6a`。
- 本地 preview SHA256：`ba7ef810f7d419e88a9856389cfada2b42d20ca89b42c1843293c80af1457164`。

来源和本地身份已登记于 `vendor/genoffice-slides/components/SOURCE-SHA256.json`，
来源说明见同目录上级 `SOURCE.md`；独立核对记录为 `source-identity.json`。
保留已有引擎 LICENSE/NOTICE。宿主 CSS 对源卡片规则加作用域并绑定现有主题，
保留源 440px 横向滚动行、68px 色卡和方案前四色预览。

图表设计 Ribbon 呈现10个样式卡片，“更改颜色”展开13个来源方案。
沿用已验收的共享 `CHART_STYLE_PRESETS`、`chartColorSchemes` 和 `chartEdits`；
没有修改 Python、bridge、wire 协议或 vendored engine。已有命名选择器弹窗保留。

当前预设从来源与待保存参数合并匹配，不持久化预设 ID。`barH` 和
`barPercentStacked` 按源 render-tree 的条形家族映射；折线图匹配忽略柱间距，
可能同时标记网格、粗柱、细柱，与源匹配器一致。点击预设只提交变化字段；
重复当前参数或待保存配色不增加历史。配色不从任意已有系列颜色反推方案 ID。

浮层使用浏览器原生 manual popover，进入 top-layer 避免 Ribbon overflow 裁切，
并将位置限制在视口内。支持键盘向下打开、首项焦点、Escape、外部点击关闭；
切对象、切功能区、锁定、销毁时关闭。浮层内部可滚动；页面/功能区导致锚点
实际移动或窗口尺寸改变时关闭，打开前延迟送达的事件不误关。旧色卡不能跨目标写入。

## 定向测试与窄屏失败记录

证据根目录：`/tmp/pptx-chart-gallery-20261111/`。未运行或重复完整测试集。

- 前端共71个不同用例分批通过。初批4文件68项见 `frontend-green.log`；
  后补菜单滚动与初始只读两项见 `frontend-final.log`。外部事件停止冒泡的
  已有菜单用例先失败后修正为 capture 监听，见 `outside-{red,green}.log`。
- 初轮真实浏览器在620px窄屏断言失败，未保存即停止，完整保留在
  `browser-before-anchor-fix/` 和 `browser-before-anchor-fix.log`，不计为通过。
  缩小复现场景的 `probe.log`、`probe-geometry.log` 记录焦点、按键、滚动、
  锚点坐标及浮层状态：焦点触发的滚动事件在浮层打开后送达，原无条件
  scroll 关闭逻辑误关，事件送达时锚点已经没有新位移。
- 第71项定向回归先 RED，见 `anchor-red.log`。修复记录打开时的锚点、
  视口与页面滚动位置，仅实际变化才关闭；4个配色相关用例通过，见
  `anchor-green.log`。补核真实尺寸变化仍关闭，单项通过见
  `anchor-resize-green.log`。未通过放宽窄屏可见性或边界断言绕过问题，
  最终浏览器额外等待两帧以确认延迟事件处理后仍可见。
- 新图库、Ribbon、主入口及两份相关测试的定向 TypeScript 检查退出0，
  见 `tsc-focused-final.log`；smoke 语法、来源身份及定向 diff 空白检查通过。
  全局类型检查仍有既有 `docx-ruler.test.tsx(25,54)` 的 `extendedIndents`
  不属于 `Options`，见 `tsc.log`，不能宣称全工作区类型检查通过。

## 冻结构建与实际文件链路

最终独立 Vite 构建退出0，44.83秒，见 `build.log`。临时配置仅关闭会写入
共享 static 的 PDF 资源复制插件，保留其余实际配置。370个 JS chunk 通过
既有预算，未调整阈值；`lazy-slides-main-BO0-k7Gr.js` 为252814字节，见
`budget.log`。旧构建日志另保留，不作为本次最终浏览器身份。

- manifest SHA256：`e6a06860a8d6261612150e702945317cd6819115e7f060e94392723588932aea`。
- 独立 edit 桥：`6d4c127b39ac6ae5a89c5fe9f3683a02ba830024d86ae53ba90db68137497f60`。
- 独立 render 桥：`05f1574d88f1ec43e4f3af778c7bb2f3557101831ef404a71d4859c3bb8db918`。

本轮 bridge 未改，独立 runtime 复用上轮已验收的同身份桥。本轮没有重跑
Python/bridge 全套；下面浏览器保存实际调用 Python/Node inspect、patch、render。

扩展 `frontend/smoke/pptx-parallel-edit-smoke.mjs`，同时启用
`PPTX_SMOKE_CHART_SWAP=1`、`PPTX_SMOKE_CHART_DESIGN=1`、
`PPTX_SMOKE_CHART_POINTS=1`、`PPTX_SMOKE_CHART_GALLERY=1`。
最终退出0、`ok=true`，见 `browser.log` 与 `browser/evidence.json`：

1. 实际显示10个源 SVG 和13个色卡，校验前四色、原生 popover、Escape、
   切功能区和切目标关闭；样式行可滚到最后一个键盘焦点卡片。
2. 交换行列并编辑99/20后，用色卡应用暖色、用卡片应用粗柱；分别单笔
   撤销/重做，重复卡片不增加历史；显式主题默认可撤销回暖色。
3. 620×900视口键盘打开色卡，延迟事件处理后仍可见且完整位于视口内，
   恢复宽屏会关闭。继续单点改色、清除/取消与双次交换的坐标投影校验。
4. 连同图片、文字修改刷新恢复，实际保存，并从界面签发链接下载 PPTX。
   独立 python-pptx/XML/ZIP 读回水平条形、类别Revenue、One=99/Two=20、
   系列颜色ED7D31/FFC000、间距50，以及仅One第0点为123ABC的覆盖。
   未涉及的母版、版式、主题部件字节不变。
5. 重开修订2，来源参数正确标记粗柱，重复点击不产生草稿；数据、元素、
   单点颜色均正确回填，清除已保存覆盖后撤销恢复空草稿。

117份实际网络 JS 响应逐一核对冻结磁盘文件，manifest 前后一致；page、
console、route 与 HTTP 失败列表为空。已目视 `chart-gallery-colors.png`、
`chart-gallery-narrow.png` 和 `revision-2.png`：色卡可见、窄屏无裁切，
重开后粗柱来源状态、蓝色单点、黄色系列及标题/轴标题/网格保留。
综合夹具图片仍在原定位置并与图表区域重叠，本轮未调整该布局。

另用 python-pptx/XML 与 openpyxl 独立回读最终下载文件，见
`independent-final.log`、`browser/independent-final.json` 和
`browser/independent-workbook.json`；内嵌工作簿精确为
`[["", "One", "Two"], ["Revenue", 99, 20]]`，实际下载47757字节。

- 来源 SHA256：`55adf85aef2dc71a0de6a7c7e1f2b701e0376723d9c2a9ac654ad22a5f261a2e`，验收后不变。
- 下载 SHA256：`32a4388667b155d43dfdcd680d493f6565b06c9a8e754dab8aa8e100fd0aac48`。

## 验收边界与剩余缺口

浏览器 API 授权/CSRF 为显式 route fixture，不覆盖生产鉴权、数据库或部署。
辅助 PDF 为有效 attachment placeholder，不验证 PDF 转换或原生 PDF 插件。
本轮不改变发布门禁、下载签发和非阻断契约；未提交、推送或部署。

本专项关闭图表设计的源缩略图库和配色色卡下拉缺口。图表数据点颜色侧栏
后续已接入，与原弹窗并存，见[格式侧栏专项](NATIVE_PPTX_CHART_FORMAT_PANE_ACCEPTANCE.md)。
完整FormatPane其他分组与整体布局仍未对齐。任意柱间距输入、圆环孔径控制尚未
暴露于宿主：它们主要是源引擎 API 能力，不能一概列为源既有独立数值 UI 缺口。
固定源散点图单点颜色写入限制仍在，外部/复杂图表安全边界未放宽。
不能标记完整 Chart Design 或 PPTX 全面对齐。
