# PDF 待保存字段剪贴板增量验收（2026-11-14）

为待保存createFormField字段增加复制/重复/粘贴右键菜单和Ctrl/Cmd+C/D/V。剪贴板仅存编辑器内存且绑定不可变来源SHA，不写系统剪贴板或localStorage；复制不改草稿，Duplicate不替换复制内容；paste/duplicate复用既有批创建stager和NativeDraft，一次动作一次历史。自动生成同父唯一叶名，保留值、选项、必填、字体尺寸/对齐等规范创建属性；单页radio按整组复制。支持同文档跨页粘贴，保留相对布局并整体夹到目标CropBox，放不下或超500预算零修改。

输入框、textarea/select、contenteditable空值/true/plaintext-only、IME、模态/菜单保留键盘拥有权；菜单回调同时绑定菜单实例、模型/草稿快照和选区；失效回调不写错条目。活动页面接收无选区粘贴，多页canvas不会重复提交。另修pending右键删除误走来源字段删除的入口，按选中pending名称删除，不影响其他创建。

## 验证

- /tmp/pdf-form-clipboard-front-final2.log：5文件108通过0失败（核心clipboard6、canvas32、batch2、form-create7、object-host61）。包括深拷贝/来源变化/命名长度/预算/组布局/跨页radio拒绝、双canvas跨页粘贴一次commit、无选区paste、过期菜单/权限/输入拥有权。React act警告保留。
- /tmp/pdf-form-clipboard-service.log：仅新增include_copy=True参数1通过1未运行，实际NativeEditorService/隔离CLI/预览确认/保存/下载；pypdf检查复制字段Alice和必填保留，原字段/原正文/来源身份保留。它是规范创建载荷的独立服务验证，不冒称同一个浏览器fixture的HTTP保存。
- /tmp/pdf-form-clipboard-types-final2.log与批创建基线逐字节相同，仍632条既有诊断、退出2，无本批PDF文件诊断；不声明全局类型/生产构建通过。没有新增后端操作/路由/签发步骤。
- 独立代码审查无重要发现；双canvas测试按审查建议补充。

## 真实浏览器及独立回读

PDF_FORM_CLIPBOARD=1运行smoke/pdf-form-batch-create-smoke.mjs，首轮/tmp/pdf-form-clipboard-browser、日志同名.log：真实源码宿主/FormDesignLayer/PDF.js、CtrlC/D/V、输入内CtrlD不改草稿、右键copy/paste和实际CLI预览通过。pypdf确认6字段Field1/2/3、Field2_copy1/2、Field1_copy1及副本文字/必填、checkbox=/Yes、AP和原正文。clipboard-fields.png实际目视；布局保持且副本可重叠，不声明自动避让或像素级源布局等价。

最后补无选区粘贴后，用前轮原PDF字节及6条真实草稿作恢复fixture（不重绑原SHA）执行最小续验；/tmp/pdf-form-clipboard-browser-final，日志/tmp/pdf-form-clipboard-browser-final.log。选择Field2复制，完成属性卡清空选区，再从活动编辑器CtrlV生成Field2_copy3，第7字段进入实际PDF预览；pypdf确认7个独立字段/值/AP/原正文，sourceSHA不变。未重跑前轮完整创建/编辑删除矩阵。证据evidence.json、fields.pdf、unselected-paste-narrow.png、actual-preview.png。390px属性卡left62/right282/宽218，无横向溢出；截图已目视。pageerror及HTTP>=400为空。

两轮都使用Vite源码/烟测API适配器及既有隔离CLI，未进行生产静态包或生产HTTP保存验收。Vite其它格式依赖扫描提示fast-xml-parser/saxes/utif2保留。脚本语法/Python语法及git diff --check通过。未提交、部署或开启生产开关。

## 剩余缺口

既有PDF字段复制/默认值与任意字体/AP语义仍未开放；跨页radio组不允许部分复制；系统/跨文档剪贴板不支持。大批量性能未验收。源任意复杂多Widget、跨页控件迁移等仍单列。剪贴板属于宿主适配，不宣称固定源所有clipboard子语义已对齐。整体PDF目标仍active。
