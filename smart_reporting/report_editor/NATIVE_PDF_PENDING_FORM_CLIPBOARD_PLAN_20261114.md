# PDF Pending Form Clipboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为待保存的新字段提供复制、重复、粘贴和对应快捷键，支持同文档跨页粘贴、唯一名称、相对布局与NativeDraft历史。
**Architecture:** 仅编辑器内存剪贴板绑定sourceSHA，不写系统剪贴板/持久存储。深拷贝已有createFormField规范输入，粘贴时复用批创建stager自动生成同父唯一叶名并整体平移/夹到目标CropBox。画布的菜单/键盘回调校验活动状态及当次快照；多页画布共用一个剪贴板实例。
**Tech Stack:** TypeScript, NativeDraft, FormDesignLayer, Vitest, Playwright.
**Spec:** 下述Design。

## Design
本批先支持待保存字段，源文件既有字段复制仍待后续可信来源/默认值/字体语义适配。复制整个新radio组仅限其Widget均在复制页面；跨页组不降级为部分字段。支持text/checkbox/date/choice/radio/signature的规范创建属性，保留值/必填等。复制不改变草稿；Duplicate不覆盖已有剪贴板；粘贴可把同页字段集放到另一来源页，保留相对布局并整体夹到可见CropBox，放不下时零改动。名称不与原来源/草稿/父子前缀冲突，叶名限64、总长256。预算500。来源改变或来源能力/编辑权限未知拒绝。输入框/contenteditable/模态窗口/菜单和IME保留原快捷键。

## Global Constraints
不新增后端操作/路由/依赖，不改发布签发；保留既有修改，不提交部署，不重复完整测试。

## Review Focus
深拷贝不共享可变数据；名称超长/父前缀；群组布局及跨页radio拒绝；旧菜单/失效权限/文档来源；快捷键不劫持输入；复制与重复对剪贴板内容独立。

### Task 1: 剪贴板核心
- [x] pdf-form-clipboard.test.ts先RED：复制无草稿变化、深拷贝、重复/跨页粘贴、命名/预算/边界/来源。
- [x] 新pdf-form-clipboard.ts，类PdfFormClipboard绑定sourceSHA并提供copy/paste/duplicate/hasContent，复用stager。
- [x] 定向GREEN。

### Task 2: 画布动作
- [x] context菜单/快捷键/失效回调RED。
- [x] main持有共享实例；canvas增加复制/重复/粘贴菜单及Ctrl/Cmd+C/D/V（非输入态），提交一次批次并选中新字段。
- [x] 定向canvas/host测试；真实Chromium菜单/快捷键/实际PDF预览和独立回读。

### Task 3: 审查记录
- [x] 独立审查并修重要问题，记录限制；不把本批记为所有源字段剪贴板对齐。

## Results
- 核心模块缺失、canvas菜单/快捷键、contenteditable空值/plaintext-only以及pending菜单删除均有RED后GREEN。
- 最终5文件108通过（含双canvas共享clipboard只提交一次、清空选择后active页仍可粘贴、同父长名称预算）；独立审查无重要发现，双canvas测试按审查建议补齐。
- 首轮真实Chromium通过复制/重复/粘贴、输入快捷键隔离、6字段实际预览及pypdf；最后active页无选区补丁后，使用前轮真实源PDF及6条真实草稿恢复最小续验，CtrlV生成第7字段并实际预览/pypdf通过，未重复原完整创建链。
- 服务只运行新增copy参数：1通过1未运行，复用现有保存/下载验证值与必填保留。
- 最终全局类型检查仍退出2，日志与批创建基线逐字节相同，无本批PDF诊断。
- 本批仅pending字段剪贴板；既有PDF字段复制/跨页radio组/跨文档及系统剪贴板仍开放。
