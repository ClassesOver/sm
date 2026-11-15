# 已有表单字段复制设计与实施计划

执行方式：沿用持续“继续”的授权，在本会话实现；不新增提交或共享构建。

**Goal:** 安全单 Widget 字段可复制、重复、跨页粘贴，保留实际 V/DV/字体/AP，原字段不变。

**Architecture:** 扩展 createFormField 的可选 copyFrom 来源身份。服务端从实际 PDF 深复制字段/Widget 和辅助对象图，重绑新名字/Parent/Kids/P/Rect；整批先预检，再复用批创建回执。前端不自报来源值。

**Approaches:** 前端投影重建会丢默认值/字体/AP；任意对象图复制边界过大；采用有界来源字典深复制。该实现选择由执行者作出。

**Tech Stack:** 现有 TypeScript/pdf-lib、NativeDraft/FormDesignLayer、Vitest/node:test、Python服务与Chromium。

## 范围与 Review Focus

- 单 Widget text/checkbox/choice，同父新叶子，允许跨页平移，保持尺寸；radio/date/signature/复杂动作暂不支持。
- copyFrom 绑定原 fieldName/widgetId/widgetIdentity/expectedWidgetSha256；保留不同 V/DV、字体、必填、选项/AP。
- 未保存副本仅移动/删除/复制；属性/尺寸保存重开后再编辑。
- 辅助对象私有，后续填写不能改变原 AP；伪造、冲突及批次后项无效均须零写。
- 已生成 PDF 的复核失败保留字节与下载，不增加发布门禁。
- 不重复完整套件，明确既有全局类型诊断；保护键盘/菜单快照及跨画布一次提交。

## 步骤

- [x] 引擎 RED：真实来源保真、后续填写隔离、批次预检及输出复核故障。
- [x] 实现 form-copy-safety.ts、form-source-copy.ts，并接入设计 census、创建 schema 和批次来源重绑。
- [x] 前端 RED：来源 clipboard、copyFrom 校验、画布入口及副本限制。
- [x] 实现 pdf-form-create/design/clipboard/design-canvas 的局部接线。
- [x] 运行新增与受影响专项；真实服务保存下载及 Chromium 复制/跨页/Undo/恢复/实际预览，独立回读。
- [x] 更新验收及有效缺口，明确首批边界。

验收结果见 NATIVE_PDF_SOURCE_FORM_COPY_ACCEPTANCE_20261114.md；各批次重叠测试不累计计数。
