# PPTX 图片透明度与背景格式验收

2026-11-11。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这两项功能闭环，不代表 PPTX Ribbon 已全部对齐。

## 固定源行为

- **Picture Format ▸ Transparency**：`pptx-engine` 的 `setPictureOpacity` 把整图不透明度写成 `<a:blip>` 下的 `alphaModFix`；值为 1 时移除该节点。
- **Design ▸ Format Background**：`FormatBackgroundPane` 提供以下选项。各项都通过 `pptx-ops` 的规范操作 `setBackground` 写入（kind 为 image / gradient / reset / graphics）；该操作还会把铺满整页、不含文字的底板矩形随背景重绘，图片背景时则改为透明。
  - 图片填充：拉伸或平铺。
  - 渐变：起止两色，方向为 → / ↓ / ↘ / 径向，角度单位是 1/60000 度。
  - 隐藏背景图形（`showMasterSp="0"`）。
  - 重置背景：移除本页自有的 `<p:bg>`，回到版式或母版背景。
  - 应用到全部：同一图片用于多页时，后续页只新增关系，复用已有媒体部件。

## 原生实现

| 项 | 内容 |
| --- | --- |
| 透明度操作 | `editSlides.pictureOpacities: [{slideIndex, elementId, expectedSha256, expectedSize, opacity}]`，`opacity` 取 0–1 的整数百分比。 |
| 透明度身份 | 绑定图片媒体的 SHA-256 和字节数；只接受单一嵌入位图的普通图片。 |
| 透明度校验 | 与删除对象、替换图片冲突时整批拒绝。 |
| 透明度前端 | 功能区“透明度 %”数字框，输入值即透明度（写回 1 − 透明度）。改回来源值即撤回该修改。 |
| 透明度预览与草稿 | 画布按待保存值预览；支持撤销/重做和草稿恢复。 |
| 透明度与替换 | 有待保存的透明度时，替换图片会被拦下并提示。 |
| 背景图片操作 | `editSlides.backgroundImages: [{slideIndices, bytesBase64, extension, tile}]`：一张 PNG/JPEG 应用到若干来源页，每页至多一张，最多 10 张。 |
| 背景图片校验 | 不能与同页纯色背景或已删除页冲突；图片经签名检查和 PIL 校验。 |
| 渐变 / 重置 / 隐藏背景图形操作 | `backgroundGradients: [{slideIndices, from, to, angleDeg ∈ {0,45,90}, radial}]`、`backgroundResets: [slideIndex]`、`backgroundGraphics: [{slideIndex, hidden}]`。 |
| 渐变 / 重置 / 隐藏背景图形校验 | 每页只能有一种填充（纯色、图片、渐变、重置四选一），冲突时整批拒绝。只有来源自带背景的页才能重置。 |
| 背景格式前端 | 设计 ▸ 背景图片或设置背景格式，都打开同一个对话框（填充：图片或渐变）。对话框里还有拉伸/平铺、起止颜色与方向、隐藏背景图形、应用到全部页面和重置背景。 |
| 背景图片与纯色 | 同一页只保留最新一种背景：设图片时清除该页待保存的纯色，反之亦然。 |
| 背景图片预览 | 待保存列表可逐项撤销；画布通过真实 render-tree 预览。 |
| 桥接 | `bridge/pptx-picture-opacity.ts`、`bridge/pptx-background-image.ts`、`bridge/pptx-background-ops.ts`。先整批校验，再调用未改动的引擎函数或 `setBackground` 规范操作；页面按稳定的 slide durable id 寻址。透明度在裁切之前应用，两者可以同批。 |

## 证据

- `reporting/slides_engine/bridge/tests/pptx-picture-opacity.test.ts`：写入、回读、清除；与裁切同批；媒体部件与其他页字节不变；重复、过期身份、越界值、删除或替换冲突均整批拒绝。
- `reporting/slides_engine/bridge/tests/pptx-background-image.test.ts`：多页共用一个媒体部件；拉伸、平铺可回读；未选中的页字节不变；越界、重复、冲突、非法图片均拒绝。
- `reporting/slides_engine/bridge/tests/pptx-background-ops.test.ts`：渐变（线性 90° 写为 `ang="5400000"`，径向写为 `path="circle"`）、重置、隐藏背景图形，全部可回读；全幅底板随渐变重绘；冲突、非法方向与颜色、重置非自有背景均整批拒绝。
- `reporting/tests/test_pptx_picture_opacity.py`（11 项）与 `test_pptx_background_image.py`（20 项）：经 Python 入口写入，用 python-pptx / ZIP 独立回读。
- `frontend/smoke/pptx-picture-opacity-smoke.mjs`：在 Chromium 中跑真实 Python→PPTX 引擎链路，授权和修订路由用 fixture。
  - 透明度：设为 60%，撤销、重做；改回 0% 后撤回；再设为 35%。
  - 背景图片：设计 ▸ 背景图片，选平铺、应用到全部页面后选择文件。
  - 渐变：切到第 2 页，打开设置背景格式，设 ↘ 渐变 #FF8800→#004488 并隐藏背景图形；该页的图片背景被覆盖，第 1 页保留平铺图片。
  - 刷新后草稿恢复，控件回显。
  - 保存为修订 2，下载字节与保存一致。
  - 独立回读：
    - 图片位图与几何不变，出现 `alphaModFix amt="65000"`。
    - 第 1 页 `<p:bg>` 是平铺 `blipFill`。
    - 第 2 页是 `gradFill`（`ang="2700000"`），并且 `showMasterSp="0"`。
    - 只新增一个背景媒体，其摘要等于上传图片；其他部件不变。
  - 重开修订 2：透明度仍为 35%；第 1 页平铺图片，第 2 页 45° 渐变且隐藏背景图形；画布截图可见。

## 与固定源的差异 / 未验收

- 背景面板的纹理库，以及多色标/自定义角度的渐变尚未接通；纯色背景沿用原有入口，未改为规范操作。
- 重置背景只在浏览器外由 Python/桥接测试覆盖：冒烟夹具的页面没有自带背景，因此按钮只会撤回待保存修改。
- 固定源的透明度是滑块，这里是百分比数字框。
- 本次在开发服务器模式下运行，生产镜像、真实授权和发布链路未验收；也未在 PowerPoint 中人工打开核对。

## 附：视图 ▸ 网格线（2026-11-12）

- **固定源实现**：`showGrid` 是纯视图状态，在画布上叠加 `.grid-overlay`，线色 `rgb(60 60 60 / 16%)`，间距 48px（即 0.5 英寸）。
- **原生实现**：功能区“网格线”改为开关按钮，`aria-pressed` 反映状态；网格间距按幻灯片尺寸换算为画布百分比，任何缩放下都是 0.5 英寸。这只是视图状态，不写入文件，也不产生草稿。
- **证据**：同一个冒烟在修订 2 上开启网格线。开启后画布的叠加层计算样式出现 `linear-gradient`，草稿为空；截图中 4:3 页面为 20×15 格。关闭后叠加层消失。
- **视图 ▸ 标尺**：
  - 刻度算法 `vendor/genoffice-slides/ruler-ticks.ts` 与固定源逐字节一致；`slides-ruler.ts` 把 `StageRuler` 移植为原生 DOM。
  - 标尺位于缩放画布之外，0 在页面中心，中文界面用厘米；按住主键在画布上拖动时，指针位置细线随之移动。外壳颜色取 `--office-*` token。
  - 冒烟断言：开启后两条标尺都有刻度，“0”与页面中心的偏差小于 2px，草稿为空；关闭后标尺移除。截图中 4:3 页面水平方向约为 ±12.7 厘米。
- **视图 ▸ 参考线**（补上了原生功能区此前缺少的开关）：
  - `slides-guides.ts` 移植固定源 `guides`、`showGuides`、`guidePreview`、`guideBubble` 的行为。
  - 默认横竖各一条居中；可以从标尺拉出新参考线（横向标尺拉出水平线，纵向标尺拉出垂直线，有 4px 死区，放回标尺即取消）。
  - 拖动可移动参考线，拖出画布 24px 以外或双击即删除；拖动时气泡显示距页面中心的厘米数。
  - 参考线按文档保存在本机 localStorage，不写入文件，也不产生草稿。
- **参考线冒烟断言**：
  - 开启后有 2 条参考线；从横向标尺拉到页面 25% 高度处，新增一条水平线，气泡读数格式为 `x cm`。
  - 双击竖线删除；本机存储里只剩两条水平线；把新加的水平线拖出画布后删除。
  - 草稿始终为空。
