# Word 设置编号值验收（2026-11-13）

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；对照 `apps/docs/src/renderer/numbering-actions.ts` 的 `currentListValue`、`previousListNumId`、`rewriteNumIdForwardSteps`、`setNumberingValue`，直接复用原字节 `SetNumberingValueDialog`。

## 功能与写回

Home 的“设置编号值”按真实目标可用性启用，支持开始新列表、继续最近不同身份的前序列表、继续并前进到指定值（0–32767）。按源语义从光标位置向后改写相同 numId；继续并前进时，同时重绑后续属于前序 numId 的项目。当前级别以外的层级、段落文字和格式保留。源计数器按 abstractNum 身份共享，不能将不同 numId 误认为一定独立计数。

`setParagraphNumberingValue` 只传可信 sourceNumId 或经过现有 normalizer 的未保存自定义定义、当前层级与 startOverrides。原始列表继续复用真实 numId；重新编号通过源 `restartNums` 新建同一 abstractNum 的 w:num，并写 startOverride；尚未保存的自定义列表通过引擎原有 pending abstract 映射，不复制一份改过 start 的 abstractNum 代替。浏览器覆盖层来自文档节点，与单次原生事务、Undo/Redo、NativeDraft 回放一致。

提交时重检正文对象、选区、可编辑性与后续受影响项目身份；迟到的异步对话框不能在销毁后出现。来源改变则拒绝提交并给出原因。取消不修改正文；普通列表切换清掉编号值绑定。IME Escape、对话框销毁和390px布局已覆盖。同一绑定身份的冲突定义在草稿生成、回放及后端拒绝；自定义编号不能把 character style 当成 paragraph style。

本专项初始验收范围限可信原有顶层段落，且目标有可核验的原始编号定义或当前自定义列表定义。当时普通 Home 快捷切换产生、尚未保存且没有定义的 synthetic 列表会明确提示先保存或选择列表库；该普通Home缺口后续已在可信原有顶层正文/标题范围补齐，见文末Home专项。复杂嵌套／只读／缺失来源目标仍不支持；此专项不关闭图片项目符号、完整段落选项或所有复杂来源范围。

## 定向测试

当前证据根 `/dev/shm/office-word-numbering-value-20261113`：

- `ribbon-red.log`：2 failed / 4 passed，证明核心已有而真实 Ribbon 仍固定禁用。
- `binding-red.log`：同一身份冲突未拒绝的真实失败；`style-red.log`：后端 character style 未拒绝的真实失败。
- `ribbon-green.log`：编号值8项、已有自定义列表4项、Ribbon39项，共3文件51项通过。`host-boundary-green.log` 是拆分宿主模块后8项专项通过，不与51项累加。
- `native-green.log`：10项 Python→真实DOC bridge→OOXML独立断言通过；覆盖原始继续／同abstract重新编号、pending custom映射、非法字段／来源／层级／样式及保留原包部件。
- 单测环境原有 Canvas getContext 提示保留在日志，不当作浏览器错误；未跑完整测试集。

## 最终物理构建与真实 HTTP

物理源码快照 `/dev/shm/office-four-format-numbering-print-metadata-20261113-v2/source`，4146份源码和102份后端Python文件分别登记摘要。首版构建成功但原预算检测 Word 主块252.7KiB超250KiB，证据保留在不带 `-v2` 的目录；将编号对话框宿主归入列表块、原生操作模块独立分块后，最终 Vite、tsc、原预算及预算合同均exit0，Word主块246.2KiB。未提高阈值，未覆盖共享static/dist。

最终manifest SHA256：`6e565b64b5d5dd5f549202d8552e4f03d994559b64d9bad62e2a9d10456163ef`。

`browser-frozen-02/evidence.json`：真实UI取消、重新开始7、多级后续项、Undo/Redo、继续前序、前进9、390px、刷新草稿、修订4→5保存、点击授权下载及新修订重开均通过。153个实际HTTP JS/CSS资源逐字节匹配最终冻结磁盘；page/console/HTTP/asset errors全部为空。独立lxml/python-docx/ZIP确认原前两项不变、新num与原91同abstract、startOverride9、当前级别1保留、后续前序项目合流为10，原居中／粗体、原文、标题、表格、页眉、原编号定义及其余包部件保持。实际下载38243字节，SHA256 `d6be33132de0dec65fe1d36d4178c50272e6281f5bd7eb20e49316691b8d6b4c`。

首轮 `browser-frozen-01` 已保存并独立回读成功，但验收脚本对307重定向调用response.body导致最终资产收集断言失败。失败目录保留；仅修验收脚本跳过重定向、增加保存响应和资产检查点后，用独立夹具重验02。每次各一次保存，不能将01称为全通过，也不能将两次操作写成总共一次保存。两次均未改产品源码。

root目视390px对话框和重开页：所有字段与确认可达，无横向裁切；新编号9、子级a)、后续10及保留标题显示正确。独立HTML零保存读取另记 `html-only/evidence.json`。

保存结果仍为 `validation.ok=false`，具体原因为 `native_source_review_pending`；已核验身份的Word下载照常签发，不宣称业务事实或完整版式验收通过。整体四格式穷尽对齐目标仍未完成；未提交、推送或部署。

## v3 统一入口最小续验

XLSX真实打印暴露隐藏表标记在导入时丢失，统一构建随后增加该必要修复。v3严格复制v2物理基线，只覆盖工作簿reader、Univer投影、对应新测试和LOCAL摘要四文件；Word产品、DOC bridge及后端副本均保持v2原字节。v3目录 `/dev/shm/office-four-format-numbering-print-metadata-20261113-v3`，manifest `490aa9f5b482fe532ebd24d01b1479fe7b85f60a5dbaab6f7863486c79701444`，Vite、tsc、原预算和预算合同均exit0，Word主块仍246.2KiB。

`browser-frozen-v3-minimal/minimal-evidence.json` 从上述实际下载的Word重新导入，实际编号值9正确、取消不修改、草稿为空、保存修订数0；153个实际HTTP JS/CSS资源及native HTML的字节均匹配v3磁盘，全部错误数组为空。这是入口/资源最小续验，不冒充第二次完整保存链。

共享工作树在v2拍入后另有段落属性、PDF目录显示、PPTX动画预览等并发代码和后端入口抽取改动；本批未覆盖这些代码，也未把它们纳入v3。所有通过结论绑定对应物理快照和明确实际HTTP链；不能直接外推为后续live工作树全量通过。完整漂移清单由统一证据单独保存。

最终v4只在v3物理基线上修复XLSX边距分类的一行fallback并加入相应测试，Word产品与DOC桥不变。最终目录 `/dev/shm/office-four-format-numbering-print-metadata-20261113-v4`，manifest `f9e161a924c55a6c9c0e5dc3bca80f5d9607b62e2c0552663bd39f830fd211be`；Vite、tsc、原预算、预算合同均exit0。`browser-frozen-v4-minimal/minimal-evidence.json` 再用原实际下载重导入，原生编号值9、取消不写、草稿空、0保存，153资源及实际HTML匹配最终磁盘，错误数组为空。root已独立复核并列入最终 `root-independent-verification.json`；此前v2完整保存和v3最小续验均保留，不重复完整保存链。

## 后续普通Home列表专项

[普通Home列表与设置编号值补齐（2026-11-13）](NATIVE_WORD_HOME_NUMBERING_ACCEPTANCE_20261113.md) 已补齐前述“普通Home新建列表须先保存”的缺口：仅对可信原有顶层正文/标题，复用真实来源定义或结构化默认定义身份，让未保存列表进入既有设置编号值、撤销/重做、草稿恢复与原生写回链。新增未登记段落、嵌套对象、图片项目符号以及完整自动编号/图库链仍不由此结论关闭，不能概括为Word已全量对齐。

该后续专项保留 `352eb5` 完整保存历史层，并在最终4203份源码、manifest `b8b97ee76d41a565f94e9f8c902e226031ada09ad9cd3bcf52deb886f421f04c` 的新入口上完成155个实际资源、0保存、草稿为空的最小续验；具体HTML、产物身份与证据分层见链接文档，不将它与本专项早期v2/v3/v4记录混为同一次保存。

该批Word HTTP执行live Python，未保留逐次后端文件起止身份回执，102份文件基线不能证明隔离执行或逐次全量匹配。验收后其他会话的live漂移见 `/dev/shm/office-next-split-master-chart-home-20261113/live-backend-drift-after-evidence.json` 及同目录 `root-independent-verification.json` 的 `postEvidenceLiveBackendDrift`；不刷新基线，也不将其他格式的后端检查移植为Word稳定结论。
