# PDF Form Design：严格单控件删除引擎增量

2026-11-11。该增量交付引擎适配、CLI/Python 字节桥接、原生草稿操作和 Form Design 删除入口；不表示全部 Form Design 或上线验收完成。

最终结论：主任务执行 final08 真实浏览器专项已通过（exit 0、summary ok=true），
本任务独立读取 summary/independent/HTTP evidence 并目视 candidate、preview、
reopened 三张截图确认。完整证据目录
`/tmp/pdf-form-design-browser-20261111-final08/`，运行日志
`/tmp/pdf-form-design-browser-final08-20261111.log`。下文保留早期失败和修复记录，
早期磁盘阻塞不代表 final08 仍未验证。

固定上游 `/home/junge/pros/genoffice-source-full` 的 `apps/pdf/src/renderer/App.tsx`
`deleteFormField` 使用 `editFormWidget(remove: true)` 删除既有控件；本地固定源
`src/main/save-pdf.ts::applyFormWidgetEdits` 也包含对应能力。但其按字段名回退到
唯一控件的行为不能作为原生来源身份契约。

新增 `reporting/pdf_engine/bridge/form-design.ts`：

- `inspectDesignWidgets(bytes)` 返回来源 SHA、字段名、精确 widget ref、字典摘要、
  绑定字段字典/引用/页面出现位置的 widgetIdentity、页面/区域与可删除原因。
- `removeDesignWidget(bytes, sourceSha256, target)` 重新读取原始来源和全部身份，
  不采用字段名或位置 fallback；只允许安全、独立、单控件 text/checkbox/dropdown。
- 拒绝 XFA、Perms、签名字典、只读字段、锁定控件、动作、结构/共享引用、
  多控件和层级字段。复用已有有界引用扫描与固定源删除原语。
- 固定 pdf-lib 1.17.1 `removeField` 对页 Annots 使用外观引用，可能遗留 widget
  悬空引用；适配器额外移除预先核验的精确 widget ref，并复读存活字段和页面
  Annots 顺序。删除不是保证安全擦除旧值。

定向 TDD：新增模块缺失/空 census 先失败；首轮实现暴露实际悬空 widget，
修复后四项通过。新增正文保持断言曾因 pdf-lib 自动加入 q/Q 内容包装失败，
最终断言核验原内容流引用及字节全部保持，额外流仅可为 q/Q，不掩盖内容变化。
命令为 `node --import tsx bridge/form-design.test.ts`，最终日志
`/tmp/pdf-form-design-green-20261111.log`：4 passed，包含伪造 SHA/ref/字段名/字典
摘要/身份、共享页引用、多控件、6 类保护样本。XFA census 触发两条 pdf-lib
既有内存剥离 warning，拒绝后没有生成修改产物，不能称零告警。

独立产物：`/tmp/pdf-form-design-20261111/source.pdf` 与 `deleted.pdf`。
pypdf 验证仅剩 keep 字段和一个可解析 Widget，正文与来源完全一致、页数为 1；
`independent.json` 的 ok=true，输出 SHA256：
`3c1dd399f68a6e6d700a2c8cfa10a6851b2d1c07e5acb8f8483bbe8a5d10edb1`。
首次独立脚本误把解析器末尾换行当正文差异，改为先精确比较来源/输出正文、
再校验已知正文，最终通过；未修改产物或产品代码来配合脚本。

CLI/Python 增量：`bridge/cli.ts` 新增严格 `inspectDesignWidgets` 和
`removeDesignWidget` 请求，输出文件采用 wx 创建且拒绝与输入同路径。
`reporting/delivery/pdf_form_design.py` 暴露 `inspect_pdf_design_widgets` 与
`remove_pdf_design_widget`，检查真实来源 SHA、输出 SHA、大小后才返回字节。
Python 实际 PDF 专项另 6 项通过：正常删除/正文保持、伪造控件摘要拒绝、实际
输出回执的三种篡改、来源 census SHA 篡改。初轮旧 dist 未识别新 CLI 请求，
RED 日志 `/tmp/pdf-form-design-python-red-20261111.log`。

GREEN 由独立测试进程仅将 `run_bridge` 调度替换为真实
`node --import tsx bridge/cli.ts`，其余生产 Python wrapper、CLI、PDF 文件、
引擎与 pypdf 校验均实际执行；日志
`/tmp/pdf-form-design-python-source-green-20261111.log`，6 passed in 10.74s。
这属于源码 CLI 验收，不宣称旧 dist 已支持；统一 bundle 后仍需单项实际
Python 入口验证。测试 PDF 由 ReportLab 与 pypdf 构造；ReportLab 的原始合并
field/widget 已先通过源码 CLI 核验为只读，成功用例显式构造受支持的分离
单控件树，没有放宽 adapter 来接受未验证结构。两 Python 文件 ruff 通过。

原生保存链增量：`bridge/operations.ts` 将 census 暴露为 `formDesignWidgets`，
声明实际 `removeFormWidget` 能力，并新增严格同名操作。删除必须是完整草稿中
唯一操作，从原始来源重读身份；输出回执校验真实字节并将操作、来源和输出 SHA
绑定到 previewDigest。不能将其拼在改字/页面重排后按旧 ref 删除。新增专项
`form-design-operations.test.ts` 2 项通过，原有 `operations.test.ts` 5 项通过，
日志分别为 `/tmp/pdf-form-design-ops-green-20261111.log` 与
`/tmp/pdf-form-design-base-ops-regression-20261111.log`。

前端增量：`pdf-form-design.ts` 列出带来源身份的字段及不可删除原因，选择后通过
真实 NativeDraft 暂存单项操作，复用既有 Undo/Redo、预览和保存路径。该操作不能
与其他修改混存；只读、保存中、来源失配、过期身份和已销毁视图均不能暂存。
预览刷新失败保留已暂存草稿并给出明确提示。`pdf-main.ts` 的 Form Design 页签
通过真实命令 `genoffice.pdf.formDesign.deleteField` 打开此面板，源元数据和恢复
草稿都检查引擎能力，视图销毁同时清理面板。

前端面板专项 4 项通过，现有页面状态回归 17 项通过；日志为
`/tmp/pdf-form-design-ui-green-20261111.log`、
`/tmp/pdf-form-design-page-state-regression-20261111.log`。
新增 `pdf-form-design-host.test.ts` 的真实 `createPdfEditorView` 黑盒集成 2 项
通过：公开 Form Design 入口、实际 NativeDraft 暂存和 Home 撤销；强制派发保存中
与只读入口不能打开/暂存。日志 `/tmp/pdf-form-design-host-green-20261111.log`。
这些是 jsdom 集成测试，PDF.js 和元数据 API 使用 fixture，不能称真实浏览器或
后端保存验收。

统一 Vite 资产构建已由主任务完成；不能称全量 TypeScript 检查通过，主构建的
tsc 被其他 workbook 测试的类型错误阻断。生产 Python 入口验证由主任务记录。

真实浏览器验收脚本已新增：`frontend/smoke/pdf-form-design-smoke.mjs` 与
`pdf-form-design-server.py`。复用提取专项的工作区、真实授权/CSRF/发布/下载服务，
编辑器与发布服务使用同一内存仓储，实现 reserve/complete/get；PDF 来源采用
上文已核验的分离单控件 fixture，无 HTTP 路由或 PDF 字节替身。

早期浏览器全链验收**未通过，环境阻塞（final08 已补验通过）**。早期 sandbox 初始化超时；随后 fixture
重复目录冲突和浏览器路径均已在 smoke 中修正。final03 在 Python 导入 dill 时
因磁盘满报 `No usable temporary directory found`。final05 能启动真实服务和
Playwright Chromium，完成真实 grant 交换（303）、编辑器页/context（200）及
冻结 JS 请求（200），但根分区再次 100%、仅约 1.6 MiB 可用时浏览器
`Target crashed`。尚未触达 `/api/file` 或删除动作，不能把定向 jsdom 测试当成
真实预览、保存、下载重开证据。已停止重复运行；没有为此修改产品代码。
final05 日志 `/tmp/pdf-form-design-browser-final05-20261111.log`，部分 manifest、
HTTP、source PDF 证据在 `/tmp/pdf-form-design-browser-20261111-final05/`。
异常收集已改为容忍崩溃页面的 content 读取失败，避免覆盖原始失败。

上述早期执行不能证明候选、Undo/Redo、实际预览确认、保存、下载独立 pypdf
和授权重开成功；这些步骤现由下述 final08 补验。新增字段、移动/缩放、字段
属性和多控件编辑均不在本次交付范围。

继续验收发现的产品缺口：磁盘恢复后主任务运行真实浏览器 final07，删除暂存成功，
但等待实际预览确认框超时。追查 `previewDraft` 的实际字节预览白名单缺少
`removeFormWidget`，导致 JSON 校验后直接返回；`prepareSave` 也仅为 replaceText
进入预览确认。新增真实 createPdfEditorView 宿主专项先 RED（prepareSave 返回
空对象），再最小修复四处接线：加入字节预览白名单、复用现有确认面板与保存
准备条件，并增加中文操作标签，保留 replaceText 行为。新专项 1 passed、旧
2 项未重复，日志 `/tmp/pdf-form-design-preview-host-red-20261111.log` 和
`/tmp/pdf-form-design-preview-host-green-20261111.log`，限定 diff-check 通过。
后端协议及发布签发未修改；表单删除的前端确认摘要会随既有保存请求传递，但
后端当前仅对 replaceText 强制验证确认摘要，不能称表单删除具有服务端强制
预览确认。表单删除安全身份仍由来源 SHA、widget ref 与字典身份严格重读保证。
修复后主任务统一完成 Vite 构建（约 45 秒）、PDF 定向 TypeScript 检查和构建
预算检查；完整 build 仍受其他 docx/slides 新增文件的类型错误阻断，不宣称全量
类型检查通过。

final08 使用 Chromium 140.0.7339.16 与真实生产资产，运行中 manifest 未变化，
实际加载的 22 个 JS 逐一与磁盘 SHA 对照。manifest SHA256：
`0a7bb15fd8019797b68833ba6d60d20beb0355163224ee0ebfa27e042bb4c1b8`；
实际 `lazy-pdf-main-DHCSOcAX.js` SHA256：
`3edeb5ea239f0e003322c829e2981f549170e918857c31289f59a29e1d4649a8`。

真实公开 Ribbon 列出 remove_me/keep，选择 remove_me 后暂存严格单项删除，
Home Undo 清空、Redo 恢复相同操作。实际 `/api/preview` 与 `/api/preview.pdf`
均返回 200，截图显示“已执行：第 1 项 · 删除表单字段”、已勾选的预览确认框、
保留正文及 keep 复选框。随后真实 `/api/save` 返回 200，登记修订 5（父修订 4）。
独立业务验收仍为 `ok=false/native_source_review_pending`，实际 PDF 下载照常
签发并 GET 200，符合非阻断契约，不能称业务验收通过。

实际下载 6833 字节，pypdf 独立复读只剩 keep 字段、一个有效 Widget，其 Parent
为 keep，无悬空 widget；正文/页数保持。来源 SHA256：
`588ae7d464ae9614031cb7bf04dc64434032dc1b854bfe3e8eab26afe49e5c12`；
下载 SHA256：
`fec2fba99015d69875832662a2107a9ad1a7d0d8c098791c627b8931dc334ea4`。
来源复读 SHA 未变。通过真实新 grant/cookie 重开修订 5，context 与下载身份一致，
Form Design 候选仅剩 keep；重开截图显示正文与复选框。pageErrors、consoleErrors、
httpErrors 均为空。

该结果覆盖真实浏览器、生产资产、PDF.js、授权/CSRF、打包引擎、发布、下载与
重开；文档/授权/产物仓储使用内存且 editor/publication 共用文档仓储，没有
HTTP 路由或 PDF 字节替身。仍不等同生产数据库/完整应用镜像/全 Form Design
验收。前端确认与后台严格来源/widget 身份的边界保持如上，未扩展后端强制
摘要校验，也不承诺逻辑删除安全擦除旧字段值。

## 2026-11-11 新建文本/复选框与必填属性增量（root04 已补验通过）

本节更新此前“新增字段与属性不在范围”的边界；它不扩大其他既有验收结论。
固定源仍为 f8c17004fb730df11f0f743164ffd8b4281bb38c；本地
src/main/save-pdf.ts:938 的 applyFormFields 创建真实 AcroForm/Widget，1024
的 applyFormWidgetEdits 只在严格身份重读后修改 required。没有重新实现写入器。
上游 App.tsx:8747/8752 的类型为 text/checkbox，对应 i18n 的
formDesignText/formDesignCheckbox；属性标题为 formDesignProperties。
本地 Ribbon 目录命令另行映射，不宣称上游存在同名字串命令。

bridge/form-design-create.ts 新增 createFormField 与 editFormFieldRequired。
新建来源受 SHA256、原始 pageId、CropBox、字段名称唯一性和类型限制；仅支持
ASCII 单层字段名、空文本初值、文本 12pt/左对齐，以及可选初始勾选的复选框。
坐标尺寸为 8..2000 PDF 单位，必须完整处于 CropBox。已有字段必须通过安全独立
单 Widget census；无加密/权限/签名/XFA/动作，默认 UserUnit，支持四个直角旋转。
required 编辑必须同时匹配 fieldName/widget ref/widgetIdentity/expectedWidgetSha256，
不会以字段名退回查找替代目标。每次设计单独保存，不能混入其他草稿。

输出复读检查真实字段、required、AP、原字段字典、Widget 字典、页面正文流、
MediaBox/CropBox/rotation、页面 Resources 字典和原 Annots 顺序。pdf-lib 添加
纯 q/Q 包装流是允许的；原解码内容流必须逐字保持。验收发现异常时保留生成的
实际 bytes/sha256/size，回执列出 output_review_failed，不用“未执行”假称没有
生成文件；签发链保持既有非阻断边界。

引擎专项四项通过：真实 text/checkbox/required/AP、精确 required 编辑与既有字段
保留、伪造/重复/超界/不支持来源拒绝、0/90/180/270 度 CropBox/rotation 保留。
node --import tsx bridge/form-design-create.test.ts 显示 4 passed；Node24 的
--test 封装只展示文件级 1 passed，不将其误称只有一条业务断言。字段删除专项
文件同时回归通过，日志 /tmp/pdf-form-create-engine-final-20261111.log；增加
Resources/Annots 验收后的专项日志 /tmp/pdf-form-create-preservation-final-20261111.log。

独立 pypdf 6.14.2 对 4 个旋转角度分别实读 text、checkbox、required 三阶段共
12 份真实文件：Fields/Kids/Parent/P/Annots/AP、复选框 V/AS/Yes/Off、必填位、
原正文/内容流和页面几何均通过。引擎输出 0 warning。实际 PDF 与 SHA 摘要在
/tmp/pdf-form-create-independent-20261111/，独立汇总 pypdf-summary.json，
来源与各阶段 SHA 在 engine-summary.json。该证据是直接引擎输出独立复读，
不是 HTTP 发布/真实浏览器验收。

pdf-form-create.ts 提供真实 NativeDraft 新建/属性面板；校验来源、能力、页面、
字段身份以及混存，支持 Undo/Redo。例行宿主 refresh 不会抹去正在输入的名称与
坐标；属性编辑使用来源 census 的 required 现值；预览刷新失败保留草稿并提示。
面板专项 6 passed，日志 /tmp/pdf-form-create-ui-final-20261111.log。

新增独立 smoke/pdf-form-create-server.py 与 pdf-form-create-smoke.mjs，不改已验收
旧脚本。使用真实 grant/cookie/CSRF、打包引擎、发布、下载、重开和共享内存仓储，
计划验证创建修订5、重开实际填写及撤销、required=false 修订6、独立下载结构。
脚本 node --check 与 Python py_compile 通过；截至本节写入尚未运行，不能宣称
新建与属性链路真实浏览器已通过。统一资产构建和浏览器结果由主任务补充。

自有前端模块及测试依赖闭包 TypeScript 检查通过（ES2022/esnext/bundler、
DOM/DOM.Iterable、vitest/globals、skipLibCheck），日志
/tmp/pdf-form-create-targeted-types-final-20261111.log。只修复 fixture 的 rect tuple
类型，未忽略诊断；这不等同整个编辑器全量构建通过。

主宿主集成新增独立 pdf-object-host.test.ts，7 项通过，日志
/tmp/pdf-object-host-green-20261111.log：三类对象设计的 exclusive 草稿中，对被禁用
的表单输入强制派发 change 不会混入 setFormValue；三类恢复草稿在对应 current
capability=false 时拒绝打开并保留原草稿；公开 edit.objects.editImage 真实接收
来源 image census 并显示正确初始坐标。该专项使用 jsdom/PDF.js fixture，不称真实
浏览器验收。主任务负责共享 pdf-main.ts 修改，本子任务只新增独立测试。

### ReportLab 真实来源资源字典误判与修复

root03 真实浏览器已触达 create 实际预览，但验收失败，未保存。证据目录
/tmp/pdf-form-create-browser-20261111-root03/，failure.json 显示 applied=[]，
实际输出已生成 3703 字节，回执为 pdf_form_create_output_review_failed。该次不能
称新建链路验收通过。final01 的隔离命名空间服务初始化超时、final02 已停止，
均未触达浏览器；真实运行由主任务普通 shell 执行。

根因是 ReportLab 来源 Resources 的 Font 为间接字典，而 pdf-lib 在插入 Widget
时将相同 Font 映射内联，另补空 XObject/ExtGState。原正文、原 F1 字体映射、
其他页面、字段及 AP 实际未变；原 Resources.toString() 把等价表示误判。最小
修复仅对 Font/XObject/ExtGState 类别解引用后比较映射，忽略三类自动空字典；
不放宽正文、实际资源映射、字段/AP、页面或 Annots 校验。

保存 root03 实际来源为 bridge/fixtures/form-design-create-reportlab.pdf，新建
form-design-create-reportlab.test.ts 先 RED，修复后 2 passed。正例验证实际三页
来源 text/checkbox；故障注入将原 F1 改为 ForgedFont，仍验收失败且实际 PDF
bytes/sha256/新字段保留，防止以放宽检查消除告警。日志
/tmp/pdf-form-create-reportlab-red-20261111.log、
/tmp/pdf-form-create-reportlab-green-20261111.log。smoke 在断言前保存每次
create/required-preview.json，保留完整实际回执供诊断。

独立 pypdf 修复后再次实读真实 ReportLab text/checkbox 输出，两者三页正文、
原内容流、F1 资源字典、页面几何、字段树及 AP 全部通过。来源 SHA256
b3e81b8aedfb7394d5d2255e3c9f7c172d32e515cf0cb62a0b93feee53963bec；文本输出
3703 字节，SHA256 b6d0ccb975157602548e526ee43910a947e53fc314ee12418270d93961e658a3；
复选框输出 4132 字节，SHA256
3566b719efaf6e13a9cda9e86d926f4b077beff42442b6513c23fcdd4e2c65a7。两者
applied=[0]、skipped=[]。证据 /tmp/pdf-form-create-reportlab-fixed-20261111/
pypdf-summary.json。本条仍是直接引擎独立复读；完整浏览器修复后结果待主任务补验。

### root04 真实浏览器两修订全链补验通过

主任务普通 shell 执行 root04，summary.ok=true；证据目录
/tmp/pdf-form-create-browser-20261111-root04/，日志
/tmp/pdf-form-create-browser-root04-20261111.log。Chromium 140.0.7339.16。
本子任务只读复核 summary、independent.json、实际下载文件大小/SHA，并用
view_image 目视 create-input.png、create-preview.png、reopened.png。

本次实际 manifest SHA256 为
e2af5a7a9380fde26ee45022598c5ebd78ed24ede6fda02141b480cc425491f3。
该值与早先 batch 的 5a02fa3e... 不同，期间其他会话重建了资产；root04 在自身
运行前后 manifest 一致，实际加载的 22 个 JS 均与当时磁盘 SHA 一一对照通过。
不能将本次浏览器结果归到早先 batch，也不将不同验收构建混为一批。

无既有字段的三页来源中，公开表单设计入口真实填写字段名 customer、矩形
[30,180,150,204]、required=true，暂存严格单项 createFormField；Undo 清空、
Redo 恢复同操作。真实 preview 与 preview.pdf 均 200，applied=[0]/skipped=[]；
目视实际 PDF 首页面正文及新增空文本框正常，执行清单显示创建字段成功，
实际预览确认框已勾选。保存请求绑定该预览摘要，真实 save 200，修订4→5。

真实下载 3703 字节，SHA256
4f86f3c53a748b10a33857a2e5a69a0a224ee61d0b665b8ce368954d6cfcd8ec；
下载身份与发布回执及重开 context 完全一致。经新 grant/cookie 重开修订5后，
实际填写表单控件可编辑，输入 Browser verified 并触发真实 setFormValue 草稿，
随后 Undo 清空该填写草稿，再进入字段属性。required 现值 true，取消勾选后
暂存严格单项 editFormFieldRequired，目标身份来自修订5实际来源。

第二次实际 preview 与 preview.pdf 均 200，applied=[0]/skipped=[]；勾选确认并
绑定该摘要后真实 save 200，修订5→6。第二次下载仍 3703 字节，SHA256
659474faf0ed9031bb840ca65573d0405f25d0b869186988fba5343d12028fb7；
下载身份与回执及重新授权打开修订6的 context 相同。目视 reopened.png 顶部为
修订6，customer 必填框未勾选，第一页原文与文本框可见，三页缩略图完整。

独立 pypdf 对两次真实下载检查通过：仅 customer 字段，FT=Tx，required 位先
true 后 false；Fields/Kids/Parent/P/Annots/AP 有效，三页正文、原内容流和页面
几何保留。真实来源 SHA256
3f8d00f67d2f9ecda2f557cdb567c9b73d8f09265a95a18f5dfea81d942e96fc，
运行后复读未变；pageErrors/consoleErrors/httpErrors 均为空。

两次发布 validation.ok 均为 false，具体原因 native_source_review_pending；
实际 PDF 下载链接照常签发并 GET 200，符合非阻断契约，不称业务事实/完整版式
验收通过。真实链路覆盖生产资产、PDF.js、grant/cookie/CSRF、打包引擎、发布、
下载、重开、实际控件填写与 required 二次编辑；文档/授权/产物仓储使用共享
内存，没有 HTTP 或 PDF 字节替身，不等同生产数据库或完整应用镜像验收。

本轮浏览器完整覆盖的是文本字段创建与 required 编辑；复选框创建已有直接
引擎、四旋转与独立 pypdf 证据，尚未完成同等浏览器全链。移动/缩放已有字段、
字段名称重命名、完整字体/样式、多行/选项/日期/单选/签名字段及复杂多控件
仍不在本轮已完成范围；未增加 OCR。

## 2026-11-11 日期、下拉、单选与已有控件布局扩展

本节更新此前“尚未完成”的表单范围；root04 的旧构建证据仍只证明其当时的
文本创建和 required 编辑，不将新代码混入旧浏览器验收。上游源码仍固定为
f8c17004fb730df11f0f743164ffd8b4281bb38c，未增加 OCR。

### 已实现的源码对齐

- 新建真实日期、下拉和单选字段，继续复用上游 applyFormFields。日期是文本
  字段加 AFDate_FormatEx/AFDate_KeystrokeEx，非独立 PDF 日期类型；只接受上游
  FormDesignLayer.tsx:30 的四种格式 yyyy-mm-dd、mm/dd/yyyy、dd/mm/yyyy、
  yyyy/mm/dd。只白名单接受字段/控件上的精确内建日期脚本，拼接或任意脚本
  不因此获得设计能力。
- 日期和文本的字号、对齐以及文本的多行/maxLen 是创建时属性。已存控件仅
  支持 rect/required，符合上游 App.tsx:4051 与 ipc.ts:708；未宣称已有字段
  名称、字体、默认值、选项或复杂样式可全面编辑。
- 单选创建为一个原子组，2–64 个独立控件、唯一导出值、最多一个初始勾选。
  下拉为真实 choice 字段，1–100 个唯一选项并校验初始值来自选项。暂不追加
  到已有单选组，不支持任意新建字段层级，名称仍为单层 ASCII。
- 已有控件编辑使用来源 SHA256 + fieldName/widgetId/widgetIdentity/
  expectedWidgetSha256 四项精确身份，不回退到名称猜测。可编辑安全标准
  AcroForm 的多控件和闭合 Parent/Kids 层级；原单控件删除限制保持不变。
  原始字段树先做深度/数量、重复子节点、Parent 闭合与环检查，再交给 pdf-lib。
  pdf-lib 生成层级时可能留下孤立非终端对象及共享 Kids 别名，该结构仍拒绝，
  未以放宽引用校验来接受它。
- 新增同页排列十一种：left/centerH/right/top/centerV/bottom、
  distributeH/distributeV、sameWidth/sameHeight/sameSize。显示空间算法和
  CropBox/旋转变换取自上游 App.tsx:4114、annotations.ts、FormDesignLayer；
  至少两个控件，分布至少三个。不同页面不混排。
- XFA、加密/受保护来源、签名字段及不可信动作保持明确能力拒绝。上游
  save-pdf.ts:894 的 addSignatureField 只创建空 /Sig 占位，未创建密码学
  数字签名且没有普通字段 AP；本轮未将其作为签名编辑或数字签名服务交付。
- 初始值/选项/单选导出值当前限可打印 ASCII，不冒充已有 CJK 字体覆盖；
  文本多行标志可创建，但初始文本仍不接受换行。控件属性/排列输出复核失败
  返回 pdf_form_widget_output_review_failed，保留实际 bytes/sha256/size 与
  告警；不得将此复核失败改为发布下载门禁。

### 定向验证

引擎 form-design-extended.test.ts 4 passed：真实日期动作/下拉值、单选 AP 与
选择状态、精确控件移动/required、两字段对齐和值保留。日志
/tmp/pdf-form-extended-engine-latest-20261111.log。

引擎 form-design-safety.test.ts 4 passed：跨页多控件标准层级的精确子控件
编辑，恶意日期脚本/XFA/空签名/循环树拒绝，全部十一种排列 × 0/90/180/270
旋转与 CropBox 偏移，以及严格参数、陈旧身份和跨页排列拒绝。包含相同输入
previewDigest 的确定性验证。日志 /tmp/pdf-form-safety-green-20261111.log。

前端 pdf-form-extended.test.ts 4 项与既有 pdf-form-create.test.ts 6 项共
10 passed；日志 /tmp/pdf-form-extended-ui-20261111.log。这两份测试的 scoped
TypeScript 检查通过，日志 /tmp/pdf-form-extended-types-20261111.log。既有
基础创建与删除定向回归分别 4 passed，日志
/tmp/pdf-form-create-compat-extended-20261111.log 和
/tmp/pdf-form-delete-compat-extended-20261111.log，未重复完整测试。

五阶段真实引擎产物均 applied=[0]/skipped=[]，独立 pypdf 再次读取原三页
ReportLab 正文/内容流/页面几何、字段 Parent/Kids/P/Annots/AP、日期动作、
下拉值与选项、单选状态，以及移动和左对齐结果全部通过。证据目录
/tmp/pdf-form-extended-independent-20261111/，摘要 pypdf-summary.json。
来源 SHA256 b3e81b8aedfb7394d5d2255e3c9f7c172d32e515cf0cb62a0b93feee53963bec。
日期 4055 字节，SHA256 6656032f19dff859d849085029c8d12b0c3c61978b5c5a8cd7fb3eb6eae71cca；
下拉 5650 字节，SHA256 3425b1fe65de4742fb9d2a9f910fae49b8343580054cf0377dddc6f1b6dcccbb；
单选 9481 字节，SHA256 81fe5bed310b0eb9ea59a628995f3aba376ca1f544bb170794b2a70910bfc123；
属性 9980 字节，SHA256 d59f332b696def2f06c3305a679b80fd6933200178455f370aa2edc94c4eddf7；
排列 10852 字节，SHA256 42125b9d8e44d21f3371770731797ea9f2384fb24eef5378f9ce72947a5d6cd9。
独立验证按 pypdf 实际表示识别下拉的 export/display 选项对，以及单选内部
/0、/1 状态名，不假设内部状态名必须等于用户可见 Yes/No。

### 浏览器验收入口与当前状态

新增 frontend/smoke/pdf-form-extended-smoke.mjs 和
pdf-form-extended-verify.py。复用真实 grant/cookie/CSRF、打包引擎、发布下载
路由和内存持久化仓储；没有 HTTP 或 PDF 字节替身。脚本设计覆盖六次修订
4→10：日期创建、下拉创建、单选创建、三字段实际填写保存、已有控件移动并
取消 required、两字段左对齐；设计修改核对实际预览并绑定 digest，逐次实际
下载与新授权重开，独立 pypdf 检查所有六次下载。保持 manifest 前后一致，
逐个核对实际加载 JS 与磁盘 SHA，收集浏览器及 HTTP 错误。

脚本 node --check 与 Python py_compile 已通过；本节写入时实际扩展浏览器
流程尚待主任务统一构建后执行，不能将脚本存在等同于浏览器通过。多控件层级、
四旋转排列已有定向引擎验证，尚未完成同等浏览器覆盖。XFA、数字签名、任意
已有字段重命名/字体编辑、已有单选组追加、任意层级新建和 CJK 初始值仍为
明确缺口。

### 扩展浏览器 root01/root02：保留失败，不计完整验收通过

root01 日志 /tmp/pdf-form-extended-browser-root01-20261111.log 记录验收脚本
读取重定向响应 body 引发未处理 Promise 拒绝。修复仅限新增扩展 smoke：先
检查 status=200、资产路径和 js/mjs，再读取 body；异步异常立即写 assetErrors，
最终严格断言无错误且有实际资产。未以忽略异常或重试来把失败改为通过，未改
生产模块。监听器的重定向/非资产跳过、js/mjs 哈希比对、body 异常捕获定向
模拟通过；原 root01 仍为失败记录。

root02 证据 /tmp/pdf-form-extended-browser-20261111-root02/，日志
/tmp/pdf-form-extended-browser-root02-20261111.log。运行使用 manifest SHA256
8611abed5ecbd0aaa71a632b2eb011fed78d8647e03247fb7a1457b8381cb98f。
实际完成 date、choice、radio、filled、properties 五次保存与下载，修订4→9。
properties 已保存下载，但重开后的额外 context fetch 在浏览器报
net::ERR_INSUFFICIENT_RESOURCES；failure.json 的 stage=properties-reopen。
assetErrors/pageErrors/httpErrors 均为空；consoleErrors 为四条浏览器资源
不足错误，服务端证据没有 HTTP >=400 响应。此证据尚不能确定资源不足的唯一
根因，也没有显示表单产品逻辑损坏；不得将这次运行标记为完整浏览器通过。

针对已经落盘的前五次真实下载，复用独立 pypdf verifier 的相同断言，仅裁掉
尚未执行的 arrange 阶段，未重跑浏览器或完整测试。partial-independent.json
记录全部五阶段通过：原三页正文/内容流/几何、Fields/Kids/Parent/P/Annots/AP、
日期动作、下拉选项/值、单选状态、已有控件移动及 required 均正确。五份下载
字节身份与各自真实发布回执一致，修订及 parent 连续；四次设计实际 preview
均 applied=[0]/skipped=[]。填写后实际值为 2026-12-25 / One / No，单选内部
状态 /V=/1、两个 /AS 为 /Off 与 /1；properties 保留这些值，日期移动至
[40,190,160,214] 且 required=false。

本子任务目视 date/choice/radio-input、filled-input、properties-input 和
properties-preview，contact 为 partial-review-contact.png：日期、下拉、
两个单选控件及第一页原文可见，属性实际预览显示填写后的三值与移动结果。
五次发布 validation.ok 仍为 false，唯一原因 native_source_review_pending；
真实下载均成功，未伪称业务事实或完整样式复核通过。

root02 来源 SHA256
57daaaa435211a10f2dce044c4c7094f056880247fdfed9fa0231de4b83ab073；
properties 实际下载 10856 字节，SHA256
77b79534252a1e0a3e2811de015ee1a37dc4b6677076198996e6a75111939802。
后续最终构建串行 root03 尚待执行，必须完整跑完排列、最后重开与独立六阶段
校验后，才能独立记录其实际通过结果；不将 root02 的部分证据拼接成 root03。

### 最终构建 root03：六修订真实浏览器全链通过

root03 为独立完整执行，不拼接 root01/root02 的部分结果。主任务使用独立打包
引擎 AGENT_REPORTING_PDF_ENGINE_DIR=/tmp/pdf-text-convert-form-runtime-20261111，
TMPDIR=/dev/shm/pdf-acceptance-root03，串行运行扩展 smoke。证据目录
/tmp/pdf-form-extended-browser-20261111-root03/，日志
/tmp/pdf-form-extended-browser-root03-20261111.log；summary.json 的 ok=true。
Chromium 140.0.7339.16。此前脚本故障与浏览器资源失败仍保留原记录，未用
自动忽略或重试将其改判通过；本结果也不证明 root02 资源故障的唯一成因。

本次实际 manifest SHA256 为
6133a8fcdea51af52e3ae39ae5079dae5875acb4b161fda884e05e793cb86cc8。
smoke 运行前后 manifest 一致，实际加载的 30 个 JS/mjs 与磁盘 SHA 对照通过；
本子任务又独立复读保存的 manifest 与全部 30 个当前磁盘资产，身份仍一致。
sourceSha256 为
782f9b3652d16838774d98f4f74eba3ac0a4a27cb793ed09d220c176080fc505，
服务端运行后实际来源复读未变。

六次公开入口操作顺序与真实修订：

1. 修订4→5：日期 customer_date，初始 2026-11-11，yyyy-mm-dd，required=true，
   区域 [30,180,150,204]；实际 Undo/Redo 验证相同操作可撤销恢复。
2. 修订5→6：下拉 customer_choice，选项 One/Two，初始 Two，required=true，
   区域 [80,140,200,164]。
3. 修订6→7：单选 customer_radio，两个真实控件 Yes/No，初始 Yes；创建原子
   组后实际重新读取并填写。
4. 修订7→8：通过真实填写表单控件提交三项 setFormValue，实际保存
   2026-12-25 / One / No，重新授权打开后值一致。
5. 修订8→9：已有日期控件 rect 改为 [40,190,160,214]，required=false；目标
   来自当前修订的四项精确控件身份。
6. 修订9→10：选择日期和下拉控件执行 left 排列；最终日期和下拉 X 均为40，
   下拉区域 [40,140,160,164]。两个单选控件仍位于原位置，已填值保留。

五次设计操作的真实 preview 均 applied=[0]/skipped=[]，实际预览确认框勾选
后保存请求绑定对应 previewDigest。每次保存均 revisionRegistered=true、
parentRevision 连续，实际下载 GET 成功，字节大小/SHA 与发布回执一致；六次
均通过新 grant/cookie 重新打开，context 修订与 sourceFile SHA 匹配该下载。
最后重开修订10，再次检查四个控件属性、日期非必填、日期/下拉 X=40，以及
三项填写值。pageErrors/consoleErrors/httpErrors/assetErrors 均为空。

独立 pypdf 实读全部六次下载通过，结果 independent.json：原三页正文、内容
流和页面几何保留，Fields/Kids/Parent/P/Annots/AP 有效；日期 AA 精确，下拉
选项和选择值正确，单选最终 /V=/1、两个 /AS=/Off 与 /1；移动、required 及
排列矩形均符合预期。本子任务再次核对六份真实下载的字节身份、连续修订和
重开 context，并目视 arrange-preview.png、reopened-properties.png 与
reopened-filled.png：第一页原文可见、日期和下拉真实左对齐、右侧单选选中，
修订10的填写栏显示 2026-12-25 / One / No。

六份真实下载身份：

| 阶段 | 字节 | SHA256 |
| --- | ---: | --- |
| date | 4055 | dcceaa697062a781f22b4e29e7d317ede9acb2da52b751833b37c9b16ea66378 |
| choice | 5650 | eb7d399336f9e9d4b588908d6cf66fa19e92d5e0fc3367e11e53e7bc61069289 |
| radio | 9481 | e8da34145fa74a6d259729ee6fc3fd79038d95d57ae92fcfc1ccc2eb0917388a |
| filled | 10355 | 7f6e6a50c2adb2f52d6de008881c8c94ae9019c8e42688191192a998cd12f7e7 |
| properties | 10856 | 6f4d33b728f63fa8484b083055659ae41f69d3a3b5e88198591705a8078b319a |
| arrange | 11731 | 7af5e971438cb9c7e4354246bc542fc53a0c26560b1d4fb00a01d3ec1594d536 |

六次发布 validation.ok 仍为 false，具体原因均为 native_source_review_pending；
真实文件链接照常签发，不把交互链路通过等同于业务事实或完整样式复核通过。
覆盖范围是真实浏览器、生产静态资产、PDF.js、授权/CSRF、独立打包引擎、真实
发布下载路由与重开；文档/授权/产物持久化仓储仍使用共享内存，不等同于完整
生产数据库或应用镜像验收。

本次完整浏览器补齐日期/下拉/单选创建、真实填写保存、已有控件 rect/required
编辑和 left 排列。其余十种排列、跨页多控件标准层级与四旋转仍以定向引擎
证据为准，未宣称同等浏览器覆盖。XFA、密码学数字签名、任意已有字段改名或
字体编辑、已有单选组追加、任意层级新建、CJK 初始值仍为明确缺口；未增加
OCR。本节完成后表单验收文档冻结，不改变生产模块或资产哈希。

## 2026-11-11 后续批：层级新建与已有单选组追加

本批继续使用固定上游 f8c17004fb730df11f0f743164ffd8b4281bb38c，复用
save-pdf.ts 的 applyFormFields 与 pdf-lib 1.17.1 的字段层级和 radio API。
此前“任意层级新建/已有组追加”缺口在本批按明确安全边界补齐，原 root03
六修订证据不替代本批验收；本节记录时新的浏览器流程尚待统一构建执行。

### 层级字段名称与树闭合

createFormField 沿用原操作，字段名允许1–16个点号分段，每段使用
[A-Za-z_][A-Za-z0-9_-]{0,63}，总长度最多256。新建前拒绝空段、重复名以及
终端前缀冲突：已有 party.customer 时，不得创建 party 或
party.customer.detail；已有 party.customer.name 时，可在相同真实 parent
下创建 party.customer.code。字段树原始检查进一步确认兄弟节点部分名称
唯一、非空且不含点号，Parent/Kids 唯一闭合；不把安全的已有层级一律禁用。

依赖 pdf-lib 的 PDFAcroNonTerminal.create 本身注册一次 dict，而
PDFForm.findOrCreateNonTerminals 又把相同 dict 注册一次，造成新父节点存在
未使用的重复注册。适配器只在本次 applyFormFields 后清理“本次新注册、同一
dict、未被任何 PDFRef 引用、且同 dict 有唯一规范树引用”的多余别名。字段
构建仍完全来自依赖，不另造字段引擎；不可清理或放宽来源中已有的孤立别名。
新产物复读检查规范非终端字典、原有字段、页面内容/资源、Annots、AP 和新字段
值；保存期间父节点被篡改的故障注入返回 warning 并保留实际 bytes/SHA/size。

### 已有单选组追加

新增独占操作 appendRadioWidget，严格字段为 kind/sourceSha256/fieldName/
widgetId/widgetIdentity/expectedWidgetSha256/pageId/rect/exportValue。复用
现有四项精确控件身份作为不可变来源 radio group 的锚点，不回退到字段名称
猜测。新控件使用固定源 applyFormFields 的已有组分支，exportValue 为唯一
非空可打印 ASCII（最多128字符），组最多64控件。追加目标页必须属于精确
来源，矩形在原 CropBox 内。追加本身不改变原有选择或 required，新控件为 Off。

输出使用 updateFieldAppearances=false；新增控件的 AP 由原生 addOptionToPage
即时生成，原有 AP 不统一重画。复读核对旧控件字典、引用和 AP 内容流字节、
旧选择/选项/required、其他字段、Annots、原三页正文/资源/几何；仅一个新
Widget 和一个新选项。复核异常返回 pdf_radio_extension_output_review_failed
并保留实际文件身份，不把告警升级为发布下载门禁。主任务已登记 append 的
HTTP 故障注入分支，最终 HTTP 执行证据待统一打包验收补记。

前端独立 binder 提供“追加单选选项”，按字段去重列出实际 radio group、已有
选项及选择；支持目标页和矩形。严格校验 source/四身份、重复选项、能力、
独占草稿及恢复草稿；readonly/disposed/stale/mixed 状态不追加。层级新建与
恢复共用同样的名称及前缀规则。旧独立单控件 remove 判定未放宽，层级/多控件
继续不能通过旧删除入口。XFA、真实密码学数字签名、CJK 初始值仍不受支持，
未增加 OCR；未以字体闭包未经验证的假设直接开放字符集。

### 定向验证与真实输出

- form-hierarchy.test.ts RED→GREEN，4 passed：规范父节点创建/复用、前缀与
  重复/深度限制、拒绝修补来源已有 alias、父节点后写损坏保留输出告警。
  日志 /tmp/pdf-form-hierarchy-red-20261111.log、
  /tmp/pdf-form-hierarchy-green-20261111.log。
- form-radio-extension.test.ts RED→GREEN，4 passed：四旋转追加保留旧值/AP，
  四身份/来源/几何/重复选项/未知属性拒绝，安全层级组追加，后写损坏保留
  实际输出。日志 /tmp/pdf-form-radio-extension-red-20261111.log、
  /tmp/pdf-form-radio-extension-green-20261111.log。
- pdf-form-next.test.ts 新增4项与原 create 前端6项共10 passed，scoped tsc
  通过。日志 /tmp/pdf-form-next-ui-{red,green}-20261111.log、
  /tmp/pdf-form-next-types-20261111.log。
- 原安全引擎4项、旧 remove 4项与 ReportLab2项定向通过。旧 create 的拒绝
  a.b 断言因已授权层级功能过期，同前端一起改成无效 a..b 后，该case定向
  通过；其余原create案例首轮已通过，未重复完整项目测试。对应日志
  /tmp/pdf-form-hierarchy-compat-safety-20261111.log、
  /tmp/pdf-form-next-remove-compat-20261111.log、
  /tmp/pdf-form-next-reportlab-compat-20261111.log、
  /tmp/pdf-form-next-create-name-compat-20261111.log。

实际独立引擎生成五阶段：party.customer.name=Alice，复用 parent 新建
party.customer.code=C001，再创建 party.consent 的 Yes/No（初选No）、向原组
追加 Maybe，最后真实 setFormValue 选择 Maybe。每阶段 applied 正常、skipped
为空。独立 pypdf 全部通过，证据
/tmp/pdf-form-hierarchy-radio-independent-20261111/pypdf-summary.json。
验证原三页正文/内容流/几何、完整规范字段树与 Parent/Kids/P/Annots/AP，
追加前后旧控件引用/字典与 normal/down AP 流逐字节身份相同；No 保留为 /1，
新 Maybe 初始 /Off，后续实际填值变为 /2。pypdf 比较显式规范化引用的对象号
和 generation，排除不同 PdfReader 进程内存地址，未忽略实际 PDF 字典或 AP。

来源 SHA256 b3e81b8aedfb7394d5d2255e3c9f7c172d32e515cf0cb62a0b93feee53963bec。
追加实际输出11136字节，SHA256
904c8a943615450c38f579187121f87ea523f8c30c854baae9007b32510ca3af；
最终填写输出11256字节，SHA256
093954cd70056881e65e8a50c91fe10788e6aaf971ef49395977d9a89b33122e。

新增 frontend/smoke/pdf-form-hierarchy-radio-smoke.mjs 与同前缀 verify.py，
支持 PDF_SMOKE_STATIC_DIRECTORY 指向主任务冻结的静态资产。脚本设计为真实
五修订4→9、逐次实际预览/确认/save/download/reopen，包含前缀冲突无草稿、
两级父节点复用、已有层级 radio 的追加/Undo/Redo、保留No及真实选择Maybe，
并实读全部五次下载。node --check 与 py_compile 通过；此处尚不将脚本存在
写成新浏览器验收通过。

### 本批真实浏览器 root01：五修订全链通过

主任务完成独立冻结资产与运行包后，本批真实浏览器首次执行完整通过。证据
/tmp/pdf-form-hierarchy-browser-20261111-root01/summary.json 和 independent.json，
summary.ok=true，Chromium 140.0.7339.16。此结果更新本节“待执行”状态，不改变
早先扩展批 root01/root02 的历史失败记录，也不将各批构建或文件身份混同。

运行使用冻结静态目录 /dev/shm/pdf-next-static-20261111-root02；实际 manifest
SHA256 为
4f618f6766d44112982ccf8fd18384db72fec7bd8ba2e245d14c5f169fa68e09。
同次 smoke 核对运行前后 manifest 一致，实际加载36个JS/mjs的字节与冻结磁盘
资产一致，assetErrors为空。本子任务再次复读保存的 manifest 并重算其身份，
与 summary 一致；未重跑浏览器或测试，未另行重读运行期 tmpfs 资产。主任务
记录运行包 /dev/shm/pdf-next-runtime-20261111，CLI SHA256
d57204f18ee14eb55d9ac3d1b98a4e3cfa4b1e2dc941417072d64bdfaac2c270。

真实操作及修订连续为4→9：

1. 新建 party.customer.name=Alice，修订5；真实 Undo/Redo 恢复同一来源操作。
2. 实际尝试新建 party，与已有终端路径冲突，前端返回明确前缀原因且草稿为空；
   随后复用规范 parent 创建 party.customer.code=C001，修订6。
3. 创建已有层级 party 下的 party.consent 单选组，选项Yes/No、初选No，修订7。
4. 从公开“追加单选选项”入口，以当前来源及精确四项控件身份追加Maybe，
   新矩形[130,170,150,190]；真实Undo/Redo，随后实际预览确认保存为修订8。
   重开后已有No仍被选中，Maybe出现在真实填写控件选项中。
5. 通过实际填写控件选择Maybe并保存为修订9，再次授权重开后Alice/C001/Maybe
   三值一致，第三个单选控件实际选中。

四次设计操作的真实 preview 均 applied=[0]/skipped=[]，保存请求绑定实际
预览确认的 digest；五次 save 均 revisionRegistered=true，parentRevision
连续。每次实际下载字节大小/SHA均与发布回执一致，重开context修订与
sourceFile SHA等于对应下载。本子任务又逐份重算五份下载身份并核对这些回执，
未重新执行生成或完整测试。来源SHA256
2f1cf2b005ee16aeef91be3889df07f87a1a4ddbd0a1c2bc8fe601e817ad06e0，
同次服务端复读sourceUnchanged=true；pageErrors/consoleErrors/httpErrors/
assetErrors均为空。

同次独立pypdf五阶段全部通过：原三页正文、原内容流、页面几何及规范字段树
Parent/Kids/P/Annots/AP有效，层级父节点真实复用；追加前后旧radio控件的
对象引用、字典、normal/down AP内容流保持原样，radioSurvivorsVerified=true
仅用于append阶段。追加仍保留No=/1，新Maybe为Off；最后实际填写后选择=/2，
允许预期的AS状态变化，不冒称填写过程旧AS保持不变。本子任务目视
append-preview.png与reopened-filled.png：实际预览显示三枚单选控件，追加时
中间No仍选中；最终修订9的真实填写栏与PDF外观均显示第三项Maybe选中，两个
文本值及三页缩略图完整。

五份实际下载身份：

| 阶段 | 修订 | 字节 | SHA256 |
| --- | ---: | ---: | --- |
| name | 5 | 3959 | 8e0e8637d15e3d9a088ee5e438c32fd63ce227526157392c79c4ddb9379d5b26 |
| code | 6 | 5433 | b1ebc7fcd6008fdc1b7da881b549b399e0bea97139b783e52cb6489f7b54370a |
| radio | 7 | 9253 | 5c1703761f1792cce0e1ddfe8772ea32351549b17f36154c8237c9ad127b879a |
| append | 8 | 11136 | 5ebad56bb23d9a770d7234d63adc5ff913834c84a0047d66aa0a22f9e0401ff1 |
| filled | 9 | 11256 | 7aafaec1150b800ea85002e07cba7c9ad99f3c6c7a5bcfee9a47c0af950b3856 |

五次发布validation.ok仍为false，原因均native_source_review_pending；真实PDF
下载照常签发，不把交互/文件结构验收通过称作业务事实和完整样式验收通过。
主任务另已确认新增HTTP故障注入
test_form_design_postwrite_review_warning_keeps_actual_http_download[appendRadioWidget]
1 passed，覆盖后写复核告警仍保留实际下载的非阻断契约。

本批真实链路包含生产冻结资产、PDF.js、grant/cookie/CSRF、独立打包引擎、
真实preview/save/publication/download及新授权重开；持久化仓储使用共享内存，
不等同生产数据库或完整镜像验收。层级新建和已有层级radio追加的本批浏览器
缺口现已补齐；XFA、真实密码学数字签名、CJK初始值及任意已有字段重命名/字体
编辑仍未支持，未增加OCR。旧安全单控件remove门禁未放宽。本次仅更新验收
文档，未修改源码、构建或资产哈希；本批表单文档冻结。


### 本批统一浏览器最终证据（root复核，2026-11-11）

/tmp/pdf-form-hierarchy-browser-20261111-root01/summary.json与independent.json均ok=true。真实修订4→9、五次保存下载重开，party.customer.name/code与party.consent、前缀冲突拒绝、追加Maybe/UndoRedo/旧选择保留/填写Maybe均通过。五份PDF独立字段树/AP/Annots/原正文验证通过；仅append阶段核验旧AS/AP严格不变。
36资产哈希一致，四类错误数组为空，来源不变；HTTP后置复核故障仍保留实际追加结果下载1PASS：/tmp/pdf-next-radio-http-fault-20261111.log。
冻结manifest和CLI、完整证据与本地夹具边界见NATIVE_PDF_SELECTION_IMAGES_HIERARCHY_ACCEPTANCE.md；不冒称生产或业务内容验收通过。


## 既有单文本控件属性编辑（2026-11-11，文本属性批次）

固定源仍为 /home/junge/pros/genoffice-source-full，ref
f8c17004fb730df11f0f743164ffd8b4281bb38c。固定源 App.tsx 的既有控件
设计编辑与 FormWidgetEditInput 当时主要处理矩形/必填；本批明确通过其
pdf-lib 原生文本 setter 实现四项既有字段属性，不冒称固定源既有 UI 已完成
相同四项。新操作 editFormTextProperties，精确来源 SHA 与 fieldName、
widgetId、widgetIdentity、expectedWidgetSha256 四项身份均须相符，每批仅此
一项操作；恢复草稿同样重新核对来源、能力与完整身份。

当前范围为安全独立单控件文本字段：multiLine、maxLen、textAlignment、
fontSize。长度整数 0–4000（0 删除 /MaxLen），字号 6–72；非零长度不能小于
现值，拒绝截断。前端只写发生改变的属性，无修改给出明确原因且不创建草稿。
UI、stage 与 restore 均保留身份、独占、只读/保存中/已关闭、来源变化约束；
例行 refresh 保留正在输入的设置，预览刷新失败保留已入草稿的操作。

安全门禁不扩大旧单控件 remove 范围。仅支持原 designEditable 控件、规范树，
无动作/日期/控件级 DA/密码/富文本/文件选择/comb/只读、多控件字段不开放。
现值限可打印 ASCII 及 CR/LF；DA 需唯一明确正字号 Tf，与 normal AP 本地唯一
字体资源一致；字体为无自定义 FontDescriptor 的 Type1 + WinAnsi 标准 Latin
12 字体（Helvetica/Times/Courier 的常规、粗体、斜体及粗斜体）。Symbol、
ZapfDingbats、自定义字体、CJK 字体闭包未验证，继续不开放；不新增 OCR。

writer 使用目标字段原 BaseFont 嵌入字体并仅更新目标 AP，不调用会处理全部
脏字段的全局 refreshFieldAppearances；Times-Roman 保持 Times-Roman，不偷偷
改成 Helvetica。原值不变；field/widget refs、/V、其余字段键、widget 非 AP
键、页面正文/几何、Annots、所有原始非目标间接对象与旧 AP 原字节均须保持。
保存 updateFieldAppearances:false，后写独立复读复核。后写复核失败返回
pdf_form_text_properties_output_review_failed 告警，同时保留实际输出 bytes/
SHA/size，不将已生成产物误当成不存在，不把告警标为验收通过。

本子任务已完成以下定向证据（未重跑完整测试）：

- 新 engine form-text-properties.test.ts：5 PASS；包含四属性、现值长度拒绝、
  限长移除、伪造身份、动作/CJK/custom-font/readonly/multi-widget 拒绝，
  Times 原字体保留及后写破坏其他字段时告警并保留真实字节。
- 新 UI pdf-form-text-properties.test.ts：4 PASS（先 RED 后 GREEN）；包括
  四属性 stage/restore、属性边界/未知键/四项伪造身份/混合草稿拒绝、真实
  DOM 面板、无修改无草稿、输入保留及预览失败后草稿保留/UndoRedo。
- scoped TypeScript noEmit PASS；两个原 engine form-design/safety 测试文件
  PASS，原前端 pdf-form-design.test.ts 的4个用例 PASS；限定本批路径的
  git diff --check PASS。未修改共享 build/hash/package/发布契约。
- 新真实浏览器 harness pdf-form-text-properties-smoke.mjs 已 node --check；
  独立 pdf-form-text-properties-verify.py 已 py_compile 并在直接实际 PDF
  五阶段实跑 PASS。浏览器 harness 强制 PDF_SMOKE_STATIC_DIRECTORY，支持
  REPORT_EDITOR_CHROMIUM_EXECUTABLE，由主任务统一冻结包、服务和浏览器。

直接实际 PDF 证据位于 /tmp/pdf-form-text-properties-direct-20261111：
真实 ReportLab 三页来源 SHA256
b3e81b8aedfb7394d5d2255e3c9f7c172d32e515cf0cb62a0b93feee53963bec；
调用 createDesignField 新建 name=Alice/code=C001，然后通过本 writer 改为
多行/32/center/16，再改为单行/无限/right/18，最后调用固定源
applySaveRequest 真实填写 Alice Updated。独立 pypdf 逐份核验原三页正文、
内容流和几何、规范 Parent/Kids/P/Annots、目标 refs/原值/真实 AP、字体字号及
非目标 code 字段字典/AP 引用和内容保持，五阶段全部通过。本直接链路无
HTTP/publication/browser，仅证明文件与适配器行为，不能代替真实浏览器验收。

本批真实浏览器验收证据待主任务统一冻结运行完成后追加；不把 harness 语法
检查或直接 PDF 证据标成真实 grant/cookie/CSRF/preview/save/download 验收。
