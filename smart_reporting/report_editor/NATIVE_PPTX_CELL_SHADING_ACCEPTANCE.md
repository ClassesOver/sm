# PPTX 单元格底纹

2026-11-10，固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；原始 Git clone 位于 `/workspace/genoffice`。

原 Ribbon.tsx 的 Table Design 根据 tableActiveCell 调用 `editTableStyle({shadingColor,cells:[{row,col}]})`，没有活动格时作用整表。固定 `packages/pptx-engine/src/table-edit.ts` 的 patchCellsTcPr 按原始 tr/tc 索引修改 tcPr；原helper未改。

Web 保留同一底纹调色板，明确当前目标：聚焦来源单元格后作用单格，通过“底纹作用于整表”切回整表。不是对桌面格内编辑/上下文菜单的完整等价声明。

协议在单表 tableStyles 项中追加 cellShadings:[{row,col,shadingColor}]，只接受固定色与none、唯一格坐标和跨表总预算500。最终顺序为preset→flags→整表底纹/边框→单格覆盖；选择新preset或后续整表底纹清掉此前单格覆盖，方向/区域flags与边框保留它们，符合源命令顺序。保留既有tableCells改字协议。

只开放能证明原始physical tc与模型logical坐标一一对应的规范单层矩形表格；合并/嵌套/扩展或无法确认身份的来源保持只读并解释原因。单格能力独立于整表样式，不因这项限制禁用既有整表底纹/边框。

验证必须覆盖仅目标格tcPr变化、全部txBody与非目标格、几何/关系保留、noFill、多个格、整体样式组合顺序、文字同时修改、历史/刷新、实际画布及下载重开，危险/伪造/失效参数不得生成错误产物。

复杂表格单格格式、单格边框/字体、任意样式库及完整Office/桌面/生产/镜像验收仍开放，功能开关保持关闭；先前LibreOffice消费RTL未镜像列的差异继续保留。

## 验证记录

17项新增+4项既有后端检查通过，包含两格/noFill、整体样式/文字组合顺序、两表共同预算500+1拒绝、缺tcPr、命名空间诱饵与祖先重绑定，以及合并/扩展/嵌套等危险来源；未确认来源事先只读。日志 `/workspace/scratch/pr210-cell-shading-backend/`。

前端18项新增+71项相关检查通过，覆盖目标切换、unsafe格不误改整表、历史/刷新/嵌套深拷贝、过期DOM、total500与表record500预算。

打包引擎Node22 --network=none实际修改通过，独立python-pptx/XML回读确认仅目标tcPr变更，全部txBody与其他格、形状几何和其他文字保留；非法格索引拒绝且无输出。证据 `pr210-cell-image/offline/independent.json`。

Standard与Slides生产构建、完整前端TypeScript、配置的Standard budget、Python应用Ruff、语法与diff检查通过；未重复完整仓库测试。原始vendored引擎、依赖/锁文件与PDF后端协议未改。

生产静态Chromium单格全闭环通过：preset/整表清覆盖、三格固定色/noFill、边框保留单格覆盖、历史/刷新、实际画布、文字同批、保存下载与重开。原合并表格整表底纹/边框浏览器回归也通过，选格能力限制没有禁掉整表功能。证据 `pr210-cell-image/pptx-browser/evidence.json`、`whole-table-browser/evidence.json`。

保留首次harness失败记录：重开后错误要求下拉框显示已保存颜色；该选择器表达待保存覆盖，没有pending时保留选择颜色占位符。实际文件此前已正确导出、独立回读通过，仅修测试期待，不改产品源码。

独立LibreOfficeDev消费浏览器下载PPTX、导出PDF，再由pypdf/Pillow/Poppler核对文字及5处精确RGB：原表头4472C4、目标E2EFDA、原交错行D6E4F0、目标FFF2CC及noFill白底。证据 `pr210-cell-image/external/independent.json`；保留PPTX/PDF/栅格产物，不把此单例视作所有Office消费者或复杂表格视觉验收。
