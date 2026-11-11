# Word 外部草稿刷新历史边界

## 范围与来源

- 同一真实浏览器 Editor 经现有 AI「生成修改建议 → 采纳到草稿 → view.refresh」建立新历史基线；不新增生产 debug hook，不重建 Editor。
- /context、/file、/preview、AI /start、/accept 和进度流均由本地 fixture 路由提供；不是实际服务端或真实模型端到端验收。
- 本 smoke 不调用 engine bridge；DOCX 在真实浏览器编辑器中解析，服务端模型由固定 fixture 提供。
- DOCX 复用 docx-native-history.mjs 的复杂多节 fixture：downloaded-native.docx SHA-256 为 7f4e32ee954f8eaaa98e97e904932369199971d323edf17b8cbbad578cde0391，模型必须声明同一来源 SHA。
- 对每个浏览器实际请求的 JS chunk 核对磁盘 SHA；运行开始/结束时静态 manifest 必须与显式传入的 DOCX_EXPECTED_MANIFEST_SHA256 一致；禁止保存、导出和修改 bridge 文件。

## 覆盖

1. 正文人工输入及分栏修改后采纳外部草稿：旧 undo 不得回放；同一 Editor DOM 和刷新正文/原始分栏保留。
2. 刷新后的新正文及分栏编辑仍可 Undo/Redo，且只回到新基线。
3. 旧正文及分栏均已撤销、只剩 redo 时采纳外部草稿：旧 redo 不得跨基线回放。
4. AI 采纳返回不属于当前来源的 blockId：刷新失败不能替换正文或清空此前正文/分栏历史。

书签、REF、SEQ 和批注的 root intent 历史、selection、storedMarks、其它 plugin state/实例/顺序由 src/docx-refresh-history.test.ts 的真实 Editor 用例覆盖。非法/过滤/锁定安装的调用时序由 docx-main 集成测试覆盖。

## 执行

由统一构建/浏览器冻结阶段运行，不在并行编辑期间重建共享静态目录：

    DOCX_TEST_DIST=/path/to/frozen/static DOCX_EXPECTED_MANIFEST_SHA256=<frozen-sha256> node smoke/docx-refresh-history-smoke.mjs

DOCX_EXPECTED_MANIFEST_SHA256 必填。可设 DOCX_COMPLEX_ARTIFACT、DOCX_COMPLEX_EVIDENCE、DOCX_TEST_PORT。默认端口 4392。成功输出 evidence 路径与四条验证结果；证据 JSON 含 fixture/不调用 bridge 声明、source/expected-manifest/manifest/chunk 身份、AI 请求、禁止保存导出请求列表及浏览器错误。

## 实现选择与约束

history().spec.key 公开的 PluginSpec 入口提供同模块的 history PluginKey；按 key 对象定位已安装插件，避免访问私有 history branches。EditorState.reconfigure 官方实现保留相同 key 的其它 state field、doc、selection、storedMarks；暂时移除再原顺序加回同一 history plugin，只有 history state 会重新初始化。仅最终状态调用一次 view.updateState。没有历史时不触发重配。

PM 的 view 在 plugin 数组变化时会按官方生命周期重建 plugin views；此方案仅有一次最终 view 更新，不重置其它 plugin state。调用者必须在完整内容及 root attrs 安装并确认成功后执行 reset；失败或锁定路径不得调用。未使用 closeHistory 冒充清空，也未重建 Editor 或改写 history 内部分支。

## 2026-11-11 实测

- 冻结静态目录：/tmp/sr-word-navigation-20261111/final2-static。
- 外部指定 manifest SHA-256：d16219950a133f029b252e955593dc52b6693013f0e146bbce73fcddf6e2c3e2；运行开始和结束均匹配。
- 最终结果：4 项浏览器场景全部通过，真实同一 Editor DOM 保留，实际加载的 125 个唯一 JS URL 均与冻结磁盘 SHA 匹配，浏览器 errors=[]、saveExportRequests=[]。
- 证据：/tmp/sr-word-navigation-20261111/history-browser/evidence.json；4 张阶段截图为同目录 01-refreshed-baseline.png、02-new-edit-history.png、03-redo-boundary.png、04-failed-refresh-preserved-history.png。已目视核对第一张新基线正文和一栏布局。
- AI 请求 6 次（3 次生成、3 次采纳）；本地 API/AI 均为 fixture，bridgeUsed=false，不调用真实模型或 engine bridge。
- 首轮在「新人工编辑一次 Undo」断言失败：keyboard.type 逐字输入的每个事件可能因复杂文档渲染跨越 PM 时间分组边界，一次 Undo 仅将 _NEW_MANUAL 变为 _NEW_MANUA；旧历史边界此前已通过。仅将测试输入调整为 keyboard.insertText 的一次真实浏览器文本事件，表达一次编辑后重跑受影响 smoke，生产和冻结静态文件均未改动。首轮错误节录保存在同证据目录 first-run-failure.log；首轮未生成截图，最终运行补齐了上述四张截图。
- 最终仅运行此受影响浏览器 smoke；没有重复 unit 全套、重建静态目录、保存或导出报告。

## 2026-11-11 final3 同资产复验

- 统一冻结目录：/tmp/sr-word-navigation-20261111/final3-static；外部指定 manifest SHA-256 为 6133a8fcdea51af52e3ae39ae5079dae5875acb4b161fda884e05e793cb86cc8，运行开始和结束均一致。
- 使用已修正的 keyboard.insertText 单次编辑输入脚本，一次运行 4 项场景全部通过；125 个实际加载的唯一 JS URL 均与 final3 磁盘 SHA 匹配。
- 最终证据：/tmp/sr-word-navigation-20261111/history-final3/evidence.json；errors=[]、saveExportRequests=[]；6 次 AI fixture 请求（3 次生成、3 次采纳），fixtureAPI=true、fixtureAI=true、bridgeUsed=false。
- 四张最终阶段截图位于同一 history-final3 目录：01-refreshed-baseline.png、02-new-edit-history.png、03-redo-boundary.png、04-failed-refresh-preserved-history.png；已目视第一张的新正文基线及一栏布局。
- 本轮未重跑 unit、未 build、未改共享生产文件、未调用真实模型或 engine bridge，保存和导出请求均为零。final2 运行与首轮输入夹具失败记录保留在上一节及 history-browser 证据目录。
