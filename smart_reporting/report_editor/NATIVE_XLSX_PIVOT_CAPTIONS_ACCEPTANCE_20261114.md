# XLSX 透视值字段自定义标题专项验收

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；本地基础 `1e4a0a34` 加工作区改动。对应账本 P05，日期 2026-11-14。

## 交付

启用源字段设置中的自定义标题输入，补齐 pane/config、纯布局/definition、状态 schema、rebuild、OOXML `dataField@name`、本地状态/外部透视表 reader 的 `name` 传递。刷新和修改聚合均保留显式标题；空白输入恢复默认标题。标题 trim 及重复标题数字后缀遵循固定源；不宣称任意既有数字后缀／混合名称碰撞均能去重。此批不包含 P04 额外 ShowAs/baseField/baseItem。

## 验证

- 三项真实失败先行：布局与状态丢标题、pane config 丢标题、UI 输入被禁用；修复后通过。测试覆盖自定义/默认/重复、特殊 XML 字符、保存重开、移除本地状态后的外部导入、刷新及清空恢复。
- 定向引擎 **35 通过**，前端 **75 通过**；两端实际导入闭包严格 TypeScript 检查通过。包括既有六种额外聚合、布局/刷新/字段重命名/控件路径；没有重复完整套件或全应用构建。
- 同模型独立审查无重要发现。
- 真实 Chromium `154.0.8037.57` 操作实际源 pane/宿主对话框，输入 `  收入 & "净额" <本年>  `，保存并实际 Blob 下载；重开字段设置后输入为已 trim 标题，再填空白恢复默认并第二次下载。输出值保持 6，无 pageerror。
- 对两份下载文件使用独立 openpyxl、ZIP/XML 回读，表头、dataField 名称、持久状态及数值均吻合。自定义为 `收入 & "净额" <本年>`，清空后为 `Sum of Amount`。

## 证据和边界

`/tmp/xlsx-pivot-captions-20261114/` 保留浏览器构建源码/metafile、脚本、两份实际下载 XLSX、截图、browser.json、独立回读脚本/结果和当前 source-binding.json。测试日志：`/tmp/xlsx-pivot-captions-{red,green,engine-final,frontend-final,ts,engine-ts}-20261114.log`。

浏览器是实际组件与引擎的隔离宿主 harness，没有全应用服务、数据库修订、真实 provider 或桌面 Excel 验证。源后缀算法边界保留；更多 ShowAs、通用缓存、数组公式和其余全域缺口仍开放。当前代码哈希已更新；前一聚合专项 artifacts 及 source-binding 作为当时的历史证据保留，并非当前文件哈希。

未提交、推送、合并或部署。整体 XLSX 对齐仍 active。
