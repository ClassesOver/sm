# PDF Multiple Text Inserts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 连续多段文字插入共用草稿、预览和保存。
**Architecture:** 复用单段 writer，在原来源预校验后按不变页序重绑中间身份；汇总原索引回执。前端保留原草稿并追加。
**Tech Stack:** TypeScript, pdf-lib, PDFium, Vitest, node:test.
**Spec:** smart_reporting/report_editor/NATIVE_PDF_MULTIPLE_TEXT_INSERTS_DESIGN_20261114.md

## Global Constraints
保持既有来源安全与其他操作隔离；不变更发布/签发；只跑受影响定向测试，不重复完整套件；不提交或部署。

## Review Focus
后续段落伪造来源/越界在写入前拒绝；跨页页序稳定；后段写入失败保留前段；回执索引及摘要完整；刷新后的追加不覆盖旧草稿。

### Task 1: 引擎多段插入
- [x] 在 bridge/static-text.test.ts 添加两段/跨页、后段非法来源、回执/摘要测试，运行观察 RED。
- [x] 在 bridge/static-text.ts 新增 insertStaticTexts，operations.ts 将 insertText 纯批次交给该入口；执行前逐项校验来源、页和 origin；复用 insertStaticText 并合并回执。
- [x] 运行 node --import tsx --test bridge/static-text.test.ts。

### Task 2: 前端追加与验证
- [x] pdf-static-text.test.ts 添加多段、第二段非法/混合拒绝；添加 dialog 连续放置草稿保持及撤销测试，运行观察 RED。
- [x] pdf-static-text.ts 按全部操作验证并追加；pdf-main.ts 门控允许纯 insertText 草稿继续插入，更新提示。
- [x] 运行 npx vitest run src/pdf-static-text.test.ts src/pdf-static-text-thumbnail.test.ts，并运行类型检查。

### Task 3: 回顾及记录
- [x] 检查差异、来源验证及失败回执；记录本批验证和剩余限制，不称整体对齐完成。

## Progress
已在隔离执行环境的 work 分支上原位实施，初始工作树干净；不创建额外副本或提交。用户“继续”沿用对齐授权，由当前 agent 实施。

## 实施与验证记录
- 第一轮前端和引擎均复现只允许单段的失败；dialog 测试复现第二段覆盖第一段。
- 引擎目标测试的第二页 CropBox 包含 [0,0]，原越界断言不成立；改为真实越界 [-1,0]，未改写产品边界。
- 依赖安装产生的 package-lock 排序/元数据变化已还原，无依赖清单变更。
- 初始服务验证遇源码 CLI 的兄弟包 @genoffice/agent-core 解析缺失；隔离 bundle 首次还缺 saxes，补入已有前端 node_modules 搜索路径后构建通过。没有添加 shim 或修改 shared dist/static。
- 独立审查指出后段加载异常丢失前段产物；新增故障注入先 RED，再加逐段异常保留，最终引擎 15/15 通过。
- 前端四个受影响文件测试 54/54 通过；包含逐次 Undo/Redo、持久草稿重建、迟到放置、500 项边界与缩略图。
- 全局类型检查退出 2，632 条诊断来自工作簿依赖缺失及类型等问题；无 pdf-main/pdf-static-text 诊断，不声明整个项目类型检查通过。
- 最终范围和证据见 NATIVE_PDF_MULTIPLE_TEXT_INSERTS_ACCEPTANCE_20261114.md。
