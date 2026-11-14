# Word 页面边框完整组件族：源代码阶段验收（2026-11-13）

本项按固定源 GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c` 移植完整 `PageBorderDialog.tsx`，保留五种设置、24线型、全部艺术型、四边开关、颜色/自动色、线宽/艺术宽度、四边距离、文字/页面测量基准、前后层次与整篇/本节/首页范围。宿主仅适配原生草稿、节身份、保存、键盘焦点和窄屏布局；没有另写 XML writer。

## 接线与保存语义

- 入口：设计 → 页面边框 → 自定义；原有方框/无快捷项保留。
- 整篇使用各节自身 `sectionId` 与 `expectedSectionSha256`，保留每节其它页面设置，一次原生事务提交，支持撤销重做与草稿恢复。
- 属性由共享 `docx-page-border-props.ts` 校验，原生 `pageBordersXml` / `applySectionSettings` 写入；`null` 仅配合 `pageBorder:false` 清除属性。
- 保护文档不允许写入；只读上下文入口禁用。
- API smoke授权与修订API使用fixture，实际运行前端、Python原生bridge、DOCX保存、HTTP下载与独立ZIP/XML回读。

## 已执行验证

- RED/GREEN：`red-props.log` / `green-props.log`、`red-native-props.log` / `green-native-props.log`。
- 完整组件与原子节helper定向验证：`dialog-unit-2.log`，5 passed、59 skipped。
- 新增艺术边框原生用例：`native-art.log`，1 passed。
- 清除、非法属性、保护文档：`native-invalid-null.log`，7 passed、2 deselected。
- 编译：`tsc-2.log` 无Word错误；其余格式错误交root统一处理，未重复完整测试。
- source browser：16 checks、0 errors、1 save；整篇方框/本节阴影/艺术立体/自定义三边、三个viewport、undo/redo、草稿恢复、实际下载、revision2重开、readonly均覆盖。
- 下载时返回 `validation.ok:false`，Word链接仍签发并可GET，独立回读确认除 `w:pgBorders` 外 document.xml结构恒等，其余ZIP parts逐字节恒等。

源阶段bridge SHA256：`3df9f2d526829bdc4f775f2b342802b6a678ae744eed7f30359a5f1c614c2a98`（2884642 bytes，256 workspace inputs）。

## 证据及待统一冻结

持久证据目录：`/home/junge/codex-evidence/smart_reporting/office-next-source-families-20261113/word`。固定源文件hash见 `source-identity.json`；bridge输入、workspace解析与metafile见 `docx-runtime/build-identity.json`；浏览器实际结果见 `source-browser/result.json`。最终static manifest、冻结前端及bridge身份由root统一构建后追加，本项没有修改 static/dist。

已知夹具限制：以表格结尾的源会触发现有编辑器尾段补齐，从而产生额外 `insertParagraph`；本专项改用明确末段夹具，未顺带扩大编辑器行为修改。该既有副作用已单独交root记录。

最新source browser轮次：`source-browser-7.log`；result SHA256 `f17c75342e2d37c9f8a0bcb474e4d326778b5aaecf1aeb95862d8a0759779a32`；实际下载 `408d38cbe5db5d3e3ca85f9d7db5d450371d5482005395c207b54010e49512c3`，37587 bytes。保存仅包含两个 `setSectionLayout`，无其它正文操作。最终源文件身份收录于 `source-ready.json`；已视觉复核390px顶部与各viewport footer hit。

## 正式冻结链（source-v2）

- 源快照manifest：`fc493bcb2305db74aac56653de4fc5ffc1fd7ba4f41fad5ecabdb705fd05b872`；static manifest：`7949df1457ac33345c20d4ba447bc26d0a922881f8812040838bf82d6f00e0a8`。
- 正式runner SHA256：`68bd85f26a77c7aa17f1bd2f056e1d7c5b04b1041f53c44d4db3f169d95da35c`。
- 输入比对发现旧runtime仍允许thick兼容值，与冻结validator不一致；保留旧runtime及差异记录，定向从source-v2构建 `docx-runtime-frozen`，256inputs逐一复核。冻结bridge SHA256：`ea442fdc0903b6be7b9230e37f8adfb145c28eb9174fbaa12e2a9ed0256e01bc`，2890865bytes。
- frozen browser：16 checks、0 errors、161加载assets逐字节hash匹配、1 save，仅两个setSectionLayout；原生undo/redo、草稿reload、3viewport、实际save/download/reopen均通过。
- result SHA256：`cf6e603d452cb34b85564420ba455082ff550ac374edfb569e0a1287ffb5bb28`。实际下载 SHA256：`f5e94ca1796a419263d85410eb24c94e46cc92e82df13c5da0a28c26059d3df9`，37587bytes，与revision-2实际文件一致。
- 独立ZIP/XML回读验证正文、表格、其它parts不变；validation=false时链接照常签发。修订2重新读取恢复自定义三边、首页、逐边距离、text origin，未追加保存。
- 正式收口回执：`/home/junge/codex-evidence/smart_reporting/office-next-source-families-20261113/word/frozen-browser/closure.json`；backendBefore/After身份一致。未重跑已通过的完整测试。
