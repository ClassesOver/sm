# Word 固定／最小行距增量验收

日期：2026-11-11。固定 GenOffice 来源：`/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

后续增量：自定义倍数已接通并另行验收，见 [自定义倍数行距验收](NATIVE_WORD_CUSTOM_LINE_SPACING_ACCEPTANCE.md)。下文保留本批当时的范围和证据。

## 本次范围

开始 → 行距 → 行距选项已由永久禁用改为可执行弹窗。支持唯一可信原有顶层正文段落、标题和列表段落的固定值 `exact`、最小值 `atLeast`，范围 1–1584 pt，精度 0.05 pt（一个 twip）；保留 1、1.15、1.5、2、2.5、3 六个倍数预设。固定／最小值与倍数互斥，切换时清除旧规则。来源为 `components/ParagraphDialog.tsx` 与 `paragraph-line-spacing.ts`；本地保留原始 twip 精度，不照搬来源读取时的小数舍入。

复用既有 Modal、焦点约束、PM 历史、草稿与 `setParagraphSpacing` 协议，以及 DOCX 引擎已有的 `mergeCellParaFormat` 写入能力。新增前后端共用的字段校验，不重建 writer。一次确定对应一个撤销步骤。取消、非法点值不修改文档；打开后文档、选区或只读状态改变则要求重新打开。表格、跨段选区、新增未保存段落、来源身份不可信等目标不开放；与不能组合的既有编辑冲突时仍遵守原 Guard。

不是完整段落对话框：自定义倍数、特殊缩进、制表位和其他段落高级选项仍缺；也不扩展页眉页脚、表格或文本框子编辑器。

## 定向测试

- 前端初始 RED：固定／最小值 collector 和 Ribbon 入口对应 3 项失败，定位到原协议限制与永久禁用。
- 接通后 `npm test -- src/docx-line-spacing.test.ts src/docx-operations.test.ts src/docx-home-source.test.tsx`：73 项通过。随后扩充边界后仅运行 `src/docx-line-spacing.test.ts`：18 项通过；两次数字有重叠，不相加。
- Python：`.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_docx_engine_bridge.py -k 'fixed_line_spacing or unmodeled_or_out_of_source_values'`：22 passed、91 deselected。覆盖 exact365、atLeast480、下界20、上界31680 twips、切回 auto360，以及缺字段、互斥混用、类型、上下界拒绝。
- 真实 ZIP 与 python-docx 独立回读行距规则／原值、文字与 run 格式、邻段和非目标包部件。既有 writer 会为目标 `w:t` 补 `xml:space="preserve"`；只排除此已定位的规范化属性，其他 run XML 仍逐字比较。首次回读失败来自该已存在规范化行为，未放宽其他差异。

本轮重新检查既有统一历史 helper 5 项通过；布局／页眉页脚历史在此前已交付，本轮没有再次实现。早期分页记录的历史缺口不应继续当成当前结论，见 `NATIVE_WORD_HIGH_PRIORITY_ACCEPTANCE.md` 与后续导航刷新验收。

## 冻结构建真实浏览器

脚本：`frontend/smoke/docx-line-spacing-built-smoke.mjs`。冻结资产 `/tmp/word-line-spacing-static-dez6m8bj/static`，manifest SHA-256 `86ee851c02adb25e3bc84a245f0fdeadf14756a885d66803aaa358cd1535e12b`。Chromium `140.0.7339.16`，实际加载 132 个 JS，逐个核验返回字节与冻结文件 SHA，前后 manifest 不变，`errors=[]`。

完整结果：`/tmp/word-line-spacing-built-RGzz3i/result.json`；截图 `reopened.png`；下载产物 `downloaded-2.docx`、`downloaded-3.docx`、`downloaded-4.docx`。

1. 取消／非法 0 值不产生草稿；固定 18.25 pt 生成 365 twips；正文 Ctrl+Z／Redo、刷新恢复通过。
2. 修订1→2：固定18.25 pt；修订2→3：最小24 pt；修订3→4：1.5倍。每次真实 Python→打包 Node 引擎保存、HTTP下载 SHA、独立 DOCX 规则／原值回读通过。
3. 明确打开修订2／3读到固定／最小原值，修订4重开读到1.5倍，正文保持一致。
4. 下载副本保留混合粗体／斜体、段后6pt、keepNext、邻段、表格和页眉。对三份保存产物额外离线比较：目标段落外全部 body XML 及目标段落其他 pPr 保持一致；对应断言已加入可复用 smoke。

只打开弹窗的截图补验：`/tmp/word-line-spacing-built-ywpxdK/dialog.png`；同一 manifest、132 JS、零保存／零导出、`errors=[]`，已目视确认弹窗与重开正文无裁切。

边界：授权、修订登记和发布响应为 fixture；真实文件处理、浏览器操作、下载字节及回读不是生产 DB／鉴权整链或桌面 Word／打印等价验收。fixture 特意返回 `validation.ok=false`，仍提供并使用 Word 下载链接；本轮没有修改生产发布／签发链路。首次沙箱运行在 Node→Python 子进程阶段受 EPERM 限制而中止；首个页面探针曾把撤销键发给 Ribbon，修正焦点后完整浏览器链通过，失败证据保留于 `/tmp/word-line-spacing-built-wQl4Dy`。

## 构建和剩余检查

`doc_engine` 的 `npm run bundle:bridges`、前端 `npx vite build`、`npm run check:budget` 与 `npm run test:budget` 均通过。新增弹窗单独分包，Word main 255390 < 256000 字节、render 723388 < 727040 字节、engine 423900 字节、行距模块3594字节；没有提高预算阈值。

完整 `npx tsc --noEmit` 仍失败：既有 `src/docx-ruler.test.tsx(25,54)` 的 `extendedIndents` 不属于 `Options`，详见 `/tmp/word-line-spacing-tsc.log`。Python 原测试文件的 Ruff 检查也仍有既有问题，不声明全局类型／lint通过。未重复完整测试套件；未提交、推送或部署。
