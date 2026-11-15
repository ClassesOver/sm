# 原生 PPTX 图表元素编辑验收

2026-11-11。固定参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`：
`apps/slides/src/renderer/components/Ribbon.tsx` 的 Chart Elements，以及
`packages/pptx-engine/src/index.ts` 的 `editChartElement`。

## 本轮范围

图表设计页新增“图表元素”，支持图表标题、分类轴标题、数值轴标题、图例位置
（无/上/下/左/右）、数据标签、网格线。复用现有 `chartEdits` 草稿、历史和保存链路，
调用固定引擎的 `editChartElement`；没有新增图表 writer 或修改 vendored engine。
元素设置从真实来源及待保存修改回填，只提交变化字段。取消及无变化确认不产生历史；
显式空标题、`false` 和 `legendPos=none` 可以保存。标题沿源行为 trim，最多1000个
Unicode码点，拒绝控制字符、孤立代理项及无效 XML 字符。

沿用已有安全边界：只允许带 `aislides-chart` 标记且图表部件/内嵌工作簿归属唯一的
可重建原生图表；外部来源、共享部件、特殊类别及扩展等继续只读。没有放宽
`chartEditSafe`。饼图、三维饼图、圆环图禁用轴标题和网格线控件。
数据、类型和元素修改合并为同一目标的一个 patch，保留陈旧弹窗拒绝覆盖机制。
修改发布/下载链路不在本轮范围，未改变非阻断签发契约。

## 定向测试与失败记录

证据根目录：`/tmp/pptx-chart-style-20261111/`。未运行完整测试集。

- RED：`protocol-red.log`、`bridge-red.log`、`frontend-red.log` 保留新增字段尚未接入时
  的失败，未计为通过。
- Python：`test_pptx_chart_style.py` 与 `test_pptx_native_edit_contracts.py` 共31项通过，
  见 `python-green.log`。覆盖非法字段、显式空值/false、Unicode边界、真实文件保存
  重开、独立 python-pptx/lxml 读取，以及所有无关 ZIP 部件字节不变。
- 桥接：`pptx-chart-style.test.ts` 与 `pptx-chart-edit.test.ts` 共6项通过，
  见 `bridge-green.log`。覆盖13种固定图库类型的格式修改后类型与数据保留，
  来源只读边界和非法格式拒绝。
- 前端：图表弹窗、媒体草稿、编辑集成、Ribbon 共52个不同用例分批通过。
  初轮 `frontend-green.log` 为48通过、1失败：测试来源未配置图例，却期望“无图例”
  生成变更；修正测试夹具为真实右侧图例后，仅重跑该失败用例通过，
  见 `frontend-integration-green.log`。另补三个无轴图表禁用控件用例通过，
  见 `frontend-axis-green.log`。未为满足测试而改动正确的无变化行为。
- Python生产适配器与新增测试 Ruff 检查通过；辅助Python编译、smoke脚本语法检查通过。

## 构建与浏览器验收

使用临时 Vite 配置将当前前端构建到独立 `static/`，仅关闭会写入共享 static 的
PDF资源复制插件，保留其他构建配置；未覆盖共享前端或引擎 dist。
Vite 构建退出0（50.74秒），见 `build.log`。370个 JS chunk 的既有预算检查通过，
未调整阈值；slides-main 为241310字节，见 `budget.log`。

本次全局 `tsc --noEmit` 退出2，唯一诊断为未涉及的
`src/docx-ruler.test.tsx(25,54)`：`extendedIndents` 不属于 `Options`。
见 `tsc.log`。不能将本轮描述为全工作区类型检查通过。

- 冻结 manifest SHA256：`f85c0a9834e5d6f958a187304037986b026403e0a22accd1d07db85c17f8971d`。
- 独立 `runtime/dist/edit-pptx.mjs`：`69100126f8519c5a5ca3f609953e7577a59d7a5f9f4a83dd32ef1c2b863a4b33`。
- 独立 `runtime/dist/render-pptx.mjs`：`05f1574d88f1ec43e4f3af778c7bb2f3557101831ef404a71d4859c3bb8db918`。

扩展已有 `frontend/smoke/pptx-parallel-edit-smoke.mjs`，沿用实际Python/Node
inspect、patch与render链路。浏览器运行于上述独立新构建，退出0、`ok=true`，
证据 `browser/evidence.json` 和 `browser.log`。API路由为明确的授权/CSRF fixture，
不声称覆盖生产鉴权、数据库、部署或PDF转换；辅助PDF是attachment placeholder。

浏览器实际验证：

1. 图表数据改为37.5，切换折线类型；元素弹窗来源回填，无变化提交和取消不改草稿。
2. 修改六类元素，格式事务撤销/重做保留前序数据与类型；与图片及文字修改同批保存。
3. 刷新恢复完整草稿，点击保存，读取界面签发链接并下载实际PPTX。
4. 独立 python-pptx/XML/ZIP 回读下载文件，确认标题 `营收😀 <&>`、轴标题
   `月份`/`万元`、上方图例、开启数据标签、关闭网格线，以及系列 `[37.5,20]`、
   折线类型和未涉及的母版/版式/主题身份。
5. 打开修订2，数据与六类元素控件再次读回正确值，草稿为空。

117份实际网络JS响应均逐一匹配冻结磁盘文件，manifest前后一致；page、console、
route及HTTP失败列表均为空。已目视 `browser/revision-2.png`，标题、图例、标签和
分类轴标题可见且网格线关闭；综合夹具的图片保留原定位置，与图表区域存在重叠，
本轮未调整该布局。来源和实际下载文件保留在同目录：

- 来源 SHA256：`eb5d3a4a38023011fcb0906f8abb6fb0d020416e5e3b37c85afd63a46e92d284`。
- 下载 SHA256：`f0b0e1af81b6dadb3a9fabe04f84b5273ee9a8b700cda953e272e0ed2850954c`。

## 剩余缺口

本专项关闭图表六类元素编辑。后续已接入配色方案、10个命名样式预设和
预设柱间距，见[图表配色与命名样式专项](NATIVE_PPTX_CHART_DESIGN_ACCEPTANCE.md)。
单点配色后续已接入，见[单点配色专项](NATIVE_PPTX_CHART_POINTS_ACCEPTANCE.md)。
源缩略图图库和配色色卡后续已接入，见[缩略图库专项](NATIVE_PPTX_CHART_GALLERY_ACCEPTANCE.md)。
图表数据点颜色侧栏后续已接入，见[格式侧栏专项](NATIVE_PPTX_CHART_FORMAT_PANE_ACCEPTANCE.md)。
完整FormatPane其他分组与布局仍开放，任意柱间距输入和圆环孔径控制属于尚未暴露的引擎参数能力；
不能标记完整 Chart Design 或 PPTX 全面对齐。外部/复杂图表仍受安全来源
边界限制。本轮未提交、推送或部署。

后续增量已完成交换行列与实际下载/重开验收，见
[图表交换行列专项](NATIVE_PPTX_CHART_SWAP_ACCEPTANCE.md)。
