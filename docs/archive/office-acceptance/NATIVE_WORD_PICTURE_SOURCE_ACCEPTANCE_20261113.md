# Word PictureDialogs 完整来源图片族验收

固定源commit f8c17004fb730df11f0f743164ffd8b4281bb38c。

完整PictureDialogs双组件移植：Crop8手柄+移动+viewport预览+16px最小+原分辨率烘焙；Cutout0..100容差/default30/520px预览/原分辨率背景采样/透明PNG。cutout.ts与固定源SHA完全相同：1603902d1abf65c1148aa80b59bed71cecdac317f2bea500396094a719b7b24a。

仅适配imports、现有modal focus/IME、卸载后迟到apply与短屏滚动。浏览器授权file input支持PNG/JPEG/GIF。原图保存复用SaveBlock.xml.replaceImage与patchImageParagraphXml，不重造OOXML；原始对象/像素SHA、base64/magic/8MB/真实尺寸/批冲突及原生回读校验。图片attrs的native草稿normalize/replay与undo/redo；异步apply复核doc、NodeSelection、node、position和generation。

内联/组合/多drawing/外链/保护来源只读。本轮开放既有来源整块图片与未保存genImage；未保存genImage三入口已接，复用既有insertParagraphImage；PNG/JPEG载荷直写，未保存GIF经浏览器烘焙PNG，不扩张原粘贴协议。

证据根：/home/junge/codex-evidence/smart_reporting/office-image-links-measure-20261113/word。

- native-final.log：4通过，独立ZIP关系/media、正文表格/第二图保持、无效格式/bytes/尺寸/staleSHA/重复、透明RGBA/比例、GIF/保护只读。
- frontend-final.log：定向101通过（pictures2、operations60、ribbon39）。未全量tsc，未完整测试。
- source-browser/result.json：12checks0errors1真实save，替换/取消/IME/Escape/目标变化拒绝/8手柄拖动+移动/undo-redo/草稿reload/390x640和640x320底部可达/fullPNG/save-download/revision2重开/只读。
- 实际下载SHA：7276f287d246dbf8fea1fee359d2ee13e203aec1861fe0d392b711913f5ae891
- 实际bridge entrySHA：92b9651a63b924c1141555254eddfe33915c3120f0f26e5fa2df6bcdd32a9624
- source/chunks/backend前后SHA匹配。独立Pillow读回实际RGBA/alpha0..255；保存validationfalse仍真实下载。

正式构建待续：本agent未改共享static/dist/build、水印族，未commit/push/deploy。root统一freeze/build后用smoke/docx-picture-source-smoke.mjs续验，不能把source证据标记正式构建证据。支持DOCX_TEST_DIST、DOCX_FROZEN_FRONTEND、DOCX_EXPECTED_MANIFEST_SHA256、DOCX_EXPECTED_BRIDGE_SHA256、AGENT_REPORTING_DOC_ENGINE_DIR。

补充验证：frontend-pending.log新增genImage投影用例3/3通过；已有operations60与ribbon39保持前次定向通过，总计102个不同用例。

最终稳定源续验：source-browser-final/result.json为genImage代码加入后12checks0errors来源图片浏览器验收；source-browser-before-genimage保留旧结果/初始open失败。最终下载SHA f73969f353c9a6b2905837973ac480029788bf20d6c79692ed4f10d59cf88ab6。genImage分支以frontend-pending.log三用例中的新增投影契约验证，尚未在浏览器单独走未保存图片入口。正式freeze待root统一完成。
