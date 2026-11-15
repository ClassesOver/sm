# GenOffice 原版功能区迁移设计

## 目标

让原生 DOCX、XLSX、PPTX、PDF 编辑页采用固定上游 GenOffice 的原版完整功能区界面和相应编辑命令，同时保留 Smart Reporting 的授权、文件身份、草稿、不可变修订、非阻断发布和下载链路。这里的“完整”指上游版本中属于该格式 Ribbon 的全部标签、分组和上下文状态都可见；点击命令必须执行、明确禁用并说明原因，或通过授权的 Web 能力完成，不能留下看似可用的空按钮。

非目标：迁移 Electron 主进程、任意本机文件路径访问、绕过服务端授权直接写文件；改变 Markdown 权威正文；宣称浏览器编辑等同桌面 Microsoft Office。

## 上游基线与现有实现

- 固定上游：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，完整克隆位于 `/home/junge/pros/genoffice-source-full`。
- DOCX：原版 `apps/docs/src/renderer/components/Ribbon.tsx` 约 4,735 行，props 直接连接 Tiptap Editor、格式状态、块/样式/节、注释、目录、页眉页脚、列表、绘图和多种对话框。仓库已移植解析器、编辑器扩展和分页预览子集；当前 `docx-main.tsx` 只有粗体、斜体、下划线、段落增删和分页预览。
- PPTX：原版 `apps/slides/src/renderer/components/Ribbon.tsx` 约 3,453 行，命令依赖选中对象、文字编辑状态、主题、版式、母版、动画、转场、布局和多种插入/格式回调。当前复用 Konva 视图和部分命令，但 AI、插入媒体等部分被隐藏或不适用。
- XLSX：原版 `apps/sheets/src/renderer/ExcelShell.tsx` 自绘 Home、Insert、Page Layout、Formulas、Data、Review、View 和条件 Chart Design 功能区；Univer 负责网格及 preset/plugin 能力，GenOffice App 将 Ribbon handler 连接到 Univer facade、编辑 journal 和 OOXML 操作执行。仓库已有 Univer 0.25.1 网格和少量命令控件，但没有迁入 ExcelShell 或其命令层。
- PDF：原版功能区以内嵌状态和处理器存在于 `apps/pdf/src/renderer/App.tsx`（约万行）。标签含 Home、Annotate、Edit、Page、View 及表单上下文页；与 PDF.js 文档、页面、注释、表单、图像、重排、导入导出、打印和 Electron 文件操作耦合。当前 Web 页面已有 PDF.js、基础页面操作、标注与独立 PDFium/HarfBuzz 写回。

## 方案

按格式将上游 Ribbon 组件和必要的视图依赖裁剪进现有前端，与现有 Web 编辑器共享唯一的文档/草稿状态。Excel 复用原版自绘 ExcelShell，但以现有 Univer facade 和 NativeDraft 代替 GenOffice workbook coordinator/journal。各 Ribbon 接受明确的格式适配器接口；适配器只映射上游命令到现有编辑器操作和受控 API，不把 Electron IPC 引入浏览器 bundle。沿用 GenOffice 许可、来源清单、固定提交和 SHA 清单，记录本地适配差异。

不嵌入 GenOffice 完整桌面 Renderer：该做法会带入重复状态、文件系统 IPC、桌面依赖与第二套修订/保存流程，无法保证 Smart Reporting 下载文件就是页面编辑状态。也不从空白重画近似功能区：会失去用户要求的原版分组、标签、上下文行为和上游本地化资产。

## 命令边界

1. 纯编辑命令直接连接现有编辑器模型，并写入 `NativeDraft`：Word 的文字/段落/表格/节格式；Excel 的单元格、样式、工作表与已支持数据结构操作；PowerPoint 的文字、形状、版式、主题、动画与转场；PDF 的页、标注、表单和已支持文字替换。
2. 文件级和操作系统命令必须提供 Web 等价操作：打开/另存走授权上传、保存新 revision 和签名下载；打印使用浏览器打印或服务端生成的可下载打印版；系统字体改用浏览器可用/文档嵌入字体；窗口切换改用同源页面导航。功能区不得接受本机路径，也不得永久留下伪执行按钮。
3. 需要新增服务端能力的命令先以具体格式、输入、输出文件身份、授权及非阻断失败行为写入阶段规格，再实现后端接口与故障注入。验收/追溯故障不能阻断已生成且身份可读的链接。
4. 证书签名是必须评估并提供 Web 等价操作的桌面能力：采用服务端受控的一次性签名请求，不读主机证书库，不把私钥落到普通工作区，不记录证书口令或签名材料；在密码容器/密钥托管、认证授权、签名可验证性和失陷恢复的威胁设计及测试完成前不得实现或开放。该签名能力的具体托管选择是本设计的显式待决安全项，应先形成单独签名服务规格再施工。不得伪称执行成功。
5. 上游产品本身不具备且当前无后端能力的命令，在对应服务实现前可暂时显示为禁用并给出具体原因；禁用是迁移中间态，不算该格式完整验收。
6. 所有命令报告具体成功/跳过/失败状态，不记录正文、模型提示、grant 或本机路径。

## 分阶段实施

### 0. 上游命令台账与边界

逐格式列出原版可见命令、分组、上下文条件、状态来源、IPC/文件调用、目标 Web 行为及验收。用固定 SHA 清单确定迁移的实际文件闭包；给桌面依赖标注禁用理由。完成后先复核依赖和许可证，再冻结格式接口。

### 1. Word

在现有真实 Tiptap 文档上装载原版完整 Ribbon 和所需对话框/调色板/图标/本地化组件。按 DOM、selection、transaction、parse/generate 和上游 Docs 测试裁剪闭包。将可支持命令接入编辑操作和草稿；文件命令接授权 API；本机文件/打印功能按命令台账禁用或接明确服务端能力。先修复 Markdown CSS 污染 Word canvas 的分页测量，再覆盖长中文、长表、缩放与移动视口。

### 2. PowerPoint

装载原版完整 Slides Ribbon，复用现有 Konva deck、真实选择/编辑状态及现有 PPTX bridge。逐项连接现有 `editSlides` schema；缺少对应后端操作时先实现严格 schema 与真实写回，未接通前不得呈现为可执行。保留原版动画、母版和版式上下文；文件命令使用原生 revision API。

### 3. Excel

移植 GenOffice 原版 ExcelShell 的七个主标签及条件 Chart Design tab，复用原版 ribbon-actions 的命令/状态语义，改接现有 Univer 0.25.1 facade、命令历史和 NativeDraft。补齐兼容性核验后的 FindReplace、Drawing、Table UI preset/plugin；禁止在同一页面并列两套 selection/history/command 状态。公式文本与缓存分别呈现；当前上游未移植的桌面网关能力列为禁用项。

### 上游命令台账摘要

| 格式 | 原版标签/命令闭包 | 当前 Web 对应能力 | 主要缺口 |
| --- | --- | --- | --- |
| DOCX | File、Home（clipboard/font/paragraph/styles/AI）、Insert（page/table/media/link/header/footer/references）、Draw、Design、Layout、References、Review、View；Table Design/Layout、Picture/Shape Format 上下文页。 | Tiptap 画布、分页预览、粗斜下划线、段落插删、简单表格文字与真实 DOCX 保存已接入。 | Home 扩展格式/列表/缩进，表格结构，页眉页脚、引用、批注/修订、绘图及上下文工具多数无完整写回路径；文件菜单需映射 HTTP。 |
| XLSX | Home（font/alignment/number/style/cell）、Insert（table/chart/image/shape/pivot）、Page Layout、Formulas（function/name/audit）、Data（sort/filter/validation/import）、Review（comments/protection）、View；条件 Chart Design。GenOffice 自绘 ExcelShell handler 调 Univer facade、edit journal 和 OOXML operation executor。 | Univer 网格、值/公式/样式、公式栏、工作表管理、合并；engine/bridge 另有行列结构、排序筛选、验证、CF、notes、tables/charts/pivots 等操作。 | ExcelShell 与大部分手工命令 UI 缺失；FindReplace、Drawing、Table UI preset 未注册；保护、透视 UI、页面 UI 和外链功能缺手工接线或有桌面网关边界。 |
| PPTX | Home（text/font/paragraph/clipboard/format brush）、Insert（slides/table/chart/picture/shapes/SmartArt/media/link）、Design（themes/background/size）、Transition、Animation、Slide Show、Review、View；Table/Chart/Picture/Shape context tabs。 | Konva 画布、文字/几何、页序、背景、主题、母版版式、转场和动画部分写回。 | 原版 Ribbon 完全缺失；字体和段落、剪贴板、插入对象、评论、放映/演讲者视图及对齐分布缺操作或 UI。需同步扩展 strict editSlides schema、bridge 和 preview。 |
| PDF | Home、Annotate、Edit、Page、View；Fill Form、Form Design 上下文页。App handler 覆盖选区复制/粘贴、文字/图像、涂改、标记、表单、OCR、裁切、页面组织、显示与导出。 | PDF.js、搜索、标注、页面操作、表单阅读、PDFium/HarfBuzz 内容流文字写回。 | 原版功能区缺失；签名、系统打印、本机文件对话框、OCR bake、裁切/图像替换、表单字段设计等需逐项新增安全 Web/服务端操作。 |

### 命令族明细（由固定上游 props/handler 与本项目 operation schema 对照）

- **DOCX**
  - Home：剪贴板/粘贴选项、字体/字号/字色/高亮、字符格式/上下标/大小写、段落对齐/方向/缩进/行距/边框、项目符号/多级列表、样式库、查找替换、AI。
  - Insert：分页/分节、表格、图片/形状/文本框/公式/链接/书签、批注、页眉页脚/页码、脚注尾注、目录/题注/交叉引用。
  - Draw/Design/Layout：墨迹工具、主题/水印/页面颜色/边框、纸张/页边距/方向/分栏/镜像边距。
  - References/Review/View：引用源/Zotero、引用样式/目录/脚注、拼写/比较/修订/评论、导航/缩放/标尺/阅读视图。
  - 上下文：Table Design/Layout（表格样式/行列/合并/拆分/尺寸/属性）、Picture/Shape Format（裁剪/尺寸/环绕/层级/对齐）。
- **XLSX**
  - Home：剪贴板/格式刷、字体与边框、填充/字色、对齐/换行/合并、数字格式/小数位、条件格式、格式库/单元格。
  - Insert：表格/图片/形状/图表/数据透视表/链接。
  - Page Layout：主题/页边距/方向/纸张/打印区域/分页/背景。
  - Formulas：函数分类/名称管理/定义名称/公式审核。
  - Data：排序/筛选/清除/验证/分列/汇总/透视更新。
  - Review/View：批注/保护/工作簿保护、公式栏/网格线/缩放/冻结与窗口视图。
  - 条件上下文 Chart Design：图表类型、数据、元素、样式和格式。
- **PPTX**
  - Home：剪贴板/格式刷、字体/段落/方向/符号/对齐分布、查找替换、新增页/分节/重置版式。
  - Insert：表格/图表/图片/图标/形状/SmartArt/WordArt/媒体/3D/链接/缩放/公式/页眉页脚/文本框。
  - Design/Transition/Animation：主题/变体/页面尺寸/背景、转场效果/时长/声音、动画效果/方向/触发/顺序/运动路径。
  - Slide Show/Review/View：放映/排练/录制/隐藏页/演讲者备注、评论/校对/翻译、普通/大纲/排序/阅读/母版/标尺/网格/参考线。
  - 上下文：Table、Chart、Picture、Shape、3D 格式；表格样式，图表类型/系列/数据，图片裁剪/替换/透明度/旋转，形状填充/描边/排列/翻转，对齐/平均分布。
  - 现有 Web bridge 对动画只接受 effect/trigger/durationMs/delayMs；GenOffice UI 还提供方向，尚未接通。
- **PDF**
  - Home：撤销/重做、转换导出、打印、文档属性、打开与文件管理。
  - Annotate：文本/笔/高亮/下划线/删除线/便签/图章/签名/评论回复。
  - Edit：改字/插图/涂改/遮盖/裁切/旋转对象；证书签名和保护。
  - Page：旋转/删除/提取/插入/压缩/页码与 Bates 编号/替换/裁切/页面尺寸/反序/拆分/合并。
  - Fill Form/Form Design：交互表单填值、静态勾叉、表单字段创建/检测/排序/删除。
  - View：缩放、页适配、连续/单页/双页布局、缩略图/目录/层、搜索、显示标注/表单。

上面保留了上游 UI 命令族粒度。移植某一 tab 前，实施 brief 必须从相应 handler 和 schema 继续列出该 tab 的每个 action id、字段和确认状态；任何未知 callback 不得显示为可执行。

### 4. PDF

按上游 PDF 功能区分离 tabs/controls 和命令映射，不复制完整 10k 行 Electron App。共享当前 PDF.js 文档、选区、注释、表单及页面操作状态；写回经现有 PDF bridge。打印、证书签名、操作系统对话框等拆成显式禁用项或独立后端设计，不在浏览器伪执行。

### 5. 共用验证与发布

每个格式逐一运行上游 Ribbon 测试中迁入部分的对应测试和本项目操作测试。浏览器测试覆盖每个启用的 Ribbon 命令至少一个成功写回及失败反馈；验证撤销/重做、草稿恢复、保存锁定、原件不变、修订创建、实际签发下载、重新打开回读和授权边界。对新增签发步骤登记 `test_http_publication_lineage.py` 故障注入，对新增签发函数登记静态守卫。以生产构建检查按格式懒加载与 chunk budget；最终镜像离线运行。使用一组系统报告产物和一组上传样本分别验收，不能互相替代。

## 关键风险与控制

- 上游 Ribbon 高度依赖桌面 Renderer 状态：先冻结命令台账和依赖闭包，再移植 UI，防止做出空壳。
- 上下文菜单、快捷键和 Ribbon 可能重复命令：同一格式只保留一个命令/selection 状态源。
- DOCX 页眉页脚、引用、批注、修订、复杂表格及 PPTX 图表对象不一定在现有写回 schema 中；不支持就显示保留/只读状态。
- PDF 数字签名不能以重写 PDF 内容流实现；涉及证书的入口在独立安全设计和签名方案验收前必须禁用。
- “全部可执行命令”范围跨四种 Office 大型应用，按格式独立验收和发布；一个格式未完成不阻塞已验收格式，但不能把阶段结果描述为四格式完整迁移。

## 验收完成条件

- 四格式均使用对应固定上游 Ribbon 的标签、分组、图标、本地化和上下文状态。
- 上游命令台账中每个动作明确标记为可执行、服务端实现或有原因的禁用；不存在未接线的假按钮。
- 所有可执行编辑均更新唯一草稿状态并经当前格式引擎真实写回；保存、导出、下载和新 revision 重开通过独立读取验证。
- 单格式功能关闭、渲染/验收失败和回滚不影响旧下载；桌面专属命令不会越过授权边界。
- 每个格式的定向测试、浏览器测试、构建预算和最终断网镜像验收通过。桌面 Microsoft Office 验收另行标记，不能由浏览器结果代替。
