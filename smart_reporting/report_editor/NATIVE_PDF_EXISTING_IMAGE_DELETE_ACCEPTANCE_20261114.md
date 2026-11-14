# 已有图片删除验收（2026-11-14）

后续文字层级增量见 [图片层级验收](NATIVE_PDF_EXISTING_IMAGE_LAYER_ACCEPTANCE_20261114.md)；本记录保留删除批次的证据与范围。

本批接通实际来源图片的一处页面绘制删除，复用已有身份、NativeDraft、Undo/Redo/恢复、实际预览确认及修订下载链。相同像素数据在其他位置复用时保留其他绘制，不改原来源。属于逻辑移除，不保证清除文件中的图片资源；安全擦除仍使用既有涂黑。

## 实现与边界

固定源 ImageEditInput 包含 deleteImage；已有背景补丁同样使用 RemoveObject/Destroy。本批使用相同 PDFium 原语，在私有内存文档中删除匹配的页面直属对象、重新生成内容并保存；不创建覆盖白块或 Stamp。

- 扩展现有 transformExistingImage 的 remove:true，rect 必须绑定原范围，不能同批移动/缩放、替换或烘焙。严格来源 SHA/pageId/imageId/expectedImageSha256 和既有独占草稿限制保持。
- removable 限身份唯一、可编辑、页面直属且位于 CropBox 的图片；模板内、重叠歧义、非默认单位/保护/表单等既有限制不放宽。来源带 GenOfficeStaticFormFills 元数据时拒绝通用图片删除，避免遗留失效填写记录，继续使用静态填写的专门删除入口。
- 删除后逐一复核所有幸存图片像素与范围、正文、页数/旋转/MediaBox/CropBox；复核失败保留已生成字节和诚实告警。没有新增发布接口、签发步骤或门禁。
- 中文编辑面板增加“删除选中图像”，检查草稿/来源快照、异步加载与未完成几何/像素修改；可撤销恢复。实际预览清单明确“删除已有图像”。
- 删除不进入会重新画回图片前景的缩略图变换路径；实际预览前缩略图仍是原稿，实际 PDF 预览后显示删除结果。模板内删除、任意组合和前后层级切换仍开放。

## 定向测试与失败记录

| 验证 | 结果 |
| --- | --- |
| 引擎 RED | `/tmp/pdf-image-delete-engine-red.log`：删除能力尚未声明，四旋转正向和模板限制断言失败，拒绝类当时通过。 |
| 引擎 GREEN | `/tmp/pdf-image-delete-engine-final.log`：15 项通过，新增删除4项和既有移动/替换关联专项。覆盖四旋转、多页同像素复用只删一处、原文/幸存图片不变、混合/伪造拒绝、模板/静态记录边界与复核故障保留真实字节。 |
| 前端 RED | `/tmp/pdf-image-delete-front-red.log`：新增删除协议和面板入口两项失败。 |
| 前端分批 GREEN | `/tmp/pdf-image-delete-front-final.log` 首轮7文件110项通过、1项失败；失败是新增面板用例多个夹具共用 localStorage 身份，后一个夹具恢复了前一个已保存的草稿，并非来源守卫失效。只清理测试场景间存储，`/tmp/pdf-image-delete-panel-final.log` 面板7项通过，未重复其余6文件。最终关联覆盖111项，不把两次重叠用例累加，也不伪称首轮整体退出成功。 |
| 真实服务 | `/tmp/pdf-image-delete-service.log`：1项通过，实际 preview/preview_file、确认前拒绝、确认保存、修订登记/授权下载流及独立 PyMuPDF/pypdf 回读；三处绘制变两处，两页各一处，幸存像素/位置和正文保持，原来源不变。业务 validation.ok=false 仍保留实际下载。 |
| 类型检查 | `/tmp/pdf-image-delete-types.log` 与上一批逐字节相同，仍有既有632条诊断，不能称全项目类型通过。 |
| 独立复核 | 同模型 reviewer 静态复核无 Important，未运行测试，不算运行证据。 |

没有重复全项目套件，未修改共享 static/dist、提交、推送或部署。

## 中文真实浏览器与独立 PDF

浏览器使用实际源码入口、固定面板/PDF.js、隔离 CLI；API 适配仅实际预览，不含生产授权/发布，真实服务链由上面的 Python 测试承担。

1. `/tmp/pdf-image-delete-browser`：夹具从表单专项沿用 getForm，意外生成空 AcroForm，正确触发现有来源限制，按钮保持禁用；保留失败，不放宽产品门控。移除无关夹具表单创建后继续。
2. `/tmp/pdf-image-delete-browser-final`：完成中文公共“编辑图像”入口、390px窗口与删除按钮、暂存、Undo/Redo、刷新恢复及实际 PDF 预览；清单“删除已有图像”，applied `[0]`、零跳过，页面/HTTP错误在 ui-evidence.json 检查点为空。末尾旧 fitz 入口在 stdout 输出弃用提示，导致 JSON 解析器退出1；PDF实际生成与Python内部断言已完成，不把整轮冒称退出0。同一文件独立重读 `/tmp/.../independent-recheck.json` 确认像素/位置与来源、输出 SHA 正确。
3. `/tmp/pdf-image-delete-browser-verified`：使用 pymupdf 正式入口，仅从上一轮真实来源和真实操作恢复草稿续验；没有伪造 SHA 或重新开发一份来源。真实预览和独立回读退出0，evidence.json 为 ok:true：drawnImagesBefore=3、After=2、perPageImages=[1,1]，幸存像素和位置不变，页面/HTTP错误为空。该最小续验不冒称重跑完整删除/Undo链。

窄屏面板和实际 PDF 预览截图已目视，删除按钮与底部动作可见；目标位置不再显示图片，其他页和同页幸存图片保持。Vite 保留 sibling fast-xml-parser/utif2（首轮亦有 saxes）依赖预扫描告警，Python imghdr 弃用提示保留；修正的 fitz stdout 告警也保留在失败日志。

隔离 CLI `/tmp/pdf-image-delete-runtime/dist/cli.mjs` SHA256 为 `b4e6368494e36c190dcfd206f6c0a34e109f3ded5c27faa784599beafc7d3527`，6,165,940 字节。整体 PDF 对齐与统一部署验收仍未完成。
