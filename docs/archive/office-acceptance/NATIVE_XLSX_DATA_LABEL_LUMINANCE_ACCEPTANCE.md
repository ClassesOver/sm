# XLSX 数值标签亮度变换验收

日期：2026-11-12；续 PR #222。限定普通 bar/column 显式 value 标签的 srgbClr / 已解析 schemeClr：零或一个 lumMod，随后零或一个 lumOff，整数百分比单位100000，值域0..100000。不关闭完整 DrawingML 颜色变换家族。

## 原始依据与实现

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `packages/pptx-engine/src/color.ts::applyColorMods` 是已有 DrawingML 颜色实现，实际在 HSL 亮度上计算 `clamp(L * lumMod / 100000 + lumOff / 100000)`、保持色相与饱和度，最后四舍五入RGB字节。复用本地 style-color 现有 RGB/HLS 转换，仅为图表增加独立亮度入口；单元格 tint 的旧截断规则不变。没有套用 RGB 通道直接乘加，也未将 DrawingML tint/shade 等价成此计算。

chart-label-color 复用既有 SaxesParser 检查颜色节点和直接变换子节点。未知、重复、嵌套、倒序、缺值、越界或混入 alpha 的组合整体返回 unsupported；不会只应用其中认识的一部分。主题槽位内部的颜色变换仍未支持，主题仍需前一批的完整配色严格解析。reader 的 plot/series/point 共用此解析，既有画布继承与字体度量不改；保存不展开 schemeClr、不重写原 lumMod/lumOff。

## 证据冲突及独立计算

固定源注释称 `#4472C4 + 75% lumMod` 为 `#2F5496`，但执行原函数与 Python colorsys 实际均为 `#2F5597`。本批记录差异并依照执行结果，未把注释当作正确性的唯一依据。另一已知样例 `#7F0000 + 40% lumMod + 60% lumOff` 为 `#FF6666`。

可复现的 `frontend/smoke/workbook-chart-label-luminance-oracle.py` 用 git show 读取固定提交的原 color.ts 和 xml-utils.ts，保留原函数体、经 esbuild 去类型后直接执行；完整原文件SHA写入证据。原实现与本地实际颜色解析共1120组（32色×7倍率×5偏移）完全一致，包括灰阶、黑白、饱和色、主题样例、固定种子随机色、端点与钳位。独立 Python colorsys 其中1114组完全一致，另6组为浮点半步舍入差异、每通道最多1，逐项保留，未隐去或说成全部精确一致。证据 `/tmp/xlsx-label-luminance-oracle.json`。

## 定向验证

- 新17项加入后有效RED为7失败/27通过；6个可解析颜色和一次改图后重解析复现缺口。初次GREEN另发现上述固定源注释舍入差异，检查原代码与独立算法后修正测试预期，无需改动颜色算法。
- 主题/亮度读取34项、既有字体/数据标签/表格主题30项、真实主题bridge2项，**66项分批通过**，未重复完整项目测试。负控包含乱序、重复、非法数值、混合alpha、嵌套变换；图表编辑后仍保留完整变换原字节，换主题后重新解析。
- 引擎两级tsc与bridge bundle通过；完整前端tsc/Vite **49.21s**、全部JS预算、Ruff/JS语法/diff检查通过，预算未放宽。

## 实际页面、下载与像素

最终证据 `/tmp/workbook-chart-label-luminance-browser-20261112/summary.json`；冻结目录 `/tmp/workbook-chart-label-luminance-static-20261112`，manifest SHA `113d9b08e185c030344fe56d62ab24767f4b97bb4d4094436505158e9d4d2580`。Chromium140.0.7339.16、字体预检通过，169份实际JS/CSS SHA与冻结磁盘一致，page/console/http/asset四类错误均为空。

真实 NativeEditorService/授权/CSRF/引擎/修订登记/下载：主题 accent2 先应用40% lumMod与60% lumOff，原色 #C0504D 得到 #E6B9B8；页面布局切换 Ember 后原色 #E97132 得到 #F6C6AD。Undo恢复、Redo重算、保存4→5、授权下载并核SHA、明确修订5重开均正确。另系列RGB #90EE90经75%lumMod得到 #3DE13D，点级显式 #FFD700保持原色，证明局部覆盖未被系列变换覆盖。实际Canvas调用仅被动记录，见 model.json / theme-reopened-paints.json，不注入模型或操作。保存1次，plannerCalls=0；此批不声称真实AI provider验收。

独立openpyxl/lxml读取下载原始主题、标签和变换，比较ZIP证明只有 xl/theme/theme1.xml发生变化，所有chart部件原字节保持，lumMod/lumOff和schemeClr均未被展开。Python colorsys独立重算源颜色，再由Pillow在真实截图中按前景/背景抗锯齿混合线恢复字形。主题亮字160/167像素、变暗RGB85像素、黄色点52像素，居中位置正确；默认字/红字后备回归，未知phClr和放不下72pt均严格0标签墨迹。根任务已查看完整截图 charts.png；切换前 before-theme.png也保留。

原件SHA `456c8a5516ca67af7a7319cc29a2cd99287ba64902b83fdc17b53b24177e0020`；下载SHA `5ee87977aecb4b96044a7087f61cd5eb42a03a3e70f36689e8197da921c6a145`。

## 仍开放

alpha/透明度、DrawingML tint/shade及其他变换、倒序/重复/超出本范围的合法变换链、主题槽位内部变换、字体族/复杂富文本、手动偏移、完整实时格式继承及复杂图表仍开放。100%缩放浏览器验收不代表全部缩放或真实Office应用渲染已验收。
