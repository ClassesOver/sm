# 四格式下一批桌面组件族验收（2026-11-13）

本批承接既有样式/媒体/单元格格式/静态填表，不替代全量功能差距索引。固定源GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c、Apache-2.0；仅迁移完整组件族并适配现有草稿和原生文件修改链路。

| 格式 | 本批能力 | 专项说明 |
|---|---|---|
| Word | 完整页面边框：设置、线型、艺术、四边、距离、节/首页范围 | NATIVE_WORD_PAGE_BORDERS_ACCEPTANCE_20261113.md |
| XLSX | 完整选择性粘贴：12类型、5运算、选项/链接、快捷键和原生菜单 | NATIVE_XLSX_PASTE_SPECIAL_ACCEPTANCE_20261113.md |
| PDF | 原图可视裁剪、八手柄/键盘、去背景容差与透明预览 | NATIVE_PDF_IMAGE_DIALOGS_ACCEPTANCE_20261113.md |
| PPTX | 完整背景窗格：纯色/渐变/图片、四方向、独立背景图形、应用全部/重置 | NATIVE_PPTX_BACKGROUND_ACCEPTANCE_20261113.md |

## 专家会补做的工作与本批落地

用户可见样式之外，验证键盘和输入法、焦点返回、小高度真实可点、取消不写入、只读/保护、异步目标变化、UndoRedo与草稿恢复。保存必须下载真实文件，用独立读取器核验目标变化及其它正文/图像/媒体保留，然后明确打开新修订。原图像素单独受控读取，避免把页面截图当图像。XLSX扩容跟随官方命令并检查用户异步选区，PDF取消按钮Enter与IME误触经独立审查RED/GREEN修复；PPTX小屏窗格与共享颜色Portal Escape已修复。

不把语义验收失败转换为签发阻断；下载响应保留validation.ok=false与具体原因。功能验收使用显式授权/修订fixture，运行真实原生writer、预览和下载，不代表生产数据库/桌面Office验收。

## 不可变构建身份

证据根：/home/junge/codex-evidence/smart_reporting/office-next-source-families-20261113。

source-v1保留首次类型错误；source-v2含最小typing修复与验收runner更新。最终4394源文件，manifest SHA256 fc493bcb2305db74aac56653de4fc5ffc1fd7ba4f41fad5ecabdb705fd05b872。TypeScript、Vite45.32s、原有资源预算均exit0；预算未提高。static717文件，构建manifest SHA256 7949df1457ac33345c20d4ba447bc26d0a922881f8812040838bf82d6f00e0a8，frozen-build-identity.json记录全部文件摘要。未覆盖共享static/dist。

冻结时Word既有runtime有一输入不匹配，保留差异后重建隔离runtime，SHA ea442fdc0903b6be7b9230e37f8adfb145c28eb9174fbaa12e2a9ed0256e01bc；256输入匹配。PDF复用runtime255工作区输入匹配；PPTX279、XLSX254匹配，无需重复构建。真实Python wrappers另存backend-wrapper-identities.json及物理副本。

## 最终结果

- Word：16项检查、161资源、0浏览器错误、1次save；37,587bytes，SHA f5e94ca1796a419263d85410eb24c94e46cc92e82df13c5da0a28c26059d3df9。两个setSectionLayout；除pgBorders外独立XML/其它ZIP parts保持；新修订2重开通过。
- XLSX：283资源、0浏览器/控制台错误、1次save，r4→r5；下载SHA 51d3b926650e5aef27f7f5a72eb9aafd32b8e602d6952a5c8ad95557b739f480；openpyxl独立读取数值/转置/链接/格式，只有sheet1和styles变化；明确新修订5复开/api/file与实际下载一致。
- PDF：裁剪/去背景各194资源、0错误、各1次save/实际download/新修订2重开。裁剪4,077bytes SHA6f0bab2173c6e2e70f7872a862a20e42a51d85f8b43b3985ac87b7ab675dbca8；去背景5,732bytes SHAe0a2fe6a627b19c46b0510381a212c89527966dd557c037c3ce68d413bd72d90。pymupdf/pypdf确认正文/相邻图像保持，裁剪范围/PNG尺寸正确，去背景角alpha0/中心alpha255。
- PPTX：冻结完整链4组交互、151资源、0错误、1次save/1次download；50,343bytes SHA256 2a049615b34bb23d29bbca6c77984df91c02eeb475434ccdd94af276a3c4110a。ZIP/lxml与python-pptx确认只改slide1/2/3.xml，原媒体/正文/讲稿保持；独立下载文件reopen actualRenderTree=true，无额外save/download。

## 仍有缺口

本批不是全量四格式功能完成。既有以表格结尾Word会补尾段的行为未修改；PPTX自定义放映的OOXML持久化仍缺。历史功能索引为分层、非穷尽清单。未经本批独立实写验收的其它组件继续保持原状态，不声称完整PC Office等价。

root最终独立核对五条实写链（PDF裁剪/去背景各一条）的实际下载摘要及161/283/194/194/151资源摘要，全部匹配；root-independent-checks.json为ok:true。再次复核4394冻结源无漂移与最终static manifest不变。工作区冻结后仅验收runner继续记录身份，产品源无额外变更。
