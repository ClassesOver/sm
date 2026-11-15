# Word 已有批注文字：可信来源 helper 专项验收

日期：2026-11-11。仅新增来源 helper、专项测试及本文；不表示宿主、HTTP、UI 或完整批注族完成。前置设计见 [宿主计划](NATIVE_WORD_COMMENT_HOST_PLAN.md)，独立文字 core 见 [core 验收](NATIVE_WORD_COMMENT_TEXT_ACCEPTANCE.md)。复用项目既有固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的引擎代码，没有改 vendor 或重新构建产品。

## 接口与边界

新增 `smart_reporting/reporting/doc_engine/bridge/docx-comment-source.ts`：

```ts
inspectDocxCommentSource(authorizedBytes: Uint8Array)
// => {sourceSha256, sourceId: string|null, commentTargets, commentReadOnlyReason}
patchDocxCommentSource(authorizedBytes: Uint8Array, operations: readonly CommentTextOperation[])
// => Promise<Uint8Array>，只返回内存文件，不写磁盘
```

宿主必须先通过现有 scope/文档版本/文件 SHA 授权入口取得真实 bytes；本 helper 不证明文件读取权限，不接受客户端 XML、路径、source 对象或保护声明。每次 patch 都重验输入来源，再调用已有 `inspectCommentText` / `resolveCommentText` core。新建、回复、删除、解决/重开不在范围内。inspect 对来源失败返回只读原因，目标锚点/链接不可信则仅对应目标只读；patch 拒绝时不返回输出、不修改调用者 bytes，不会创建半份文件。

`sourceId` 由真实文件 SHA、固定且已核验的 comments part、document/comments 关系 XML hash、完整正文 XML hash 和实际 anchor 快照派生；core 再绑定完整 comments XML hash、ordinal 和原 comment 片段。任何源包变化使旧操作失效。inspect 模型不暴露原 XML；该字符串不是 scope 权限凭据。

## 来源校验

- 使用既有 `assertZipInflatesWithinLimits` 做真实解压预算（文件 24MiB，最多 2000 part，单 part 8MiB，总解压 64MiB）；XML读取再限 4MiB。解压/CRC 由 JSZip 负责，没有新增 ZIP 解压器。
- 现有 zip-gate 的 central scanner、源 loadDocxZip 的 Unicode neutralizer 均为私有函数，无法直接导入。最小补充是约40行 ZIP32 header 身份元数据检查：原 central/local 名一致、唯一且不含大小写别名、非规范路径、Unicode Path extra 或 ZIP64 extra。UTF8 flag 的真实名字也从 header bytes 核对，不依赖 JSZip `decodeFileName` 回调。无法支持的 ZIP 明确只读。
- 先获得受限 raw JSZip 视图，再用既有 `loadDocxZip` 对所有文件 part 逐字节比较；Strict/前缀转换、重复 style 清理等归一化产生差异即只读。原 comments UTF-8 fatal 解码，不允许损坏 UTF-8、非 UTF-8 XML 声明冒充原字符串。
- XML 复用既有 `xmlParser` / `attrsOf` / `childrenOf` / `nameOf` 及 `XMLValidator`，加拒绝 DTD、未知实体、非法字符、局部命名空间重绑定、未声明前缀和重复 expanded-name 属性；没有新增 XML parser/serializer。
- 只支持 package 唯一 officeDocument → `word/document.xml`、document 唯一 comments → `word/comments.xml`、可选唯一 settings → `word/settings.xml`。关系路径复用 `resolveRelationshipTargetPath`。main/comments/settings 的 content type 必须匹配；隐藏无关系 settings、缺 part、重复 content type 均只读。
- 所有实际 `.rels` 都从原 XML 列表核验重复 Id、命名空间、DTD、异常 TargetMode，避免 `parseRels` Map 覆盖重复 Id。comments 关系不能 External。comments 自身 hyperlink 必须具有唯一实际 r:id、标准 hyperlink Type、External 模式、符合既有 http/https/mailto 安全规则；该规则来自非可导入的 `edit-docx.ts`，这里只做最小同规则复用，无网络访问。内部/空/无法解释的 hyperlink 保守只读。
- protection 按真实 settings 的实际 Word namespace 解码，包括别名前缀、字符引用。任何缺失或未知 enforcement、强制保护、重复别名 enforcement 均只读；只允许明确 `0/false/off`。
- 实际 main 中每个 comment 必须有唯一、有序 start/end/reference；start/end 必须在 paragraph、reference 在 run 且 run 在 paragraph，marker 为空且仅有 w:id。未知正文包装、局部 namespace 变化、孤儿、多故事 marks 均只读。定位来自原正文，不接受客户端范围。

patch 整批规划后仅写核验的 comments part，并显式关闭 JSZip 自动补目录。写出后 CRC 回读、核对原 entry 集（包括原来没有目录 entry 的包）及所有 part 原 bytes；仅 comments part 可以等于 core 返回值。未知现代 parts、所有关系、正文锚点、作者与富文本由原包/core 原切片保留。

## TDD 与真实文件证据

仅运行本新增测试文件，没有重复原 core 全套、产品 build、全图 tsc 或完整测试。

```sh
smart_reporting/reporting/doc_engine/node_modules/.bin/tsx --test \
  smart_reporting/reporting/doc_engine/bridge/tests/docx-comment-source.test.ts
```

首轮 **10 组通过**，日志 `/tmp/word-comment-source-green.log`。覆盖实际 ZIP 来源/过期操作/迟到无效批次不改变 source、关系冲突和命名空间、保护别名/实体/缺失、真实正文锚点、外链安全、raw/normalized 差异、损坏 UTF8、真实重复 ASCII/UTF8 central 名、Unicode path extra、case alias、空内部链接、非法 marker 父位置、expanded-name 重复保护属性、没有目录 entry 的原包保全。

RED 证据依次保留：

- `/tmp/word-comment-source-red.log`：缺 helper 模块。
- `/tmp/word-comment-source-links-red.log`：空/内部 hyperlink 未收窄。
- `/tmp/word-comment-source-anchor-red.log`：marker 父位置未收窄。
- `/tmp/word-comment-source-expanded-red.log`：同 URI 的两个 enforcement 属性。
- `/tmp/word-comment-source-directories-red.log`：JSZip 隐式新增 word/ 目录。

实际文件在 `/tmp/word-comment-source-evidence/`，由 fixture → helper → 内存结果实际落盘；不是手写期望输出替代 helper：

- `source.docx` SHA256：`0693ef69d8df630a53dfce73b7fc698ec2c4d0591ca41b5952a6426b929f3ecc`。
- `edited.docx` SHA256：`3b931301705183c920852a7d4a314328ca73583329a07a98cc8ffe7f606088c2`。
- `model.json`：可信源模型；`zip-lxml.json`：独立 Python zipfile+lxml 的校验结果。
- `duplicate.docx`、`utf8.docx`、`unicode.docx`：真实 ZIP 故障向量，不是 JSZip Map 的 mock。

独立 ZIP/lxml 确认 14 个 entry 集不变，所有 XML/rels 可解析，**只有 word/comments.xml 改变**，文字为 `新😀 & 中文`；原斜体、hyperlink、document anchor、commentsExtended/commentsIds/commentsExtensible/people 的未知内容及所有 rels 原 bytes 保全。压缩包重新生成会改变 ZIP 容器元数据；本契约是 part 内容和 entry 身份保全，不声称整个 ZIP bytes 不变。

尚未接 `edit-docx.ts` inspect/patch、Python白名单、宿主授权调用、公开 HTTP 或前端面板/Undo/草稿恢复/flush。没有签发链路修改，没有运行发布链路回归，不宣称用户批注闭环或桌面 Word 视觉验收通过。未 commit/push。

## 独立 review 后的故事来源修正

独立 review 发现首轮“其它 story”使用 `word/` 路径及 ASCII 前缀正则筛选，遗漏真实绑定的 Unicode 前缀 header 和位于 `headers/` 的 header。本轮新增两份真实绑定 DOCX 回归，先确认 inspect 错误授权（RED：`/tmp/word-comment-source-story-red.log`），再移除该正则。

现在对所有 `.xml`、Override/Default Content Type 标识为 XML 的 part、document 实际 header/footer/footnotes/endnotes/glossaryDocument 关系目标，复用现有 XML parser 遍历并按继承的**实际 Word namespace URI**识别三类 comment marks；不依赖前缀拼写或 `word/` 路径。其它 part 出现实际 Word marks 即来源只读。未知命名空间的同 local name 不是 Word mark，真实 unknown XML 正例验证其内容可原字节保全。额外的非 `.xml` Default Content Type XML 向量也先 RED（`/tmp/word-comment-source-default-story-red.log`）后通过。

新增4组窄向量 GREEN：`/tmp/word-comment-source-story-green.log`。最后只运行这4组加已有真实 DOCX+lxml正例，共 **5组通过**：`/tmp/word-comment-source-story-final.log`；未重复 core 或完整测试。真实来源 `unicode-story.docx` / `outside-story.docx` 保留在原 evidence 目录；非法输入无输出且 source bytes 不变。最后重跑正例生成的 edited.docx SHA 已更新到上节，独立 ZIP/lxml 仍确认只改 comments part。该修正仍未接宿主/UI。
