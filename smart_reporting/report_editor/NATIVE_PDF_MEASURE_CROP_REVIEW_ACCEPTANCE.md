# PDF 测量标签页框裁切风险提示

2026-11-12。延续真实页边探针：CropBox `[30,40,430,440]`、UserUnit=2、页内测量线 `[330,200]→[410,200]`、64个W标签实际超出可见页框。原普通绘图回执没有专项提示。

## 实现与范围

新增 `pdf_engine/bridge/measure-label-review.ts`：仅对已应用的measure操作作生成后诊断，读取**实际输出**PDF的CropBox与MediaBox交集，并复用writer的 `measureLabelBounds` 正式Helvetica保守字体边界。该边界基于实际舍入后的Tm和未加字偶距的9pt Tj；它是字体包围框，不是逐字形墨迹，因此提示措辞为“可能裁切”，不把风险评估当成精确像素结果。

不改变原标签、线段坐标、字号、页面框、UserUnit或writer。普通路径按来源页身份及最终页序找到实际输出页；样式改字混合路径沿既有稳定页序处理。旋转和UserUnit不需要二次乘入包含关系，因为标签与页框都在同一PDF用户坐标中。

- 可能裁切：`pdf_measure_label_crop_clipping`，保留原操作索引，附输出页码、实际可见框、保守标签框和超出边。
- 复核异常：`pdf_measure_label_crop_review_failed`，实际生成文件保留并提示人工检查；PDF加载、页索引、边界计算等诊断失败均不抛出阻止生成结果。
- 两条绘图返回路径均将新增告警返回到reviewIssues；未应用或被跳过的measure不获得本次告警。新增的crop clipping/review_failed属于生成后可变诊断，不参与previewDigest，避免预览后诊断暂时失败间接阻止同内容文件保存；原operations、实际outputSha及generic/form reviewIssues的摘要语义保持不变。

提示由既有预览/保存回执展示机制承载；不是自动重新排版，也不意味着页边裁切本身已经消除。仍需用户核对实际预览后移动测量线或调整测量单位。

## 引擎定向证据

- `bridge/measure-label-review.test.ts`：11项通过（追加摘要非阻断边界后最终执行）。含四旋转的非零CropBox/UserUnit2真实写入与AP标签/线段保留、正常标签不误报、普通caret不进入测量诊断、实际最终裁切/页重排后的正确输出页码、MediaBox交集、非法复核输入软失败、styled混合路径、生成后实际getCropBox故障仍保留输出与已应用决策；正常预览与保存阶段诊断失败时的普通/styled实际字节完全相同、SHA和previewDigest相同，而warning code诚实变化。
- 既有 `measure-label-bounds.test.ts`：2项通过，保持正式字体包围框及literal Tj编码边界。
- 既有 `text-measure-caret-mixed.test.ts`：7项通过，保留实际混合AP/resources验证、未应用操作不得发出布局告警、失败字节与原操作索引。
- 新测试已加入package.json既有显式test列表，没有运行全项目测试。`git diff --check` 通过。日志 `/tmp/pdf-measure-clip-new.log`、`/tmp/pdf-measure-clip-regression.log`，摘要边界先RED后GREEN见 `/tmp/pdf-measure-clip-digest-red.log` / `-green.log`。

## HTTP、保存与展示验证

保存回执检查发现另一个实际断点：普通addDrawing不在Python的PDF_RECEIPT_KINDS中，publication以前只取字节，丢失reviewIssues。现将addDrawing加入回执范围，没有加入PDF_CONFIRMATION_KINDS，不新增保存确认门槛；正常字节生成路径保持原生引擎。

- `test_http_publication_lineage.py::test_measure_label_crop_review_never_blocks_applied_pdf_http_download` 三项通过：实际长标签裁切、生成后诊断失败回执，以及styled预览成功后仅保存阶段诊断失败。均经过真实FastAPI/会话cookie/CSRF/Origin、实际Node引擎预览、preview.pdf、保存及下载；实际风险/故障成为validation问题，文件仍签发，应用索引保留、跳过为空。
- 下载由pypdf独立核对原线段、64个W标签、AP BBox超页框、CropBox与原UserUnit保留（纯测量UserUnit2，styled受原安全边界限制为UserUnit1）；HTTP字节SHA/size与签发身份相等，原文件不变。故障注入是在真实生成字节之后替换诊断回执；全程故障测试重绑测试摘要，保存阶段单独故障保持原内容摘要；引擎端另有实际getCropBox异常测试。保存阶段单独故障时，preview.pdf和原确认摘要仍有效，下载保留实际改字与测量标签。
- 既有测量外观HTTP、原生PDF真实保存下载、发布链静态非阻断守卫共3项通过。AGENTS.md列出的其余10个发布/导出合同入口分批参数化执行共79项通过（2项依原测试配置deselected），没有跑全项目测试。
- `pdf-object-host.test.ts` 12项通过，新增测量风险展示专项：显示独立警告和“已执行”，不误称未执行，不改变草稿，实际预览请求保留绑定摘要。此为宿主UI单元验证，PDF.js被fixture替代，不冒称真实浏览器或生产数据库端到端。
- PDF bridge bundle通过，metafile包含新增helper。完整前端npm build（Node heap4GiB，含tsc）通过，Vite42.17秒。首次全量JS预算检查发现合入PR219后Word/PPTX主包分别253.6/260.4KiB超250KiB，随后仅通过既有纯helper的静态ESM拆包恢复预算，不放宽阈值；最终Word238565 bytes（232.97KiB）、PPTX242803 bytes（237.11KiB），全部JS预算与预算合同通过。
- 本HTTP文件有既有lint问题，新增测试行经Ruff单独筛查无错误；native_pdf_contract.py与git diff检查通过。

本记录不冒称生产数据库、真实模型或真实浏览器保存整链通过。保守字体边界可产生风险提示而非精确裁切结论；没有自动移动/缩小标签，实际页边裁切仍存在。未部署或开启功能开关。


## 同批构建预算复核

仅调整vite.config.ts的manualChunks：Word现有批注模型/控制器拆为docx-comment-model（21471 bytes），PPTX既有规划/校验模块拆为slides-draft-plans（16365 bytes），保持原同步调用与静态导入。首次选择notes模块没有降低Word main，已撤回无收益规则，转而按实际内联模块拆出批注边界。

相关既有103项窄测通过；最终Vite54.49秒，全部预算和预算合同通过。Chromium实际导入两main及两新包成功，无页面错误；manifest核对新包无main传递回边。日志 `/tmp/office-budget-vite-final.log`、`/tmp/office-budget-final.log`、`/tmp/office-budget-module-import.log`；manifest SHA `da3919e9fa1658bbb3ae81feafc37232956ae06af50b0351d588336509ae4097`。导入专项不冒充完整Word/PPTX编辑、保存浏览器验收；未重复完整项目测试。
