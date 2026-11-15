# XLSX 行列标题显隐：源行为与独立适配

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，`apps/sheets/src/renderer/ribbon-actions.ts:965–1020`。不是打印标题开关：更改当前工作表 `rowHeader.hidden` / `columnHeader.hidden`，执行官方 `sheet.command.set-row-header-width`（隐藏0、显示46）和 `sheet.command.set-col-header-height`（隐藏0、显示20）。源另修正 Univer 隐藏后重新显示时 `VIEW_MAIN` / `VIEW_COLUMN_RIGHT` 的 left，避免原生 `|| 46` 默认吞掉零宽。源把 `showHeadings` 记到 page setup journal，保存 `sheetView/@showRowColHeaders`；与编辑栏纯会话显隐不同。

本地引擎 page-setup writer 已支持 `showHeadings`；本轮需由 root 接入 reader/model、加载到 Univer、功能区和文件差分。独立 `frontend/src/workbook-headings.ts` 仅负责视图命令，返回 sheet identity/name/showHeadings，不自行 markDirty 或保存。Readonly 如同既有视图操作只改会话；可编辑按 root 差分链保存。不重建 Univer，不改任何单元格内容。

## 适配与边界

按固定源操作顺序先改旧 sheet config、再等待两尺寸命令，成功后修正捕获 viewport。增加本地 workbook/sheet core 与 active sheet 检查；避免异步期间替换工作簿、切工作表或关闭编辑器后，把迟到 viewport 修正作用于新目标。调用方可传 `isActive` 提供 dispose/busy 所有权。native 返回 false 或目标过期均拒绝成功结果，调用方不得记录成功；已经执行的旧目标 config/命令不伪称自动回滚。

## 定向证据

环境恢复后审查现存模块，发现仅检查旧 sheet 仍在工作簿中不足以检测 active sheet 已切换。新增定向用例先 RED，实际 promise错误地resolve成功（`/tmp/workbook-headings-switch-red.log`）；补 active core检查后 GREEN。

`npx vitest run src/workbook-headings.test.ts` 本次5项通过，`/tmp/workbook-headings-green.log`：隐藏/显示两header与零宽viewport修正、工作簿替换、同簿active sheet切换、native命令false、缺失工作簿。随后 `npx tsc --noEmit --pretty false` exit0（`/tmp/criteria-headings-typecheck.log`）。没有重跑完整测试。

这只证明独立模块定向契约，真实原生布局、功能区点击、文件保存重开仍待 root 集成和浏览器验收，不计该缺口整体完成。

Root链路补充：reader新增showHeadings（兼容旧模型省略，实际读取明确布尔）、withWorkbookView按源值灌入两header.hidden并保留已有header字段。真实ZIP默认/隐藏/恢复、真实Univer hydration及无关编辑、Python/openpyxl/ZIP仅目标sheet变化均已定向通过，日志/tmp/workbook-headings-reader-green.log、/tmp/workbook-headings-view-real-model-green.log、/tmp/workbook-headings-hydration-green.log、/tmp/workbook-headings-python-green.log。保护preflight只新增set-row-header-width/set-col-header-height两项视图命令，未放开真实行高列宽；负例RED→GREEN见/tmp/workbook-headings-protection-{red,green}.log。主入口/草稿/浏览器验证尚待继续。

主入口现已集成，按当前真实header配置与文件基线产生applyPageSetups差分；readonly仅视图。真实main1项及浏览器dev toggle/hidden键盘/draft/Python保存/rev2重开通过（/tmp/workbook-headings-main-preservation.log、/tmp/workbook-headings-gui-final.log）。初载曾浅覆盖Univer默认header尺寸，已由真实Worksheet negative修复为width46/height20默认并保留原对象字段，避免undefined尺寸引发输入/排版回归。最终统一build及预算通过，但标题独立无注入built图形验证仍待补，不把dev观察当静态证据。

最终标题无注入built /tmp/workbook-headings-final-built.log exit0：303 JS200/静态SHA，真实功能区toggle，原生clipboard验证隐藏时键盘值77.00，draft reload/Python保存/rev2隐藏重开/恢复显示，pageErrors=[]。不以aria镜像替代底层读取：文件真实reader/ZIP/openpyxl及dev native config已另定向覆盖。普通行高列宽保护边界未放开。
