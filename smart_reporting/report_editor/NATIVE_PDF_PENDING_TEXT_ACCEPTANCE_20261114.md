# PDF 待保存插入文字管理增量验收（2026-11-14）

新增“管理插入文字”入口：逐条查看待保存 insertText，复用文字窗口修改内容、字体、字号、颜色、粗斜体、行距、对齐及同页基线 X/Y，或精确删除所选条目。每次确认仅改变原 NativeDraft，支持逐次 Undo/Redo 及持久草稿恢复；删除最后一条恢复干净状态。500 项满预算仍可编辑/删除。未增加后端操作、依赖或签发流程。

## 重要修正与证据

上一批多段插入只验证了底层和独立配置控件，遗漏 pdf-main 公共按钮的两层独占门控，导致用户界面第二次插入被锁。本批新增宿主 RED 并同时修复 click guard 与 disabled 控制，纯 insertText 草稿仅豁免文字插入/管理，其他变更仍隔离。原验收记录保留，不能追溯说上一批已完成公共入口验收。

管理列表初版在重绘后让旧按钮引用新快照，可能用旧索引删除错误条目。独立审查复现；新增 detached-row RED 后加每次 render 的独立代次校验，过期、关闭、权限变化、草稿变化均不授权。修改/删除后刷新失败保留真实已采纳草稿并明确提示。

- 最终前端定向：pdf-static-text-host、pdf-pending-text、pdf-static-text-dialog、pdf-static-text、pdf-static-text-thumbnail、pdf-operations，共75通过、0失败。日志 /tmp/pdf-pending-text-final.log。PDF.js与API在宿主单测中有替身，不当作真实PDF验证。
- 真实 Chromium：smoke/pdf-pending-text-smoke.mjs，最终运行 /tmp/pdf-pending-text-browser-reviewed，日志 /tmp/pdf-pending-text-browser-reviewed.log。直接加载实际源码 pdf-main、真实 PDF.js canvas、实际 PDFium 检查模型；公共入口连续插两段、改第二段及基线、删第一段、Undo/Redo、页面重载恢复均通过。
- 390×700 真实截图 manager-narrow.png、edit-narrow.png 均已目视；编辑窗口 clientWidth=scrollWidth=356，left=16，无横向溢出；高度666/scrollHeight926，纵向滚动可到取消和应用。
- 最终浏览器草稿交给上一批隔离 CLI 实际写 PDF，applied=[0]、skipped=[]。独立pypdf保留原标题、只提取Updated second，不包含已删First inserted或被替换Second inserted；另起进程回读实际文字矩阵基线[160,220]、字号14和一页结构。证据 evidence.json、edited.pdf、independent-baseline.json。源PDF SHA保持不变。
- 浏览器 pageerror/HTTP≥400 均空。Vite依赖扫描仍提示其它格式 fast-xml-parser/saxes/utif2 不能从兄弟工程解析；本批PDF实际加载成功，不隐藏这些构建环境提示。
- tsc --noEmit退出2：/tmp/pdf-pending-text-types-final.log 与上一批 types 日志逐字节相同，632条既有诊断，无本批PDF文件诊断；不声明全局类型或生产构建通过。git diff --check 与 smoke脚本语法检查通过。

## 验收边界

浏览器通过Vite源码入口执行，API是烟测宿主适配器，文件/检查模型由实际来源与CLI提供；本批没有HTTP授权保存/下载或生产静态包验收。最终PDF由浏览器草稿直接传CLI生成，不能将其称作完整生产保存链。上一批服务保存/下载独立证据不重复计数。

仅管理未保存插入文字，位置仅限同页；没有跨页移动、画布直接拖拽/选择、富文本选区样式、段落reflow或AI list/edit/move/delete工具。原生来源限制和与其它操作混用限制保留。此管理窗口是宿主适配，不宣称源窗口逐像素等价。未提交/部署/开启生产开关。
