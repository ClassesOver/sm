# Word 复杂长报告分页对照

2026-11-11 最新冻结构建实测：同一份原生 DOCX 在报告编辑器预览由 **15 页恢复为 10 页**，全部10页的分页切片 start/end/section 与固定 GenOffice 一致，最大数值误差约2.3e-13 px。连续四次打开结果稳定，正文、表行和注释标记齐全。LibreOffice 另存 PDF 仍为 **12 页**，原始报告 Markdown 直出 PDF 为 **8 页**（本轮未重跑），不代表不同打印引擎已对齐。旧截图中的串页／叠印为截图视口误判，已更正。

样本用项目 `ReportRuntime.render_markdown` 真正生成报告 PDF 和 Word。然后在报告 Word 上构造原生修订：A4 正文共三节，按单栏、双栏、单栏换节；双栏中插入一张含重复表头、62 行数据的长表；正文中有两条脚注和一条文档尾注。所有四路均包含同样的 46 个正文段落标记和 62 个表格行标记；双栏和原生注释是 DOCX 修订独有内容，原始报告 PDF 不含这些后加的设置。该报告关闭封面与目录，使用带页码的页眉页脚。

| 路径 | 总页数 | 第 2 节首段 | 脚注 1 / 2 | 表格数据页 | 第 3 节首段 | 尾注 |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| 报告编辑器，修复前构建 | 15 | 5 | 3 / 8 | 9–11 | 12 | 15 |
| 报告编辑器，仅字体行高修复冻结构建 | 10 | 4 | 2 / 5 | 6–7 | 8 | 10 |
| 报告编辑器，字体别名和页眉作用域最终构建 | 10 | 4 | 2 / 5 | 6–7 | 8 | 10 |
| GenOffice 固定源码版 | 10 | 4 | 2 / 5 | 6–7 | 8 | 10 |
| 原生 Word 另存 PDF，LibreOffice 24.2.7.2 | 12 | 4 | 2 / 5 | 6–8 | 9 | 12 |
| 原始报告 PDF，ReportRuntime / WeasyPrint | 8 | 2 | — | 4–6 | 6 | — |

三条 DOCX 路径均能找到全部正文与表格标记；两条脚注均与各自的正文标记同页，尾注均独占最后一页。网页表格续页可见重复表头；LibreOffice 也重复表头，但第一列表头 `TABLEHEAD` 在窄栏中折成两行，直接搜索完整词会漏报。宿主首屏正文行距明显更大，已有差异出现在单栏正文，不能仅归因于表格、分栏或脚注。

2026-11-11 后续诊断更正：旧 locator.screenshot 在 1000 px 高的视口内截取 1122.53 px 高纸张，超出固定预览浮层 949 px 高的可见滚动区域，把底层编辑器正文拍入图片底部，导致页底叠印和 BODY103 串页的误判。真实 viewport 截图无该问题；只将视口增高至 1500 px，未改变文档、分页或生产 CSS，首页、脚注页和尾注页截图即正常。computed 纸张背景原本就是白色，强制白底单变量实验无变化。实际 BODY103 克隆坐标不在尾注页裁剪区域内；测量 DOM 与 clone 的 BODY101 字号、行高、尺寸一致。末页满容量窗口不是本次误判的根因。

- 两个网页均通过真 Chromium 点击“视图 → 分页预览”，无 JS 页面错误。宿主从本地 Vite 加载构建产物 `lazy-docx-main-CxC0HC1X.js`（SHA256 `8510da68ba6f6bbc3ea0b849f3a32e7c96722a5cb78d31891d1aa0e7adba639b`），复用现有 GUI 探针，文档接口由离线夹具提供；探针下载响应、宿主读取、GenOffice 读取及 LibreOffice 输入为同一 DOCX 字节，SHA256 均为 `7f4e32ee954f8eaaa98e97e904932369199971d323edf17b8cbbad578cde0391`。GenOffice 检出 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，工作区干净，用临时 Vite 启动原始应用。
- LibreOffice 运行项目原生 Word 导出实际调用的 `libreoffice_to_pdf`；报告 PDF 运行 `ReportRuntime.render_markdown` 的独立渲染路径。页数以实际浏览器页元素和 `pdfinfo` 为准；浏览器落页用可见裁剪区域内的 DOM 文字坐标，PDF 用 `pdftotext -layout`，并抽查 PNG。未执行线上保存、授权签发或 Microsoft Word 桌面版。
- 运行原件、脚本和逐页结果保存在本机 `/tmp/sr-word-complex-20261111`：`make.py`、`probe-prep.py`、`summarize.py`、`host.json`、`source.json`、`runtime.json`、`comparison.png`、`downloaded-native.docx`、`native-export.pdf`、`ws5/out/report.pdf`。


更正证据保存在 /tmp/sr-word-complex-20261111：diag-actual-viewport.png 是实际可见视口，corrected-page-1.png、corrected-page-3.png、corrected-page-15.png 分别为完整处于可见预览区域的首页、脚注页和尾注页；corrected-geometry.json 对每张纸的矩形与 pv-scroll / viewport 交集断言 valid=true。旧 comparison.png 仅作为调查历史，不再作为串页缺陷依据。

持久诊断脚本 frontend/smoke/docx-preview-clip-diagnostic.mjs 独立读取 downloaded-native.docx / native-model.json，可用 DOCX_COMPLEX_ARTIFACT、DOCX_COMPLEX_EVIDENCE、DOCX_TEST_DIST、DOCX_TEST_PORT 指定样本、输出和冻结资产。脚本逐个验证浏览器实际 JS 的磁盘 SHA，开始/结束核验 manifest，连续四次打开预览要求切片相同，核对全部 46 正文、62 表行及 3 条注释标记，并在截图前断言整张纸位于实际可见预览区域。上面 15 页仍是字体修复前实测数据，后续字体修复的最终页数另行登记。


字体修复后最终冻结构建验收

冻结目录 /tmp/sr-word-complex-20261111/final-static，manifest SHA256 a5de596017e97b16db7e3782e604988eed0c356927c18259968b1b84d3ee211a；实际浏览器加载 lazy-docx-main-ByUHjouC.js，SHA256 d6bf7a07cb5a3e0426816497e36e53b5ea224bee853b7dc59455ea10f9b8cd5f。最终持久探针 exit 0：连续四次开关预览的 start/end/section/pageNo 切片完全一致，10 页；46 正文段落、62 表行、两条脚注及一条尾注的可见标记全部保留，浏览器 errors=[]，每个实际加载 JS 的 SHA 与冻结磁盘文件一致，开始与结束 manifest 相同。首轮新夹具载入超时未进入分页；增加失败日志后，同一冻结目录再次执行正常通过，未通过修改产品消除超时。

BODY101 段落宽 657.71875 px、字号 14.6667 px、上下间距 0/8 px 不变，行高从 43.8381 px 降为 27.5029 px，段高从 175.375 px 降为 113.015625 px；--doc-line-factor 从 1.8681 变为 1.172，CJK 为 1.3。该行高和段高与固定版实测相同。宿主仍实际绘制 Noto Serif CJK SC，CJK span 行高30.5067 px、宽105 px、高21 px，固定版 span 宽102.609375 px、高17 px，因此不能以总页数相同宣称所有字形、行末或段落落页一致。字体修复分离浏览器可用字体与 Word 排版指标，根因与针对性测试由字体适配验收记录说明。

最终截图人工核看：final-browser/page-1.png（首页）、page-2.png（脚注页）、page-10.png（尾注页），都满足整纸完全位于可见滚动区的几何断言，无先前误判的透出正文。截图与完整 evidence.json 位于 /tmp/sr-word-complex-20261111/final-browser。页脚仍显示“第 N / 1 页”；原样本分母实际为 `PAGEREF report_section_end_0 \* Arabic`、缓存值为 1，并非 `NUMPAGES`。后续固定源码真实浏览器复核同样为 10 页且保留该分母，不能据此判定宿主缺失总页数替换。LibreOffice 及报告 PDF 的对照数字沿用前次真实证据，未重复完整测试或旧四路渲染；本轮未修改对外导出路线，也不将样本写为已通过完整页码验收。

本轮针对性校验：bundled-fonts、style-scope、mixed-columns、measure-current-pagination、recovery 共 70 项通过；另字体槽 12 项通过。`tsc --noEmit` 与独立 outDir 的 Vite 构建通过；Word main/render/engine 分别 213286/714176/423291 bytes，均未超过既定预算。整体预算检查仍失败：共享工作区的 XLSX `lazy-workbook-main-CYgl2rOm.js` 为 256.1 KiB，超出 250 KiB；本轮未扩大预算或改动 XLSX。独立预算结果为 final-budget.json。构建有既存大块/循环 chunk 提示，不记为零构建告警。


2026-11-11 页脚字段专项复核

只替换原样本页脚域指令，分别生成真正的 `NUMPAGES` 与 `SECTIONPAGES` 临时夹具，其余 ZIP 部件原字节保留。固定源码真实应用与上述 `final-static` 冻结宿主网页均得到 10 页；`NUMPAGES` 每页分母为 10，`SECTIONPAGES` 三节分母依次为 3、4、3，`PAGE` 依次按节从 1 重启，两端 errors=[]。宿主实际加载 JS 逐一核验磁盘 SHA，开始与结束 manifest 相同。这验证已有文件的三种页码域预览，不覆盖未保存页眉页脚编辑状态或保存后域缓存。

证据根目录 `/tmp/sr-word-complex-20261111`：原样本源码复核为 `source-footer-original.json`，真正域源码证据为 `source-footer-NUMPAGES.json`、`source-footer-SECTIONPAGES.json`；宿主证据为 `host-footer-NUMPAGES/evidence.json`、`host-footer-SECTIONPAGES/evidence.json`。两夹具 SHA256 分别为 `7b4683fa0d2743e2354f4350dd89525c661163caf7fd36384610a75cabca2336`、`7cbc81a180cbb8fb8a0e12a87bbff33f2dd565d1cc525d695af2b692d78f2feb`。探针为 `source-footer.mjs`、`host-footer.mjs`；仅本地浏览器专项检查，没有重跑完整测试或重新构建。

源码将 `PAGE`、`NUMPAGES`、`SECTIONPAGES` 分别解析为专用占位标记，分页预览按逻辑页码、物理总页数与节页数填入；其他域（包括 `PAGEREF`）保留原缓存值。报告生成器使用节末书签的 `PAGEREF` 表示重启编号节的页数，复杂样本后加换节仍继承原书签引用，因此其语义不能直接改解为全篇总页数。保存链路未传入 `pageCount` 时真正 `NUMPAGES` 的 OOXML 缓存另有默认值 1 的边界，与此样本的 `PAGEREF` 现象须分开处理；本轮仅调查并记录，没有修改该链路。


页眉测量作用域与完整切片对照补充

字体行高修复后总页数相同但 BODY107 仍落页不同，继续调查确认还有隐藏页眉测量作用域差异：固定源 canvas paddingTop=95.9542 px，宿主使用原始 marginTop=75.6 px；宿主隐藏 hf-strip-probe 原挂 document.body，在 .docx-native 作用域外，漏掉动态文档样式，header 保留高度仅30.1875 px。单变量将该 probe 放入真实宿主祖先后，header 高度65.6875 px，canvasContentTopPx=95.9541667 px。仅给 probe 自己加 .docx-native 类不能匹配动态样式的祖先选择器，不能替代容器绑定。同步真实 canvas padding 与测量 origin 后，首页切点963.5568→905.7963833333333，精确匹配固定源。

适配新增显式 bindHfProbeParent 容器绑定，默认源 app 仍挂 body；宿主 createDocxHfProbeScope 在文档样式挂载后、首次 HF 测量前绑定，在宿主移除前释放。绑定栈支持多个宿主乱序销毁，最终还原原有外部 parent；每次有效作用域切换增加缓存 epoch，防止复用不同宿主样式下的高度。三个定向 DOM 回归通过，含40→75→40高度缓存切换。root 将所有分页测量与画布 padding 接到同一有效 canvasTop；没有硬编码分页切点。

该集成修复的同样本 dev 真浏览器对照（hf-scope-integrated-dev.json 与 source-first-page-facts.json）：10页全部 start/end/section 切片一致，最大切点数值误差2.2737367544323206e-13 px；第1页容量943.4458333 px，BODY101宽657.71875 px、高113.015625 px、行高27.5029 px；pageErrors=[]。此处是定向 dev 对照，最终冻结构建须另记身份与四次开关证据，不能沿用上一字体修复构建的 manifest。


字体别名与页眉作用域最终冻结验收

final2-static 的 manifest 为 ba7cf67c3fbcc163a3327fc20d42143bf54763d33c9f8f723ab66303592a9fc7；实际加载 lazy-docx-main-BSjjkjDe.js，SHA256 fe368d9c71afa1f6ab5979a09197248a58d1cd0ead025e0d8f07dc27c9ebde2c。持久 probe 以 DOCX_SOURCE_CUTS=source-first-page-facts.json 对照固定源码实测切片，最终 exit0；全部10页 start/end/section 一致，最大误差2.2737367544323206e-13 px（容限1e-6 px），四次开关预览切片一致。canvas paddingTop95.9542 px、paddingBottom83.1333 px；46正文、62表行、3条注释全部可见标记齐全，实际JS逐文件SHA与冻结文件一致，manifest首尾不变，errors=[]。BODY107现位于第2页，与固定源码一致。

CDP CSS.getPlatformFontsForNode 对 BODY101 实际命中 Caladea-Regular（custom=true，318 glyph）与 NotoSerifCJKsc-Regular（custom=true，7 glyph）。浏览器 familyName 报 Caladea (Fontations)，故验证使用 PostScript 身份而非纯familyName字符串；前两次新CDP断言因该后缀误判中止，修正探针身份判定后完整验收通过，未为通过该断言修改产品。固定源码的CJK实际命中系统Noto，宿主是已加载的web字体；切片一致不扩展为像素或全部字体来源一致。

人工查看 final2-browser/page-1.png、page-2.png、page-10.png，首页、脚注和尾注均在完整可见预览视口内，正文与注释分隔清晰，未见串页。数据位于 /tmp/sr-word-complex-20261111/final2-browser/evidence.json（含sourceDiff、canvasMetrics、platformFonts和实际chunk身份）。仍保留NUMPAGES缓存1、桌面Word未验收、不同PDF打印引擎未复测与未对齐的边界。本轮新增生产改变围绕字体解析、隐藏HF作用域、实际canvas起点及未保存HF／页码预览的宿主接线，未硬编码页数或切点。

2026-11-11 未保存页眉页脚与页码状态专项

`frontend/smoke/docx-preview-live-hf.mjs` 使用相同复杂 DOCX/native-model，真实 UI 对 `final2-static` 执行：修改第 1 节页眉后全部继承节预览即时显示新文字；解除第 2 节页眉链接后再改第 1 节，第 2、3 节仍保留解除当时的原页眉快照；第 2 节页码格式改为大写罗马数字、起始号 7 后预览显示 VII、VIII，真实对话框恢复十进制/1 后恢复原预览。每次关闭预览前后的 localStorage 草稿逐字相等；清草稿重开原件也恢复原预览，无陈旧状态。没有保存或导出请求。manifest SHA256 `ba7cf67c3fbcc163a3327fc20d42143bf54763d33c9f8f723ab66303592a9fc7`，所有实际加载 JS 身份通过、errors=[]，证据 `/tmp/sr-word-complex-20261111/live-hf-preview/evidence.json`。

此专项 `ok=true` 仅覆盖上述即时状态与草稿不变契约。真实正文 `Ctrl+Z` 未撤销页眉修改，也未撤销页码格式/起始号修改，证据 `historyBoundary.headerUiUndoRestored=false`、`numberUiUndoRestored=false`；当前页眉及布局操作直接进入 NativeDraft，尚未接入正文 TipTap 历史。本轮没有扩展撤销功能，也没有将测试直接调用 `NativeDraft.undo()` 冒充 UI 撤销通过。

final2 定向校验与构建：字体适配 9 项、字体槽 12 项、画布几何 5 项、HF 作用域 3 项及 recovery 56 项覆盖本轮变化；新增未保存状态、无编辑能力模型回退与几何用例均记录失败后修复。recovery/columns/slots 合并运行 72 项通过、1 项因夹具缺少真实 SectionInfo 的空 refs 失败；补齐夹具后该项单独通过，没有重复完整测试。`tsc --noEmit`、独立 Vite 构建及完整包体预算通过，final2-budget.json 的 failures=[]；Word main/render/engine 为 214166/714888/423291 bytes，预算未扩。较早 final-static 的 XLSX 预算超限属于历史结果，不能作为 final2 的现状。构建仍有既存循环 chunk／大块提示。
