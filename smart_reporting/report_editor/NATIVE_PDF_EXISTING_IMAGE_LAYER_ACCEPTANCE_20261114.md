# 已有图片文字层级切换验收（2026-11-14）

本批支持安全页面直属图片置于文字下方或上方，保留图片像素、矩阵/范围、原文和其他对象。沿用原身份、独占草稿、Undo/Redo/恢复、真实预览确认与修订下载，不新建发布接口或签发步骤。

## 规则与边界

可见固定源 IPC 的 ImageLayer 为 belowText/aboveText，PageImageRef.aboveText 按首个文字对象分界。沿用 bridge 原 firstTextIndex：下方把目标插入首个直属文字对象前，上方追加到页尾；其余对象相对顺序不变。本工作区未包含完整源 image-edit.ts，本批属于按该可见合同实现的限定适配，不宣称重放了全部桌面 writer/宿主语义。

- 要求引擎支持 InsertObjectAtIndex，页面有可读取的直属文字且无 Form 对象；目标页面直属、身份唯一、处于 CropBox 且通过原有编辑来源检查。
- 沿用静态填表元数据、保护/表单、歧义与非默认单位等限制；无文字页、含模板页面或复杂来源不开放。图像像素可被其他位置复用，切换本处对象不会替换共享像素。
- layer 与删除、几何、替换、烘焙互斥，同层请求拒绝。页面 Rotate 四方向与图片自身旋转矩阵分别验证。
- RemoveObject 后重新插入同一对象，不重新生成图片；finally 检查其是否仍挂在页面，只销毁未挂载的对象，避免双重释放。输出复核目标及其他图片文字层级、像素/范围、正文和页面；复核失败保留已生成字节。
- 中文面板增加“文字层级”、当前状态、禁用原因和独立应用守卫；来源/草稿变化或未完成混改不得提交。清单显示“图像置于文字上方/下方”。
- 未进入实际 PDF 预览前保留原稿缩略图，不用旧前景图假冒新层级；实际 PDF 预览后显示真实遮挡结果。不包含任意图层管理或复杂模板重排。

## 定向测试与复核

| 验证 | 结果 |
| --- | --- |
| 引擎 RED | `/tmp/pdf-image-layer-engine-red.log`：未声明 layer 能力/协议；正向及输出故障场景失败，拒绝类通过。 |
| 首次 GREEN 迭代 | `/tmp/pdf-image-layer-engine-green1.log` 中实际排序已执行，但测试错误要求正文 objectPath 序号不变。排序必然改变页对象序号；改为明确断言全部原文/字形/颜色/字体/范围保留且直属文字序号按目标前后移动恰好±1，未放宽正文实际属性。 |
| 引擎关联 GREEN | `/tmp/pdf-image-layer-engine-final.log`：20项通过，含双向四旋转、共享像素/其他页、混改/同层/来源拒绝、无文字/含Form/静态记录边界和复核字节保留，以及删除/移动/替换受影响专项。 |
| 自身旋转矩阵追加 | `/tmp/pdf-image-layer-own-matrix.log`：仅新增1项通过，检查30°自旋转目标的完整六元素矩阵在PDF序列化精度1e-4内保持及实际像素不变；没有重跑上面20项。 |
| 前端 RED/GREEN | `/tmp/pdf-image-layer-front-red.log` 两新入口/协议测试失败；最终 `/tmp/pdf-image-layer-front-final.log` 七文件114项通过，含面板、验证、缩略图、像素/异步替换/可视编辑和公共宿主。保留既有React act警告。 |
| 真实服务 | `/tmp/pdf-image-layer-service.log`：belowText/aboveText 两参数2项通过。实际预览、确认前拒绝、确认保存、新修订、授权下载流及 PyMuPDF 回读；图像内容/位置集合、原文与来源不变，两方向的真实遮挡像素分别增加/减少。validation.ok=false 仍保留真实下载。 |
| 全局类型 | `/tmp/pdf-image-layer-types.log` 与上一批逐字节相同，仍为既有632条诊断，不称全项目通过。 |
| 独立复核 | 同模型 reviewer 静态复核未发现 Important；未运行测试，不计作运行证据。 |

测试仅新增及受影响专项，和历史批次有重叠，不相加作唯一总数；没有重复完整套件。

## 中文真实浏览器和视觉证据

`/tmp/pdf-image-layer-browser/evidence.json` 为 ok:true。真实源码/固定面板/PDF.js/隔离CLI，HTML zh-CN 且七个功能区标签均为中文。浏览器API适配只提供真实预览，生产授权/发布由上面的服务测试承担。

- 从公共“编辑图像”选择“置于文字下方”，坐标输入锁定，独立应用、Undo/Redo、刷新恢复后，来源绑定的 layer 操作保持。
- 390px面板 left16/right374，clientWidth=scrollWidth356；窄屏与实际预览截图已目视，操作与底部按钮可用。
- 实际预览清单“图像置于文字下方”，applied `[0]`、零跳过。三处绘制仍为三处，两页分布 `[2,1]`，像素与位置集合不变，来源SHA不变，页面/HTTP错误为空。
- 不透明图片覆盖正文的样例：目标范围内黑色文字像素从0增至543；独立 get_bboxlog 确认图片已在首个文字对象之前，截图中 COVERED CONTROL 实际可见。不是仅凭 aboveText 字段断言遮挡效果。
- 上方向真实保存与遮挡回归由服务 aboveText 参数独立验证，没有冒称浏览器重复完成双向流程。

隔离 CLI `/tmp/pdf-image-layer-runtime/dist/cli.mjs` SHA256 为 `04bb87dbfa3d8e52afa32d98ff9cedd033340a34fb1ba24c80544b67ebf1a77c`，6,169,192字节。Vite仍有 sibling fast-xml-parser/utif2 预扫描告警，Python imghdr 弃用提示保留。未修改共享 static/dist、提交、推送或部署，整体PDF对齐仍未完成。
