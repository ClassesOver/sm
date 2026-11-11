# 简单正文修订：宿主与前端集成验证

日期：2026-11-10。固定源为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本文覆盖原 core 之后的宿主、草稿和界面接入；旧 [core 验收](NATIVE_WORD_TEXT_REVISION_ACCEPTANCE.md) 中“尚未接入”的描述仅代表当时阶段。全量 Word/XLSX 对齐仍未完成。

## 已接入范围

- `doc_engine/bridge/edit-docx.ts` 签发顶层简单正文插入/删除目标与原 XML 贡献的 UTF-16 `sourceRange`。独立验证 document/body 命名空间、顶层归属与保护状态。
- `resolveTextRevision` 严格五字段：kind、blockId、expectedObjectSha256、revisionId、action。目标身份绑定原块快照及 wrapper 序号，不能使用可重复的 w:id、作者、相同文字或 PM mark 位置代替。
- 宿主对同段多目标一次验证原快照并处理，保存前验证整批，最终按实际输出位置核对 XML。Python 既有入口白名单接入，不新增下载或发布门禁。
- `docx-text-revisions*.ts` 提供原 baseline 投影、严格规范化与草稿重放。相邻同标记被 PM 合并时仍按原范围分别决策；普通 paragraph editable 没有放宽。
- 审阅页新增“修订列表”，按来源目标逐条定位、接受、拒绝；保留格式、中文/emoji、tab/换行等支持范围。用独立历史边界及 TRACK_IGNORE 处理真实 Undo/Redo；保存、关闭、只读或嵌套表输入锁定时拒绝写入。
- main 在 notes/plain fallback 前规范化修订段，再合并所有操作，统一核对总数 ≤500 及互斥。草稿恢复在过滤 note/patch 操作前校验整批。修订与同段其他写入、相邻结构目标，以及任意 setSectionLayout/insertSectionBreak 不混批。

复杂、嵌套、move、属性/表格/段落标记修订等保留只读。尚无新建跟踪修订、接受全部、完整批注编辑、完整审阅/保护功能。简单修订闭环不能据此视为整个 Review tab 已完成。

## 实际证据

| 层次 | 结果与留存 |
| --- | --- |
| 宿主专项 | 27 个不同用例通过；四方向、同快照多目标、跨段插入后的输出索引、迟到失败无输出、同段冲突、命名空间及保护。`/tmp/word-revision-host-green.log`、`word-revision-protection-green.log`、`word-revision-mapping.log`。 |
| 生产 Python 保存 | `/tmp/word-revision-host-20261110/`：source/resolved DOCX、model、operations、manifest、原/预期 XML；独立 ZIP/lxml 核对 16 个非目标部件字节相等。不是 HTTP 认证测试。 |
| 映射与列表专项 | 9 项窄测试通过，覆盖重复 wrapper ID/相邻同 mark/emoji/换行、精确范围、严格投影、真实 TrackChangesExtension 与 UndoRedo。永久测试为 `docx-text-revisions.test.ts`、`docx-text-revisions-import.test.ts`、`docx-text-revision-controls.test.ts`。 |
| 宿主真实 model → PM | 同宿主证据目录中的 `frontend-projection-evidence.json`、`frontend-projection-probe.log`；四方向 inline 与 core 保存后 parse 的 PM 结果逐字段一致。临时 probe 已移除，不交付依赖 /tmp 的测试。 |
| collector/replay 接入 | `docx-text-revisions-integration.test.ts` 两项通过；日志 `/tmp/word-revision-integration.log`。普通操作旧专项 59 项通过，`/tmp/word-revision-existing-operations.log`。 |
| main 实际 collector | AST 提取实际闭包、使用真实 schema/编译器：4 项组合及篡改用例通过；另只执行新增 500/501 边界的两项，通过。`/tmp/word-revision-main-collector.log`、`word-revision-main-collector-boundary.log`。 |
| 草稿恢复 | 45 项通过，`/tmp/word-revision-recovery-init-green.log`。更新过期字体/嵌套表 mock 后暴露多节初始化早于 sectionRibbon 的 TDZ，增加 ready 守卫后通过。只修改受影响初始化顺序。 |
| 构建与门禁 | 最终 `npm run build` 通过，`/tmp/word-revision-final-build-v2.log`；产物 `lazy-docx-main-DwTCtJEL.js` 已直接核对包含最终 ready 守卫。`check:budget` / `test:budget` 均通过，日志同前缀 final-budget / final-budget-contract；未扩大预算。桥最终重打包 `/tmp/word-revision-final-bridge-bundle.log`。 |

最终追加 `tsc --noEmit` 通过（`/tmp/word-revision-final-typecheck.log`，exit 0）；覆盖构建期间最后的初始化守卫及测试 fixture 修改。

额外类型错误修正只将两个 never helper 改为 function 声明，使 TypeScript 能正确收窄；没有放松运行时验证。构建中的现有大 chunk 提示、第三方 PURE 注释提示不属于本项功能验收。

恢复专项最初因旧 mock 缺少字体函数而失败，随后 importOriginal 尝试又受旧 decoration mock 影响，最终以保持轻量的缺失导出补齐解决。一次误从仓库根启动的同名测试搜索命中 worktree，未收集测试（日志 `/tmp/word-revision-recovery-updated-fixture.log`），不计测试通过或产品验证。没有运行完整测试套件。

## 浏览器与交付边界

真实 Chromium、公开 save/download 路径的 fixture 验收由 [built 验收](NATIVE_WORD_TEXT_REVISION_BUILT_ACCEPTANCE.md) 单独记录，以该文档最终结果为准。该 fixture 使用真实 Python patch 和下载文件身份，认证、revision 路由由探针提供，不能等同生产认证集成或桌面 Word 排版等效。本轮没有提交、推送、部署，也没有修改报告发布签发链。
