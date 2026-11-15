# XLSX 固定源 PrintDialog 可执行能力对齐

日期：2026-11-13。固定源 `/home/junge/pros/genoffice-source-full`，提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本专项在既有打印预览、page setup 日志、writer、NativeDraft 与下载链上补齐源对话框可执行字段；不改图表或新增服务端导出体系。

## 源映射与宿主边界

| 固定源能力 | 本地实现与状态 |
| --- | --- |
| `PrintDialog.tsx:44–110`：方向、九种纸张、自定义文件纸张、三种边距与文件自定义、六种缩放状态 | `workbook-print-preview.ts` 初始化真实重放后模型，按源区分 none/sheet/columns/rows/fit-file/custom，保留文件自定义边距和非标准 fit 计数；百分比 10–400，纸张包括 B4/B5 |
| `PrintDialog.tsx:119–180`：范围、重建、过期结果丢弃 | active/workbook/selection，单单元格选区禁用 selection，隐藏表不打印；generation/关闭/dispose 拒绝迟到结果，设置后 120ms 重建，失败清空旧预览并禁止输出 |
| `PrintDialog.tsx:185–255`：当前页、fit/actual 与尺寸变化 | 页导航、实际大小/适合页面、ResizeObserver；预览不进入 Tab 顺序，区域可聚焦；沙箱 iframe 不执行脚本 |
| `PrintDialog.tsx:257–449`：持久设置、页码范围、网格线/行列标 | 单字段即时写入既有 pageSetupJournal，经原 applyPageSetups 保存；范围状态只影响输出，按 job-wide 1-based 包含边界裁切 HTML 页面，不修改页码正文或源 job |
| `PrintDialog.tsx:519–554`：页设置返回、取消、输出 busy/error | 页设置打开既有页眉页脚对话框；确认/取消/Escape 统一 onClose 后自动刷新。打印前重新捕获；取消只关闭预览，已明确的设置更改按源保留为草稿 |
| `page-layout-actions.ts:450–548`：当前表 overrides、工作簿多纸张、打印/导出 | 仅 active sheet 接受对话框 overrides，其他可见表保持各自纸张；复用既有浏览器系统打印。PDF 入口明确需要在系统对话框选择“另存为 PDF”，不声称应用已直接导出 PDF |
| `page-layout-actions.ts:595–612` / `formula-settle.ts`：打印前稳定公式 | `capture` 用当前 Univer 原生 `onCalculationResultApplied(30000)` 等待结果应用，再捕获快照；之后仍复检 book/sheet/source、选区、epoch 和编辑代次 |
| `desktopApi.listPrinters/printWorkbook/exportPdf`：系统默认/命名设备、静默打印、copies/collate、直接 PDF 文件 | 浏览器宿主缺少这些桌面 API，继续明确缺口。打印机、份数/逐份由系统对话框管理；未造设备、未伪造发送/导出成功，也不把完整硬件族标记完成 |

身份安全：打开时固定 workbook core、worksheet core/ID/名称、原始 bytes 引用与路径；每次捕获和写入复检。异步读取后核对 epoch、编辑代次和选区几何。只读/保护表可预览打印但禁用页面设置，写入时仍独立核查编辑态与保护。替换身份不能把旧对话框设置写到新工作簿，人工草稿保留。

## 当前物理证据

证据目录 `/dev/shm/office-workbook-print-dialog-20261113`。旧运行环境的 RED 日志已不可读，不将旧摘要当作当前物理证据；源码与测试实际保留。

- `focused-current.log`：四文件 25 passed / 2 failed。独立 dialog/preview/HF 通过；main 的首次打印捕获在人工输入后因原生公式异步回写过期。
- `host-diagnostic.log`：定位失败原因为“工作簿或选区已变化，请重新预览或打印。”，不是绕过身份检查。
- `host-settle-green.log`：接入原生结果应用等待后，新 main 三例通过。
- `focused-final.log`：最终五文件 **29 passed**（dialog 6、preview 6、HF 8、main print-scale 7、routing 2）；包含既有缩放和路由回归，测试次数不可累加。日志中只有已有 Univer `getSnapshot` 弃用提示，未重复完整 suite。
- `hidden-red.log`：真实 HTTP 发现在 workbook 范围打印了隐藏表后，新增真实 engine → Univer → HTML 两例均失败，分别定位 `SheetModel.hidden` 与 snapshot `hidden` 丢失。
- `hidden-green.log`：只补 reader 与 Univer projection 的隐藏状态传递后，两文件 **8 passed**（新增 hidden 2、相邻 preview 6）。`hidden` / `veryHidden` 均不进入全书打印；可见表仍保持旧模型缺省。此处相邻六例与上项重复，不累加成总数。
- `margins-red.log` / `margins-green.log`：第三轮 HTTP 的草稿恢复发现预设边距被误分类为 custom，新增 main 定向一例先失败再通过（其余七例未重复）；同用例验证已保存文件和 NativeDraft 恢复两条分支。修复只将打印 capture 的边距 fallback 改用已存在的 `matchMarginPreset`，不更改实际边距或 header/footer。
- own 路径 `git diff --check`、smoke `node --check`、verifier `py_compile` 均通过。全局类型检查与 Vite/预算由 root 统一冻结执行，本专项未自行重建共享 static/dist。

产品冻结身份：

| 文件 | SHA-256 |
| --- | --- |
| `workbook-main.ts`（含并发任务既有改动，打印只局部写 host） | `42036ea651cd8cc70daca583b140d7e4ec7127f14367c2899cde095c0abee04c` |
| `workbook-print-preview.ts` | `2fe919cffa287c2117db2a13987bafd5445d7f8612b94c6cb62825343907e650` |
| `workbook-print-preview.css` | `86e9bafee0ff0e165266027b3c0a3077cbf5b80a8ee8a02eea040f77c4200e3c` |
| `workbook-header-footer-editor.ts` | `e519090cd7bb029d98fec6adb25cc292b4ae36fae9e0ccb88368fd0c70ae252e` |

main 打印局部写前身份 `e0cb3942d959fce53cc82732f29c55a209dcb372c65daf1c16cf4cc68a6c3861`。未覆盖并发图表区域。

隐藏状态窄修相对 v2 物理基线只有 reader 三个新增行（含注释）、projection 两个新增行；后续 v3 只叠加以下精确文件，不纳入工作区其他并发产品改动：

| 文件 | SHA-256 |
| --- | --- |
| `workbook_engine/packages/xlsx-engine/src/workbook-read.ts` | `2bb095fe6fbdfbfe2079f4d20d3fe9b7d61297b73621ac12459ccdc703338778` |
| `frontend/src/workbook-vendor/core/univer-data.ts` | `a15e814bda289d14fa68c5f50ec204c5d554266d566ffc75fe186a276f93b4ce` |
| `frontend/src/workbook-print-hidden-source.test.ts` | `1c7c1a67b4132ee8e5289f60f5d38fdd07beb8d0850cc6f05ef24cdea68ffdfa` |

## 真实 HTTP 与 PDF 回读

脚本 `frontend/smoke/workbook-print-dialog-smoke.mjs`，独立夹具与回读 `frontend/smoke/workbook-print-dialog-verify.py`。复用既有 `workbook-ai-charts-server.py --source`，不新建服务端输出路径。

`browser-frozen-01` 在原生单单元格禁用断言处停止；隔离诊断确认实际 option 的 `disabled` 为 true，脚本改为等待原生 DOM 属性，未为此改产品。`browser-frozen-02/initial-selection.json` 已确认禁用，且经过关闭/Escape、选区裁切后，在 workbook 范围发现隐藏表确实进入打印，停止并触发上述 RED/GREEN 窄修。两轮均在保存前停止，未签发修订或 PDF，不作为完整链通过证据。

`browser-frozen-03` 使用 v3 manifest `490aa9f5b482fe532ebd24d01b1479fe7b85f60a5dbaab6f7863486c79701444`。已完成隐藏表排除、设置遍历、页眉返回刷新、桌面与 390px 截图、指定第 2–3 页真实 spool HTML 与两页 PDF；在草稿恢复的边距分类处停止，仍为零保存。PDF 已由 `pdftoppm` 渲染两页并目视：表格、重复标题、行列号清晰，原 even 页眉与更新后的 odd 页眉分别保留，无隐藏表内容。后续从该轮真实草稿 envelope、原始 fixture 和实际 PDF 续验，不重复整轮已完成操作；证据明确保留该轮失败与续验来源。

`browser-frozen-04` 使用 v4 静态与 v3 原字节复用工作簿桥，从 03 的实际草稿继续。草稿恢复（B5、70%、narrow、gridlines、Updated 页眉）、390px 取消可达、一次真实保存、授权下载及修订 5 重开均完成；独立 verifier 已通过。随后脚本末尾的 pageerror 空数组断言失败：续验 harness 的 `addInitScript` 同时在沙箱子 iframe 访问 localStorage，造成 11 条安全异常。没有放开产品 sandbox；harness 已加 `window.top !== window` 守卫，并将未来保存响应、下载、独立回读和资源身份检查点前置持久化。**04 整体脚本仍为失败，不记为首次或整轮通过。**

04 API 响应变量未在失败前单独写盘，不伪造恢复该响应。`browser-frozen-04/artifact-recovery-evidence.json` 以原 `r5/saved.json`、实际下载字节、原 HTTP 记录和后续独立回读证明：parent 4 → revision 5，恰好一条保存 POST 200、一条授权 `/native/artifacts/<grant>/xlsx` GET 200、修订 5 文件 GET 200，下载内容与登记身份一致。该恢复证据显式记录 `originalRunOk: false` 与 `validationResponseNotPersisted: true`。

`browser-frozen-05-readonly/evidence.json` **exit 0**：将 04 已下载文件经真实授权 HTTP 重新打开，零保存、零 planner 调用；重新独立读取原 XLSX/PDF。`browser-frozen-06-readonly-mobile/evidence.json` **exit 0**：按追加的窄屏要求，分别真实滚动 PDF、打印、取消按钮，检查四边位于 390×844 viewport 内并截图，未再次打印或签发。最终 PDF/打印按钮均为 y=722.109375、height=36，可见且可达。两轮没有草稿注入、没有沙箱异常，pageerror、console error、HTTP error、资源身份错误均为空。173 个实际加载 JS/CSS 与 v4 物理文件 SHA-256 一致。

独立 openpyxl/lxml/ZIP 回读确认：D95 人工值与 bold、F1 公式、原 A1:D80 数据、print area/title、30/60 手动分页、first/even 页眉、fit 2×3、copies=2 保留；B5 横向、scale=70、fit=false、narrow 六边距、gridlines/headings、Updated odd 页眉正确。除 sheet1/styles 外其余九个包 part 字节不变。pypdf 确认 PDF 为两页、每页 729.12×516 pt，含第 31–80 行及重复标题，无 hidden 内容；两页 PNG 和桌面/窄屏/保存后重开截图已实际目视。

结论范围：功能证据由保留失败边界的 03 打印阶段、04 唯一保存/下载/修订重开、05–06 零保存独立回读组成；不声称单次全绿脚本。未重复完整 suite，未重复签发。业务验收不标通过；既有 `native_source_review_pending` 非阻断策略保持，04 未持久化的 validation 响应不冒充已读取。桌面硬件 API 缺口仍按上表明确保留。

## 最终物理身份与执行边界

| 项目 | SHA-256 / 状态 |
| --- | --- |
| v4 manifest | `f9e161a924c55a6c9c0e5dc3bca80f5d9607b62e2c0552663bd39f830fd211be` |
| v4 打印主文件（v3 精确单行修复，非当前 live whole main） | `17501a4891713d1f9b10e6cbb7526e8465c0e1cbedfc6c1262be27a3028dfc97` |
| v4 workbook bridge | `e55d981bafede6384914e48a37839f079b97282e5f0ed09d9db5230aa5816662` |
| 原 fixture/source | `20f28f5f8722a231ea94992a602dca4f581a38f0ef871ef3a8bf9da70464b098` |
| 实际下载 XLSX（8218 bytes） | `23c6012149da45e825f501853eca0669504e1fd5094a6acdb9d1e41e1ef393d1` |
| 实际两页 spool PDF | `5418f61501d071f6a701451cc1095dd48c432a5d00c14755784478a879db632d` |
| live `reporting/delivery/office_engine.py` | `46ebe5b4daa68ac076deaee474f491eb505dbbdeadbda62dca72b57901b1d236` |
| live `report_editor/native_office.py` | `79eb0bbe143a4e26db7648b46964f6e7f803ab81a96bd3833bc51e20edea001a` |
| live `report_editor/native.py` | `679bfa60e8b06267f77f5bae00f48c92d054d737cfc048f5f0f2c041ac7c73d6` |
| live `report_editor/native_api.py` | `d9498352bb1c12106468726755b96f0751776f0ada8eb6fa2d26626ee1630026` |

静态目录 `/dev/shm/office-four-format-numbering-print-metadata-20261113-v4/source/smart_reporting/report_editor/static`，工作簿桥同 v4 `source/smart_reporting/reporting/workbook_engine`。v4 的 `OVERLAY-PROVENANCE.json` 记录从 v3 只改 main 单行和对应测试；v3 从 v2 只叠加 hidden 两产品、测试及 LOCAL-ADAPTATIONS 摘要。Vite、预算与桥构建由 root 执行。本 HTTP 后端执行的是 live 工作区文件，不能称为 v4 物理后端副本；四文件启动/结束身份已在只读续验中一致，且与 04 启动身份一致。
