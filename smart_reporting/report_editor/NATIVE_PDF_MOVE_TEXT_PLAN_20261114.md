# PDF Original Text Move Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 通过来源对象身份移动原PDF文字，保留原字形/字体/字距；实际预览确认后保存。
**Architecture:** 新增moveText白名单操作（sourceSha256/pageId/objectId/expectedTextSha256/delta），映射固定引擎TextEditInput.translate；仅移动整对象。使用现有PDF文字开关、修订/预览确认/下载合同。界面复用原位文字对象选择器，增加位移输入和提交；草稿可Undo/Redo/恢复。
**Tech Stack:** TypeScript, PDFium, NativeDraft, Python NativeEditorService, Vitest, Playwright.
**Spec:** 下述Design。

## Design
复用固定源translate保持实际对象，区别于擦掉再插字。只开放安全无表单/无保护/无批注/默认单位来源，最多500个独立对象移动；与其他种类暂不混用。全部原SHA/对象/矩形和目标CropBox边界先校验；重复、歧义、源匹配不独占不能执行。实际输出独立回读字体/文字/目标位置及全部非目标对象，异常保留已生成字节并报告跳过/复核失败。位移为原PDF用户坐标，不随显示页旋转换算成屏幕方向。范围为单文字对象，未完成任意段落块/跨对象reflow或AI工具。

## Global Constraints
保留已有修改；不新增依赖/路由/签发步骤；新操作必须使用现有文字开关和预览确认；只跑定向测试，不提交部署。

## Review Focus
对象冒用和全部输入预校验；重复/共享对象；字体和非目标保留；实际写入后复核失败仍保留字节；只读/预览/保存/过期控件不可提交。

### Task 1: 引擎
- [x] source-text-move.test.ts先RED（位置/字体/页结构、伪造/越界、后置复核故障）。
- [x] source-text-move.ts复用validateTextEdits/applyTextEdits的translate；operations.ts增加schema/能力/纯移动分发。
- [x] 引擎定向GREEN。

### Task 2: 宿主/服务
- [x] pdf-text-move.test.ts与宿主测试RED；验证并生成来源绑定操作，增加位移UI及独占门控、实际预览标识。
- [x] native.py文字开关和native_pdf_contract确认种类包含moveText；服务禁用/确认/保存下载测试。
- [x] 定向Vitest和实际Chromium/CLI/pypdf位置核验。

### Task 3: 审查
- [x] 独立审查，修复重要问题；记录实际验证和剩余缺口。

## Results
- 初始schema未知moveText RED，前端模块缺失RED。复用固定源translate，不改固定源text-edit实现。
- 引擎最终5/5：四种页面旋转、倾斜原文字、跨页两对象、原文字体/几何/非目标保留、全部输入无效零写入、实际写入后复核异常保留字节。
- 最终6个前端专项53/53；文字开关/只读/失效/Undo/Redo/清零/独占隔离/真实预览进入均覆盖。
- 独立审查无重要发现，建议补多对象成功批次，已加跨页两对象回归。
- 真实浏览器首次暴露预览分支未含moveText，补宿主RED后修复；第二轮仅是暂存后异步控件更新前立即断言的烟测竞态，保留失败，改为等待同一严格禁用条件。最终final2通过。
- 类型检查新增target空值诊断已修，最终日志与上一批逐字节相同（632个既有诊断）；不声明全局通过。
- 服务开关/保存确认/实际下载4项通过；末尾加强输出页面几何验证后，最终运行实际保存参数1通过3未运行，不重复累计。
- 最后验证器增量不改输出writer；final-runtime-continuity.json确认最终bundle重算PDF与浏览器实际预览逐字节相同。
- 未提交/部署/开功能开关；详细记录见NATIVE_PDF_MOVE_TEXT_ACCEPTANCE_20261114.md，整体目标保持active。
