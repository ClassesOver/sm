# PPTX GenOffice 对齐 PR 汇总验收

日期：2026-11-11。范围由用户确认为“本会话全部 PPTX 对齐改动及必要依赖”。
GenOffice 参考固定为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 分支与范围

在独立 worktree 提取本次 PPTX 代码和最小共享依赖，未将共享目录的其他未提交修改整体提交。
最初基于 `9f2c4944d96ccab0671026af7f8c38ffc293b3c0`；准备 PR 时 `code` 合入 XLSX PR #213，
因此更新到 `9d90d2d022c53631f01cb36f5d799034661dde99`。唯一文本冲突为
`NativeOfficeReadContext` 的等价类型定义，保留共享接口并导出 PPTX 使用的选择类型。
XLSX 提交保留在基线，不计入本 PR 的功能范围。

本次包括 PPTX 原生 AI 草稿/审阅/取消、备注、经典评论、剪贴板与链接、查找替换、
图表数据/设计/样式/数据点、组合/排列/图层/框选、隐藏页与放映、图片裁切、
厘米大小位置、会话百分比缩放、相对图片原始尺寸，以及图表/形状格式分组。
完整能力边界和各专项证据见同目录 `NATIVE_PPTX_*_ACCEPTANCE.md`。

仅提取必要的 AI 事件/进度、助手面板、任务栏、Ribbon 滚动和宿主入口依赖。
未纳入其他未提交 Word/PDF/Workbook 功能、依赖升级、DOCX 引擎迁移、部署或数据库修改。
未改发布门禁、下载签发和溯源逻辑；未新增 Plotly 链路。
专项文档中的旧路径、构建身份和“未提交”结论是各专项完成时的历史记录，
本文件说明 PR 最终打包状态，不把旧证据冒充当前构建证据。

## 提取复核与定向验证

证据目录：`/tmp/pptx-pr-20261111/`，不提交临时产物、依赖目录及日志。
依照项目要求，未重复完整测试套件。

- 独立 slides_engine 安装依赖并执行 `npm run bundle:bridges` 成功。
- `python-targeted.log`：101 项 PPTX 原生操作、备注 API、取消终态及备注/评论/剪贴板链接协议测试通过。
- 提取复核发现共享取消逻辑缺失终态保护；`shared-cancel-red.log` 两项失败复现后，
  在 planner、preview await 后和异常入口补齐既有取消检查；`shared-green.log` 两项通过。
- 启动集成测试在配置测试专用 HMAC/public URL 后通过，验证 PPTX AI 路由和 shutdown 注册；
  初次缺少测试环境变量的失败保留在日志，没有修改生产配置。
- 宿主 AI 关闭时入口回调也必须关闭；新增回归先失败再通过（`entry-*-log`）。
- 提取后的迟到图片来源、原生 AI 传输和任务栏定向样本共三项通过；另有15项按筛选跳过。
- 更新到最新 `code` 并改用锁文件独立依赖后，PPTX 范围 TypeScript 检查退出0；
  `frontend-rebased-clean.log`：AI 开关两项、PPTX AI 客户端十一项，共13项通过。

两个独立只读复核覆盖前端提取和 Python 服务接线，取消终态与关闭入口问题修复后均已复核。
这不是完整测试集通过、真实模型调用或生产鉴权验收的声明。

## XLSX 基线阶段独立构建与预算

最终前端按分支 package-lock 在 `/dev/shm` 独立 `npm ci --ignore-scripts` 安装；
Workbook 引擎也按更新后的锁文件重装，slides 引擎使用本分支的独立 bundle。
构建使用真实生产配置，临时配置仅移除向共享 static 复制 PDF 资源的插件并改变输出目录。
因此不宣称该复制插件、生产部署或 PDF 转换已验收。

`build-rebased-clean.log` 构建退出0，输出冻结在
`/dev/shm/pptx-pr-20261111/static-release`。manifest SHA256：
`bdf9151fa4e61166ab9592d71b32b22d279e4fdd981bb3b8cb4b84651f1603a3`。

必要的分包修正包括共享图标、三个 PPTX 格式分组及 Ribbon 滚动；
Workbook 本地 node_modules 不再被路径规则错误归入自有 engine，
不同安装根的 schema/zip/format 依赖分包，不跨版本合并或放宽预算。

350 个 JS chunk 中 PPTX main 为255316字节，低于250KiB上限；
几何分组6874字节，图表分组9465字节，形状分组6768字节。
**全站预算检查仍有一项失败**：`lazy-workbook-icons-5u0fopQy.js`
280818字节，相对现有274KiB上限超出242字节。未扩大预算，也未将此声明为通过；
PR 以 Draft 提交，后续需处理或独立确认该 Workbook 图标预算问题。

独立运行引擎 SHA256：

- edit-pptx：`f78ceb6e6256b43e27b0067a5d63d98b7b11e66f73325c4ab3a8eb840d05e9b2`
- render-pptx：`4fd9061aca988f83794ee246227546f8fd46af9fe93a47475be0d9ebb3707592`

## XLSX 基线阶段浏览器与文件回读

更新基线前的隔离构建已完成图片原始尺寸和形状格式两条真实 Chromium 流程，
分别有113份运行 JS 身份校验和零错误。两条流程的宽/窄屏截图已目视；
不据此宣称整个 Ribbon 窄屏完全适配。
最新锁文件构建的 `browser-rebased-clean.log` 退出0，revision=2，114份运行 JS
逐一与冻结产物校验大小/SHA256，四类错误数组均为空；重开截图已目视。
下载47032字节，SHA256：
`cdedf292f8c97a290f24a30abfc088769065d76ff51a6e2476445a749632a335`。
`verify-release-download.py` 与 `verify-release-xml.py` 通过：

- 实际下载图片框EMU `[914400,1828800,1828800,457200]`，原文本框未改。
- 仅修改 `slide1.xml` 的图片大小/位置、裁切及既有 creationId；43个其他文件部件字节一致。
- 媒体blob身份、图表、嵌入工作簿、主题/母版/版式、文字和第二页均保留。
- 真实保存请求、下载回执身份与实际文件一致；已完成下载bytes打开修订2。

浏览器使用真实 Python inspect/patch/render；鉴权/CSRF是明确标识的 route fixture，
辅助PDF为有效占位附件。

## 仍开放的能力

旋转、复杂填充与轮廓编辑、效果、文本框设置、完整 FormatPane 布局和多选格式编辑
仍需专项对齐。当前图片替换的新原始尺寸需保存重开，未保存替换沿用受保护的回退语义。
生产鉴权、数据库、真实模型、PDF 转换和部署不在本次浏览器 fixture 验收范围。

## PR 创建后的 Word 基线同步

PR #216 创建后，`code` 又合入 Word PR #214，推进至
`302517bfca0fee2bdf6a7e04edfe272db22462ec`，导致 Vite 配置冲突。
将其合入功能分支，保留 Word 的 PDF serializer 分包和 PPTX 的共享图标分包。
共享选择类型自动合并后复核语义不变。Word 的 DOCX 引擎目录迁移成为新的基线；
相应适配 PPTX find-replace 生产代码及其测试的共享 XML 工具引用路径。
这不是将其他未提交 Word 代码加入 PR 范围；最终差异仍相对于最新 `code`。

按更新后的 slides/doc engine 锁文件分别重新 `npm ci --ignore-scripts`；
`engine-word-merge.log` bundle 成功，`tsc-word-merge.log` TypeScript 检查退出0。
查找替换 Vitest 两项通过，图片裁切 node:test 三项通过。
首次将 node:test 文件交给 Vitest 时报告无 Vitest suite；保留校准失败日志，
随后用其实际 tsx/node:test 入口通过，未为迎合运行器修改生产代码或测试断言。

`build-word-merge.log` 构建退出0，冻结输出 `/dev/shm/pptx-pr-20261111/static-word-merge`。
manifest SHA256：`f3a4b9baac90f373e481d98749695fa61216376df1457e742f2232f4ccbcac7d`。
edit engine SHA256 更新为
`0814aee61947db84d602e70eb2443ec6a94c085887aa8c66d1fc3e8a1a557b54`；render 身份不变。

365个JS chunk中，PPTX main为255524字节，在250KiB内；三个格式分组大小不变。
最终预算检查**未通过**，有两项非PPTX包超限：

- `lazy-docx-main-DMsXLABf.js`：257813字节，比250KiB上限多1813字节。
- `lazy-workbook-icons-5u0fopQy.js`：280818字节，比274KiB上限多242字节。

未放宽预算，也未宣称全站预算通过；继续以 Draft PR 交付。
最新 `browser-word-merge.log` 退出0，revision=2；118份运行JS与冻结产物逐一核对，
page/console/route/HTTP四类错误数组均为空，保存前flush和下载重开流程通过。
下载47032字节，SHA256：
`ec58dd2c4ff51cdc9094e2c133c2ed6f4d7ff1f678d68746d0ef0148592b9394`。
`verify-word-merge-download.py`、`verify-word-merge-xml.py` 均通过：
图片框EMU为 `[914400,1828800,1828800,457200]`，原文本框保持，
43个其他文件部件逐字节一致。最新修订2截图已目视。
鉴权、PDF占位和生产部署限制与前述一致。
