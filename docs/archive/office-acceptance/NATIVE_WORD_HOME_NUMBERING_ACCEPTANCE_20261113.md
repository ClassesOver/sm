# 普通Home列表与设置编号值补齐（2026-11-13）

固定参照 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，对照 `apps/docs/src/renderer/numbering-actions.ts` 的 `allocateListNumId`、`createNumberingDef`。本专项承接设置编号值专项，补普通Home新建列表在未保存时没有可信定义的缺口。

## 产品范围

普通Home按钮不再为新列表写入无定义的 `native-ordered/native-bullet`。优先采用来源文档中首份同类原始编号定义（包括正文尚未引用的定义），创建从1开始的新编号绑定，服务端通过原 `restartNums` writer 写入同一 abstractNum。没有同类原定义时，保存结构化默认定义身份，由原 `newDefs` 默认writer生成五级定义；浏览器即时覆盖层与源 `createNumberingDef` 一致，不用九级图库近似源默认列表。

重启/继续编号保存默认定义的稳定身份，正文是覆盖层唯一状态源。Undo/Redo、草稿重放和清除列表保留文字、样式及来源身份；标题转列表后清除可以恢复原始标题。编号操作增加每项 `listKind`，用于未被正文引用的项目符号定义在草稿恢复时保持bullet；服务端按真实来源定义/当前级别核验，不能用此字段伪造编号类型。旧不带该字段的编号操作仍接受。

主要产品文件：`frontend/src/docx-custom-list.ts`、`docx-ribbon.ts`、`docx-operations.ts`，以及 `reporting/doc_engine/bridge/docx-numbering-value.ts`、`edit-docx.ts`。现有段落属性等并发代码保留，不修改共享样式或全局保存契约。

## 定向证据

证据根：`/dev/shm/office-next-word-home-numbering-20261113`。

- `red.log`：四项实际Home交互失败，暴露临时编号没有定义及原toggle丢来源身份；`green.log`：4项新增+8项编号值+4项自定义列表共16 passed。
- `heading-red.log`：标题无法转换的真实失败；修复后 `adjacent-final.log`：5项Home+6项列表+39项Ribbon共50 passed。此前109项检查中4项旧测试失败，因为旧夹具没有生产列表扩展/来源anchors且仍断言旧synthetic协议；已把对应夹具与预期改为生产绑定，保留首次失败日志。59项operations测试在该次检查通过。
- `native-red.log`：旧v4引擎不能接受默认定义/listKind，4 failed、4 passed，作为旧协议对照；`native-green.log`：新物理引擎下8项Home与10项相邻编号值共18 passed。
- 原生测试通过ZIP/lxml/python-docx独立回读：默认五级定义、两不同num引用同abstract、startOverride、未使用定义复用、段落粗体/正文保留，非目标parts逐字节不变；类型伪造、混合定义、级别超限、冲突默认身份拒绝。

## 352eb5 历史快照与完整 HTTP 闭环

完整保存层使用当时的源码快照 `/dev/shm/office-next-split-master-chart-home-20261113/source`；4202份源码摘要、102份live后端身份基线。该历史层manifest为 `352eb5fc3903b0d6c145c1f1e873e2ad983a2f58b7ec1e0d3567f18b3ba1a560`，HTML为 `a0057f54cf306d8929d2b90ca3378879dd4c59f181cec839ba391b0fbd2c123b`；后续最终入口见下节。该层tsc、Vite、四套桥、原预算及预算合同均exit0；Word主块246.6KiB。预算文件与此前v4逐字节一致。PDF预算曾三次失败（255.7/250.7/250.4KiB），随后按拆分宿主/页面功能区职责分块修复到249.3KiB，不提高预算；失败阶段完整保留。共享树后续PDF compare、native-selection-ai分块未混入该历史快照。

`browser-frozen-01` 首次完整运行exit0：从两个普通段落创建Home列表，复用未被正文引用的原num定义；取消设置编号值不写；Undo/Redo、第二项restart9、NativeDraft reload、唯一一次保存4→5、授权下载和修订5重开全部完成。155份实际JS/CSS资源SHA与该层物理资源一致；page/console/HTTP/asset错误均空。390×844对话框四边在视口内，确认按钮可达；窄屏对话框和新修订正文截图已root目视。

实际下载38145B，SHA256 `05120581541e4e42d12d4ebb938e52ef9bfc4f59012bcf4270b4deacdf3736e0`。独立ZIP/lxml/python-docx确认两个不同numId10/11均指向原abstractNum7，分别startOverride1/9；没有复制abstractNum，原标题、粗体、居中、页眉和15个非目标parts保留。保存响应为 `validation.ok=false / native_source_review_pending`，仍有真实Word下载与新修订编辑授权；不标业务验收通过。

原生测试用桥与最终桥仅第一行createRequire引号不同，其余全部字节一致，证据 `final-native-bridge-reconciliation.json`。HTTP宿主Python执行live仓库，102份复制文件仅作身份基线，不能声称后端隔离执行。

本专项只覆盖可信原有顶层正文/标题的Home列表；新增未登记段落、嵌套对象和全部源自动编号/图库链不由此专项关闭。原始四格式穷举目标仍active。

## b8b97e 最终入口零保存续验

最终物理源码仍位于 `/dev/shm/office-next-split-master-chart-home-20261113/source`，最终清单为4203份源码；manifest为 `b8b97ee76d41a565f94e9f8c902e226031ada09ad9cd3bcf52deb886f421f04c`，实际native HTML为 `aaa3eb21c2eb976afff3d1ae6a7ace757b75e2613a1b7272c6613cc4728a29c2`。`352eb5` 完整保存层作为历史保留，最终入口续验不重复完整保存或下载签发。

`/dev/shm/office-next-word-home-numbering-20261113/browser-readonly-final/minimal-evidence.json` 记录重导入上文实际下载的同一Word（SHA256仍为 `05120581541e4e42d12d4ebb938e52ef9bfc4f59012bcf4270b4deacdf3736e0`），读取编号值9，取消后正文快照保持；实际执行的minimal分支断言NativeDraft operations为空。回执 `ok=true`、`minimal=true`、`savedRevisions=0`，168条HTTP记录中保存请求0。155个不同URL的实际JS/CSS资源（143 JS、12 CSS）SHA全部匹配最终冻结磁盘，page/console/HTTP/asset四组错误均为空；本次收尾仅独立读取既有证据和核对文件身份，没有重跑浏览器、保存或测试。

## HTTP宿主与验收后漂移限制

Word HTTP实际执行的是live Python仓库；102份后端文件仅为冻结身份基线，不是可运行的隔离后端。本专项没有保留每次Word HTTP执行前后逐文件后端身份回执，不能移用PPTX、PDF或XLSX的历史起止检查作为Word结论。

验收结束后，其他会话继续修改live后端，当前不能宣称全live后端与基线一致。统一根 `/dev/shm/office-next-split-master-chart-home-20261113/live-backend-drift-after-evidence.json` 保留早期漂移记录，后续扩展以同目录 `root-independent-verification.json` 的 `postEvidenceLiveBackendDrift` 为准。未据此刷新102份基线，也不把后续live代码自动纳入本专项通过范围。这里关闭的是可信原有顶层正文/标题的普通Home列表缺口，不是Word全量对齐。
