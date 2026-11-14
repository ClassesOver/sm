# PDF Pending Text Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 管理纯 insertText 草稿：列出、修改内容/字体/样式及同页基线位置、删除。
**Architecture:** 保持 insertText schema；以完整草稿快照及索引防止过期窗口误改。复用配置窗口和验证，不新增 writer 或保存/签发流程。
**Tech Stack:** TypeScript, NativeDraft, Vitest/jsdom, Playwright.
**Spec:** 下述 Design。

## Design
采用管理列表 + 复用配置窗口，X/Y 是 PDF 同页基线坐标。复用窗口保持字体/颜色/多行验证一致；尚未写入的操作直接修改草稿，避免新增后端操作。源 list/edit/move/delete inserted text 是能力参照；本批不声称完成 AI 工具或与源 UI 逐像素等价。
确认仅一次 setOperations，Undo/Redo 可回退；刷新恢复沿用 NativeDraft。取消不修改；删除最后一段恢复干净草稿。只管理未保存新增文字；只读/保存/预览/来源变化不能提交；500 条满预算仍可管理。

## Global Constraints
不新增依赖，不改后端和签发；保留上一批修改，不提交/部署，不重复完整测试。

## Review Focus
重复条目定位；旧回调/权限变化；非法内容/越界；满预算管理；刷新失败保留已采纳的修改。

### Task 1: 修改文字
- [x] pdf-static-text-dialog.test.ts 添加编辑内容/样式/坐标、重复条目、取消/过期/非法坐标的 RED。
- [x] pdf-static-text.ts 增加 edit(index)，复用现有字段，编辑时显示基线 X/Y，验证全部候选后单次替换。
- [x] 定向 Vitest 通过。

### Task 2: 管理列表和入口
- [x] 新建 pdf-pending-text.test.ts，列表/精确删除/失效/权限/满预算 RED。
- [x] pdf-pending-text.ts 提供 open/refresh/dispose，接入 pdf-main.ts 的按钮、更新及销毁；容量满仍允许管理。
- [x] 定向 Vitest、Chromium 实际模块交互/窄屏截图。

### Task 3: 记录
- [x] 独立审查并处理重要问题，记录证据与剩余范围。

## Ledger
沿用隔离环境 work 分支及连续推进授权；上一批修改均保留。文档存于既有 PDF 记录目录（根 docs 被忽略）。

## Results
- 初始 edit(index) 缺失 RED；管理模块缺失 RED；源码宿主夹具补齐已有 PropertiesDialog 所需 sourceFile.path 后，新入口测试正确复现 disabled=true 的 RED。
- 修复两处通用独占门控：纯 insertText 草稿仅豁免插入/管理入口，其他变更仍拒绝。上一批底层通过不能当作连续插入公共入口通过，本批已补齐宿主和真实 Chromium 证据。
- 独立审查发现旧列表回调复用新快照导致索引偏移，故障 RED 后补逐 render 代次校验。
- 最终六个受影响测试文件 75/75；真实 Chromium 公共入口、PDF.js、草稿恢复、窄屏截图与实际 CLI 输出/pypdf 回读通过。
- 全局类型检查退出2，日志与上一批逐字节相同（632条错误，主要工作簿依赖和类型），无本批 PDF 诊断；不伪称全局通过。
- 证据及剩余边界见 NATIVE_PDF_PENDING_TEXT_ACCEPTANCE_20261114.md。
