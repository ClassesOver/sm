# PDF 与固定 GenOffice 的对齐状态

2026-11-10；来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
整体状态：**未完成，不可将当前 PR 视作 PDF 全功能对齐或上线验收通过**。

这是功能族映射，不是穷尽所有子组件的命令数量统计。对固定 App.tsx
（Git blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`）做 TypeScript AST
回调清点得到206个带 onClick/onChange/onSubmit 的 JSX 节点，其中63个位于
主 Ribbon 源码区域；这些数包含对话框、重复布局及动态组件，不能充当
已完成比例的分母。原始记录在证据包的 `source-census.json`，委托子组件
仍须逐个核对。禁用按钮和“文件能打开”不计作功能已完成。

| 来源功能族 | 当前原生状态 | 明确剩余差异 |
| --- | --- | --- |
| 文件/保存/另存 | 导入、来源身份、不可变修订、幂等保存、下载与重开有分层证据 | 桌面路径/文件监听/全部入口及部署宿主等价性未完成 |
| Home/Annotate 四类文字标注 | 高亮、下划线、波浪线、删除线按多行文字选区写入；可切换草稿及安全来源的已保存标注 | 关联回复/弹窗/结构、签名及复杂源标注只读，尚非完整源切换语义 |
| 标注颜色 | 固定源默认色，只有高亮接受自定义颜色；下载验证 RGB | 完整源颜色弹层/上下文工具与现有批注编辑未全部对齐 |
| 文字编辑 | 来源身份绑定的有限文字替换及真实预览、字体/溢出跳过回执 | 插入静态文字、完整字体/对象/游标语义及复杂源对象未完成 |
| 便签 | 新增/未保存便签编辑删除、创建时间绑定，安全既有便签及标准平铺叶子回复编辑删除，历史/实际预览/下载重开 | 旧草稿未知创建时间不补造；全文侧栏与定位已接通，安全既有和未保存根线程可追加平铺回复并管理草稿身份/编辑删除联动；含回复根便签正文/整线程删除、嵌套/弹窗/复杂/富文本线程仍未接通 |
| 绘图/测量 | 手绘、标定测量、矩形、椭圆、箭头、多边形、插入符号及固定源颜色/线宽已接；待保存记录支持精确列表选择、平移/删除，七类geometry支持透明stroke画布命中/拖动，image另支持数值等比缩放/四角控制柄（`NATIVE_PDF_SHAPE_CANVAS_ACCEPTANCE.md`）；安全已保存六类绘图支持身份绑定逻辑删除 | 完整上下文/快捷键、measure标签与caret的源UI/实际AP视觉差异仍开放；复杂已保存来源只读。源普通线宽固定，saved移动/改样式不是已确认缺失源功能；逻辑删除不等于安全擦除 |
| 安全涂黑 | 涂黑/清除涂黑/应用涂黑已接通：标记区域为可撤销草稿，保存新修订时由固定引擎 `redaction.ts`（PDFium ApplyRedaction）永久移除区域内文字/图像/路径并黑块覆盖，来源修订不变；pypdf 独立回读不可提取（`NATIVE_PDF_REDACTION_ACCEPTANCE.md`） | 涂黑与页面尺寸同批；空白草稿页；跨页共享图像/表单控件及关联批注、共享外观或无法证明安全的引用图由引擎拒绝（fail-closed） |
| 页面旋转/删除/顺序 | 来源页身份、左右/全部旋转、删除、反序/移动、历史与回读通过 | 全部页选区/范围组合和相邻上下文仍有差异 |
| 裁切 | 当前/全部保留页按显示方向百分比、真实下载通过 | 源图像拖拽控制柄未接通；只是隐藏内容 |
| 页面尺寸 | 五个固定预设、受限来源、实际输出预览与下载通过 | 自定义/复杂来源及裁切/改字同批混用未接通 |
| 提取/插入/替换 | 插入空白页已接通：当前页之后、按当前页显示尺寸，可旋转/移动/反序/删除/撤销，草稿恢复、实际预览、保存下载、pypdf 独立回读与重开通过（`NATIVE_PDF_INSERT_BLANK_ACCEPTANCE.md`） | 空白页保存前不接受标注/裁切/改字；提取页面、插入外部 PDF、替换页面仍需新文档/多来源身份及授权交付 |
| 页面合并/拆分 | 合并页面（N 合 1，2–16，横/纵顺序，分隔线）与拆分页面（2/4/9）已接通：固定引擎 `mergePagesBytes`/`splitPagesBytes`，单独保存为新修订并先显示服务端实际预览；输出日期沿用来源，确认摘要可复现；N 合 1 保留可见批注/表单外观为静态内容，按 CropBox/旋转/UserUnit 排版；含表单的拆分页暂禁用（`NATIVE_PDF_PAGE_LAYOUT_ACCEPTANCE.md`） | 拆分 PDF/合并 PDF/提取页面/插入 PDF/替换页面（多产物登记下载、外部来源身份）；表单拆分页的字段树/Widget 重映射 |
| 缩略图/目录/单双页/跳页/夜间模式 | 已接入并有浏览器证据；阅读位置/缩放恢复及侧栏尺寸持久化已接通 | 全文便签侧栏已接通；比较和完整快捷键/布局未穷尽 |
| 附件 | 查看/下载、安全平坦名称树新增/身份绑定移除、草稿历史、实际预览及下载重开通过 | 分层/共享/关联附件、受保护来源、超出预算及原位改字混用未开放；移除目录不能擦除内容 |
| 缩放/适合页面 | 源阶梯/滑块/滚轮/锚点、全保留页独立单双页行适配与持续自适应已接通 | 原生批注卡片位于页下，桌面侧边批注边距及完整宿主布局仍不同；10–800%限制保留 |
| 搜索 | 固定源逐处索引/计数、跨片段、大小写/全词、循环导航、选中框与预览身份映射 | OCR/自动OCR、浮动搜索栏、复杂字形精确几何及全部快捷键未完成 |
| 打印 | 已保存 PDF 的浏览器整份打印 | 源系统打印机、范围/双面等功能需 Web/宿主等价约定 |
| 填写表单 | 受限 text/checkbox/radio/choice 及字段导航通过 | 静态表单填写、复杂字段、签名字段与完整行为未对齐 |
| Form Design | 未接通 | 新建/检测/排列/修改/删除字段及严格 widget 身份 |
| 转换导出 | 当前格式下载 | PDF到Word/Excel/PPT/Markdown及完整转换服务未接通 |
| 图片/链接/水印 | 插入图像已接通（PNG/JPEG → 浏览器转 PNG ≤2000px，拖出位置，写为 Stamp 批注）；水印与页眉页脚/页码已接通（固定源 StampDialog + 原样复用 stamps.ts 渲染，覆盖全部页面、页码按当前页序；设置后锁定页面结构直至保存或撤销），编辑链接已接通：拖出区域后填写 http/https/mailto 地址或页码（二选一，与固定源 LinkDialog 一致；不安全协议拒绝），页码按来源页绑定、目标页删除时拒绝，保存后回读 Link 批注（`NATIVE_PDF_DRAW_ACCEPTANCE.md`） | 编辑来源中已有图像；已保存图像/链接/水印的编辑删除（待保存图像已可精确移动、等比缩放和删除，链接可删除）；页眉页脚字号与颜色调节（固定源对话框亦未提供） |
| 保护/加密与签名 | 可视签名已接通：固定源 SignatureDialog 的手写（矢量笔迹按签名板比例经视口逆变换放置）与键入（固定源四种字体、紧裁栅格化为图像）（`NATIVE_PDF_DRAW_ACCEPTANCE.md`） | 签名字段绑定、已保存签名复用；密码/权限、既有签名验证和证书签名未完成（证书签名依赖外部服务） |
| AI 入口/审阅/批注处理 | 源三个快捷入口与审阅未接通 | 本会话没有固定源服务身份/等价任务契约验收；不能标为完成 |

## 当前可复核的交付

- `NATIVE_PDF_ROTATE_ALL_ACCEPTANCE.md`
- `NATIVE_PDF_INSERT_BLANK_ACCEPTANCE.md`
- `NATIVE_PDF_DRAW_ACCEPTANCE.md`（含编辑链接、水印与页眉页脚）
- `NATIVE_PDF_CROP_ACCEPTANCE.md` / `NATIVE_PDF_CROP_ALL_ACCEPTANCE.md`
- `NATIVE_PDF_PAGE_SIZE_ACCEPTANCE.md`
- `NATIVE_PDF_SELECTION_MARKUP_ACCEPTANCE.md`
- `NATIVE_PDF_VIEW_ACCEPTANCE.md`
- `NATIVE_PDF_MARKUP_REMOVAL_ACCEPTANCE.md`
- `NATIVE_PDF_SEARCH_ACCEPTANCE.md`
- `NATIVE_PDF_SAVED_NOTES_ACCEPTANCE.md`
- `NATIVE_PDF_PENDING_NOTES_ACCEPTANCE.md`
- `NATIVE_PDF_NOTE_PREVIEW_ACCEPTANCE.md`
- `NATIVE_PDF_COMMENTS_ACCEPTANCE.md` / `NATIVE_PDF_REPLIES_ACCEPTANCE.md` / `NATIVE_PDF_LOCAL_REPLIES_ACCEPTANCE.md` / `NATIVE_PDF_SAVED_REPLY_EDITS_ACCEPTANCE.md`
- `NATIVE_PDF_ATTACHMENTS_ACCEPTANCE.md` / `NATIVE_PDF_ATTACHMENT_WRITE_ACCEPTANCE.md`
- `NATIVE_PDF_READING_ACCEPTANCE.md`
- `NATIVE_PDF_FIT_ACCEPTANCE.md`
- `NATIVE_PDF_SIDEBAR_ACCEPTANCE.md`

每项分别写出原始材料、固定源行为、浏览器/引擎/服务/SQL/容器的证据
边界、失败迭代及实际下载身份。不把重复运行累计为新检查，也不以
placeholder/stub/disabled control 证明完成。

## 不能凭实现推定通过的外部依赖

固定 `CertSignDialog.tsx`（blob `d1340a75490336d36d00c91122efc91a6a969ded`）
直接依赖系统/文件证书库、inspectCertificate、signWithCertificate 和
releaseCertificate。当前 Native API 没有这些服务，也未提供已授权后端
签名服务或非敏感证书别名。所选管理实例的最新配置观测为 secret bindings、
runtime variables、outbound identities 列表均为空；这不代表企业不存在
签名服务，也不表示进程中没有其他用途的凭据。本次没有扫描密钥文件。
元数据回执保留在 `dependency-readiness.json`。

因此**完整对齐目标中的真实证书签名验收目前被外部服务/证书配置阻塞**。
已向用户请求服务名/接口文档和非敏感证书标识，未请求私钥或密码。
`NATIVE_PDF_SIGNING_WEB_DESIGN.md` 给出具体边界和待接入契约；它是设计提案，
不是已实现的签名功能或安全验收证书。其他表格中列出的普通实现缺口仍然
是未完成的开发工作，不能归因于这个外部阻塞。

完整应用镜像、真实生产身份/权限/网络、桌面视觉兼容仍未验收；既有8GB/vfs
完整构建 ENOSPC 缺口不由 mounted-runtime 结果替代。功能开关保持关闭。
