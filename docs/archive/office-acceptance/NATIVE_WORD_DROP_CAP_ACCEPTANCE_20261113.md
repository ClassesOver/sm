# Word 首字下沉：固定源接线与保存验收（2026-11-13）

参照 `/home/junge/pros/genoffice-source-full`，固定提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。源 `apps/docs/src/renderer/components/ribbon-insert-tab.tsx:1014–1042` 已有“无／下沉／悬挂”，以 `dropCap` JSON 属性表示、默认三行；现接入已有源菜单、DropCapExtension 与原 `mergePPrFormat` 写回，不另写渲染器。

## 本次实现边界

- 可选取可编辑的顶层正文、标题、列表段落，设置或移除首字下沉，沿现有 Undo/Redo、NativeDraft、原生保存和新修订重开。
- 同一段可保留人工正文和局部富文本操作。首字下沉独立生成 `setParagraphDropCap`，不占用或清空其它意图；原生段落格式操作完成后再合成 `w:framePr`，保留其余 pPr。
- 新普通段落可携带 dropCap 保存；已有定位框、受保护或不可信锚点拒绝变更，原文保留。未把嵌套段落、全部浮动框或所有原生 framePr 组合纳入能力。
- UI 沿源固定三行；传输归一只接收 `drop`/`margin`、整数 1–10 行及空值清除。这是本地输入边界，不宣称源 UI 提供自定义行数设置。

## 定向验证

证据根 `/dev/shm/office-next-word-drop-cap-20261113`：

- `frontend-red.log` 保留最初按钮禁用、菜单缺失及新段属性丢失失败；`native-red.log` 保留原生操作不支持失败。
- `frontend-composition-red.log`、`native-composition-red.log` 分别保留与段落底纹回放及 paragraphProperties 组合时的真实失败，修正后组合用例通过。
- `frontend-green.log`：新增首字下沉 5 例、原段落对话框 20 例、正文装饰 4 例通过；相邻旧测试 `docx-body-decorations.test.ts:52` 仍有 1 例失败。相同断言在前批不可变物理源码独立复现，见 `predecessor-decoration-check.log`，因此未为本轮改写旧断言，不能写成全部相邻测试通过。
- `native-final.log`：9 例通过；独立桥验证见 `bridge-verification.log`。没有重复完整测试。

## 同一冻结构建的真实 HTTP 链

统一根 `/dev/shm/office-next-dropcap-combo-merge-master-elements-20261113`，4,283 份物理源码、104 份后端身份基线。`pre-http-integrity.json` 记录本轮入口、四引擎及日志身份；前端 tsc、Vite、未提高阈值的预算与预算契约、四个原生桥均 exit 0。workspace 包解析回同一物理快照，`BRIDGE-SOURCE-RESOLUTION.json` 未发现引用 live 业务源码的桥输入。

唯一完整链：`/dev/shm/office-next-word-drop-cap-20261113/browser-frozen-01/evidence.json`，`ok=true`：取消无修改 → 下沉／撤销／重做／清除 → 两段分别下沉与悬挂 → 同段手工插入 MANUAL、局部斜体 → 390px 菜单可达 → reload 恢复原草稿 → 一次保存修订 4→5 → 点击实际 Word 下载 → 新修订重开。没有重复保存。159 个不同 JS/CSS 响应逐一与冻结文件 SHA 匹配，实际 HTML、manifest、桥身份匹配，pageerror／console error／HTTP error／资产错误均为空。

- manifest SHA256：`615163c4c3ded620bb13234122204fc6f4002f03c2c8079a1d1c444da6373650`
- Word 桥 SHA256：`9cb976eadea1f7043bba39b6c872d07f0e2fc5928be6c626335760a62cd9080a`
- 下载文件：38,201 字节，SHA256 `270e909d471aba5a3e65bdfc2b4ea9a857ab2c078c067918de1843d2ca201b41`。

`independent-readback.json` 由 python-docx、ZIP、lxml 独立读实际下载文件：两段 `w:framePr` 分别 drop/margin、均三行；MANUAL／粗体／局部斜体与未知 `autoSpaceDE` 保留；未编辑的标题、表、sectPr 结构保持；16 个非目标部件原字节相等。含人工正文改动的此场景允许 core 修订元数据变化；cap-only 的非目标 core 保全由定向原生用例另行验证。root 已目视桌面及 390px 菜单截图，首字布局与三个菜单项可见。

## 身份与验收结论

HTTP 实际执行 live Python，104 份物理后端副本仅为身份基线。执行前 `render_preparation.py`、`service.py` 已被并发工作修改，与冻结基线不同；`backend-before.json`、`backend-after.json` 保留真实逐文件 SHA，本次执行期间 104 文件起止相等。不能称后端隔离或 104 文件均匹配冻结基线。runner、fixture 和三层 server 依赖的执行前字节副本与起止 SHA 单独保留。

保存回执保持 `validation.ok=false` 及具体 review 原因，同时签发实际身份核验过的文件下载链接。技术保存闭环通过不等于业务验收通过。整体四格式对齐 goal 仍 active；本专项不关闭其它未验证源入口、复杂嵌套对象或完整 AI 工作流。不提交、推送或部署。
