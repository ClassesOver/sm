# 全局注释不可用时的普通字符混编

2026-11-10。本批解除“全局注释能力不可用”与普通安全段落字符混编的耦合，未开放未知注释协议。

先前普通干净 DOCX 的同段改字+局部格式已由 notes normalizer 的 final-run fallback 支持；本次真实重复 note、悬空引用来源均无 `notes` 模型，普通段落仍 `editable=true`，前后端却连带拒绝。新增纯正文辅助继续复用原差分、来源坐标、格式白名单和 canonical replay。

main 缺 notes 模型时，先执行既有 ordinary diff；失败才对普通 editable 来源尝试纯 run 计划，第二次检查失败仍抛原错误，不吞掉 section/header-footer/layout 原因。草稿回放只重建对应正文，保留未编辑的未知注释引用及显示编号。服务端只有无 notesPlanner、来源未保护且普通 paragraph 可编辑时放开最终 run 计划；注释操作、来源 marker、伪造引用和未知内联对象仍拒绝。

验证与证据：

- `/tmp/word-plain-without-notes-back-red.log`：重复 note / 悬空引用正向两例精确失败，既有四类拒绝边界通过。
- `/tmp/word-plain-without-notes-back-green.log`：9 例通过，涵盖两正向及 note 来源、伪造新/旧 marker、注释操作、陈旧/其他 block hash、未知内联对象拒绝。未知注释部件、关系、Content_Types、未编辑正文源段逐字节保留。
- `/tmp/word-plain-without-notes-front-green.log`：新 helper 与现有主视图 recovery 两文件 38 例通过。
- `/tmp/word-plain-without-notes-opaque-front-final.log`：额外独立契约验证未知注释引用编号不改、未知内联改写拒绝。初版手写 plan 的 inheritFrom 不符合既有 canonical 规则而被正确拒绝，改为末字符来源 4 后仅重跑该例通过。
- `/tmp/word-plain-without-notes-gui-red.log` / `...-gui-green.log`：Chromium 140 真实主视图普通段键入并局部粗体，草稿刷新、undo/redo、实际 patch_docx 保存下载重开；最终唯一 `patchParagraphRuns`，无注释操作，注释部件/关系/Content_Types SHA 保留，pageErrors=[]。
- tsc 本批检查只有并行测试类型诊断，已交所属 agent 修复；最终类型检查、构建和预算由 root 统一执行。
- root 最终构建冻结后，`NATIVE_GUI_PREVIEW=1` 同场景完整通过（`/tmp/word-plain-without-notes-built-preview.log`，exit 0）。所有实际加载 JS 响应逐项 SHA 等于当前静态构建文件；包括 `lazy-docx-main-CetCLxMW.js`（`e40841f2b08d1c74a58e30f5bdd2fe772b22434a4748f57f89321253b73eb439`）和 `lazy-native-docx-engine-DsROsJBD.js`（`29e787ebfd5fe24856ad8b1d9a5eadc96cbb2ca04e8b2f9d7711f39c42af35a6`）。草稿恢复、undo/redo、真实保存下载重开通过，未知 notes 部件与关系保留，pageErrors=[]；没有重复 Python/前端测试组。

GUI 使用替身 context/file/preview 路由和真实 Vite/浏览器、Python bridge 保存；不代表真实 AgentOS 服务或 Office 桌面测试。没有运行完整 suite、提交或推送。

本批对独立 A（单元格边框+底纹组合）的只读交叉复核：新增多单元格颜色与多个有序边框 steps 的穿插保存检查，不重复 A 原整组测试。ZIP 所有成员在等效操作次序间字节相同，rich 正文和其他 part 保留；不同 cell 正文碰撞及冒用 cell hash 仍拒绝（`/tmp/word-cell-combination-review-final.log`）。前端未选中正文、其他 cell 底纹+正文、未知表属性、重复 docxIndex 和仅伪造 intent 检查均拒绝，多 cell 组合归一回放通过（`/tmp/word-cell-review-front.log` 和 `/tmp/word-cell-review-forged-intent-final.log`）。未发现生产问题、未修改 A 生产。
