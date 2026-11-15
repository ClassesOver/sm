# PDF 缺口补齐 PR 集成记录（2026-11-14）

本轮连续增量合并为一个 PR：多段文字与草稿管理、原位改字和新增文字组合、安全整文字对象移动；表单批创建、待保存/安全来源字段剪贴板（文本、复选框、选项、日期、空签名、含跨页来源的完整单选组）；安全页面直属图片删除和文字层级切换。详细历史证据按各专项验收记录保留，当前范围见 [活动缺口](NATIVE_PDF_ACTIVE_GAPS_20261114.md)。

## 基线与合并

- 初始工作树基于 `1e4a0a344ffbd5b73f71c0a84bb67f766f19e8e9`；创建 PR 前获取默认分支 code，基线更新到 `f71802558409a8321484749240cdb148c4535f9c`，纳入其后29个上游提交。
- 原开发树改动保存为中文提交后 rebase 到最新基线；四处冲突逐项合并：对齐状态、前端 PdfModel、引擎 inspectPdf 和引擎测试登记。同时保留签名字段模型/检查/测试与本轮文字移动能力，未覆盖上游签名字段验收。
- `pdf-main.ts` 自动合并后保留共享助手生命周期、签名字段交互以及本批文字/表单/图片入口和独占门控。独立只读静态复核对照基线、原提交及 range-diff，未发现 Important 集成问题；复核者未另跑测试。

## 最新组合验证

仅运行与集成有关的定向检查，没有重复完整套件。

- 引擎8文件47项通过：signature-fields、operations、source-text-move、text-insert-mixed、form-multipage-radio-copy、form-empty-signature-copy、existing-image-layer、existing-image-delete。日志 `/tmp/pdf-pr-integration-engine.log`。
- 前端7文件154项通过：pdf-signature-field、pdf-static-text-host、pdf-object-host、pdf-text-move-controls、pdf-form-design-canvas、pdf-form-clipboard、pdf-operations。日志 `/tmp/pdf-pr-integration-front.log`。
- 最新组合隔离CLI构建成功，路径 `/tmp/pdf-pr-integration-runtime/dist/cli.mjs`，SHA-256 `737d1ba3f3319d641ca268f16bb34111cc15d15856dbc7957042d94bc190985f`，未替换共享构建。
- 服务保存/下载：使用上述实际CLI，只运行来源跨页单选组参数，1通过、1未选中；真实预览确认、新修订、实际字节下载及复核失败保留下载均覆盖。日志 `/tmp/pdf-pr-integration-service.log`。
- 实际Chromium跨页单选组：非首成员页复制/重复、当前页移动、跨页粘贴、整组删除与历史恢复、实际预览通过；pypdf回读原组和两个副本共9按钮，页面数量[2,5,2]，V/DV/AS保留，无页面或HTTP错误。证据 `/tmp/pdf-pr-integration-radio-browser/evidence.json`。
- 实际Chromium文字组合：原位改字与插入草稿管理、编辑、删除及历史恢复通过；实际CLI写回后独立提取文本为 Changed original 和 Updated second，未保留被删除/替换的插入内容；无页面或HTTP错误。证据 `/tmp/pdf-pr-integration-text-browser/evidence.json`。浏览器为源码宿主和隔离CLI验证；服务保存下载另测，不称生产HTTP整链验收。
- `tsc --noEmit` 退出2，共633项诊断。与原开发树632项按位置归一比较，仅多上游 workbook_engine/bridge/split-pane.ts 缺失 zod 模块诊断，该文件与 origin/code 逐字节一致。未出现本批PDF文件诊断；全局类型检查及正式前端构建不能称通过。日志 `/tmp/pdf-pr-integration-types.log`。
- React act、Vite兄弟依赖扫描及 imghdr 弃用等环境警告保留。历史批次结果不是这次组合的重复执行，不叠加计算通过数量。

## PR 范围限制

这次是已实现增量的代码审阅入口，不是 PDF 全量对齐或生产上线验收。复杂来源、任意操作混合、完整AI工具覆盖、系统/跨文档剪贴板及证书相关能力仍有缺口；OCR按用户要求排除。仅推送功能分支并创建PR，不合并或部署。
