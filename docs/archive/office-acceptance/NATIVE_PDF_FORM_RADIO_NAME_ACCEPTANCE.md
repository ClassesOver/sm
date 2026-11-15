# PDF 安全单选组叶子名称编辑验收（2026-11-11）

## 来源与范围

固定源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`apps/pdf/src/renderer/FormDesignLayer.tsx:568` 说明名称 generated, not shown，`App.tsx:4052` 的 `patchDesignField` 对已有 Widget 提取 rect/required。因此这批属于用户持续授权的更多字段属性增量，不计作固定源原有名称编辑 UI 迁移。

复用 `editFormWidget.newFieldName`、来源 SHA 及旧完整 fieldName/widgetId/widgetIdentity/expectedWidgetSha256；任一精确旧 Widget 可锚定整个来源单选组。限定同父层级叶子改名，不移动 Parent/Kids、不合并/拆分字段。保留独立单 Widget 旧支持；非单选多 Widget 继续拒绝。

单选组须 2–64 个 Widget、未只读且互斥。每个选项唯一、≤128字符可打印 ASCII，选项数与 Widget 数一致。开启状态名唯一；原 `/V`、`/DV` 缺失、Off 或合法开启名，所有 Widget `/AS` 与 `/V` 一致。字段/祖先/Widget 不得带 A/AA（包含可识别日期动作）；Parent/Kids/页面 Annots 引用闭合且唯一，整组控件均通过设计复核。AP 必须包含 N，可选 D/R；每种状态字典仅 Off 和该 Widget 开启名，状态均指向非空可读取间接原始流，不允许共享外观流。XFA、签名、任意动作和不闭合引用均未放开。

## 最小实现

`bridge/form-design.ts` 对整组一次计算 `radioRenameEditable` / `radioRenameReason`，避免只检查锚定控件而遗漏其他按钮；失败时整组返回不可改名。`form-design-properties.ts` 复核完整组 census 后使用原生 `setPartialName`，`save(updateFieldAppearances:false)`。写后比对每个间接对象，仅允许目标字段 `/T` 不同；原始外观 stream 字典和 encoded bytes 同时比较。另复核新名称、旧名称消失、同一字段 ref、同一组 Widget ID 集合和输出安全 metadata。

写后复核故障继续返回实际 bytes/SHA/size 及 `pdf_form_widget_output_review_failed`，不把验收标记通过，也不丢失实际文件。统一 HTTP 签发与故障注入由 root 执行。

前端已有字段属性面板对完整安全组启用名称输入，明确“改名应用于整个单选组，保留所有按钮及选中值”。草稿重新核对每个兄弟的设计资格、改名资格、选项数组/选中值一致、唯一 Widget ID 和组完整性；截断/不一致组不放行。名称变更仍单独保存，不附带 rect/required/options，继续既有 Undo/Redo 和预览确认。

## 定向验证

- 新原生 `bridge/form-radio-name.test.ts` 先真实 RED（3失败/1通过），实现后4项通过；受影响旧 `form-widget-name.test.ts` 的3项同步通过。旧多控件拒绝用例改为非单选的多 Widget 文本字段。合计7 PASS，日志 `/tmp/pdf-next-radio-name/native-green.log`。
- 新 UI `src/pdf-form-radio-name.test.ts` 先真实 RED（2失败），实现后新2项、旧name3项、choice3项合计8 PASS，日志 `/tmp/pdf-next-radio-name/ui-green.log`。
- 覆盖根组、层级组、跨页组、未选中组、第二 Widget 锚定；全原始对象及AP流/ref/值/正文保持；拒绝 unison、重复选项/开启名、错 AS/V/DV、缺失/共享 AP、日期动作、外来 Parent、重复页面 Widget，以及冲突/跨父/混合编辑/过期身份。故障注入验证实际改名文件仍可读取完整组。
- 窄 TypeScript 检查无本轮新增错误；仍有6个已有宿主依赖声明错误（Process.resourcesPath 两项和 @genoffice 包四项），日志 `/tmp/pdf-next-radio-name/typecheck.log`，不宣称完整类型检查通过。
- 独立原生序列 `/tmp/pdf-next-radio-name/independent/` 从已有真实浏览器来源创建单选组和无关 code，用第二 Widget 改 `party.answer` → `party.renamedAnswer`，再经完整桥接按新名填 No。独立 pypdf 已通过全部间接对象（仅/T例外）、AP原始/解码流、字段树/Widget引用/页面Annots、Yes状态保持、No后续填写和正文/几何不变。日志 `native.log`、`independent.json`。这不是本轮浏览器证据。
- 改名 PDF SHA-256：`080e4d7697a435ba3a772b38856c11178161c26a57d31841e445f3cfa3b91409`；后续填 No PDF：`7d44df0dd2725fe65114fd5a98f450f5527a7597dfeb84f91c9eb5727c788f6a`。

专用真实浏览器脚本 `frontend/smoke/pdf-form-radio-name-smoke.mjs`：创建 party.answer(Yes/No) 与 party.code，第二按钮锚定拒绝重名，再单独改名、Undo/Redo、实际预览确认、保存下载重开、按新名填 No 再下载重开。独立 verifier `pdf-form-radio-name-verify.py`。默认端口4346，变量 `PDF_FORM_RADIO_NAME_SMOKE_DIRECTORY` / `PDF_FORM_RADIO_NAME_SMOKE_PORT`，以及公共冻结资产/打包引擎变量。Node syntax / Python compile已通过；统一冻结后的真实 browser 已 exit 0，证据 `/tmp/pdf-link-radio-decimal-form-browser/summary.json`；四次保存下载重开及独立 pypdf 通过，37 个实际 JS 响应匹配，来源未变、错误列表为空，最终 UI 已目视。实际改名 PDF SHA-256 `9377033c760a7df0ca8fabfae5cd70bfe556c377055ff7b4073cc9f9a3e8fa12`，后填 No PDF 为 `68178d8efe351e30b55fb504b07faa7d4c627d78ab45128b00337252186fbc55`。恢复草稿 host 新用例1 PASS；HTTP后置复核告警仍签发1 PASS，初次错误的单流 AP 测试断言改为状态字典逐流/引用核验后只重跑该失败用例，没有生产改动。完整证据见 `NATIVE_PDF_LINK_RADIO_DECIMAL_ACCEPTANCE.md`。

## 保持未完成

不含任意多 Widget 文本/下拉/复选框改名、跨父移动、父节点改名、任意脚本字段名重写、共享外观或非互斥组、XFA、签名字段。未新增 OCR。
