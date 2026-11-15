# 原生 PPTX 相对图片原始尺寸验收

2026-11-11。固定参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
本专项接续会话基准百分比缩放，在已有大小与位置分组增加“相对图片原始尺寸”。

## 来源和实现边界

核对固定源 `apps/slides/src/renderer/components/FormatPane.tsx` 的
`naturalSize`、`relOriginal`、`naturalPx`、`scaleBasis`、`commitScale` 和 `stepScale`。
FormatPane SHA256：`7af130c4cd8901b83c96ae7bd0f534c97ed8a083415518ccd624655516a342cd`；
中文 pane SHA256：`071ac21956cd1e4fb5a92c11a79ff95582f991af5a2b132ef82fb58f6f6692d8`。
这是宿主行为适配，不是完整 FormatPane 的逐字复制。

- 复用当前渲染树 picture 节点的 `data:image/` URL，使用浏览器
  `Image.naturalWidth/naturalHeight`；不发起额外远程图片请求，不增加后端字段。
  该基准是96dpi坐标下的自然像素，不另行读取图片 DPI 元数据或推算物理印刷尺寸。
- 图片原始尺寸就绪后默认启用；关闭后使用本次选中时的可见框尺寸基准。
  纯切换仅改变百分比显示，不改实际 geometry、不创建草稿或历史。
  若用户已有完整但未提交的输入，先按切换前基准执行已有 flush；无效输入阻止切换。
- 原始宽高分别作为宽度/高度百分比基准，继续复用厘米、1%步进、比例锁定、
  边界校验、撤销重做和保存前 flush。沿用既有比例锁状态，不借本专项调整其默认策略。
  裁切不改变原始像素基准；尺寸修改合并到已有 pictureCrops geometry，保留 srcRect 和来源身份。
- 解码期间暂禁用原始模式的百分比输入，厘米仍可编辑；失败或来源缺失后回退会话基准，
  开关禁用并给出中文原因。同一对象同一 URL 不重复解码。
- 当前对象、URL、待保存替换状态及销毁参与异步有效性判断，旧回调不能污染新选择。
  图片替换待保存时立即禁用原始模式、回退会话基准，保存重开或撤回后重新读取。
- 图片来源变化不依赖输入合法性，不触发提交，也不重建或丢弃未完成的厘米输入；
  旧原始基准下的待提交百分比失效。解码回调只刷新百分比和来源状态。
- 主入口在分组目标更新后传入图片来源，迟到的渲染树也可更新当前对象。
  不改 wire、Python/bridge、引擎、发布签发或下载链路。

## 定向回归与复核

证据目录 `/tmp/pptx-original-20261111/`。未运行或重复完整测试集。

- `component-red.log`：新增4项原始尺寸用例在开关缺失时失败。
  `component-green.log`：新增4项、既有会话缩放4项、厘米6项，共14项通过。
- `integration-red.log`：新增迟到渲染数据集成用例在主入口接线前失败；
  `integration-green.log`：该用例及既有会话缩放、厘米/裁切集成，共3项通过。
  覆盖保存请求的真实 geometry、裁切身份、撤销重做、正文保留及未失焦字段 flush。
- 独立只读复核发现来源更新先 flush 的问题：厘米输入为空时会阻止新来源解码，
  甚至保留待替换图片的旧基准。`source-input-red.log` 已复现；移除来源更新的 flush，
  将身份失效与输入提交分开，`source-input-green.log` 的新增回归和核心换算用例2项通过。
  复核确认原问题关闭，未发现该修复引入的新实质问题。
- 最终定向 TypeScript 检查 `tsc-focused-final.log` 退出0。

## 独立构建与预算

初次构建 `build.log` 不能替代上述复核修复后的构建；最终 `build-final.log`
退出0，50.05秒，输出 `static-final/`。临时配置只移除会写共享资源的 PDF 复制插件，
未覆盖共享 static、引擎 dist 或修改预算。

`budget-final.json` 检查376个 JS chunk，failures=[]：

- `lazy-slides-main-BtSVaSTD.js`：255555字节，250KiB预算内剩445字节。
- `lazy-native-pptx-geometry-DjvLRLSz.js`：6874字节。

manifest SHA256：`020477d66d9111eca639c213fa3208a1f81efca982fc27a22b6b3ab132ab1b65`。
继续使用前一专项独立 runtime，未修改或重建引擎：

- edit：`0814aee61947db84d602e70eb2443ec6a94c085887aa8c66d1fc3e8a1a557b54`
- render：`4fd9061aca988f83794ee246227546f8fd46af9fe93a47475be0d9ebb3707592`

## 真实浏览器和独立下载核验

既有 `smoke/pptx-parallel-edit-smoke.mjs` 增加 `PPTX_SMOKE_ORIGINAL=1` 分支；
既有会话缩放分支显式关闭原始基准，继续表达其原有会话语义。
首两轮浏览器脚本校准失败记录保留在 `browser-initial.log`、`browser-initial2.log`
及对应目录：首次把图片位置误写为672/96，按真实来源96/288修正；
第二次假定空 edits 会序列化为数组，实际 NativeDraft 会省略它，改为核对缺省空数组。
两次均未修改生产代码、构建或放宽零错误、geometry、身份与裁切断言。

最终 `browser-final.log` 退出0，`browser-final/evidence.json` 为ok=true、revision=2。
实际加载121份 JS，逐一核对响应与磁盘大小/SHA256；manifest运行前后不变。
pageErrors、consoleErrors、routeErrors、failedResponses均为空。
`original-wide.png`、`original-narrow.png` 和 `revision-2.png` 已目视；
分组无水平溢出，不据此宣称整个Ribbon已在窄屏完全适配。

真实浏览器通过的行为：

- 原图48×32像素、可见框192×96像素，初始显示原始基准400%/300%；
  切换会话100%/100%无草稿，按会话宽度150%后得到288像素，切回原始显示600%。
- 纯基准切换不增加历史；撤销/重做保留当前基准。锁定比例后宽200%得到96×32像素。
- 实际文件选择器替换图片后，旧原始基准立即禁用并提示待保存替换；撤销后恢复原始基准。
- 真实鼠标拖动裁切，百分比/厘米修改合并进同一crop记录，无额外通用geometry记录，
  srcRect与来源身份保留；刷新恢复后重新得到原图基准。
- 不触发blur而保存高度150%，保存请求得到48像素；实际下载身份与签发回执一致。
  使用实际下载bytes打开修订2，显示原始400%/150%、厘米5.08×1.27；
  再次切换基准不产生草稿。

`verify-download.py`、`verify-xml.py` 均通过，结果为
`browser-final/independent-final.json`、`xml-final.json`；额外Pillow回读为
`image-pixels-final.json`：

- 来源SHA256：`bc7bdb76fe741a413cffd4a46f9728a0beddbce06136337d058e4c752605d5e8`。
- 实际下载47034字节，SHA256：
  `6807a65eda6b65add1a62f6b7648ff1e2dfe06017a5bed421c492e0d55c00083`。
- python-pptx回读图片EMU `[914400,1828800,1828800,457200]`，即左2.54cm、上5.08cm、
  宽5.08cm、高1.27cm；原文本框EMU `[914400,914400,4572000,914400]` 未改。
- 来源和下载图片均为48×32像素，图片blob SHA256相同；文字、图表、主题、母版、版式、
  嵌入工作簿、媒体和第二页均保留，srcRect按PPTX十万分之一精度回读。
- ZIP仅 `ppt/slides/slide1.xml` 变化，43个其他文件部件逐字节相同。
  除修改的图片xfrm/srcRect及既有保存器补入Picture 2 creationId外，
  图片剩余XML精确相同；其他对象和第一页非对象XML也逐字节相同。

鉴权/CSRF为明确标识的API route fixture；辅助PDF是有效附件占位。
真实Python inspect/patch/render、下载和独立回读已运行，不据此声称生产鉴权或PDF转换通过。
最终实现及专项脚本身份另登记于 `implementation-identity.json`。

## 仍开放

旋转、复杂填充/轮廓编辑、效果、文本框设置、完整 FormatPane 布局及多选格式编辑
仍需专项对齐；图片替换后的新原始基准须保存重开，当前不会读取未保存替换文件作为基准。
现有 geometry 安全边界保持，不扩大受限图片、图表、组合、表格或负实际位置范围。
生产鉴权、数据库、部署和 PDF 转换不属于本次验收；代码未提交、推送或部署。
