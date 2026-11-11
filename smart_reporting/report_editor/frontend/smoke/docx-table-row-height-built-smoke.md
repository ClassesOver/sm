# Word 指定/清除行高 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-row-height-built-smoke.mjs
```

使用 root 最终 frontend/bridge 构建，仅启动端口4242的vite preview，不build；可由 `DOCX_ROW_HEIGHT_SMOKE_PORT` 覆盖。公开编辑区真实DOM输入、草稿刷新、save请求、项目Python inspect/patch、真实HTTP下载及修订重开。

来源2×3表：首行300/exact、次行400/省略hRule，保留cantSplit、混合runs、中文emoji、尾空段、主题shd、pretty XML。另含横跨两列/纵跨两行且有隐藏continue文字的来源。节正文高度14800twip。

流程：首行600→undo/redo→次行输入0恢复自动→草稿刷新→保存/实际下载→修订2重开→自动行设750恢复atLeast→保存；复杂rowspan caret设900覆盖两行→保存/下载→修订11重开→30000请求截断原节上限→保存→修订12重开。

严格断言actual operations行带/null步骤、exact/atLeast规则、原节clamp、下载SHA、移除直属trHeight后整个document.xml逐字相等，所有其他parts SHA和逻辑/物理格身份不变。JS资源200且SHA匹配本地构建，console/pageerror为空。失败记录stage、截图和HTML。路由仅替代授权和修订存储。

准备状态：Node语法与嵌入Python compile检查通过；等待root统一构建后执行，尚未声称built通过。

最终 built 实测（2026-11-10）：首轮 session68650 exit0，日志 `/tmp/word-row-height-built-smoke.log` 为 `ok:true/errors:[]`；实际DOCX/下载/修订产物 `/tmp/docx-row-height-built-hEuDYT/`。Chromium140.0.7339.16。全部指定/清除/clear后设/undo-redo/草稿恢复/复杂rowspan/原节14800上限/下载/修订重开和严格XML原字节断言通过。源SHA `d597c279c0eab8c05e69c9fd4a16b62dc690f174e77e20974cae36e8c54a59df`，下载修订2 SHA `819af49c355b960c14f7578917b02693ec73d72f6f6ea91bb339ca1803155090`。

最终实际加载 `lazy-docx-main-B8p62kZ7.js` SHA `44873ea1427a0a4e5787f98d73c7836f905ddcd3b430ed10ebf1135d8a0c4946`；`lazy-native-docx-engine-fi36lBWH.js` SHA `0d082be303183e213e42848358ea30d0935e38a1e4ebdd0957af2302cb13c68c`，200与本地assets逐字匹配。修订12上限截图 `row-height-reopened.png`；其巨大行是14800twip真实设置的预期效果。

额外正常高度目视截图：仅重开已保存文件，未重复修改/保存，session62570 exit0，`/tmp/word-row-height-reopen-screenshots.log` 为 `ok:true/errors:[]`。产物目录新增 `revision-2-row-height-reopened.png/.html`（600/exact、次行自动）、`revision-3-row-height-reopened.png/.html`（自动后750/atLeast）、`revision-11-row-height-reopened.png/.html`（合并来源两行900）；修订11目视确认MERGED中文/emoji、右侧C1/C2、外部前后段完整，隐藏continue不展示。
