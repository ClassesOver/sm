# XLSX 编辑栏显隐

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`：App.tsx:688 默认显示，:4733 `toggle-formula-bar` 切换会话状态并给容器添加/移除 `formula-bar-hidden`；styles.css:6041 对该容器下原生 `[data-u-comp='formula-bar']` 设置 display:none，由原生 flex workbench 重排。ExcelShell.tsx:3313 的 View 显示复选项回显此状态。它不是工作表/文件状态，不存本地偏好，不入撤销或标脏，不重建编辑器。

本地此前 header=true/formulaBar=true 已挂载原生栏，但 ribbon disabledReasons 声明固定预设不可切，main 没有路由。

独立模块 `frontend/src/workbook-formula-bar-view.ts` 提供 `createFormulaBarView(host)`，返回 visible/toggle/dispose。CSS 在模块内导入，host class 名改为本地专属 `workbook-formula-bar-hidden`，保留源原生selector。只切class，保留公式栏与网格原生节点/编辑器实例；会话默认显示，释放幂等清自己class，不碰旁边host或其他class。

3项定向测试从缺模块RED到GREEN（`/tmp/workbook-formula-bar-view-red.log`、`/tmp/workbook-formula-bar-view-green.log`）：默认状态与toggle、host隔离、原公式输入DOM未变、迟挂native栏、释放保留节点且停止后续toggle。未改main/ribbon/vite/static，未build/完整测试。

root后续集成：main创建控制器，View命令toggle后只更新反馈/ribbon pressed，无markDirty；只读/保护允许视图切换但加载/保存期间阻止；host卸载释放。ribbon需移除旧disabledReason、回显aria-pressed。集成之后仍须真实GUI确认编辑栏display与网格高度reflow、隐藏后原生键盘输入/显示后内容保留以及草稿无纯视图编辑；本模块测试没有渲染布局能力，不能当这些已通过。

最终root接手验收：子agent provider余额错误中止后，root查明输入RangeError来自新标题hydration浅覆盖默认尺寸，已真实Worksheet RED→GREEN修正。最终built /tmp/workbook-formula-bar-budget-final-built.log exit0，303 JS200/磁盘SHA，无runtime注入；隐藏时输入→公式85，显示/隐藏双向reflow，草稿恢复、真实Python保存/openpyxl、rev2重开，pageErrors=[]。最终budget main247.7KiB/engine425.9KiB，契约通过。会话显隐不进入文件和undo，保存仅一个真实金额编辑。mock身份/修订HTTP不代表生产HTTP验收。
