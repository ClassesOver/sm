# 公式追踪新 built smoke（待统一产物）

执行：`node smoke/workbook-formula-trace-built-smoke.mjs`，可用 `FORMULA_TRACE_SMOKE_PORT` 覆盖默认4261。脚本只启动已有产物的 Vite preview，不构建。准备状态不算实际通过，等待 root 明确新统一 dist 后执行。

本地真实 HTTP 文件/context 夹具，五张保护表（普通、冻结、自定义150%、RTL、隐藏轴）和单独可编辑表。前置/从属箭头与边框的实际 DOM/SVG 几何、箭头方向、移除、切表不残留与编辑后清理；截图包含选区、viewport及完整界面。跨表只计数，INDIRECT和结构化列名A1不得画伪箭头。只读阶段草稿存储/历史可用状态/保存状态保持，下载及来源 SHA 相同且save0；独立main测试已证明运行时snapshot/真实历史对象不变，built不通过调试后门读取snapshot。编辑阶段仅插行触发清理并Undo，不把真实编辑误记为零修改。

每个实际加载 JS 与磁盘产物 HTTP200/SHA 比对、pageErrors为空；最终保存source、cases JSON和截图到打印出的临时目录。18个source向量已在单测证明，built不重复该低层验证。授权/修订为夹具，不证明生产HTTP、桌面Excel或完整公式依赖图等价。

新增复合场景：RTL150Frozen（冻结C3、150%）、RTLHiddenEnd（引用范围终列隐藏）、RTLMerge（合并锚点明确拒绘）。先从真实canvas选择框像素读取D6中心，再核对可见箭头tip；Frozen/RTL150Frozen滚回使offscreen端点重新可见，要求两条箭头恢复并对齐当前选择中心。SVG连接官方单格float的实际DOM位置，不以非零宽代替正确对齐。第一次RTL负宽失败及第二次Frozen端点失败保留在调查文档，修复重建后的运行才可记最终通过。

可用 `FORMULA_TRACE_FROM=RTL150Frozen` 从指定几何case继续；`FORMULA_TRACE_FROM=tail`只跑尾链。续跑必须保留此前同dist通过日志/截图并在验收报告合并列出，不能把tail输出的空cases当作所有几何case运行。最终证据见 `../../NATIVE_XLSX_FORMULA_TRACE_ACCEPTANCE.md`。
