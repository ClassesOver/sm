# Native XLSX 公式追踪验收

2026-11-10，固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
三入口：追踪引用单元格、追踪从属单元格、移除箭头。保护/只读表可查看，
仅会话浮层，不写公式、草稿、撤销历史或源文件。来源及SHA见
`frontend/src/workbook-vendor/SOURCE.md`，调查和历史失败见
`NATIVE_XLSX_FORMULA_TRACE_INVESTIGATION.md`。

## 最终统一产物与验证

root统一构建 `/tmp/office-row-breaks-trace-pane-build.log` 完整tsc+Vite通过
（40.55s）；budget/contract通过，main248.9KiB，未提高cap。
以下均运行此冻结dist。首次脚本假定goto后来源仍可见、以及150%像素探针只接收
实色边缘，造成测试定位失败；后续仅修脚本、从失败case继续，不重建/修改产品。
最终各case证据合并判定，不把单次tail的空cases数组冒充七场景完整执行。

| 场景 | 实际结果 | 日志 / 截图目录 |
|---|---|---|
| Plain / Frozen / Zoom150 | 前置/从属/清除与canvas端点对齐；Frozen先1条可见，滚回后2条恢复并按新位置对齐 | `/tmp/formula-trace-built-pane-positioned.log` / `/tmp/formula-trace-built-R89tEu` |
| RTL | 2前置、1从属、清除；箭头向左且对齐真实canvas目标 | `/tmp/formula-trace-built-pane-rtl-continue.log` / `/tmp/formula-trace-built-ymjiEd` |
| RTL150Frozen / RTLHiddenEnd / Hidden | 每表2前置、1从属、清除；RTL150Frozen实际滚动后仍对齐；隐藏引用范围终列不产生伪宽 | `/tmp/formula-trace-built-pane-composite-scroll.log` / `/tmp/formula-trace-built-D3X05o` |
| tail最终退出0 | 合并拒绘、跨表只计数、INDIRECT/结构化A1不画伪箭头、切表释放、插行后释放与Undo；118 JS HTTP200/SHA、pageErrors0、save0 | `/tmp/formula-trace-built-pane-tail.log` / `/tmp/formula-trace-built-UBeJkC` |

最后source与只读前后下载SHA均为
`10cee14b9c17885fd18624f770a7893376d1018805a058ac9cb853894b48f08f`。
真实下载保存在最后目录的downloaded-before/after-reading.xlsx；最后运行仅
通过FROM=tail验收尾链，几何截图引用上表已通过的同dist分段证据。

窄测试：源18向量；main/Ribbon只读snapshot/draft/history/status不变；安装
失败/生命周期；官方RTL负宽RED；pane真实DOM端点与布局变化RED→GREEN；
ref重绑释放RED→GREEN。最终pane10项通过
`/tmp/trace-pane-final-tests.log`，其后仅ref1项新增窄回归
`/tmp/trace-ref-green.log`通过；`/tmp/trace-types-ref-final.log`通过。

## 明确边界

直接公式文本引用，不是完整计算依赖图。名称、结构化和动态引用不展开，
明确反馈不完整；跨表只计数。扫描20000已存单元格、单次/累计200个规划浮层，
跨度20000行/2000列，超出明确拒绝。零可见面积、合并锚点/端点明确拒绘。

每箭头使用两个官方单格float，读取当前pane中实际可见裁剪部分中心；host只
连线，不复制viewport计算。完全offscreen端点不画，页面明确提示滚动至可见
区域后显示。当前float祖先style/class变化触发合并单次rAF，无常驻轮询；
ref重绑、切表、mutation、替换、销毁均释放监听和SVG。高亮按freeze最多4段。
本验收使用本地真实HTTP文件/context夹具，不证明生产鉴权、桌面Excel或完整
公式引擎等价；不新增Plotly或持久化浮层。

统一证据manifest：`/tmp/formula-trace-acceptance-manifest.json`，列出七case
所有截图路径/大小/SHA和对应实际断言日志，另有原tail三份source/download
身份及build/budget日志SHA。当时DOM几何数值未落盘，manifest明确说明，只保留
当时真实7px对齐断言和截图，不补造历史数值。

补充资产清单运行：`/tmp/formula-trace-built-pane-tail-assets.log`退出0，
`/tmp/formula-trace-built-Bh4duC/assets.json`记录118条实际HTTP响应path/status/SHA，
仍pageErrors0/save0。它是额外tail身份，生成ZIP时间戳不同，source/download
一致SHA为`9f88ffc0a040753b5f81d1fd51ef6d3dbca850b3a214a1db68bb56c02ca0bc3f`；
manifest将其与原UBeJkC验收身份分开，七几何case没有重跑。
