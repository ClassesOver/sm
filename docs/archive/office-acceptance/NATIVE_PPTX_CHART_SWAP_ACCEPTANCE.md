# 原生 PPTX 图表交换行列验收

2026-11-11。固定 GenOffice 参考提交：`f8c17004fb730df11f0f743164ffd8b4281bb38c`。
对应上游 `apps/slides/src/renderer/components/Ribbon.tsx` 的 Switch Row/Column，
以及 `packages/pptx-engine/src/index.ts` 的 `editChartElement({switchRowCol:true})`。

## 实现与协议

图表设计的数据组新增“交换行列”，采用上游 `IconSwitchRowCol`。复用现有
`chartEdits`、草稿恢复、撤销重做、来源限制、保存和下载链路，没有修改 vendored
engine 或新增 OOXML writer。每次交换是一笔历史，连续两次恢复原方向；交换后编辑
数据、类型或六类元素继续合并同一目标，旧弹窗不能覆盖已交换的草稿。

`chartEdits[].switchRowCol` 是可选的严格布尔字段，表示相对当前修订来源是否交换。
显式 `categories`/`series` 始终表示用户最终看到的数据方向；省略数据而只传
`switchRowCol=true` 时使用来源的交换结果。桥接在显式数据加交换标志时做反投影，
再交给原生引擎交换，确保图表缓存、内嵌工作簿和已有单点颜色一起转置。
共享的纯数据投影仅用于宿主状态与原生参数转换，不负责写文件。

继续整体校验后再提交：最终数据不超过100个类别、20个系列，名称最多100个
Unicode码点；散点图的最终类别必须是数值X，组合图至少两个系列。交换后的结果
违反这些约束则保留原草稿。现有 `chartEditSafe` 未放宽：外部、共享图表部件/
工作簿、扩展与特殊数据源继续只读。重复目标、删除冲突、未知字段照常拒绝。

双次交换会清除多余的图表patch，保留此前其他修改；这不声称自动清空编辑器通用
“有未保存修改”状态。本轮未修改发布或签发链路，既有非阻断下载契约保持不变。

## 定向验证

证据根目录：`/tmp/pptx-chart-swap-20261111/`，未运行完整测试集。

- RED：`protocol-red.log`（布尔新字段尚未开放）、`frontend-red.log`（缺少按钮/
  草稿支持）、`bridge-red.log`（原协议不接受交换字段）均保留。
- Python共40个不同用例通过：`test_pptx_chart_swap.py`、`test_pptx_chart_style.py`、
  `test_pptx_native_edit_contracts.py`。初轮39通过，工作簿空表头期望为None的新增
  测试失败；确认原生writer写入空字符串后修正夹具，仅重跑该失败用例通过。
  见 `python-green.log` 和 `python-swap-green.log`。实际PPTX的图表、水平条形
  类型、双向交换、格式及所有无关ZIP部件保留；openpyxl独立读取嵌入工作簿。
- 桥接共9个不同用例分批通过，涉及既有数据/样式与新增交换专项。13种图库类型
  交换后类型、数据、标题、图例和实际来源已有的单点颜色匹配转置结果。
  非法布尔、超过20个最终系列、非数值散点X、组合图不足两个系列均先拒绝且
  不改变archive。见 `bridge-green.log`、`bridge-swap-final.log`、
  `bridge-kinds-final.log`；只有各次最终通过的用例计为完成。
- 前端55个不同用例分批通过：图表弹窗、媒体草稿、编辑集成与Ribbon。
  覆盖来源数据与待保存数据交换、连续两次、后续编辑、撤销重做、刷新恢复、
  保存请求、过期弹窗拒绝。见 `frontend-green.log`、`frontend-swap-green.log`、
  `frontend-swap-final.log`。Ribbon在按钮接入后另行复核，见 `ribbon-final.log`。
- Ruff、Python编译、浏览器smoke脚本语法检查通过。

测试夹具修正记录：颜色解析结果带`#`，水平条形创建必须是`kind=bar`加
`barDir=bar`，数组断言必须包含第二个系列。另查明固定源的scatter构建器不写
`dPt`，因此13种测试比较真实来源颜色转置，未把未生成的请求颜色视为来源颜色，
也未为通过测试修改上游能力。上述失败保留在各阶段日志。

## 独立构建和类型检查

Vite通过临时配置构建到独立 `static/`，关闭写共享static的PDF资源复制插件，
其他配置保留。构建退出0（44.59秒），370个JS chunk的原预算检查通过、阈值未改。
slides-main为243232字节，见 `build.log`、`budget.log`。

全局前端 `tsc --noEmit` 仍退出2，唯一诊断为未涉及的
`src/docx-ruler.test.tsx(25,54)`：`extendedIndents`不属于`Options`，见 `tsc.log`。
桥接与新增测试沿引擎的ESNext/Bundler、strict配置定向检查退出0，
见 `bridge-tsc-strict.log`。最初以NodeNext试跑产生原源码省略扩展名的诊断，
该命令配置不符合引擎基线，未作为产品失败或通过证据。

- manifest SHA256：`801889ef387a8708d0b3f5caa04fe0231fc5ca57eb587101a4725c5ad401cf98`。
- 独立edit桥：`792f1013a8ce802d6bb00f83158fa663901cf967ed0f5ceaddd75694ba0463f0`。
- 独立render桥：`05f1574d88f1ec43e4f3af778c7bb2f3557101831ef404a71d4859c3bb8db918`。

## 实际浏览器保存、下载和重开

`frontend/smoke/pptx-parallel-edit-smoke.mjs` 增加
`PPTX_SMOKE_CHART_SWAP=1`模式；使用上述独立新构建和桥，实际Python/Node执行
inspect、patch与render。浏览器API授权/CSRF为显式route fixture，不声称覆盖
生产认证、数据库或部署；PDF为attachment placeholder，不验证PDF转换。

浏览器运行退出0、`ok=true`，见 `browser.log`、`browser/evidence.json`：

1. 修改数据为37.5、切换line、修改六类元素，然后交换，类别为Revenue，
   系列为One/Two；再次交换完整恢复前序草稿，第三次交换后将One改为99。
2. 撤销数据修改保留交换，重做恢复99；与图片、文字修改一起刷新恢复并保存。
3. 从界面签发的链接下载实际PPTX。独立python-pptx/XML读取类别Revenue、
   两系列One=99/Two=20、line类型及原六类元素；未涉及的母版/版式/主题身份保留。
4. 打开修订2，从数据和元素弹窗再次读回正确值，草稿为空。

117份实际网络JS响应逐个匹配冻结磁盘文件；manifest前后一致；page、console、
route和HTTP失败列表为空。已目视 `chart-swap-dialog.png`：交换后的表格、数据输入
和确认按钮可见；`revision-2.png`显示两系列的99/20与原标题、图例、轴标题。
综合夹具图片仍在原定位置并与图表区重叠，本轮未调整该布局。

另用openpyxl独立读取实际下载文件的内嵌工作簿，精确得到
`[["", "One", "Two"], ["Revenue", 99, 20]]`，见
`browser/independent-workbook.json`。实际下载47717字节：

- 下载 SHA256：`e63a78ebe762b2c9cbceb1164c3ef6b5c943af2f7270650f1ddc4aea61fbc062`。
- 来源 SHA256：`8f945ea0b7d95bebdee1e0eeec054cef1d6bddda825cc2d7ff78f53a953ed33c`，验收后不变。

本专项关闭“交换行列”缺口。后续配色方案、10个命名样式预设及预设柱间距
已接入，见[图表配色与命名样式专项](NATIVE_PPTX_CHART_DESIGN_ACCEPTANCE.md)。
单点配色后续已接入，见[单点配色专项](NATIVE_PPTX_CHART_POINTS_ACCEPTANCE.md)。
源缩略图图库和配色色卡后续已接入，见[缩略图库专项](NATIVE_PPTX_CHART_GALLERY_ACCEPTANCE.md)。
图表数据点颜色侧栏后续已接入，见[格式侧栏专项](NATIVE_PPTX_CHART_FORMAT_PANE_ACCEPTANCE.md)。
完整FormatPane其他分组与布局仍开放，任意柱间距输入和圆环孔径控制属于尚未暴露的引擎参数能力。
不代表完整Chart Design或PPTX全面对齐。本轮未提交、推送或部署。
