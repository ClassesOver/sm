# PDF 测量线混合、单选按钮删除与货币精度验收（2026-11-11）

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。继续三域增量，不含 OCR；本批限定范围验收完成，整体 PDF 对齐和完整转换保真仍未完成。未提交、部署或启用生产开关。

## 本批实现

文字：固定 measure/caret writer 可与样式改字、选区样式和文字标注交错保存。输入先校验页面身份、几何和可打印 ASCII 标签；写后逐字节核对 AP 路径、标签、字体资源、Rect/BBox/Matrix、原标注资源及操作索引。成功添加的每条测量线返回 `pdf_measure_label_appearance_review_required` 软告警，说明固定 writer 从中点起写、BBox 估算与草稿不同；告警进入预览摘要，不伪装成未执行。后置失败保留实际生成字节并给具体原因。

真实渲染发现水平标签顶部及短线长标签右端裁切，仍未修复。独立诊断的水平标签缺46像素、短线长标签缺1166像素；本批两条斜线 fixture 标签完整，不能从其通过推断所有测量标签保真。caret 固定填充三角形与 Web 开口标记也未达到视觉全等。未修改共享 writer。

表单：安全互斥2–64 Widget单选组可删除一个未选中且非默认的按钮，保持至少一个。专属 `radioRemovalEditable` 不扩大旧 `removable` 或必填属性权限；严格核验组状态、选项、动作、AP/字段/页面引用及数组独占。用既有原生方法移除 Kids/Opt，原 Annots 数组精确移除目标引用，再删除无外来引用的目标 Widget 对象。其他原始间接对象和流保持，后续仍能选择幸存选项。是逻辑删除，不承诺擦除历史或已脱离外观字节；最后一个 radio 不开放删除。

公共 operations 和直接 CLI 均接入 `removeDesignWidgetWithReceipt`，保留实际字节和失败复核回执。真实专项发现旧包装丢掉后置警告，已修复。另定位 `removeAnnot` 会归一化跨页正文，新 radio 路径改为核验过的原 Annots 数组删除；旧独立字段语义保持。流快照统一原生 encoded bytes，避免内存流与保存后类型差异产生误告警。

转换：货币格式按来源小数位生成，保留数字类型和值，包括尾零；已识别的独立货币、百分数行加入现有字体 advance 与来源 ink 的最小宽度 claim，计入输出新增的分组逗号，保留更宽已有列。整数/指数、普通正文和表格布局规则未扩大。没有全局 fitToPage、缩字号或栅格化替代。

## 冻结构建、身份与实际下载

- 一次成功 Vite 构建、一次 bridge bundle、一次 runtime package，均 exit 0。375个JS分块预算零超限；PDF main249380 bytes、form controls33248 bytes；未修改预算。
- Static `/tmp/pdf-measure-radio-currency-static`，manifest SHA-256 `671f93ee01a57aceaf5a4fb4726c2544aeaac46f56c9ab8f7d4381aef2a2f5ec`。
- Runtime `/tmp/pdf-measure-radio-currency-runtime`，CLI SHA-256 `7bc798766db4335d50563636e7cad3cf39b154923cd0bae468fcc7a1db38302a`。
- 45个前端文件、184个引擎/清单文件和954个实际bundle inputs最终无漂移；LOCAL180项、converter48项local hash全部匹配。运行包许可、来源清单和两个WASM身份匹配。
- 本轮直接核对69个固定Git blob时发现既有IPC来源清单误把本地裁剪版hash当上游hash。IPC仅裁去桌面printerOptions类型/入口，代码未改；SOURCE已纠正为固定blob SHA `c60ce0c653ccdb6a1e6825d7e0c3a0b78a9b937c78a351deac4360767b89d620`，LOCAL保留本地hash。只将纠正后的SOURCE说明/清单同步至运行包，CLI未变，不重复bundle/package。前批“全部上游逐项核验”陈述对IPC不准确，本批纠正，不重写旧证据包。
- 三条真实浏览器链路均 exit 0，各37个实际JS响应与冻结资源匹配，集合与hash相同；来源未变，asset/page/console/HTTP errors为空。真实grant、cookie、CSRF、预览确认、签发下载及重开；持久化仓储为fixture内存实现。

文字实际下载 `/tmp/pdf-measure-radio-currency-text-browser/mixed.pdf`，14399 bytes，SHA `34d2b2910c9896d1e2117794fde959c119db86128a8aab335ee8cd66ee6b6be8`。真实pointer标定3m、选区改字、underline、caret、第二条测量线，Undo/Redo及原indices0–4保持；测量线告警只对应0/4。独立pypdf核字体/标签/路径/原页；Poppler实际渲染与只扩大Rect/BBox的诊断副本差0像素，证明所选两条斜线标签完整。`actual-render.png` 已由root目视。

表单 `/tmp/pdf-measure-radio-currency-form-browser` 四次保存：创建Yes/No/Maybe、code，删除No，后选Maybe。删除文件9011 bytes，SHA `053dec2e0980aa5e8837cf07ea5ab2f75bee1ff82dfdb8cec920e3dfc48ccccc`；后填9130 bytes，SHA `168903d5bab8ec5984cc43db9383143d9cc1bd49655f58f965c62a46abf1639c`。独立pypdf确认删除步骤只有目标Widget对象和Kids/Opt/Annots相应项消失，所有其他原对象/AP流保持，幸存on名仍/0、/2。后填步骤按既有填值语义改变V/AS，不声称其所有对象不变。最终重开UI已目视。

XLSX `/tmp/pdf-measure-radio-currency-xlsx-browser/converted.xlsx`，5895 bytes，SHA `1236f4ff311b19611ad1f40a342cdfe4a3be2c2c4e25d4826df167fc485a6f63`。对这个实际下载仅一次Calc，profile/output均在/dev/shm，exit0；实际PDF88584 bytes，SHA `3d2f8b85f325eadd0fc9dfdbe6c774ef476449ce92b696ef025f9646c2d32dea`。openpyxl核数值/格式及A/B列宽14.09/14.83；实际PDF提取及目视显示 `$12,345.678`、`€31.1`、`-£0.0500`、`12.345%`、`0.0007%`，无`###`，前批普通小数/字体/混合样式也保留。`rendered-currency.png` 已目视。

两页来源仍打印六页：原表宽集中放A/C/F而中间槽仍有默认列宽、正文落窄列并逐块堆行、图片参考区延伸共同导致；单改paperSize不能解决。详见 `NATIVE_PDF_XLSX_PRINT_LAYOUT_DIAGNOSTIC.md`。`overallFidelityPassed=false`，下载照常签发并明确验收未通过。

## 专项、审阅与非阻断

- 文字native核心5项、成功测量告警1项、高位字节故障1项分阶段通过；UI2项通过，均有真实RED→GREEN。交叉审阅发现ASCII解码会抹去高位字节，补operator/label变异用例后改为Buffer.equals；只跑新增失败项。helper/UI scoped strict tsc通过，不推断全项目通过。
- 表单新native5项、旧设计4项、公开新旧4项，UI新2+旧4项分别通过。部分早期fixture直接构造层级radio产生孤儿父节点，修为实际createDesignField安全来源；不把fixture错误冒称功能RED。窄类型检查仍有既有宿主/依赖声明问题。
- 转换新3项及受影响旧decimal3项分别通过，保留的pre-fix实际XLSX被独立verifier拒绝；没有重复完整测试。
- HTTP新增measure/caret后置故障3项及radio删除故障1项通过；真实measure软告警1项和签发静态守卫1项另通过，共6个唯一检查。首轮真实告警测试遗漏操作sourceSha256导致422，仅修fixture后重跑失败1项及首次守卫；已通过4项不重跑。日志 `/tmp/pdf-measure-radio-currency-http-green.log`、`http-warning-green.log`。
- 三域完成交叉只读复审。没有新增Python生产签发函数；所有新后置步骤已在 `test_http_publication_lineage.py` 登记，生成文件身份可读即保留下载，validation不伪称通过。

总证据 `/tmp/pdf-measure-radio-currency-final-evidence-20261111.json`。全项目typecheck、完整生产镜像/权限/部署仍未通过或未验收；本机Node v24.18.0不等于完整生产镜像验收。仍开放任意混合编辑、完整游标/复杂文字重排、测量线普遍标签裁切、任意复杂多Widget/XFA/签名、完整Office/MD/HTML保真及PPTX首行约+6.350708pt偏移。
