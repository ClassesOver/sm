# Word 导航、大纲与刷新历史增量验收

日期：2026-11-11。固定 GenOffice 来源 HEAD：f8c17004fb730df11f0f743164ffd8b4281bb38c。

## 范围

- 标题导航：复用源标题识别与树模型，支持折叠、定位、活动标题与动态标题更新；普通段落/列表的标题样式继承也参与导航。同名、空标题按位置消歧。没有页面缩略图、搜索、移动/删除或升降级标题功能。
- 大纲：使用源 outline plugin 的页面/大纲切换与标题折叠。源实现只识别 docHeading，未扩展为导航所支持的全部样式继承标题。
- 外部草稿刷新：完整安装、根属性播种与 doc.eq 核验成功后清空旧 Undo/Redo，新编辑仍可撤销；锁定、非法回放与安装失败保留原 EditorState/选区/历史。失败回滚不承诺撤销调用方预先写入的 NativeDraft.operations。history plugin 重配会重建 plugin views，不承诺原 view 实例不变。
- 只读可使用导航和视图；纯视图不保存、不导出、不修改正文或草稿。

## 定向回归

- 导航 7 项真实 Editor 测试；大纲 3 项真实 editorExtensions 测试；历史 helper 与既有历史 10 项测试均已有 RED/GREEN 证据。
- view 路由 5 项；Ribbon 新增 readonly/按下状态用例 1 项。
- 主视图本轮最终定向恢复 9 项通过（53 项跳过），覆盖四类 external refresh 场景及 notes、comments、reply、odd/even 与 HF link 代表场景。
- 交叉复核发现 updateState 回滚不会发 transaction；新增安装后失败用例先复现导航未刷新（RED），在 finally 显式同步 navigation/outline 后通过。
- 证据目录：/tmp/sr-word-navigation-20261111；未重复完整测试。

## 最终构建与浏览器

最终冻结目录：/tmp/sr-word-navigation-20261111/final3-static；Vite exit 0。本轮8个生产文件在构建开始/结束指纹一致。

- Manifest：6133a8fcdea51af52e3ae39ae5079dae5875acb4b161fda884e05e793cb86cc8。
- 冻结 engine bridge：ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6。
- 导航：navigation-final3/evidence.json。可编辑/只读、真实点击与键盘、重复/空/继承/列表标题、动态更新、关闭；文档 DOM 和 localStorage 不变，导航不追加既有草稿。panelRight=editorLeft=240，画布不超屏。
- 大纲：outline-final3/result.json。均匀双栏、只读、两节混排三场景全部通过；真实折叠/展开点击不用 force，退出后正文/表格/页面 style/分栏/草稿/保存状态精确恢复。普通叶标题真实输入生成草稿，Ctrl+z 恢复。
- 历史：history-final3/evidence.json。四项全部通过：同一 Editor 成功刷新清旧 undo/native layout、刷新后新编辑正常 UndoRedo、redo-only 旧分支清除、非法回放失败保留旧正文和布局历史。
- 三项各125个实际加载 JS（含 worker）逐个对照冻结磁盘 SHA；manifest 前后不变，errors=[]，保存/导出请求均为零。root另行逐文件核验汇总于 integration-verification.json，并目视导航、历史与混排大纲成功截图。
- 导航/大纲使用真实 Python 创建并 inspect 的 DOCX 和冻结引擎，HTTP路由为 fixture；历史 API/AI 为 fixture，不调用真实模型或 engine bridge。没有验收生产鉴权、下载、保存或桌面 Office 整链；本轮为视图和内存历史能力。

## 实测发现与修复

- updateState 回滚不会发 transaction：主视图 finally 显式同步 navigation/outline，新增安装后失败用例 RED→GREEN。
- 混排大纲首次真实浏览器暴露标题坐标重叠、点击被其它句柄遮挡；新增几何断言在旧构建 RED。仅大纲模式清除 .doc-col-block transform/width，隐藏分栏 float；保留原 inline 坐标，退出页面恢复。最终混排展开四标题 top=400.34/439.83/496.16/554.34，无重叠，三场景 GREEN。旧失败截图与几何保存在 outline-browser/。
- 导航首轮 window.getSelection 探针不能代表编辑器状态，按钮保留焦点时可为空；改读真实 Editor selection。历史首轮逐字输入跨 PM 500ms 分组，改为单次真实 insertText 事件表达一次编辑。仅修正 smoke，保留失败说明；没有据此修改生产代码。

## 全局检查限制

- 完整 tsc exit 2：最终日志仅 Slides/XLSX 错误。本轮 Word 根节点 type 遗漏已修正并复查消失；最后 CSS 修复未修改 TS，未重复完整测试。
- 最终 Word 入口255049 bytes（普通250KiB阈值内），engine423900 bytes；共享 native-docx-render783110 bytes（710KiB阈值外），workbook-engine443.3KiB、workbook-main266.1KiB也超预算。保留 budget-final3.json，没有放宽阈值，不宣称全局门槛通过。
- 冻结验收后共享 main/ribbon 又被并行任务修改，最终源码复核检测到两文件指纹变化；本轮导航/大纲/刷新/销毁接线仍在，其余六文件指纹未变。浏览器结论严格对应上述 final3 资产，不冒充后续并行源码的完整验收。
- 不涉及发布签发链路、提交、推送或部署。完整 Word 对齐尚未完成。

专项脚本与记录：frontend/smoke/docx-navigation-smoke.mjs/.md、docx-outline-view-smoke.mjs/.md、docx-refresh-history-smoke.mjs/.md。
