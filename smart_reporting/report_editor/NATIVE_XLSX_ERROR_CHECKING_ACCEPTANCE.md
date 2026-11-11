# XLSX 错误检查验收

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，实际源探针和已知loaded正则误报/漏报见 `NATIVE_XLSX_ERROR_CHECKING_INVESTIGATION.md`。本项扫描当前完整载入工作表的现有计算结果并循环定位，不是完整 Excel 语义错误向导；不改公式、不自动修复、不强制计算，不新增streamed服务。

实现复用官方cellMatrix稀疏遍历、ERROR_TYPE_SET加源现代错误精确集合、range.activate和现有goToReveal。只读/保护/已保存可用，loading/saving/calculationBusy/disposed禁用；reset/dispose与工作簿/表/目标选区身份保护停止旧导航，不写snapshot/draft/history、不发保存。错误数量、当前表范围和当前计算结果在反馈明确显示；失败不报无错误。

controller首6项RED→GREEN，最终含用户手选竞争7项GREEN `/tmp/workbook-error-checking-selection-green.log`；同表改选新回归RED `/tmp/workbook-error-checking-selection-red.log`，最小修复捕获目标选区后停止旧滚动/反馈。含测试窄types `/tmp/workbook-error-checking-selection-types.log` exit0。

真实main只读循环/内容草稿历史请求不变、保存中禁用及非native saved导航2项最终GREEN `/tmp/workbook-error-checking-main-final-green.log`；保护工作表及disposed单项GREEN `/tmp/workbook-error-checking-protected-green.log`；Ribbon可用/pending/aria-busy单项GREEN `/tmp/workbook-error-checking-integration-green.log`（该轮main初始缓存settle用例失败，后独立最终通过，保留原日志）。集成含main/ribbon测试定向types exit0 `/tmp/workbook-error-checking-integration-types.log`。统一构建及真实built浏览器仍待完成。

完整前端types和Vite构建 `/tmp/office-wrap-error-checking-final-build.log` exit0（41.34s）；首轮新wrap测试fixture的resetNoWrap字面量类型已补显式类型，不改生产或放宽tsconfig。随后budget失败：XLSX main251.6KiB超过250KiB，日志 `/tmp/office-wrap-error-checking-budget.log`；预算契约通过。已将独立error checking controller配置单独chunk，未升cap，重新构建和最终budget仍待结果，不以首build宣称验收通过。

独立error chunk后完整构建 `/tmp/office-wrap-error-checking-chunk-build.log` exit0（40.12s），但主包仍250.2KiB超过250KiB，预算失败保留 `/tmp/office-wrap-error-checking-chunk-budget.log`。进一步把共用goto-reveal纳入既有workbook-navigation分块，仅构建配置变更，未改运行逻辑/预算cap，最终构建与浏览器仍待结果。

最终统一 `/tmp/office-wrap-error-navigation-build.log` exit0（完整types/Vite40.28s），同前缀budget/contract均exit0，XLSX main249.2KiB、error checking1.6KiB，未升cap。新dist冻结后真实built已放行，浏览器结果仍待验收。


## 最终 built 实测通过

2026-11-10，session47316终态exit0；`/tmp/workbook-error-checking-built-smoke.log` 为ok=true、18 checkpoints、120实际JS、saveCount=0、pageErrors=[]。一次运行通过，无重复probe。总manifest `/tmp/workbook-error-checking-built-evidence.json`，原始完整结果 `/tmp/error-checking-built-HDMduP/result.json`，即时cases.json及18张截图均保留。

真实openpyxl XLSX含Protected/Editable/Other/Clean四表。官方计算后当前错误表依次B2 `=1/0`→D4 `=#REF!`→F6跨Other!B2传播DIV/0→I9 string `#FIELD!`→Z220 string `#REF!`→B2回绕，精确5项；H8 `#REF!suffix`与J10纯文本`=1/0`未误报。每次官方名称框地址与反馈一致，实际canvas选择边框可见；root及probe执行者目视 `/tmp/error-checking-built-HDMduP/4-Z220.png`，远处Z220所在行220和列Z真实显示、反馈/名称框/蓝框一致。Clean没有被其它表错误误报；Other只报本表5项。

受保护表可只读导航，检查前后localStorage、undo/redo、保存状态及保存按钮状态精确相等。Editable仅公开键盘修B2为7，扫描立即变为4项而跨表F6仍报错；再次连续next/wrap未改用户编辑后的history/draft/status。公开Undo恢复B2后再次5项，检查未吞Undo或产生新历史。全程零保存请求。`source.xlsx`、`download-before.xlsx`、`download-protected-after.xlsx`、`download-after-user-repair.xlsx`真实HTTP下载均SHA256 `ae4558198a24cf2d57746b51723adab010c007bf6ecbdb4835167ff23375951c`；用户修复只保留为本地草稿，下载的是未保存源文件，不冒称已保存修复。

Chromium140.0.7339.16；120个实际加载JS均HTTP200且SHA与本地新dist一致。主要资源 `lazy-workbook-main-D9WyaCv5.js` SHA256 `b54cfa2dc6fb467878efada34667683985bdd1d2592271f754c5a2b0c3715542`，`lazy-workbook-error-checking-B0juLW5T.js` SHA256 `9b3a90088338f5560d663d04799409f0e5c2a40a766d6ac2aef00d5b33ddcc75`，`lazy-workbook-navigation-D_ByP4ts.js` SHA256 `625d2ba9c87c9262d31e0ecafe587357d95f19c4a5d75bd596d5fe1e12456509`；完整120身份及截图/源/下载SHA见manifest。

本项验收范围为当前完整载入表已有结果检查及只读导航；不是Excel完整语义规则向导、自动修复/忽略规则、跨整簿流式扫描或桌面Excel等价。authorization/context为本地夹具；真实产品built入口、官方计算/UI、源与下载HTTP均实际执行，不宣称生产授权服务验收。未全测或重复旧专项。
