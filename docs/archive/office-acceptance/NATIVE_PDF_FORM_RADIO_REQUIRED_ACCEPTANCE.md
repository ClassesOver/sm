# PDF 安全单选组整组必填保真修复验收（2026-11-11）

## 先探针辨别现状

固定源 `/home/junge/pros/genoffice-source-full` commit `f8c17004fb730df11f0f743164ffd8b4281bb38c` 已有 required 属性；本地 `editFormWidget.required` 也已能通过 `applyFormWidgetEdits` 调用正式 `field.enableRequired/disableRequired`。本批不是从零新增必填功能。

真实基线 `/tmp/pdf-next-radio-required/baseline-probe.log`：安全组、unison组、共享AP组都被旧generic路径接受为成功；缺失AP走后置复核失败；required与rect混改可接受。安全组虽然成功，但全间接对象差异显示除目标 `/Ff` 32770→32768，还新增一个 Helvetica 字体对象（`baseline-safe-diff.log`）。根因为 `save(updateFieldAppearances:true)` → `PDFForm.updateFieldAppearances()` 在迭代前无条件 `getDefaultFont()`。因此本批只收窄既有入口并修复保真，不宣称新的操作类型。

## 最小实现及安全边界

复用 `editFormWidget.required`、来源SHA和旧fieldName/widgetId/widgetIdentity/expectedWidgetSha256。新专属 `radioRequiredEditable` / `radioRequiredReason` 不扩大 removable、editFormFieldRequired 或其他属性权限。

限定原安全闭合2–64按钮互斥组，复用严格选项/状态/V/DV/AS/AP流/引用/无动作/字段树校验；额外核对每个按钮 `/P` 与唯一页面归属。原始Opt缺失时保留原on-state选项语义；若存在，则必须为严格字符串/十六进制字符串数组且长度与Widget数一致，防止getExportValues过滤异常项后误判。字段本地 `/Ff` 须是直接PDFNumber、整数、0..0x7fffffff；拒绝继承、间接、负数、小数及超界标志，避免物化继承状态或把原引用改成标量。不扩XFA/签名/任意动作/不闭合或共享AP来源。

`form-design-properties.ts` 在所有radio required请求上优先进入专属分支，拒绝rect/newFieldName/choiceOptions混改、no-op与坏组，保留仅rect的旧路径。任一旧按钮可作精确锚点，重新核对所有兄弟metadata、required一致与完整数量。正式 `enableRequired/disableRequired` 后 `save(updateFieldAppearances:false)`；全间接对象及原始流encoded bytes比较仅允许目标字段 `/Ff` 不同，并要求旗标恰好xor2、字段ref/按钮ID集合/新required及组资格一致。原V/DV/AS/AP/Kids/Opt/正文和所有原引用不得变化，也不得新增默认字体对象。

写后复核失败沿用 `pdf_form_widget_output_review_failed` receipt，保留实际bytes/SHA/size与具体原因，不冒充验收通过。前端已有字段属性面板复选框显示“整组必填”，仅完整一致安全组可用，明确整组效果和独立保存；单改required只序列化required。普通文本/下拉/复选框旧generic行为及独立radio区域编辑保持。

## 定向验证

- 新原生 `bridge/form-radio-required.test.ts` 先真实5项RED：缺metadata、旧路径新增字体、no-op/混改未拒绝；实现后5PASS，`native-red.log` / `native-green.log`。覆盖根/层级/跨页/未选择、开关两方向、NoExport位保持、精确全raw对象/Ff例外、第二按钮锚定、过期身份、当前/默认/外观保持、缺Opt、继承/间接/小数flags、坏Opt/P/state/AP/unison/date-action、混改/no-op拒绝、独立rect仍可用、写后具体故障保实际文件。
- flags负数/超31位边界扩展定向1PASS：`flags-boundary-corrected-fixture.log`。初始负数fixture误置PushButton位而不再是radio，已纠正为仅符号高位+radio+NoExport；不把该fixture失败说成实现BUG。
- 受影响旧原生extended4+hierarchy4共8PASS，`native-affected.log`，未重复完整测试。
- 新UI2真实RED→GREEN，同时name2/widgetName3/extended4共11PASS，`ui-red.log` / `ui-green.log`。覆盖完整组资格和required一致、截断组、混改/no-op、整组文案、仅required序列化及Undo/Redo。
- 窄tsc本批文件无错误，记录 `typecheck.log`。当时共有8项：宿主resourcesPath/依赖声明6项与并行text分支measure-label-bounds.ts2项；不宣称完整类型检查通过。
- 独立原生公共桥接序列 `/tmp/pdf-next-radio-required/independent/` 创建2按钮和code，切required=true、再false、后续按原名填No。独立pypdf读取全部原始间接对象/encoded及decoded流，仅Ff required位允许变化，按钮/字段引用、Opt/V/AS/AP/DV/正文/页面几何保持，No后续填值成功。`native.log` / `independent.json` 已通过；不是本批真实浏览器证据。
- required PDF SHA256 `d2b140cb6029cc27a213030d88dbc014e25d9a81f86faedad3fd2dadef4db801`；optional `cd9d4304ceabfba92929ac0080eb6a9e600feb4cc6facc9302b9633a4e47ac0c`；后续填No `74b4e49907ee340acff804cf79d5edf30366aec83d14d599ad53eaf79dbaa3f0`。

专用浏览器 `frontend/smoke/pdf-form-radio-required-smoke.mjs` 默认4348，变量 `PDF_FORM_RADIO_REQUIRED_SMOKE_DIRECTORY/PORT`，以及公共冻结资产/packed engine/Chromium变量。5次保存：创建radio、code、整组必填开、关、填No；真实grant/cookie/CSRF、冻结资产、第二按钮锚定、Undo/Redo、预览确认、下载重开、两按钮required同步与独立pypdf `pdf-form-radio-required-verify.py`。Node syntax/Python compile通过。统一真实浏览器/HTTP及host恢复草稿集成由root补充最终证据，尚未提前标通过。

不含单Widget radio新必填权限、任意复杂字段、跨父字段设计、任意脚本、XFA、签名或OCR。

## 统一实际链路补验（2026-11-11）

总证据见 NATIVE_PDF_LABEL_REQUIRED_SLOTS_ACCEPTANCE.md。真实 `/tmp/pdf-label-required-slots-form-browser/summary.json` 已通过，5 次预览确认/保存/下载/重开、37 个实际 JS 与统一资产匹配，来源未变、四类 errors 为空。独立 pypdf 确认 required 与 optional 只变 Ff required 位，其余全部原始对象/AP/引用保持。实际 required SHA `992c4ad0a7db10c0cf881af16ef1900046e032d75191d77b12d72ebe58fd38e0`、optional `9aaef9074e9531ec160f523f96cc092245feabd0330eb7c78f7d7caeef3f32e4`；后填 No SHA `56a978a72bff0acda1bbb8007b1edb4f5e63f3d8de911ba4652092eb8cab5463`，root 已目视重开。

host 恢复草稿新增单项通过，验证来源兄弟身份与预览确认；首次仅 fixture 误带 append 的 rect/exportValue，修 fixture 后只重试该项。HTTP requiredRadioGroup 后置故障专项核 Ff xor2、全原对象例外及实际下载保留通过。窄 tsc 当时的文字 helper 两项类型诊断已由文字侧修复并 scoped 验证，不由此推断完整项目类型检查通过。
