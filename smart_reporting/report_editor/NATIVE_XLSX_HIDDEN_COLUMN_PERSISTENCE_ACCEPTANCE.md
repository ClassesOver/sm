# XLSX 结构编辑后隐藏列保留

2026-11-10。分页预览实际保存验收发现：原隐藏 C 插列后在实时网格中变为隐藏 D，下载文件却丢失 hidden。失败产物 `/tmp/page-break-editable-built-AoAKGt` 保留保存请求和 ZIP 检查。

根因是完整列结构操作没有迁移 `<col min/max>` 属性，导致保存 baseline 与实时列身份不一致；随后宽度 writer 重建目标列，只写 width/customWidth，丢弃 hidden、style、outlineLevel、collapsed 等属性。

修复按固定来源 `transformColDefinitions` 迁移完整列定义范围；插入扩展范围，删除裁剪或移除范围，保留属性。列宽写入只替换 width/customWidth/bestFit，保留可见性、样式和分组，显式取消隐藏继续由 outline 操作控制。单引号、双引号及等号空白均被正确读取和更新；无效或重叠列定义拒绝，避免生成重复属性。

## 已核验

- 新真实 ZIP/Univer 及原 axis 范围共9项定向验证通过，包含 Undo/Redo、源隐藏身份、宽度调整和主动取消隐藏。`/tmp/geometry-hidden-final-green.log`。
- 引擎 geometry 7、sheet-ops/cell-shift 25 项回归通过。`/tmp/geometry-writer-regression.log`、`/tmp/geometry-structural-regression.log`。
- 与固定来源真实函数对照37组向量通过（32组结构范围及5组列宽）。`/tmp/geometry-hidden-source-parity.log`。
- 独立复核发现原属性 parser 仅支持双引号；补真实 parsererror RED 后，单引号/空白/范围4项与几何回归7项通过。`/tmp/geometry-hidden-quotes-red.log`、`/tmp/geometry-hidden-quotes-final.log`、`/tmp/geometry-writer-quotes-regression.log`。
- 本地来源及哈希清单已同步，原 SOURCE-SHA 未改。最终 workbook bridge `/tmp/xlsx-hidden-quotes-bridge-build.log` exit0。

新增浏览器保存断言要求原 D 隐藏属性保留且不产生 index3 的伪列宽补丁；此前待构建状态由下述最终产物验收补齐，原失败证据保留。

最终统一前端 `/tmp/office-margins-hidden-final-build.log` exit0（40.01s），budget与contract exit0；XLSXmain236.8KiB未抬cap，最新桥接已包含quote修复。新增源隐藏D断言已在该最终产物完成真实保存/下载验证。

## 最终 built 保存闭环

`/tmp/page-break-hidden-final-built.log` exit0、ok=true；产物
`/tmp/page-break-editable-built-YUH8oD` 含保存请求、下载 `saved.xlsx`、
`zip-inspection.json`、七份实际打印 HTML 和最终网格截图。该轮未重复已通过
的保护只读 probe，未修改产物或重新构建。

- 实际跨 epoch 设置、行列插删、Undo/Redo、尺寸和隐藏后，保存一次；Python
  `patch_office` 应用真实浏览器 operations，HTTP 下载 SHA 与保存文件一致：
  `f31488ec18509726e18a48ac970f65ceee0fbe4cb8c01ab1ef77c1ec350a2c8f`。
- openpyxl 和 ZIP 检查确认源隐藏 C 插列后为 D，最终隐藏列为 D/F/G；原 D
  不再生成 index3 的伪列宽补丁。显式取消隐藏的独立 ZIP/Univer 合同保持通过。
- area A1:H40、titles 1:1、rowBreaks [10,14]、colBreaks [4,5]、行高42、
  可见列宽20、隐藏行6/7均通过。七阶段实际预览/打印页数为
  4/4/9/9/9/9/6，逐阶段相同。
- 118 个 built JS 资源 HTTP200 且 SHA 与磁盘一致，pageErrors=[]。

本专项关闭已复现的隐藏列结构/列宽保存缺口，不宣称所有 OOXML 属性、
生产授权 HTTP、桌面 Excel 或打印机行为完全等价；修订与授权路由仍为本地
夹具，文件变更、下载和 ZIP 检查真实。
