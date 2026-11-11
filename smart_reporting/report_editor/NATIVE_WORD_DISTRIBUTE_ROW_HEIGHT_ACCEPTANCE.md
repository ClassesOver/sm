# Word 平均分布各行验收记录

本项已完成下述专项验收，全量 Word/XLSX 目标仍开放。固定来源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，精确语义及真实 DOM 调查见 `NATIVE_WORD_DISTRIBUTE_ROW_HEIGHT_DESIGN.md`。

## 契约

使用真实内容排版后的 TR 高度平均值，单行选区扩为整表，多行及合并选区按逻辑行带。临时把实际 PM 根和 `.doc-zoom` 包装器设为100%测量，并在 finally 保留原值与优先级恢复，避免缩放及折叠边框的屏幕像素取整影响。目标行均须成功测量，不能忽略缺失 DOM 后把部分平均值写给全部行。

仍用 setTableRowHeights，新增严格四键步骤 `{kind:'distributeTableRows',top,bottom,heightTwips}`；普通三键设置/清除不变。均分强制 atLeast，后续普通设置不能让之前 exact 复活。不接受客户端 heightRule、XML 或上限。实测值不按节正文高度截断；当前模型仅支持正安全整数至31680 twip，超过范围明确拒绝，不冒称已支持任意超高行。

## 已验证证据

- 独立真实 Chromium 13 个来源/宿主测量向量证明临时100%能使100/150/75%显示比例得到相同705twip；最小schema探针尚非最终宿主验收。
- 新步骤先在旧core/bridge拒绝处RED，core5项、新bridge2项及旧bridge6项通过；限定类型检查通过，见 `/tmp/row-distribute-*.log`。
- 最终bridge `/tmp/word-row-distribute-bridge-build.log` exit0。Python新协议6项 `/tmp/word-row-distribute-python-green.log`通过，覆盖混合有序回放、exact→atLeast、clear、非法字段/kind/空值、超过节高保留实测值及31681拒绝。
- DOM测量模块初4项通过 `/tmp/word-distribute-row-measure-green.log`，正在独立复核和接入UI；未重复完整项目测试。

独立真实Chromium窄复核 `/tmp/word-distribute-row-dom/review.log` 发现pending图片等待在dispose后不终止，已交UI agent补deadline、current取消及监听器清理；未以初4项测试宣称生命周期完整。fonts.ready等待布局稳定，并不证明每个字体加载成功；宿主允许字体回退，测量采用实际fallback排版，不新增全局字体失败门禁。

后续UI与测量15项通过 `/tmp/word-distribute-row-ui-green.log`；取消/超时/监听器新向量先RED后单项GREEN `/tmp/word-distribute-row-cancel-{red,green}.log`。等待现具15秒总期限、100ms来源状态/zoom失效检测、abortable fonts/decode/rAF及finally清理。真实宿主测量模块独立Chromium13向量 `/tmp/word-distribute-row-host/run.log`验证不同zoom相同705twip、缺行拒绝并还原zoom。最终UI类型检查 `/tmp/word-distribute-row-ui-types.log` exit0，生产已冻结。统一build `/tmp/office-row-distribute-cross-highlight-build.log`正在执行，尚未用这些窄测试替代最终文件闭环。

统一build已exit0（40.25s），同前缀budget与budget-contract exit0，未提高预算。Word均分及XLSX RTL高亮的最终资源探针分别执行中。

## 最终浏览器验收

`/tmp/word-row-distribute-built-smoke.log` 首轮exit0、ok=true/errors=[]，产物 `/tmp/docx-distribute-row-built-n70w1P`。公开Ribbon实际将显示比例依次设100/150/75%，同DOCX/相同caret均分整表，三档均为1312twip；每档精确DOM Undo/Redo、恢复原zoom、草稿刷新、Python实际patch、HTTP实际下载、ZIP回读及明确新修订重开通过，规则均atLeast。

额外真实鼠标选择前两行仅均分该行带，步骤 `{kind:'distributeTableRows',top:0,bottom:2,heightTwips:927}`，第三行500不变；只掩直属trHeight后完整document.xml逐字相同，非目标部件字节及原cell身份不变。静态JS200/SHA与本地构建匹配。root目视 `local-rows-reopened.png`，原内容、多段、中文与表格行带正常；三档截图 `zoom-100-reopened.png`、`zoom-150-reopened.png`、`zoom-75-reopened.png`均保留。

合并逻辑行带由UI/共享core及既有复杂合并来源行高专项覆盖，本次新增built使用普通3×3表，并未据此声称穷尽所有复杂合并排版。生产HTTP与桌面Office/PDF排版等价仍无本项证据。自动适应内容/窗口/固定列宽仍是独立缺口。
