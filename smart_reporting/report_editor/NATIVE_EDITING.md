# 原生 Office 接入指南

系统报告先走现有编辑入口。文档报告仍以 Markdown 为正文；从当前报告修订打开 Word 或 PDF 时，服务端验证产物身份并创建独立分支。保存为新修订，页面可继续下载并显式打开新修订。现有报告 XLSX/PPTX 编辑入口保持原有授权和修订链。上传的四格式文件使用独立工作区与修订仓储。

| 格式 | 当前范围 |
| --- | --- |
| DOCX | 正文、基础整段格式、非空整段上标/下标及返回基线、段落对齐/缩进、已有编号层级、六档倍数行距和段前/段后间距开关、普通表格文字、符合条件的固定列宽表增删行列、段落插删，支持从草稿导出 PDF。末尾 section 可改纸张、方向、边距、分栏和页眉/页脚距离。复杂对象保留；每表每批仅一次结构修改，须保存并重开后继续。精细段落对话框、复杂表格/合并拆分、分节及页眉/页脚部件编辑尚未接通。 |
| PDF | 搜索、高亮、便签、旋转、删页、重排/反序及受支持 AcroForm 字段填值。原位改字另开开关，支持可唯一定位且字体与空间允许的文本对象；扫描页仍可标注。 |
| XLSX | 复用工作簿网格与现有单元格、样式和结构操作，支持已核验来源的六档文本旋转；未建模继承格式禁用旋转。引擎为 GenOffice 浏览器子集，桌面外链改绑及依赖桌面网关的功能未移植。 |
| PPTX | 复用 Konva 画布，支持文字、位置、版式、背景、页序、主题、转场、动画及 16:9/4:3/A4/A3 横竖尺寸等已适配操作。尺寸缩放在保存后重开更新画布；自定义源尺寸须先明确选择标准预设才能切换方向。上传路径暂不提供 AI 配图、改图和文稿候选。 |

Word/PDF AI 使用当前报告模型的 Agno 配置。候选先经过真实引擎核验，用户采纳后只进入草稿。PDF AI 仅允许所选文字对象的替换；最终保存前仍须查看实际 PDF 并确认预览。无法定位、字体缺字或文字溢出时，该项保留原文并显示原因。

## 灰度与回滚

下列开关默认均为 `false`。同功能的旧 `AGENT_NATIVE_*` 变量仍可读取，新变量优先。

| 开关 | 作用 |
| --- | --- |
| `AGENT_REPORT_EDITOR_DOCX_ENABLED` | 启用 Word 原生编辑。 |
| `AGENT_REPORT_EDITOR_PDF_ENABLED` | 启用 PDF 基础编辑。 |
| `AGENT_REPORT_EDITOR_PDF_TEXT_ENABLED` | 在 PDF 基础编辑之上启用原位文字修改。 |
| `AGENT_REPORT_EDITOR_AI_ENABLED` | 为启用的 Word、以及启用原位文字修改的 PDF 提供 AI 候选。 |
| `AGENT_REPORT_EDITOR_UPLOAD_ENABLED` | 启用四格式导入及上传 XLSX/PPTX 的编辑。上传 Word/PDF 的编辑还需要各自的格式开关。 |

开关随应用进程加载，对该进程的所有授权用户生效。先使用仅测试人员可访问的独立实例，生产实例保持关闭；仅隐藏宿主按钮不能限制服务端入口。依次启用 Word、PDF 基础、PDF 文字，再启用上传；启用 AI 前另测模型连接和采纳流程。每批查 `GET /ready`，并完成编辑、保存、实际下载、新修订重开和独立工具回读。启用 PDF 文字时 readiness 会实际探测中文数字改字及字体资源。

遇到文件身份异常或内容丢失时，关闭相关开关并重启。保留新增数据库表、工作区、既有修订和静态资源。现有下载授权在有效期内继续可用；验证或追溯失败会显示具体原因，仍可下载身份已核验的文件。

## 上传组件

在同源宿主中加载构建后的 `/reports/v1/editor/assets/native-upload.js`，调用：

```js
import { createNativeUploader } from '/reports/v1/editor/assets/native-upload.js'

const uploader = createNativeUploader(container, {
  getAuthorization: fetchCurrentWorkspaceCapability,
})
// 宿主卸载页面时调用 uploader.dispose()。
```

宿主负责从当前登录会话取得短期签名凭据，返回 `{ thread, capability }`。组件将它们置于请求头，提交 `POST /reports/v1/native/import`，表单只有 `file` 和 `requestId`。服务端按签名确定数据库、公司、用户和线程；单文件上限 24 MiB，只接受未加密的 PDF、DOCX、XLSX、PPTX，拒绝旧二进制和宏格式。上传文件没有系统报告的事实核验和追溯状态。

本仓库提供组件与验签 API；Odoo 或聊天宿主需在各自仓库接入页面、复用已有的短期凭据签发流程，并把 `/reports/v1` 转发到同一来源。验收进展和证据见 [GenOffice 升级记录](../reporting/slides_engine/UPGRADE.md)。


2026-11-05 PR #190 follow-up: PPTX Design adds custom cm/mm/in dimensions,
validated as integer EMU coordinates from 1 to 56 inches per axis in both
native API and file bridge. Both axes share one draft/history operation;
canvas resizing is materialized on save/reopen. New-presentation default size
remains unavailable without a blank-deck creation flow. Feature flags stay off;
no deployment or production database acceptance is implied. See
`NATIVE_RIBBON_PLAN.md` for scoped validation and remaining acceptance work.

Custom-size browser acceptance now passes with an explicit Chromium 154
executable and a native-input preflight. The earlier input failure also occurs
in bare HTML on the managed Chromium 140 runtime, so it is not evidence of an
editor defect. See `NATIVE_RIBBON_INPUT_DIAGNOSIS.md` for the controlled
comparison, exact command, independent file/geometry readback and limitations.
Custom sizes can swap orientation without selecting a preset; matching
aspect ratio alone never labels a custom size as a standard preset.


Word 选区链接已接通插入、编辑和移除，沿用原文件锚点、修订与下载链。
仅支持有锚点的可编辑正文/标题/列表段落中的安全外部 URL；新增段落、表格及复杂链接保持明确不可用。
源段落仍有链接时不支持修改正文；须先移除该段全部链接并保存，再在新修订改文字。
实际浏览器三次修订、独立文件关系/样式回读及打包引擎 HTTP 验收见 `NATIVE_WORD_LINK_ACCEPTANCE.md`。
该段验收不代表完整 Word 功能或生产部署通过，开关仍关闭。


Native PPTX Home Paragraph now supports six source line-spacing multipliers and
0–500pt before/after spacing through a nonempty strict paragraph-format patch.
Readback preserves mixed/unset and alternative source units; only explicitly
changed fields are written. The pinned engine is unchanged. Scope, commands,
independent readback, restore/lock tests and packaged HTTP/browser evidence are
in `NATIVE_PPTX_SPACING_ACCEPTANCE.md`. Bullet/indent/direction and complete
source parity remain open; feature flags remain disabled.


PPTX Paragraph continuation (2026-11-06): source bullet/number galleries, custom
Unicode, start value, hanging indent, bullet size/color, relative level and
LTR/RTL are connected through strict fields and the unchanged pinned formatter.
Draft records retain execution order; mixed/inherited values, overflow and
500-record budget are handled explicitly. Picture upload stays visibly disabled;
caret/table/group editing is not covered. See `NATIVE_PPTX_LISTS_ACCEPTANCE.md`
in report_editor. Real PostgreSQL repository plus four-format ASGI/file
acceptance is recorded in `NATIVE_POSTGRES_ACCEPTANCE.md`; production grant
storage and clean application-image acceptance remain open.


Word 表格后端保真阶段（2026-11-06）：新增受限固定列宽表的增删行列
协议，复用 pinned generator 并按源坐标保留幸存格原 XML；原段落属性
丢失问题在独立探针中消除。单表单结构操作、同表文字混用拒绝、新修订
锚点及实际写回检查已接通。前端仍不开放结构编辑；详见 report_editor
中的 `NATIVE_WORD_TABLE_ACCEPTANCE.md`。未修改 vendor 源码或发布开关。


Word 表格前端后续：已接通六个受限增删行列按钮，使用源坐标及原始宽度；
支持草稿刷新恢复和撤销重做，每次结构命令单独撤销。同表后续修改须先
保存并打开新修订。合并/嵌套等复杂表格和多格选区仍禁用，详见
`NATIVE_WORD_TABLE_ACCEPTANCE.md`；这不代表完整 Word 功能区对齐。


2026-11-06 并行补缺：Word 接通受限整段上/下标，baseline 显式覆盖文件样式
继承；Excel 接通六档文本旋转并修复 direct rotation/indent 读取；PPTX 接通
保守源 gate 下的转场应用到全部，额外速度/声音/换片等元数据来源不允许
批量覆盖；PDF 接通全部保留页 +90°，保留删除/重排/表单状态。具体命令、
测试与限制见 `NATIVE_WORD_VERTICAL_ACCEPTANCE.md`、
`NATIVE_XLSX_ROTATION_ACCEPTANCE.md`、`NATIVE_PPTX_TRANSITION_ALL_ACCEPTANCE.md`
和 `NATIVE_PDF_ROTATE_ALL_ACCEPTANCE.md`。

Word 四表新修订流程另外通过真实 PostgreSQL 四类仓储（修订、产物字节、
下载授权、编辑授权/会话）组合验收，见 `NATIVE_WORD_TABLE_SQL_ACCEPTANCE.md`。
这仍不代表生产租户身份、部署网络、完整应用镜像或 Office 桌面通过。
全部功能开关保持关闭。

PPTX 原生单页转场现通过薄适配层保留速度、点击/自动换片、时长、声音、
扩展及音频关系；仅支持已建模普通来源和固定 Morph 兼容结构，其他来源
禁用并拒绝强制提交。批量应用仍保留更严格来源门槛。实际文件、浏览器和
Node22 只读断网验收见 `NATIVE_PPTX_TRANSITION_PRESERVATION_ACCEPTANCE.md`；
不代表播放、Office 桌面或任意兼容结构通过。

PDF 当前页裁切已接通：按显示方向输入四边百分比，支持旋转、重复裁切、
撤销/重做、刷新和重排/删页组合。裁切仅改变可见 CropBox，保留底层文字、
表单和批注，不能用于删除敏感信息；裁切全部保留页也已接通，各页使用自身显示方向和可见范围，整批单步撤销；
批量验收见 `NATIVE_PDF_CROP_ALL_ACCEPTANCE.md`。
下载、独立回读及分层证据见 `NATIVE_PDF_CROP_ACCEPTANCE.md`。

PDF 页面尺寸现支持受限来源的 A3/A4/A5/Letter/Legal，复用固定上游等比缩放
与居中实现，并显示真实写回预览。非默认 UserUnit、签名、导航坐标、印刷
框及未建模批注来源禁用；不与裁切/原位改字混用。尺寸不同的页重置裁切，
尺寸已匹配的页保持原样。验收见 `NATIVE_PDF_PAGE_SIZE_ACCEPTANCE.md`。

PDF Home/Annotate 的四类文字标注现按多行选区写入，复用固定源选区/匹配与
AP 写回；本次草稿可叠加/切换，高亮可自选颜色。已保存标注的移除尚未
接通，明确禁用；复杂或不可读来源保守拒绝，详见
`NATIVE_PDF_SELECTION_MARKUP_ACCEPTANCE.md`。整体仍未全面对齐，当前功能族
差异见 `NATIVE_PDF_ALIGNMENT_STATUS.md`，证书服务前置条件和 Web 设计见
`NATIVE_PDF_SIGNING_WEB_DESIGN.md`。
