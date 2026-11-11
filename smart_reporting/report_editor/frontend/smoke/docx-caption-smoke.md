# Word → GenOffice 题注增量（2026-11-11）

固定参照：本地 GenOffice 源码 /home/junge/pros/genoffice-source-full，ref f8c17004fb730df11f0f743164ffd8b4281bb38c。参照 apps/docs/src/renderer/components/ribbon-references-tab.tsx:164 的 CaptionModal 与 packages/docx-engine/src/generate.ts:3027 的 generateCaptionXml。

## 可用范围

- 标签固定为“图 / 表 / 公式”，描述最多 1000 个 UTF-16 code unit，拒绝非法控制字符与未配对代理项。UI 修剪首尾空白；服务端仅接受规范化的描述。
- 光标必须位于可信原 DOCX 顶层普通正文、标题或普通列表段落的开始或结尾。独立插入一个原生 Word 题注段落；不在表格、内容控件、受保护对象内部插入。分节段落后拒绝插入。
- 每次只插入一个题注，独立保存；与正文、目录、书签、交叉引用等混合操作拒绝。前端一个 ProseMirror 事务，支持撤销、重做、同源草稿恢复和保存锁。
- 复用固定源 generateCaptionXml，生成真实 SEQ 域，含 begin / instruction / separate / 缓存数字 / end，begin 带 dirty 标记。**不会自动重排已有题注**；Word 中更新域后才由 Word 计算。dirty 不保证所有 Word 客户端打开即更新。

## 编号边界

GenOffice 原 CaptionModal 扫描 docProtected 计数再加一，不能证明中间插入、reset、显式数字或复杂域的真实编号。本增量不把其计数法包装成完整自动编号。

- 服务端从可信源 document.xml 读取真实完整 SEQ 域；客户端不能提供 number、genXml 或缓存内容。
- 同标签既有字段必须是简单 SEQ 标签 或 SEQ 标签 \* ARABIC，完整且非嵌套，并已有连续缓存 1..N；新缓存明确为 N+1。支持分拆 instruction run、XML 数字实体与 CDATA；字面 CDATA 与实体文本区分处理。
- 插入点必须位于该标签最后一个既有 SEQ 字段之后；可以在正文中间插入，但不能使后续同标签数字发生变化。
- 拒绝同标签的 fldSimple、reset、重复前序号、章节重置、其他数字格式、不完整/嵌套/锁定字段、修订和文本框内字段，或非连续缓存。不把不确定数字显示为准确预览。
- 其他标签的复杂 SEQ 不会误禁当前标签；Word 命名空间别名/局部改绑或需引擎归一化的源，由源核验或最终原始部件身份比对拒绝。

## 信任和保真

操作格式严格限定为 {kind:'insertCaption', blockId, expectedObjectSha256, position:'before'|'after', label:'图'|'表'|'公式', text}。

blockId = SHA256(sourceSha256 + ':block:' + docxIndex)，段落原 XML 另有 SHA256。服务端校验源快照、完整顶层段落和保护状态，只拼接 word/document.xml；其他 ZIP 部件、未知内容、属性和原段落不重新序列化。属性解析复用既有 XML 工具，避免带引号的 > 或属性值中的伪 w:instr 隐藏真实字段。

前端 normalize 只剥离与可信源推导完全一致的单个 docProtected 投影，然后交普通 collector 检查剩余内容，拒绝投影篡改。

## 验证与复跑

- bridge：./smart_reporting/reporting/doc_engine/node_modules/.bin/tsx --test smart_reporting/reporting/doc_engine/bridge/tests/docx-caption.test.ts。本轮遵循 RED → GREEN；后续边界仅定向复跑，无完整测试重复。
- frontend：在 smart_reporting/report_editor/frontend 执行 ./node_modules/.bin/vitest run src/docx-caption.test.ts，可用 -t 单独验证新增边界。
- RED/GREEN 日志均位于 /tmp/docx-caption-*，分别记录 bridge、frontend、CDATA、quoted-greater、position 的精确输出。
- 浏览器：DOCX_TEST_DIST 指向冻结前端目录，DOCX_TEST_ENGINE 指向冻结桥，必须传 DOCX_EXPECTED_MANIFEST_SHA256，执行 node smoke/docx-caption-smoke.mjs；DOCX_TEST_OUTPUT / DOCX_TEST_PORT 可隔离日志与端口。
- smoke 使用真实 locator 点击、PM 撤销重做、刷新恢复草稿、立即保存、真实 Python patch、下载字节身份、独立 ZIP/lxml、四个新修订重开；检验图1 → 表1 → 公式1 → 图2，保存返回 validation.ok=false 但链接仍签发且下载。保存/上下文 HTTP 响应为 fixture，不代表真实鉴权或线上发布。
- 浏览器执行前后核验 manifest、bridge 与每个实际 JS 资源 SHA256，生产文件冻结后才运行。本任务不修改发布链路、不运行全局 build/tsc、不提交推送部署。

## 本轮冻结浏览器证据

2026-11-11 在 root 冻结的 final3-static / final-engine 上运行一次独立 smoke，退出码 0，浏览器 errors 为空。

- Manifest SHA256：ee917f165ef2810a6abfbd41c0094bdc3ff258137e93735cf32d3c114efdac27。
- Bridge SHA256：ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6。
- 完成撤销、重做、刷新恢复、图1 / 表1 / 公式1 / 图2 四次真实 Python 保存，逐次签发并实际下载验收失败的产物，重开修订 2 至 5。
- 四次保存都只改变 word/document.xml；独立 ZIP/lxml 读取实际下载的修订5，检验真实 SEQ 字段顺序与缓存数字2，其余 ZIP 部件逐一原样相等。
- 证据：/tmp/sr-word-references-20261111/caption-final/evidence.json。
- 独立 ZIP/lxml：/tmp/sr-word-references-20261111/caption-final/independent-zip-lxml.json。
- 日志：/tmp/sr-word-references-20261111/caption-final-run.log。
- 截图：/tmp/sr-word-references-20261111/caption-final/caption-1-reopened.png 至 caption-4-reopened.png；已目视核对最终修订5，题注与正文正常排版，序号为图1 / 表1 / 公式1 / 图2。
- 下载文件：同证据目录 download-2.docx 至 download-5.docx。

此证据不替代 Word 实机更新域测试，也不代表验收故障注入报告被标记为通过；fixture 保持 validation.ok=false。
