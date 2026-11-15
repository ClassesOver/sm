# PDF 已有安全下拉字段选项编辑验收（2026-11-11）

## 固定源事实与范围

固定源 `/home/junge/pros/genoffice-source-full` 的 HEAD 已重新核对为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`FormDesignLayer.tsx:639` 有 choice 选项输入，但该处使用待创建 `input`。`App.tsx:4052` 的 `patchDesignField` 对已有 Widget 仅提取 rect/required；固定源 `src/shared/ipc.ts:705` 的 `FormWidgetEditInput` 无 options；`src/main/save-pdf.ts:980` 的 choice 分支仅新建 Dropdown。本批是用户持续授权的更多字段属性增量，不声称固定源已实现已有选项编辑，也不据此冒称列表字段已完成。

复用 `editFormWidget`，新增 `choiceOptions?: string[]`。选项编辑须单独保存，与 rect、required、newFieldName 互斥；保留来源 SHA 及原完整 fieldName/widgetId/widgetIdentity/expectedWidgetSha256 绑定。

仅接受来源整体通过既有表单安全复核、精确安全单 Widget、未只读、不可自由输入、非多选、未排序的 PDFDropdown。原 Opt 必须是可读字符串或 export/display 相同的二元组，1至100条、唯一、每条1至200个可打印 ASCII 字符。拒绝复杂 I/TI 选择/滚动索引、不同 export/display、字段/Widget或祖先携带 A/AA（包括通用设计已识别的精确日期动作）、非正常或缺失 AP、多 Widget、PDFOptionList、XFA、签名/保护、任意动作及不闭合树等不支持来源。当前 V 和默认 DV（包含合法继承值）只能不存在或是原选项中的标量字符串；新选项必须继续包含它们，禁止静默清空或换值。空操作拒绝。

## 最小实现与保留契约

`bridge/form-design.ts` 新增纯读 `inspectDesignChoiceOptions`，在既有 Widget metadata 发出 choiceOptionsEditable、choiceOptionsReason；仅可编辑目标发 choiceOptions、choiceValue（无选中为 null）、choiceDefaultValue（无默认值为 null）。`form-design-properties.ts` 复用原生 `PDFDropdown.setOptions`，明确 `save({updateFieldAppearances:false})`，不调用 select、不标记 dirty、不重建字段或 AP。

pdf-lib 的 Dropdown `setOptions` 仅改 Opt；其普通 AP 只绘制当前选中值。因此保留现值时可以原样保留 AP。PDFOptionList 的 `setOptions` 会标 dirty，普通 AP 绘制全部选项；强行保留 AP 将显示旧列表。因此列表不开放，不能把 Dropdown 证据当成列表保真证据。

写后比较所有间接对象，唯一允许变化是目标字段字典的 Opt；V/DV、Ff、DA、AP、原始流字节、父树、字段/Widget 引用、页面内容和所有无关资源都保持。回读真实 options、新来源 Widget 可编辑性与原引用。后置复核异常使用既有 receipt 返回实际 bytes/SHA/size 和 `pdf_form_widget_output_review_failed`，不丢文件、不标记验收通过。公共保存/签发由 root 接线并验收。

前端既有“字段属性”面板对 choice 增加“下拉选项（每行一个）”，初值来自模型，显示当前不可编辑原因，严格保留行内字符；不 trim、去重、替换现值或默认值。仅真正改动时序列化 choiceOptions；不携带未改 rect/required/newFieldName。Undo/Redo、预览确认和保存重开复用既有链路。公共 `pdf-main` 恢复草稿透传由 root 修改。

## 实际定向测试与探针

- Native 新增 `bridge/form-choice-options.test.ts`：先真实 RED 3 failed / 2 passed（旧 metadata 缺失及 validator 拒绝），实现后新增5项及受影响旧7项共12/12 PASS。原始日志已直接落盘 `/tmp/pdf-next-choice-options/native-{red,green}.log`。
- Frontend 新增 `src/pdf-form-choice-options.test.ts`：先真实 RED 2 failed / 1 passed（旧 validator 拒绝及 textarea 不存在），实现后新3项及旧13项共16/16 PASS。原始日志 `/tmp/pdf-next-choice-options/ui-{red,green}.log`。未重复全量测试。
- Native 覆盖根字段/层级字段重排和增删未选项、保持原现值与 DV、逐对象和原始 AP 保留；删除现值/DV、重复/非法/空/过量/无变化选项写前拒绝；editable/multiselect/sorted/export不一致/I/TI/readonly/multiWidget/list/missingAP 边界；旧完整身份/来源摘要/混合属性拒绝；输出回读故障保留实际新选项 bytes。
- root交叉审阅补充：已知日期 AA 挂到 Dropdown 字段或 Widget 原先会沿用通用设计许可；专项先真实 RED（choiceOptionsEditable意外为true），仅在choice纯读器显式拒绝字段/祖先与Widget A/AA，修复后本文件6/6 PASS，记录 `/tmp/pdf-next-choice-options/actions-{red,green}.log`。保留原普通日期字段支持，不改变全局动作许可。
- UI 覆盖完整旧身份、仅 choiceOptions staging、无变化及选中值/default丢失拒绝、来源 metadata 不完整/不可编辑拒绝、恢复草稿 malformed/mixed 拒绝、面板原选项回显及真实 Undo/Redo。
- 独立原生序列位于 `/tmp/pdf-next-choice-options/independent/`：从真实三页来源创建 choice/code，原值 Two，选项 One/Two 修改为 Three/Two/Four，保存后仍 Two 且 AP 不变，再全桥填值 Three。独立 pypdf 核验通过树闭合、所有原对象仅目标 Opt 例外、AP原字节与引用、无关code、正文和页面几何保留。日志 `native.log` 与 `independent.json`。本证据不是本轮 browser。
- 选项 PDF SHA-256 `67b398c044d292fb8c615ae3a211b70f1f985555bd4538ed04815696f97ce35e`；后续填值 PDF `49b6eb2320f35d004808722fb44c48250a781db2aa570f0c324dcb87f86ae726`。
- 定向 strict tsc 已修复触及共用 snapshot 分支的 PDFDict 类型窄化；最终 `/tmp/pdf-next-choice-options/typecheck-final.log` 只剩6项既有宿主 resourcesPath / 未解析 GenOffice UI 声明诊断，无本批生产文件诊断，不能声称全项目 typecheck 通过。首次从仓库根目录运行缺 Node types 的命令属于工具路径错误，不作代码失败证据。

## 浏览器脚本与统一验收

专属 `frontend/smoke/pdf-form-choice-options-smoke.mjs`、`pdf-form-choice-options-verify.py`。环境 `PDF_FORM_CHOICE_OPTIONS_SMOKE_DIRECTORY`、`PDF_FORM_CHOICE_OPTIONS_SMOKE_PORT`（默认4345），沿用统一 `PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR` 与 Chromium 路径。使用独立脚本名，不覆盖前批名称编辑证据。

脚本使用真实 grant/cookie/CSRF、冻结生产静态资产、打包引擎、预览确认、保存签发下载及重开：创建 choice/code；先拒绝删除当前值；实际编辑未选项；Undo/Redo；保存后重开面板回显；在新选项 Three 上填值再保存重开；独立 pypdf 比较真实下载文件。Node syntax、Python compile、限定 diff 检查已通过。统一冻结后真实 browser 已 exit 0，四次实际保存/下载/重开及独立 pypdf verifier 通过，root 已目视最终 UI。证据 `/tmp/pdf-png-choice-rich-form-browser/summary.json`，37 个实际 JS 响应匹配冻结资源，来源未变且错误列表为空。选项修改实际下载 SHA-256 `aab514a0da7189fafa18b41d030f0352f89ec8736250fc67b42324d3178730a4`，后填 Three 为 `bb2ad1afdd582161a1c327f3c5f4295ad07e74aefd9bd0c40ac394a078995290`。恢复草稿 host 新专项1/1、HTTP 后置复核告警仍签发专项1/1通过；初次 HTTP 失败是测试误将合法 export/display Opt 二元组当成字符串，修正语义断言后只重跑该用例。统一证据、全站预算限制见 `NATIVE_PDF_PNG_CHOICE_RICH_TEXT_ACCEPTANCE.md`。

仍不含列表 AP 重建、export/display 分离编辑、多选/可输入下拉、共享多 Widget、默认值修改、值替换、复杂选择索引、字体/AP重新生成或 OCR。
