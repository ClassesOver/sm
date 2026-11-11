# 正文简单修订 built GUI 专项验收

日期：2026-11-10。状态：**本次简单顶层正文修订 built GUI 专项通过**。在 root 通知最终 build-v2 和 bridge bundle 成功后，完整浏览器仅运行一次、exit 0；五次实际保存、下载、新修订重开及 ZIP/lxml 独立校验全部通过。不是完整 Word 审阅族验收。

脚本：`frontend/smoke/docx-text-revisions-built-smoke.mjs`。本任务只新增该 smoke 和本文，不改生产、不运行产品 build、不提交推送，不跑全量测试。

## 验证契约

- 真实 DOCX 来源由 python-docx 包装 ZIP，原正文写入简单顶层 ins/del wrappers；Python `inspect_docx` 签发 reviewTargets。四个 wrapper 同段、同 `w:id=7`、同 author/date；相邻两插入、相邻两删除，含重复中文/emoji 文本。另保留前后段、header/footer、opaque customXml part。
- Chromium 加载现有 built native.html，通过审阅 tab 的 `text-revision-list` 和“正文修订列表”执行定位、下一条、接受/拒绝；不注入 editor 实例或私有 PM 意图。
- 五个独立保存场景：接受插入、拒绝插入、接受删除、拒绝删除、同段四目标批次。每场景检查 Undo/Redo、local draft reload、公开 save 的精确 `resolveTextRevision` 请求，且禁止偷偷降为整段替换。
- fixture HTTP 路由只代理报告授权 context/file/preview/save。save 使用真实 Python `patch_docx`；下载使用真实本地 HTTP 附件服务器和 Chromium download，再独立 zipfile/lxml 回读。
- 独立 verifier 直接按原 XML wrapper ordinal 和决策计算期望，不调用生产修订 core 计算期望；核验整个 document.xml 的 C14N 结果、前后段、所有非目标 ZIP 部件 SHA256、所有 XML/rels 可解析及 ZIP CRC。
- 每次明确打开新 revision URL 后，检查只列出剩余目标；四目标批次必须零剩余且 Next 禁用。浏览器加载的 JS 内容逐项与当前 static/assets 文件 SHA256 一致。
- 成功的保存先写 checkpoint；复跑使用 `DOCX_TEXT_REVISION_SMOKE_DIR` 恢复已保存产物，避免重复提交。保存后仍须下载验证与新修订重开，不以 checkpoint 文件存在替代验收。

## 当前实际执行

1. `node --check frontend/smoke/docx-text-revisions-built-smoke.mjs`：通过。
2. 仓库根执行 `DOCX_TEXT_REVISION_SMOKE_FIXTURE_ONLY=1 node smart_reporting/report_editor/frontend/smoke/docx-text-revisions-built-smoke.mjs`：通过；输出 `fixtureOnly:true, sources:5, targetsPerSource:4`。证据目录 `/tmp/docx-text-revisions-built-Hwbrm7/`，留存 revision-1/10/20/30/40.docx 及 checkpoint。此命令没有启动产品 preview/browser，没有发生保存。

3. root 最终前端构建日志为 `/tmp/word-revision-final-build-v2.log`，root 通知 `lazy-docx-main-DwTCtJEL.js` 已含最终 ready guard；本 agent 未运行产品构建。
4. 仓库根实际执行一次：

```sh
DOCX_TEXT_REVISION_SMOKE_DIR=/tmp/docx-text-revisions-built-Hwbrm7 \
  node smart_reporting/report_editor/frontend/smoke/docx-text-revisions-built-smoke.mjs \
  > /tmp/docx-text-revisions-built-Hwbrm7/run.log 2>&1
```

实际结果：exit 0、`ok:true`、Chromium `140.0.7339.16`、5 次 save、5 次 Chromium 公开链接下载、5 次明确新修订重开，`errors:[]`。未遇到中断，没有重发保存、没有重跑整个 smoke。

## 最终文件与行为证据

以下文件全部位于 `/tmp/docx-text-revisions-built-Hwbrm7/`，是容器留存证据，不是永久资产：

| 场景 | 来源 → 保存修订 | 下载文件 | 实际文件 SHA256 | 重开剩余目标 |
| --- | --- | --- | --- | --- |
| 接受插入 | 1 → 2 | `accept-insertion-download.docx` | `bcd3fd243d3e8382c8fbd592620994b54e2f894fc967aeb4f123aa2b4310c95c` | 3 |
| 拒绝插入 | 10 → 11 | `reject-insertion-download.docx` | `359cfc8ef3a073ef9f452e3f1a5be1f84bbcbb90a88b3879349b06067b19e288` | 3 |
| 接受删除 | 20 → 21 | `accept-deletion-download.docx` | `8616a1495a798994970306595c9b75be4d2afd06297b268bbce364c8750b4c72` | 3 |
| 拒绝删除 | 30 → 31 | `reject-deletion-download.docx` | `52e3cf944b2bea48ace1d7fa71909a77f8ca5ae98b9cba68605b9f798bd50536` | 3 |
| 同段四方向 | 40 → 41 | `same-paragraph-four-download.docx` | `1a21380f4aa04947e5b9ed0ec9e1e879cbbf099b5c8ebd551a1b2f521f619ab5` | 0 |

每份下载身份与真实 Python 保存产物一致，ZIP CRC 通过、XML/rels 全部可解析；**各 19 个非目标 ZIP 部件 SHA256 全部不变**，含 header/footer、样式、关系、core properties、opaque customXml。原正文前后段不变，整个 document.xml 的 C14N 等于独立 verifier 按指定原 wrapper 计算的唯一结果。四方向的保留/移除和 delText→t 恢复符合预期。同段四目标的最终文字为 `前😀|中文😀同删二😀|后`；没有丢失同段先前的决策。

每场景都实际点击第二个相邻同 mark/相同文字 wrapper 的“定位”，DOM selection 的 UTF-16 from/to 必须等于服务端 `sourceRange`，再由 Next 到第一条删除；证明没有只按文本、author 或重复 `w:id` 猜目标。每场景完成一轮真实 Undo/Redo：单目标一次撤销恢复原 DOM，多目标一次撤销只去掉最后决策，Redo 恢复；刷新后 DOM 与决策按钮禁用状态精确恢复。公开 save 请求仅包含预期的 `resolveTextRevision`，没有 replaceParagraph 或重复目标。四单目标保存重开时各有 3 条真实剩余修订；同段四目标保存重开为 0 条且 Next 禁用，旧目标身份不再签发。

截图：每场景各有 `<场景>-draft.png` 与 `<场景>-reopened.png`，共 10 张。已实际查看 `accept-insertion-reopened.png`（3 条剩余目标）与 `same-paragraph-four-reopened.png`（0 条、Next 禁用）：modal、中文/emoji 文案与控件可见，未见裁切或错误覆盖。

`result.json` 与 `checkpoint.json` 包含完整操作原文、下载/独立校验结果、重开状态及身份；`run.log` 是未截断的实际执行输出。五份 `revision-2/11/21/31/41.docx` 是保存产物，五份 `*-download.docx` 是独立 Chromium 下载产物。

## 最终 built 资源身份

浏览器实际加载并逐项核验 **121 个 JS 文件**：响应均为 200，response body SHA256 等于 `static/assets` 同名真实文件。完整 manifest 在 `result.json.loadedChunks`，其中：

- `lazy-docx-main-DwTCtJEL.js`：`65e9986117efcda1b57e78a82e69147247688b73e733cae7239f6493fc0e6d88`。
- `lazy-native-docx-engine-BElqpfMB.js`：`fc2658a32ecde3c717d787240d93dce1baeb7d0ea1d6ce9ffc2b9aa39e3f67c5`。

资源身份只是证据的一部分；通过结论同时依赖上述真实用户操作、Python 保存、下载和重开独立检查，不能仅由 hash/manifest 推出。

## 已知验证范围

此 smoke 只证明授权的简单顶层正文插入/删除修订，不涵盖修订录入、全篇接受拒绝、作者过滤、复杂内联、嵌套修订、移动修订、表格/页眉页脚 story、批注或完整 Word 审阅族。fixture route 不代替真实生产会话权限与服务器部署端到端验证。未触碰发布签发链，不冒充非阻断发布回归已重跑。
