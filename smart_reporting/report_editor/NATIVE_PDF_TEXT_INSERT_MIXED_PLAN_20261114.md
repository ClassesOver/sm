# PDF Replace and Insert Text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 原位改字与静态新增文字在同一草稿预览保存，保留实际输出和原索引。
**Architecture:** 原来源先校验全部新增落点/来源及静态来源能力；复用 replaceStyledText 后按不变页序由引擎重绑 insertText 到中间产物，索引/摘要始终绑定原输入。
**Tech Stack:** TypeScript, PDFium, pdf-lib, NativeDraft, Vitest, Playwright, pypdf.
**Spec:** 下述 Design。

## Design
沿用授权PDF对齐目标，仅开放 insertText+replaceText。来源沿用静态插入的无批注/表单/保护和默认单位限制；新增坐标不随改字自动重排。复用writer保留字体/对齐/独立回读合同，代价是重复加载。全部新增校验在首次写入前；后置故障保留已生成字节并诚实返回原索引告警。浏览器不能自造中间身份。

## Global Constraints
保留前批修改，不新增依赖、路由或签发步骤；不提交部署，只跑受影响专项。

## Review Focus
交错索引；全部输入预校验；改字跳过保留新增；新增失败保留改字；公共门控和文字控件真正可用。

### Task 1: 引擎
- [x] text-insert-mixed.test.ts 覆盖多页/交错/摘要/预校验/跳过/故障保留 RED。
- [x] static-text.ts 导出原来源预校验；text-insert-mixed.ts 组合writer；operations.ts 在样式分支前路由纯文本混合批。
- [x] 运行 text-insert-mixed/static-text 定向引擎测试。

### Task 2: 前端
- [x] pdf-text-insert-mixed.test.ts 与宿主测试 RED。
- [x] 验证器验证混合内每类操作；原位改字/插入/管理及文字控件只开放文本批次；归一原来源哈希。
- [x] 定向Vitest、真实Chromium公共入口和CLI/pypdf验证。

### Task 3: 记录
- [x] 独立审查，处理重要发现，更新验收和剩余缺口。

## Ledger
沿用work分支和原授权，保留前两批变更。整体穷尽目标保持active。

## Results
- 初始引擎混合成功/跳过测试因旧样式独占规则失败，前端/公共按钮也有RED，随后实现GREEN。
- 引擎 text-insert-mixed + static-text 共21通过；新增用例含原来源/落点预校验零写入、原索引/摘要、改字跳过保留插入、插入中间加载故障保留改字、plain replacement缺失可选sourceSHA由引擎可信归一。
- 宿主夹具补实际文字对象后覆盖双顺序；独立审查发现Edit页签第二入口遗漏，RED后纳入相同豁免。
- 10个前端相关文件71通过。更广专项发现旧drawing测试把本来已支持的安全link列为拒绝；从HEAD提取原验证器运行1个独立测试证实基线允许，删除临时文件后改成javascript非法目标，未改产品link安全策略。
- 类型检查曾有新增fixture的Object.fromEntries类型推断错误；改为解构保留kind后最终全局tsc日志与上一批逐字节相同，仍退出2、不声称全局通过。
- 实际Chromium双顺序、混合下管理/删除/新增、窄屏及CLI/pypdf通过；服务实际preview/confirm/save/download测试3参数通过。
- 详见 NATIVE_PDF_TEXT_INSERT_MIXED_ACCEPTANCE_20261114.md。
