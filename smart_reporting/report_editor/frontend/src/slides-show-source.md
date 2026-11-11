# 浏览器静态放映来源记录

- 调查源：GenOffice commit f8c17004fb730df11f0f743164ffd8b4281bb38c，Apache-2.0。
- apps/slides/src/renderer/components/SlideShowView.tsx SHA256 a52121f289769c7d91d12e141a6c10764a141f09087f42c5bb66a5e99d559a79。
- apps/slides/src/renderer/slideshow-utils.ts SHA256 d3cdbbb002ef220a32447c3b1929407448b318993820785d12bc39a3bee1f6fc。
- LICENSE SHA256 68e32334df324ef4fc79fad3a26487e5abac36055a484bb6c8d7ecf9d8350885；既有 vendor/genoffice/LICENSE 与 SOURCE.md 保留许可证和渲染器来源。
- 放映入口：apps/slides/src/renderer/components/Ribbon.tsx:2330/2341 调用 onSlideShow(true/false)，App.tsx:1904 将其委托 show-actions.ts 的 startSlideShow；本地 startShow/startShowCurrent 均保留 sourceActionId=onSlideShow，由宿主区分起点。Ribbon.tsx SHA256 6a261cf18bbdbf2b39fa51add3d30383a10ded4a072303e0012cb7e5cde00aba；show-actions.ts SHA256 d71e13c737a6a5d94440b414e0046fe92ae5f84077f5139902b817c73c0cfb9e。
- 组合动作：arrange-actions.ts groupSelected/ungroupSelected，SHA256 671ff16bfc371691760b148bcf5c6735e095e2519853c3d76672ce828341cd32。组合图标采用既有 Lucide Group/Ungroup 适配，非固定源图标复刻；当前页放映使用既有固定源 IconPlayCurrent。

完整源放映组件依赖 Electron IPC、动画、转场、录制与媒体功能，未移植。浏览器组件仅复用既有 vendor/genoffice/renderer/NodeBody.tsx StaticNode 与 Konva 静态渲染；不新增 PPTX 解析器。组件宿主负责提供当前草稿生成的只读渲染树，已经排好顺序并过滤隐藏页面；startIndex 指向该可播放数组，组件不会二次过滤改变索引。无下载、草稿修改或保存。
