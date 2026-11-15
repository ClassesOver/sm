# Word 高优先级增量验收（2026-11-11）

固定 GenOffice 来源为 f8c17004fb730df11f0f743164ffd8b4281bb38c。本轮三个独立增量：布局/页眉页脚统一历史、普通正文书签、可信简单正文修订批量接受/拒绝。完整 Word 对齐仍未完成。

## 统一历史

setSectionLayout、setHeaderFooter、setHeaderFooterLink 通过 NativeDocxHistory 文档属性事务进入正文 PM history；布局和正文交错时按编辑顺序撤销/重做。页眉子编辑器仍在提交前维护自己的输入历史，提交后作为正文历史的一个步骤。恢复草稿为打开时初始基线，不产生可撤销的恢复步骤；只读、保存、已关闭草稿的 Guard 不接受历史修改。相同操作不重复记录。

5 项 helper 测试与主视图交错历史/锁/恢复回归通过；布局/HF 定向回归通过。最终恢复测试另发现查找替换回放误将根历史属性视为正文差异，仅将 getBaseline 的 nativeDocxOperations 与当前状态同步，来源正文及严格 collector 校验不变；原失败项单独重跑通过。复用同一 Editor 执行外部 refresh 不清空既有 PM 历史，未将此边界声明为已解决。

真实 Chromium 复杂 10 页样本：修改页眉后退出输入、正文 Ctrl+Z 恢复、Redo 恢复修改；节页码格式/起始号修改后正文 Ctrl+Z 恢复；未保存预览、节继承/断链内容正常。errors=[]，保存/导出请求为零。脚本 smoke/docx-native-history.mjs；最终证据 /tmp/sr-word-high-priority-20261111/history-final/evidence.json。

## 批量修订

审阅面板增加“接受/拒绝所有支持的正文修订”，只处理服务端签名授权的顶层简单 ins/del。整批先核验来源和既有投影，再用一个 PM 事务提交；一次撤销/重做，保留已有单项决策，任一授权目标不一致则整批不变。复杂/嵌套/move/属性或其它故事修订保留，界面不得声称全文件修订全部处理。

9 项定向测试通过。冻结 Chromium 接受/拒绝各一例，真实 Python→打包 Node bridge 保存、下载 SHA、独立 lxml 对比、新修订重开通过。每例处理 4 个授权目标；仅目标 ins/del 包装改变，19 个其它 ZIP 部件及含 pPrChange 的复杂段不变，errors=[]。证据 /tmp/sr-word-high-priority-20261111/revisions/result.json；脚本 smoke/docx-text-revisions-batch-built-smoke.mjs。路由使用本地授权/修订夹具，不等同生产鉴权、桌面 Word 或真实打印验收。

## 书签与构建状态

书签范围、身份与保存协议见 NATIVE_WORD_BOOKMARK_ACCEPTANCE.md。7 项 bridge、5 项 frontend 与真实 Python 薄桥专项通过。真实指针暴露并修复 blur 事务重绘列表吞 click：定位/删除按钮 mousedown 保持选区；恢复结束后主视图重新刷新书签控件解除临时锁。最终冻结 Chromium 创建、PM UndoRedo、reload 恢复、定位、创建保存下载、新修订2删除保存下载、新修订3重开通过。两次均只改变 document.xml，所有 XML 有效，122 个 JS 身份核验、errors=[]；保存返回验收失败时仍保留下载。证据 /tmp/sr-word-high-priority-20261111/bookmarks-final/evidence.json。创建下载 SHA-256 c5a5b8fe4e818265b4d6c8e64de6bbd8be47f2aca9c5887739be0b5fb92bf626，删除下载 7e99ef97d888b6ab2cefa00950eacbbd046ee26746a1d3be9e7ed30c4fdaacc2。

最终冻结目录 /tmp/sr-word-high-priority-20261111/final2-static，manifest SHA-256 ae3123670680d5fc2a0e4529d61a560072b26c44cd67f4935fd10da223c3526a；浏览器逐 JS 验证身份与前后 manifest 连续性。最终历史探针通过；批量修订复用先前成功保存的不可变产物，只补最终构建的两例新修订重开，savesThisRun=[]，errors=[]。原始完整保存证据保留在 revisions/result-stage1.json，最终重开证据在 revisions/result.json。

前端 tsc 曾在该轮代码整合后通过；中途完整 npm build 被并行 slides-canvas-selection.test.ts 的 4 条 onSelectMany 类型错误阻断。最终 tsc 输出为工作区其它 PDF/XLSX 文件的错误（详见 /tmp/sr-word-high-priority-20261111/tsc-final.log），无本轮 Word 文件报错，不能标记全局类型检查通过。最终 Vite 打包与所有既定 chunk 预算通过；预算原值不变。Word main/render/engine 分别为 225699/714888/423291 字节。没有提交、推送或部署。
