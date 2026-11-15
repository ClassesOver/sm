# XLSX 分页预览专项验收

2026-11-10。已完成下述专项验证，全量 Word/XLSX 对齐仍开放。固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的范围浮层呈现与宿主 `planSheetPrint` 共用打印页段；不另造近似分页算法。来源与接线详情见 `NATIVE_XLSX_PAGE_BREAK_PREVIEW_INVESTIGATION.md`。

预览与 File Print 通过实际保存操作重放后模型读取同一份有效页面设置，实时快照提供尺寸与隐藏轴；独立字段 capture 处理结构编辑和 Undo/Redo。共享引擎补齐手动分页符随行列结构变化的坐标转换。浮层支持实际 Worksheet 身份、异步代际取消、普通视图清理、受保护表阅读；不新增文件或历史操作，资源上限如实反馈。

## 证据

- 主入口 2、planner/overlay 9、controller 3、Ribbon 43、共享结构与元数据 3、journal 5 项定向验证通过；类型检查通过。没有重复完整测试。
- 最终统一前端 `/tmp/office-doc-engine-page-break-build.log` exit0（41.52s），budget 与 contract exit0。原主 chunk 超预算后仅拆分页预览相关模块，XLSX main 236.8 KiB，未提高 250 KiB 上限。
- 只读 `/tmp/page-break-built-readonly3.log` exit0、ok=true：Plain/Frozen/Zoom150/RTL 四张真实受保护表，实际浮层几何、关闭清理、按 Worksheet 切换模式、草稿/历史/保存状态和下载 SHA 不变；118 个资源 HTTP200/SHA、save0、pageErrors0。产物 `/tmp/page-break-preview-built-mttiys`。
- 可编辑 `/tmp/page-break-built-editable-final.log` exit0、ok=true：七阶段预览水印与实际打印 iframe 页数依次 4/4/9/9/9/9/6；覆盖跨 epoch 设置、插删行列、Undo/Redo、实时尺寸、新隐藏轴。重复标题逐页存在，42pt 行高按 90% 为 37.8pt。实际 Python `patch_office` 保存一次、真实 HTTP 下载 SHA 与 ZIP 验证通过：area A1:H40、titles 1:1、rowBreaks [10,14]、colBreaks [4,5]、行高42、可见列宽20、新隐藏行6/7和列F/G。118 个资源 HTTP200/SHA、pageErrors0。
- 产物 `/tmp/page-break-editable-built-pox3x9` 包含七份打印 HTML、保存请求、下载 XLSX 和 ZIP 检查。root 目视 `editable-final-preview.png` 确认页码及蓝色分页边界可见。

## 尚存独立保存缺口与限制

验收发现原隐藏 C 经插列后变为 D，实时预览/打印保持隐藏，但现有 geometry 保存链输出宽度补丁时可能丢失源隐藏标记。证据 `/tmp/page-break-editable-built-AoAKGt/save-payload.json` 与 `zip-inspection.json`；该缺口已独立安排修复，不能把本项证据用于声称隐藏属性无损保存。

顶层 `editingEnabled:false` 的既有全局门禁不挂载编辑器；只读浏览器证据使用 `editingEnabled:true` 加真实 sheetProtection。授权及修订路由为本地替身，不证明生产 HTTP、桌面 Excel 或打印机输出完全等价。


## 后续：独立隐藏列保存缺口已解决

上文“尚存独立保存缺口”保留首次验收的历史事实；该缺口已按固定源列定义
迁移语义和保留非宽度属性的 writer 独立修复。最终统一产物
`/tmp/office-margins-hidden-final-build.log` exit0（40.01s），budget/contract
exit0且未抬cap；最新 bridge 包含单引号/空白属性修复。

新增断言的可编辑 built `/tmp/page-break-hidden-final-built.log` exit0、ok=true，
产物 `/tmp/page-break-editable-built-YUH8oD`：真实保存/下载 ZIP 保留源隐藏列D
及新隐藏列F/G，保存请求不含原 index3 伪列宽补丁；七阶段预览/实际打印页数
仍为4/4/9/9/9/9/6，页面设置、尺寸及隐藏行断言通过，118资源HTTP200/SHA、
save1、pageErrors=[]。下载 SHA 为
`f31488ec18509726e18a48ac970f65ceee0fbe4cb8c01ab1ef77c1ec350a2c8f`。
详见 `NATIVE_XLSX_HIDDEN_COLUMN_PERSISTENCE_ACCEPTANCE.md`；上述其他宿主
及授权限制继续适用，不据此关闭全量 XLSX 对齐目标。
