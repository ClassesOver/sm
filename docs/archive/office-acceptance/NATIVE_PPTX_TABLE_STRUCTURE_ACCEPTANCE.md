# PPTX 简单表格行列结构验收

2026-11-10，固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
原仓库已实际 clone 到 `/workspace/genoffice`，sparse checkout 包含 slides/pdf 与相关引擎、UI、i18n 源码；这不是生产部署证明。

## 原始素材与方法

从 `apps/slides/src/renderer/context-menu-items.ts` 的六种行列菜单、`table-actions.ts` 的参数转换，以及 `packages/pptx-engine/src/index.ts` 的 `editTableStructure` 入手。原始菜单不是 Ribbon；本实现用 Web Table Design 弹窗承载同一组操作，复用未修改的固定引擎 helper。

协议 `tableStructures[{slideIndex,elementId,kind,index,before?}]`；插入必须显式 before，删除不允许 before。六种操作为上/下插行、删行、左/右插列、删列。每来源页一次，最多100项，1–75行列，不得删除最后一行列或突破上限。

## 保真与拒绝边界

只开放矩形无合并且来源尺寸规范的表格。原 XML 的 gridSpan/rowSpan/hMerge/vMerge、extLst、非规范引号/非正整数尺寸、解析模型与原网格或外框不一致、缺稳定 cNvPr 均拒绝。结构与同表改字/样式、slideSize、同页版式/重置不能混用；其他对象/其他表的修改及复制有组合验证。

固定 helper 插入格清空 txBody，只继承 tcPr（边框、底纹、边距等），不声称继承字体。回读核对外框、网格、稳定形状身份与矩阵；幸存单元格 XML 做 C14N 比对。原始文件不覆盖。

UI 支持历史、刷新恢复、单项撤销及严格草稿校验。待保存时画布与格子保持来源快照，保存重开后才显示新结构；不会将可能改变对象 ID 的结构命令注入来源 render-tree。

## 验证范围

- 21项唯一相关后端/真实 native roundtrip 检查；初轮20通过，1项使用旧 dist 失败，重新打包后该真实 roundtrip 与协议检查2项复验通过。六种操作、原格 XML、空白新格、tcPr、尺寸、复制/其他对象/新表组合及无输出拒绝。证据 `/workspace/scratch/pr210-table-structure/backend-regression.log`、`native-roundtrip.log`。
- 26项新 UI 检查；相关 Ribbon 与 native 组检查已运行。既有501次 Enter 的压力用例默认5秒超时，单独30秒限制复验通过，未全局修改超时。
- 浏览器脚本 `frontend/smoke/pptx-table-structure-smoke.mjs` 使用生产静态资源、实际 Python/打包引擎，覆盖暂存/撤销重做/恢复/保存/下载/重开，独立 python-pptx 检查网格与原文字。

合并/复杂尺寸/扩展表格、同页连续多次结构操作、完整样式库与生产鉴权/SQL、桌面及完整镜像验收仍开放。功能开关保持关闭。

## 集成验收记录

Standard 与 Slides 前端构建、配置的 Standard budget 通过；PDF strict tsc 仅保留六项既有宿主/未打包 UI 声明诊断，无新增错误。应用 Python Ruff 与 diff 检查通过，未重复全仓测试。

打包运行时在 `node:22-slim --network=none` 执行实际修改成功，伪造字典/非法结构请求非零退出且无输出文件；独立 pypdf/python-pptx 检查正文、批注数量、网格与空白新列。证据 `/workspace/scratch/pr210-next/offline/independent.json`。此结果不代替完整应用镜像、数据库或鉴权验收。

生产静态 Chromium 浏览器已通过六按钮中下插行的完整闭环：撤销重做、刷新、保存下载、3×3 网格、原文字/其他对象、重开后继续可编辑。证据 `/workspace/scratch/pr210-table-structure/browser/evidence.json`。
