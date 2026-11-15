# Word 引用增量集成验收（2026-11-11）

固定源：/home/junge/pros/genoffice-source-full，HEAD f8c17004fb730df11f0f743164ffd8b4281bb38c。当前仅交付以下两个限定子能力，不关闭整个引用功能族。

## 本轮实现

- **普通书签交叉引用**：插入/引用功能区打开同一可信列表，在另一无书签普通顶层段落或标题的 UTF-16 光标处插入真实 REF 域。缓存从已保存单段书签原文取得，不接受客户端名称、缓存或 XML。复杂/跨段书签、歧义范围、保护和过期身份拒绝。见[专项范围](frontend/smoke/docx-cross-reference-smoke.md)。
- **图/表/公式题注**：引用功能区打开题注对话框；在原始普通段落、标题或普通列表的开头/结尾插入真实 SEQ 域。已有同标签字段须是连续 1..N 的简单序列，插入点须在其最后一条后。编号来自可信源，不接受数字覆盖；不自动重排和更新域。见[专项范围](frontend/smoke/docx-caption-smoke.md)。
- 两项均是单个独立保存意图，接入 PM 历史、UndoRedo、草稿恢复、来源/对象哈希、保存锁和销毁解绑。精确剥离可信投影后继续 ordinary diff，混合正文/部件修改不偷偷丢弃。

## 已有验证

- Python 真实打包 Node 桥：test_docx_native_references.py，2/2 通过；独立 ZIP/lxml 核实仅 document.xml 变化、未知部件保留、真实 REF/SEQ、特殊字符、旧身份/混合操作/伪造编号和中间插入拒绝。
- root 前端：docx-caption-dialog.test.ts、docx-reference-entries.test.tsx、docx-ribbon.test.ts，21/21 通过。对话框覆盖预览文本、caret、不再有效的选区、保存锁、失败不关窗；插入入口覆盖回调与 mousedown 保留选区。
- 各 owner 专项按 RED → GREEN 验证，详见两份专项文档；交叉复核额外发现并经 RED → GREEN 修复 CDATA 指令、属性值中大于号和数字实体缓存语义边界。真实数字实体按一次解码及 UTF-16 边界映射处理；若现有核心对字面实体二次展开，交叉引用来源明确只读，避免缓存与画布语义不一致。未重复完整测试，未修改发布/签发链。

## 最终冻结浏览器

冻结构建：/tmp/sr-word-references-20261111/final3-static；manifest ee917f165ef2810a6abfbd41c0094bdc3ff258137e93735cf32d3c114efdac27。冻结 bridge：/tmp/sr-word-references-20261111/final-engine/dist/edit-docx.mjs，SHA256 ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6。两项真实 Chromium 专项均首跑通过，root 已核验 evidence.json、下载独立 XML 结论、实际资源身份和成功截图。

Vite 与 Node bridge 打包均成功。Word main/render/engine 分别为 244187/714888/423900 bytes，全部在原预算内，未调宽阈值。最终共享工作区全局预算未全过：workbook-main 为259086 bytes，超253 KiB预算14 bytes；此前一次 frontend tsc 的 XLSX 测试错误后来被其它会话修改，故结束前再次检查；最新 completion-tsc.log 仍失败于并行 PDF/XLSX 代码（pdf-convert-office.test、workbook-editable-ranges、workbook-main、workbook-pivot 等），无本轮 Word 类型错误。此前阶段全局 tsc 曾通过，不代表不断变化的共享工作区最终全绿；未越界修复其它会话的代码。

## 浏览器结果

- 交叉引用：cross-reference-final/evidence.json，1 次真实保存，修订 2 重开；真实点击插入/保存、UndoRedo、刷新草稿和验收失败提示/下载均通过。独立 lxml 证明真实 REF SavedTarget 字段、可信缓存、原 bold 两段和书签保留，仅 document.xml 变化。
- 题注：caption-final/evidence.json，4 次真实保存、修订 2..5 重开；实际显示图1 → 表1 → 公式1 → 图2。每次均返回 validation.ok=false 及具体原因，下载链接/字节身份保留；最终下载独立 ZIP/lxml 通过。
- 两项均逐个核对 122 个实际加载 JS 的磁盘 SHA256，manifest 前后一致，errors=[]；运行后冻结 bridge 身份保持不变。本轮生产源码指纹亦保持不变。
- 证据根目录 /tmp/sr-word-references-20261111；成功截图为 cross-reference-final/success.png、caption-final/caption-1-reopened.png 至 caption-4-reopened.png。root 已目视最终两图，文字、编号与版式符合本次夹具。
- HTTP 授权/保存响应为本地夹具；真正修改和再 inspect 通过冻结 Python/Node 桥完成，不冒充生产鉴权整链。未提交、推送或部署。

## 尚未交付

PAGEREF/页码引用、复杂或跨段书签交叉引用、全局自动域更新、章节/重置/中间插入后的全局题注重编号、引文/书目/索引仍未完整实现。生产鉴权/发布整链、桌面 Word 更新域、PDF/打印机视觉等价不在本地 HTTP 夹具证据范围。验收失败仍签发已生成且身份可读取的产物链接，且不标记通过；本轮保持该既有契约。
