# PPTX 母版/版式实色填充与无填充专项验收（2026-11-13）

## 实际源能力与本轮范围

固定源 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`apps/slides/src/renderer/MasterView.tsx:235–252` 的 ctxItems 对既有顶层 text/shape 提供真实“填充”与“无填充”右键入口；`pickColor` 140–146、`onColorPicked` 148–163 和隐藏 color input 379–383 完成选色。`apps/slides/src/main/slides-main.ts:2967–2992` 经 masterTxn 派发 `{op:'setFill',target:{part,el},fill}`，完成后重新生成继承渲染。

本轮只实现现有 master/layout 顶层 text/shape 的 `#RRGGBB` 或 `none`。不包含逐 run、组内对象、轮廓、渐变编辑、自定义绘图、母版部件创建删除；不能凭底层 ops 支持更宽的类型就声称源 UI 已暴露那些能力。待新增框仍使用其已有默认样式，不能以客户端 clientId 冒充真实 sourceId。

## 实现边界

- 沿已有 `masterElementEdits` 增加 `setFill(partPath,spid,fill)`，Python、前端恢复模型和实际 source bridge 均严格校验部件、整数 SPID、唯一对象、颜色和 exact keys。任意 XML、未知 part/SPID、alpha/颜色名、重复目标和同对象填充/删除冲突均不接受。
- inspect 独立提供 `fillEditable`、`fillValue`、`fillReason`。fillEditable 需要有效原部件、唯一原始 SPID、顶层 p:sp 和唯一可写 p:spPr；不以文字是否存在判断。无 txBody 的 shape 可填充而不可改字；缺少 p:spPr 的畸形对象禁填充，既有文字 editable 判断保持独立。
- 真实实色/none 可显示；复杂、继承、非六位实色等状态用 null 明确说明，不伪称“无填充”。新控件只替换为实色/none。
- 原生 setFill 通过现有 loadMasterOps/runTxn 写 part，并走原 savePptx、预览、修订和下载链。没有新增 XML 写回器或保存入口。NativeDraft/UndoRedo/reload 沿用原链；删除对象时去掉同对象待提交填充，其他对象、部件和普通页面草稿保留。
- `slides-main.ts` 本轮只改待办摘要一行以显示 setFill；保留其他会话播放功能。没有修改 Word、native_office.py、slides.py 或已完成批次物理冻结目录。

## 定向验证

证据根 `/dev/shm/office-next-pptx-master-fill-20261113`：

- Python 新协议先 1 failed / 13 passed，接线后 14 passed；相邻 master element 协议 22 passed。
- 新前端首 5 用例先失败后 5 passed，覆盖文字只读但填充可写、复杂来源说明、颜色/none、其他部件保留、删除清理、同草稿预览、Undo/Redo、恢复、只读、IME 与过期快照。另一个同值重复采纳用例先暴露操作重排，修复保留原事务位置后通过。相邻母版结构/文字 UI 共 8 passed。
- 主实际 source/bridge 2 用例先失败后通过：master/layout 实色与 none 结果与固定源 part 事务一致，无文字 shape 的 fillEditable 与文字 editable 独立；身份/颜色/任意 XML/重复及删填冲突拒绝，复杂填充不误读为 none。
- native `patchElementFill` 对缺少 p:spPr 的源对象可能静默无写入。新增定向用例先红，独立检查唯一可写 p:spPr 后，最终 3 个实际 engine 用例全通过；该限制没有反向收紧已有文字 editable。
- 对尾换行颜色的静态疑虑经当前 JavaScript 实际探针和新增前端/bridge断言确认：原实现已经拒绝，没有产品修复。该额外绿色边界不冒充 RED→GREEN 缺陷修复，记录在 `colour-boundary-check.json`。
- 独立 stdlib ZIP/lxml/python-pptx 回读实际引擎产物：11 文件部件集合一致，只目标 master/layout 2 个部件变化，其余 9 个字节保持；实色/noFill、形状变换及正文保持均核验。结果 `independent-engine-verify.json`。

没有运行完整测试套件、构建共享 static/dist、提交或推送。本轮 13 个产品/测试文件冻结前身份见 `product-ready-sha256.json`。真实 HTTP 需使用本轮统一冻结身份，不能由上述局部证据或旧批次资源替代。

## 真实 HTTP 状态

runner、三层 fixture/server 与独立下载验收脚本已物理保存于证据根 `harness/`，运行前 SHA 为 `harness-pre-run-sha256.json`。fixture 的 layout SPID 9002 特意无 txBody 且有源实色，用于实际浏览器核验填充能力独立；master SPID 9001 保留文字和源实色。runner 分别记录 Python 冻结基线差异、实际运行起止逐文件身份与期间漂移，不宣称 Python 隔离。

本轮唯一完整 HTTP 在 `browser-01/` 完成，复用原保存入口，只发送一次 `/api/save`，登记 revision 2。实际运行身份：

- 统一快照 `/dev/shm/office-next-page-borders-ribbon-master-fill-detect-20261113/source`；source 清单 SHA256 `a2c8335a67179ac8dc92e37750638affac9e5338555538ae5907d5c66783af1c`。
- HTTP 实际 `.vite/manifest.json` SHA256 `5ede4bf0e2689e7427f0e90ea296a912ae56aa4ef124be01a1916d8af55c3c90`；155 个实际响应资源逐个与冻结磁盘字节比对，入口脚本也在其中。
- edit-pptx SHA256 `fbf108d82430f0a9954cb6664d01a69802c90907047eb8391c6e99f5d3f99bcb`；render-pptx SHA256 `2d3bca918a24430b102d7bb6367ce2679acf8c9fa730b36d67ea07dd6ddff13c`。
- 实际启动 runner SHA256 `3884ea78804744044d20a401a36983c732c33bbd22fcf889746f2f918a7b4ac2`；三个 server 和独立 verifier 起止身份记录于 `browser-01/harness-before.json`、`harness-after.json`，与预存脚本一致。
- 输入 fixture SHA256 `80ba5674e1b996fb19b42efb2fe32727c14d1a94915580ce2ca36d6e93a73065`，导入前后字节身份一致；签名下载 SHA256 `661a85f620b5a8d13a9f9907dbd29743784c964c8f85844b7e491942013c1560`，与保存回执一致。

实际浏览器覆盖源颜色、同值不新增草稿、选色未采纳关闭、master none→Undo/Redo→实色、无 txBody 的 layout 可填充但文字只读、layout 实色→none、草稿重载、两页继承预览、390px 对话框、保存及实际 revision 2 重开。没有 pageerror、console error 或 HTTP 错误。保存回执 `validation.ok=false`，明确返回 `native_source_review_pending`（原生内容尚未重新核验业务事实与完整版式）；该告警未阻断已核验文件身份的签名下载，不标记业务验收通过。

独立 `stdlib.zipfile+lxml+python-pptx` 回读下载：47 文件部件集合保持，只 `ppt/slideMasters/slideMaster1.xml` 与 `ppt/slideLayouts/slideLayout7.xml` 变化，其余 45 部件字节一致；master SPID 9001 为 `#1A73E8`，layout SPID 9002 为 noFill。两个对象非填充 spPr 和 txBody 保持，layout 原本不存在的 txBody 没有被添加，普通页文字与 notes 保持。完整结果见 `browser-01/independent-verify.json`。

视觉检查了正常页继承蓝色母版且版式无填充、revision 2 对话框以及移动端截图。移动端需向下滚动对话框才能看到填充控件；另用同一下载文件做 `visual-readonly/` 只读续查，0 次保存，155 响应资源仍逐个对齐冻结磁盘，来源状态为“来源：无填充”，控件可操作且无水平溢出；`layout-fill-mobile-scrolled.png` 显示实际控件、状态和关闭按钮。该续查不重跑完整保存。

Python 使用当前仓库宿主，未宣称 Python 隔离。105 文件 before/after/finally 逐项身份完全稳定，实际期间漂移 0；但与统一冻结基线有两项既存差异，故 `frozenBackendBaselineAligned=false`：`smart_reporting/report_editor/native_pdf_contract.py`（冻结 `de4b206f…`，实际 `8fe8eef7…`）、`smart_reporting/reporting/delivery/docx_native.py`（冻结 `28a07f30…`，实际 `1f100ad6…`）。完整 SHA 在三个 backend 清单；没有改写基线，也没有因差异重做保存。

最终产品回读见 `product-final-sha256-check.json`：13 文件中 12 个与 ready 清单一致；共享 `slides-main.ts` 因其他会话继续迭代而不同，本轮仅保留先前的 setFill 摘要一行，未覆盖并发工作。端到端与下载验证使用上述物理冻结资源，不能用随后共享工作区身份替代。
