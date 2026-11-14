# 浏览器放映来源记录

- 调查源：GenOffice commit f8c17004fb730df11f0f743164ffd8b4281bb38c，Apache-2.0。
- apps/slides/src/renderer/components/SlideShowView.tsx SHA256 a52121f289769c7d91d12e141a6c10764a141f09087f42c5bb66a5e99d559a79。
- apps/slides/src/renderer/slideshow-utils.ts SHA256 d3cdbbb002ef220a32447c3b1929407448b318993820785d12bc39a3bee1f6fc。
- LICENSE SHA256 68e32334df324ef4fc79fad3a26487e5abac36055a484bb6c8d7ecf9d8350885；既有 vendor/genoffice/LICENSE 与 SOURCE.md 保留许可证和渲染器来源。
- 放映入口：apps/slides/src/renderer/components/Ribbon.tsx:2330/2341 调用 onSlideShow(true/false)，App.tsx:1904 将其委托 show-actions.ts 的 startSlideShow；本地 startShow/startShowCurrent 均保留 sourceActionId=onSlideShow，由宿主区分起点。Ribbon.tsx SHA256 6a261cf18bbdbf2b39fa51add3d30383a10ded4a072303e0012cb7e5cde00aba；show-actions.ts SHA256 d71e13c737a6a5d94440b414e0046fe92ae5f84077f5139902b817c73c0cfb9e。
- 组合动作：arrange-actions.ts groupSelected/ungroupSelected，SHA256 671ff16bfc371691760b148bcf5c6735e095e2519853c3d76672ce828341cd32。组合图标采用既有 Lucide Group/Ungroup 适配，非固定源图标复刻；当前页放映使用既有固定源 IconPlayCurrent。

固定源 `SlideShowView`、`show-keys`、`show-menu`、`slideshow-utils`、`MorphStage`、`ContextMenu` 和 `SlideThumb` 已迁入，复用真实 `AnimatedSlide` / `animation-play` 完成来源及当前草稿的对象动画分步、转场、黑白屏、数字跳页、结束屏、历史导航和全部页网格。宿主用既有 `render-tree` 与 `preview` 读取同一完整 NativeDraft，不新增 PPTX 解析器。传入完整页数组，隐藏页和从隐藏当前页起播由源顺序函数处理；startIndex 是完整数组下标，退出返回最后查看的完整数组下标。

浏览器适配提供原生 dialog、键盘与焦点隔离、全屏降级及清理；媒体、录制、排练计时、演讲者视图、逐文字运行链接和自定义放映配置尚缺授权宿主接口或模型。Morph 仅按真实名称回退配对；源 CSS 转场为近似效果。完整功能映射、适配和逐文件 SHA 见 `vendor/genoffice/SHOW-SOURCE.md` 与 `SHOW-SOURCE-SHA256.json`。放映不下载、不更改草稿、不保存。
