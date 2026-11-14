# PPTX 文件菜单逐命令盘点

2026-11-13。对照固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/slides/src/renderer/components/Ribbon.tsx` 文件菜单八个入口，追到 `file-actions.ts`、`App.tsx` 和 `main/slides-main.ts`；本地追到前端回调及原生传输。此表只穷尽该八项入口，不等于整个 PPTX 或桌面主菜单已经穷尽。

本地路径以 `smart_reporting/report_editor/` 为根。打开上传文件与保存修订是受控工作流，不将桌面 IPC 名称对应或可见按钮当作功能等价证据。

| 固定源入口 | 源真实语义 | 本地入口／实现 | 判断与缺口 |
| --- | --- | --- | --- |
| `onOpen` | 主进程文件选择，打开另一份演示文稿；`CmdOrCtrl+O`。 | 外层 `/reports/v1/native/import` 注册已授权工作区文件，原生编辑器绑定 document/revision/source SHA；PPTX 功能区文件页没有打开命令。 | 文件导入存在，但编辑器内打开／切换另一份演示文稿入口和快捷键仍缺。不能把 HTTP import 测试当作菜单闭环。 |
| `onSave` | `file-actions.ts::save` 串行保存，flush 活动编辑／备注，保存后重映射对象；`CmdOrCtrl+S`。 | `frontend/src/slides-native-ribbon.ts::saveRevision` → `slides-main.ts::save` → `native-office-view.ts::createNativeOfficeTransport.save` → `api.save`；创建新修订，返回下载及重新打开链接。 | 受控新修订保存已接线；与桌面原地覆盖及对象 remap 的生命周期不同。续批已将 Ctrl/Cmd+S 接入同一保存按钮，先提交活动输入，保留 IME/dialog/锁定/重复按键守卫；快捷键 6 项及相邻打印键 3 项定向通过。真实保存下载重开另按[续批验收](NATIVE_REVIEW_IMAGES_SCATTER_ACCEPTANCE_20261113.md)登记，不能用单测代替文件闭环。 |
| `onSaveAs` | 与保存共用队列，选择路径及文件名，成功后采用新路径。 | `saveAs` 控件明确禁用。 | 缺少另存文件／命名的授权 Web 等价流程，不能用“创建修订”关闭另存为缺口。 |
| `onNameWithAi` | flush 当前编辑，模型建议名称，交给另存为对话框；用户取消不改文件。 | PPTX 文件菜单没有对应入口；现有阅读／编辑 AI 不等于命名。 | 缺少。未来需复用 Agno、当前快照和既有授权文件链，不能独立提供模型任意路径。 |
| `onExportPdf` | 排除隐藏页，优先矢量 SVG，不能矢量化的页面退为 2x PNG；附加对象／文本链接，字体 CSS，主进程生成 PDF。链接读取失败退为无链接 PDF。 | `exportPdf` 控件明确禁用。通用 native `/api/export` 的存在不证明 PPTX 格式已接通此导出。 | 缺少。浏览器打印／print-to-PDF 是打印验证，不能替代该矢量、链接和字体契约。 |
| `onPrint` | `PrintDialog.tsx` 全部／当前／自定义、隐藏页、整页／2／3／6 张讲义／备注、方向／边框、系统打印；主菜单 `CmdOrCtrl+P`。 | `slides-main.ts::openPrint` → 相同草稿的 render-tree／preview → `slides-print-render.tsx` → `slides-print-dialog.ts`；复用原字节 `shared/print-html.ts`。 | 浏览器等价入口已实现。新增快捷键进入同一链；活动输入先提交再冻结。桌面设备队列／静默打印和真实纸张输出未验证；详见专项验收。 |
| `onExportImages` | 排除隐藏页，离屏 2x PNG，用户选择目录，每页写出一个文件。 | `exportImages` 控件明确禁用；打印 PNG 仅为临时预览。 | 缺少 PNG 正式导出、命名／文件身份及下载链。不能以打印临时 data URL 代替。 |
| `onExportImagesJpg` | 同 PNG，格式为 JPEG。 | 无独立 JPEG 文件菜单入口／导出链。 | 缺少。应与 PNG 保持相同页筛选与逐页输出契约。 |

## 相邻但不混计的入口

固定源还在主菜单提供打开新窗口、关闭／退出和最近项目等扩展，功能区有自动保存开关及快速保存。它们没有被混入以上八项，也不能因为浏览器有标签页或 localStorage 草稿就判为等价完成。自动保存写出文件、崩溃恢复、并发窗口会话与新修订工作流应单列验收。

文件菜单中文和图标也不应跳过：本地存在通用“图片导出”单入口，源为独立 PNG／JPG 两项；缺少的 AI 命名和打开入口没有可对照的本地图标。已接通打印的测试不覆盖缺失入口的中文或图标。

## 本次实际证据及限制

- [打印验收与冻结浏览器证据](NATIVE_PPTX_PRINT_ACCEPTANCE_20261113.md)；历史冻结构建与后续源码／新冻结构建分别记录。
- [四格式本批增量](NATIVE_PARITY_REVIEW_INCREMENT_20261113.md)。完整对齐目标仍 active。
- 此表依据真实源分支和本地调用链人工盘点；没有给未执行的菜单动作伪造通过结论。
- 后续若接入导出，应复用当前文件身份登记／修订／独立回读及非阻断下载链；验收失败返回具体 issues 并保留已核验产物，不以门禁失败终止签发。
