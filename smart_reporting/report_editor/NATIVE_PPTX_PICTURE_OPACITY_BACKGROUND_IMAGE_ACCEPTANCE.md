# PPTX 图片透明度与背景图片验收

2026-11-11。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这两项功能闭环，不代表 PPTX Ribbon 已全部对齐。

## 固定源行为

- **Picture Format ▸ Transparency**：`pptx-engine` 的 `setPictureOpacity` 把整图不透明度写成 `<a:blip>` 下的 `alphaModFix`；值为 1 时移除该节点。
- **Design ▸ Format Background ▸ 图片填充**：`FormatBackgroundPane` 提供拉伸/平铺两种方式和“应用到全部”。引擎 `setSlideBackgroundImage` 写入 `<p:bg>`；同一图片用于多页时，后续页只新增关系、复用已有媒体部件。

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
| 背景图片前端 | 设计 ▸ 背景图片打开对话框，可选拉伸/平铺和“应用到全部页面”，然后选择文件。 |
| 背景图片与纯色 | 同一页只保留最新一种背景：设图片时清除该页待保存的纯色，反之亦然。 |
| 背景图片预览 | 待保存列表可逐项撤销；画布通过真实 render-tree 预览。 |
| 桥接 | `bridge/pptx-picture-opacity.ts`、`bridge/pptx-background-image.ts`：先整批校验再调用未改动的引擎函数；透明度在裁切之前应用，两者可以同批。 |

## 证据

- `reporting/slides_engine/bridge/tests/pptx-picture-opacity.test.ts`：写入、回读、清除；与裁切同批；媒体部件与其他页字节不变；重复、过期身份、越界值、删除或替换冲突均整批拒绝。
- `reporting/slides_engine/bridge/tests/pptx-background-image.test.ts`：多页共用一个媒体部件；拉伸、平铺可回读；未选中的页字节不变；越界、重复、冲突、非法图片均拒绝。
- `reporting/tests/test_pptx_picture_opacity.py`（11 项）与 `test_pptx_background_image.py`（10 项）：经 Python 入口写入，用 python-pptx / ZIP 独立回读。
- `frontend/smoke/pptx-picture-opacity-smoke.mjs`：在 Chromium 中跑真实 Python→PPTX 引擎链路，授权和修订路由用 fixture。
  - 透明度：设为 60%，撤销、重做；改回 0% 后撤回；再设为 35%。
  - 背景图片：设计 ▸ 背景图片，选平铺、应用到全部页面后选择文件。
  - 刷新后草稿恢复，控件回显。
  - 保存为修订 2，下载字节与保存一致。
  - 独立回读：图片位图与几何不变，出现 `alphaModFix amt="65000"`；两页 `<p:bg>` 都是平铺 `blipFill`；只新增一个背景媒体，且其摘要等于上传图片；其他部件不变。
  - 重开修订 2：透明度仍为 35%，两页背景都是平铺；画布截图可见。

## 与固定源的差异 / 未验收

- 背景面板的渐变填充、纹理库、“隐藏背景图形”、“重置背景”尚未接通；纯色背景沿用原有入口。
- 固定源的透明度是滑块，这里是百分比数字框。
- 本次在开发服务器模式下运行，生产镜像、真实授权和发布链路未验收；也未在 PowerPoint 中人工打开核对。
