# 静态填写来源适配

固定源为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`（Apache-2.0，现有 vendor/genoffice-pdf/LICENSE / NOTICE 适用）。

`vendor/genoffice-pdf/renderer/static-form-fill.ts` 和 `form-mark-target.ts` 复用同名上游 renderer 文件。唯一适配是首行的纯类型导入：移除 Electron/大型 FormCatalog/SignatureDialog 的类型依赖，仅保留算法实际使用的字段，算法正文保持原字节。

`pdf-static-fill.ts` 接入原生编辑草稿、对话框和页面坐标：静态文字/勾叉为透明图片，不创建AcroForm；原生 checkbox 命中沿同源 App.tsx 的 setFormValue，印刷方框沿同源检测形状与mark-target吸附；完成填写的必填检查为软提示。

后端 `reporting/pdf_engine/bridge/static-form-fill.ts` 复用同源 main/image-edit.ts 的 PDFium insertImage/imageMatrix/deleteImage 片段，解码改用已有PNG/BGRA桥接，复用已有串行PDFium上下文；不启用Electron、不使用Stamp批注。已有 save-pdf.ts 的 GenOfficeStaticFormFills reader/writer保持不变，负责metadata与页重排/删除映射，涂黑区域的记录先清理以防敏感明文残留。

已保存图像只在sourceSha、原页面、metadata id/rect和图像fingerprint唯一匹配后可重编/移除。新增位图回读检查真实图像数量、矩形、尺寸与RGB像素摘要。后续metadata写入或输出复核失败保留实际生成PDF，给出reviewIssues；下载继续沿现有非阻断身份链。

当前范围：默认UserUnit、正交旋转的非签名非加密PDF（可含已有原生表单）。保存后的静态填写支持原来源页内移动和尺寸调整；不声称支持跨页移动、OCR、可搜索静态字或证书签名。删除是逻辑删除，敏感信息须用涂黑。独立回读与浏览器runner见 smoke/pdf-static-fill-*。
