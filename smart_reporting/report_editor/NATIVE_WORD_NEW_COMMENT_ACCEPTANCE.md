# Word 新建批注增量验收（2026-11-11）

## 固定来源与实际语义

固定源码 /home/junge/pros/genoffice-source-full，ref f8c17004fb730df11f0f743164ffd8b4281bb38c。

- apps/docs/src/renderer/review-actions.ts:169–232：取消只清 pending range；新建先保存选区，空光标用 wordRangeAtCaret；提交后按真实文字节点范围加 mark。作者来自 authorName()（设置未加载时中文默认“用户”），日期为 UTC、精确到秒的 ISO 字符串。新线程没有 parentId；回复另有独立动作，不混同新建。
- editor/comments.ts:26–76：UTF16 的准确 from/to，可跨 run、跨段和重叠；不能以整段替代部分选中文字。空段内部无 text node，但不打断跨段选区。
- components/ribbon-tabs.tsx:999–1005 与 ribbon-insert-tab.tsx:1128–1145：审阅“新建批注”和插入“批注”共用回调和真实 IconComment SVG。
- 来源 SHA256：review-actions 2b856090cb56b26ffd3b96a693a72c4b76dbbccc43ceb05e7abc83baccf61d8a；editor/comments 9bd8ef6b1d065e7aceafc27c2b56a9a016adb4ccd09d42bfaad2296bbad89e40；author-name 1cda3fc4e817ca72328ed8c57c8a55de09141b7386e46bdbb72cf047d59b0d6f；ribbon-tabs d475b39d10a2b8dacfcf6a5293ec87f15e0a2d00b9d22d46f8e35ebb39e1cff2；ribbon-insert-tab 6776b90c10b42033b3e3efbc7dca31950d5e2e2e7342ed40fa58602c95cc561f。

## 最小实现

前端与 engine bridge 的 docx-comment-create.ts 增加 createComment，复用既有原 bytes helper、文档/作用域授权、Python/Node 薄桥、NativeDraft 和真实保存发布链；没有重做已有批注文字编辑，没有调用 saveDocx(options.comments) 重建整个批注族。

服务端以原始快照 sourceId、真实 paragraph SHA、source block/paragraph ordinal 及 UTF16 起止/实际文字核验整个批次，拒绝旧版本、伪造文字、切断 surrogate、跳过中间段和混合正文操作。普通空段仅允许在选区内部作为 source-bound 0..0 范围，首尾仍必须包含实际文字。新数字 ID 扫描所有实际 XML/content-type XML 部件的已有 ID，含非 .xml 扩展名；paraId 也避让整包已有 paraId/durableId。新增独立根线程、作者和时间均保留。

锚点与新批注通过现有 XML 分片和 fast-xml-parser XMLBuilder 创建；不把客户端 OOXML 拼入包。只修改所需段内 run/锚点及 comments；无批注的来源会添加合法 part/relationship/content type。既有 commentsExtended 按已知 schema 追加根线程记录，旧项、people/commentsIds/commentsExtensible 和未知 XML 原字节保留，不重建。对未知现代 metadata schema 不猜测和重写。

前端新建 composer 保存真实选区；取消不写草稿。添加或 native-session 保存前 flush 将新意图纳入同一 PM doc 属性/NativeDraft，支持 Undo/Redo 和恢复；保存通过原不可变修订链生成下载。两个入口共用控制器、中文标签与源 SVG；未失焦输入不依赖 blur 提交。

## 已验证证据

- 初始 core RED：/tmp/word-comment-create-core-red-20261111.log（缺失新能力）。首次实现局部 fragment 缺 namespace 失败后，改为在已经完整验证的原文环境内用现有 parser 解析片段；另保留测试换行转义与一次错误工作目录失败日志，不将这些当生产缺陷。
- core/source 受影响专项：/tmp/word-comment-create-core-source-20261111.log，17 passed。恶意 ZIP duplicate fixture 的预期 Python duplicate-name warning 保留。
- 最后 core：/tmp/word-comment-create-core-empty-final-20261111.log，5 passed；覆盖部分 emoji run、跨段、普通空段、表格格内精确范围、既有/重叠线程、现代 metadata、非 XML 扩展名 ID 避碰、拒绝旧来源和非法后续批次。/tmp/word-comment-create-core-20261111/{source.docx,saved.docx,zip-lxml.json} 含独立 ZIP/lxml 回读。
- 前端基础：/tmp/word-comment-create-frontend-red-20261111.log → 同前缀 frontend-green；跨空段新增严格 RED→GREEN：/tmp/word-comment-create-empty-{red,green}-20261111.log，最终 3 passed。没有将普通空段误称复杂锚点后缩窄支持范围。
- 主入口：/tmp/word-comment-create-main-final-20261111.log，1 passed/51 skipped；双入口真实 SVG、部分文字、取消、未失焦 flush、Undo/Redo、恢复及 session 请求。首次主回归暴露旧测试 DOM 未清理及错误 SessionOptions 调用，两者仅修夹具，失败日志保留。
- 受影响旧文字编辑：/tmp/word-comment-create-affected-frontend-20261111.log，10 passed；未运行完整前端 suite。
- 真实 HTTP：/tmp/word-comment-create-http-20261111.log，1 passed/21.10 秒；后续 ID/content-type 校验打包后的受影响单项：/tmp/word-comment-create-http-final-20261111.log，1 passed/21.26 秒。真实 FastAPI 会话、CSRF、生产 Node 桥九次调用；部分选区“chor t”、新 ID 与旧 ID 无碰撞、原文件不变、revision 2/parent 1、幂等只完成一次、实际签名下载、新修订重开、旧来源/伪造文字拒绝均通过。第二轮目录 /tmp/word-comment-create-http-final-20261111/test_create_comment_http_exact0 有原文件、下载文件和 evidence.json。
- HTTP 特意令 validator raise，结果仍 validation=false 且原因保留，已核验产物链接实际可下载；没有修改发布/导出链，不增加验收阻断。保留环境已有 imghdr DeprecationWarning，不声称零 warning。
- 前端统一 build 仅由 root 执行。旧 9f184 或较早 assets 不视为本轮浏览器验收；最终冻结构建的 Chromium 证据见下节。

## 打包身份与环境

原始生产桥 SHA256 为 c1a55a650cbef8d9d75602cbc19f2a2300a302a946f65273fe095f5e5aa33add；第一次新建功能打包为 5647e96c7a7459bef66e7a2ed5f87093035c38e1bb2c537388936485bd3f7e7d，对应首轮 HTTP；完整相关 XML ID/日期校验后为 b862df29c12298253be97badfacb16dc2805bb92bf6a956382edafaf9daef47d，对应第二轮 HTTP；普通内部空段修复后的最终桥为 abe54d7c7306eb05a136e6b8caf7255f80e870ee3eee88fa154fb7245b30fd71，对应 core 五项和最终 built browser。每次仅在实现实际变化后必要 bundle，没有运行完整 suite。最终类型检查 /tmp/word-comment-create-types-freeze-20261111.log exit0。

HTTP 使用真实 FastAPI middleware、签名 grant/session/CSRF、实际生产 Node bridge 和下载 router，仓储复用既有内存 Repository，正文为合成 DOCX；不是已部署生产登录或实际用户数据验收。浏览器 API route fixture 另行明确标识，不将两类环境混为一谈。

## e13 构建完整交互浏览器闭环

2026-11-11 使用 root 最终统一构建，在 Chromium 140.0.7339.16、端口 4308 执行一次 smoke，exit0。日志 /tmp/word-comment-create-browser-final-20261111.log；完整证据 /tmp/word-comment-create-browser-final-20261111/evidence.json，ok=true。API 路径 /reports/v1/native/fixture-comment-create/{1,2} 明确为 fixture，保存实际调用生产 Python/Node bridge；真实 HTTP 鉴权与签发由前述独立专项覆盖。

- manifest SHA256：e13de64ff923e7fb122a0e0b053331d7de3729247c7526f1f32d859c3868b210；生产 bridge SHA256：abe54d7c7306eb05a136e6b8caf7255f80e870ee3eee88fa154fb7245b30fd71。122 个实际加载 JS response 均逐一比对原始响应字节与磁盘 SHA。
- lazy-unified-main-CDx5xlXk.js：16812 bytes，SHA256 0c805fb6d7ca45e8934b20da7bbe81765c39d1166fd96ccdc9e66eccff40706e；lazy-native-main-DVVvQpDh.js：22664 bytes，SHA256 a15834539ec1a5cced494373f27af105b3c4d8645cb53f25f4e7e0893671a2db；lazy-docx-main-CQiXXdsv.js：188811 bytes，SHA256 e52351683defe418ad0cc0b6a8cfe950205ef815c1f495c8879a4ebe3ba5f8c9。
- 取消不入草稿；新建后 Undo/Redo、reload 恢复通过；第二条中文 emoji 批注未失焦即保存。两个重叠锚点均为 UTF16 from=2/to=8、实际文字“chor t”，原 ID1 保留，新 ID0/ID2 无碰撞。作者“用户”，UTC 秒时间分别 2026-11-10T19:34:36Z 与 2026-11-10T19:34:38Z（本地均为 2026-11-11）。
- 原 DOCX SHA256 b01f670b124be13d8a234a54e88b0b380299692d51675ab28c70978b75003d22 保持不变；实际下载文件 SHA256 549f88218438ea954fb9ff607e00a30bc190c85fad9b63fe161aca92d4d0fd5e。独立 ZIP/lxml 回读确认仅 word/document.xml 与 word/comments.xml 改变、全部 XML 合法、原批注保留。保存后 revision 2 可重新打开并读取新增批注；旧 source 操作由实际 bridge 拒绝。
- 故意验收失败的 fixture 仍显示具体原因与下载链接，保存后输入禁用。pageErrors、consoleErrors、failedResponses 均为空。new-comment-history.png、new-comment-unblurred.png、new-comment-delivery.png、new-comment-revision-2.png 四图已逐张目视：中文入口、源 SVG、精确引文、正文、交付告警和重开批注可读；不宣称完整桌面 Word 像素一致。

本次浏览器覆盖两个重叠的部分文字锚点；跨 run/跨段/普通空段/表格等范围仍对应各自 core 与前端专项，不冒称均在浏览器重测。收尾独立检查端口 4308 已关闭，无 smoke 残留进程。

## final2 构建仅入口与资产连续性

PDF 专项修复后 root 再次统一构建，最终 manifest SHA256 更新为 e2faddb5fb62f0db91b90b3248be4b8355ab5979d0b110eaa92dfde27dfe4daa。本轮没有修改 Word 生产源码或 bridge，没有重跑完整批注保存 smoke 或 HTTP；上节完整交互证据仍属于 e13de64 构建。

复用原 smoke 新增 DOCX_COMMENT_CREATE_ENTRY_ONLY=1 分支，在 Chromium 140.0.7339.16 实际从 native 入口加载 docx-main，单次 exit0。日志 /tmp/word-comment-create-entry-final2-20261111.log；独立证据 /tmp/word-comment-create-entry-final2-20261111/evidence.json，mode=built-browser-comment-create-entry-only、ok=true。仅 GET context/file 与 operations=[] 的 preview 请求；正文 DOM、空 NativeDraft 与源 DOCX 身份保持不变，未打开新建 composer，零编辑、零 save、零 export。

- 审阅“新建批注”与插入“批注”均可见、可用，aria-label 分别为“新建批注”“为所选内容新建批注”；两个 SVG 的两条 path 与固定来源 IconComment 逐字一致。entry-review.png、entry-insert.png 已逐张目视，中文与图标正常可读。
- 实际加载 122 个 JS response，原始字节 SHA 全部与最终磁盘一致；lazy-unified-main-Clb0faQN.js 为 16812 bytes、SHA256 d0286a4a6e49c7f7aeac4cb40b903cb3c59c0d1c982ca049b4978504e690571a；lazy-native-main-CoBCbb8k.js 为 22664 bytes、SHA256 5e89f510fe441d829ea9695e9673bd3048eab98c7df903acdead05e5a0c2c6a7。
- lazy-docx-main-CQiXXdsv.js 仍为 188811 bytes、SHA256 e52351683defe418ad0cc0b6a8cfe950205ef815c1f495c8879a4ebe3ba5f8c9；生产 bridge 仍为 abe54d7c7306eb05a136e6b8caf7255f80e870ee3eee88fa154fb7245b30fd71。pageErrors、consoleErrors、failedResponses 均为空，端口 4308 已关闭。

final2 仅证明最终构建入口、中文双入口和运行资产身份，不冒称在新 manifest 下重做完整交互、下载或修订重开。API route 继续明确为 fixture，真实 bridge 仅执行来源 inspect。

## 明确边界

当前精确锚点覆盖标准主正文、简单 run（保留 rPr）、跨 run/跨段/内部空段、普通表格格内/跨格文字及与既有简单批注重叠。不是整段降级；不能安全绑定时整批拒绝，不截取一部分作为成功。

超链接、域、修订、绘图/内联对象、控制字符、SDT 包装、非主 story 等复杂锚点只读并给出具体原因；标准包路径或可信原 bytes/namespace/保护条件不满足时不授予新建能力。此边界是当前宿主安全适配能力，不声称固定源本身不支持这些对象，也不声称完整源功能等价。源支持的受保护文档 comments-only 限制尚未由本宿主授权暴露，没有绕过保护。

本增量创建文字根线程，不扩展图片批注、回复、解决、删除、线程作者身份服务或多人协作。浏览器 API route fixture 与生产鉴权专项分别表述，不能用基础 provider probe 或 DOM 测试冒充完整保存验收。
