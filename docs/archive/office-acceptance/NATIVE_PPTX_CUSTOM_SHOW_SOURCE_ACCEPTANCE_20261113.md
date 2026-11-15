# PPTX 完整自定义放映族源码与原生持久化验收（2026-11-13）

## 范围与固定源

固定源位于 /home/junge/pros/genoffice-source-full，HEAD 为 f8c17004fb730df11f0f743164ffd8b4281bb38c。源组件 apps/slides/src/renderer/components/CustomShowDialog.tsx 的 SHA256 为 6be205018d29915264b549abce674de60bdf276cc8cf5424563c9fe320edcddd，中文文案参照 renderer/i18n/panes/zh.ts。本轮迁移完整左右栏操作族：已有放映列表、新建、删除、名称、页面复选框、播放顺序上下移动、播放、关闭，保留源组件的重复页面显示与排序行为。

源 show-actions.ts 的 updateCustomShows 仅维护状态及 localStorage，App.tsx 从 localStorage 恢复。固定源未提供真实 p:custShowLst reader/writer；源码负面搜索、组件清单和实施设计分别保存在证据根 custom-show-negative-searches.json、pptx-component-inventory.json、implementation-design.md。源 UI 迁移与本地原生持久化扩展必须分别记账，不能将源 localStorage 行为当作 PPTX 文件持久化。此前背景族文档中“自定义放映未迁移”是此前阶段事实，本次新增验收在此记录，不改写历史结论。

本地 slides-custom-show-dialog.tsx 保留完整源操作结构，宿主补原生 dialog、焦点圈定与恢复、低高度滚动、输入法组合按键隔离和提交错误回显。slides-main.ts 通过既有 NativeDraft 提交完整列表快照，进入撤销/重做、刷新恢复、预览、修订保存及下载链路；对话框打开后草稿发生变化时拒绝过期提交，历史操作关闭旧对话框。播放读取同一草稿的 render-tree/preview 快照，将 customOrder 交给固定源 SlideShowView；播放不生成编辑操作，退出返回最后来源页。

## 本地 OOXML 扩展与边界

packages/pptx-engine/src/custom-shows.ts 读取及写入实际 ppt/presentation.xml 的 p:custShowLst；bridge/pptx-custom-shows.ts 复用既有 runTxn 原子事务，edit-pptx.ts 在结构操作前把来源页索引绑定到实际 slide 部件，结构操作后解析当前 presentation r:id 写回。客户端不能指定部件路径或外部关系。已有数字 show ID 保留，新建临时 cs-ID 由服务端分配 uint ID；不会为自定义放映额外创建关系。重复来源页引用保留，重排按实际部件身份保持引用，删除页面时过滤对应引用。显式 customShows=[] 经 Python 包装层和实际引擎确实清空文件列表，不能因空数组丢失而恢复旧配置。

未修改的 show 原始 XML 和未知 p:extLst 扩展保留；修改名称使用回调替换，避免 $&、$1 被 String.replace 解释为替换表达式。读取拒绝损坏 XML、DTD/实体、错误或被局部重绑的 p/r 命名空间、重复 presentation 关系 ID、未知/外部/缺失的 slide 关系，不把损坏源报告为可编辑。不能删除被实际 ppaction://customshow 或 presProps.xml 默认 showPr/custShow 引用的配置。该拒绝针对编辑操作，不改变既有非阻断发布规则。

源 UI 本身没有“添加重复页”按钮：可以显示、调整并播放文件中已有的重复序列，勾选页面仍按源语义追加或移除该页。本轮没有扩展重复页创建功能。尚未保存的页面增删需要先保存，再管理自定义列表；源标签按来源页编号呈现，播放依据当前草稿页序映射。

## 定向验证与失败证据

本轮新增/受影响测试按定向范围执行，未重复完整测试：bridge 5/5、Python 4/4、UI 三文件 14/14；最后母版 union 类型保护调整后主入口定向 1/1。覆盖完整增删改名/选页/排序、既有重复页、输入法组合方向键、错误回显、历史关闭旧对话框、播放参数及无草稿变更；真实源播放器另覆盖 [2,0,2] 导航和退出来源页。

实际 Python -> edit-pptx 管道的结构操作另有 structural-real-engine.json：重排保持实际部件引用、删除页清理引用、显式空数组持久化。bridge 还覆盖未知扩展保留、美元名称、空列表/空放映、命名空间伪装、重复关系 ID、未知数字身份与客户端路径拒绝、活动 show 引用删除保护。

源码 browser/source-v1 保留失败证据：测试错误地在 Canvas 页内查找 DOM 文字；改为实际 Canvas 截图像素比较、序号和退出来源页检查后 source-v2 通过。该修正属于验收断言，不将失败轮冒充通过。源码证据不代替最终冻结静态验收。

## 最终源码、运行时与静态身份

证据根为 /home/junge/codex-evidence/smart_reporting/office-component-inventory-20261113，PPTX 专项目录为其 pptx 子目录。

最终物理源码快照 final-source-v2 共 4439 个文件，SOURCE-SNAPSHOT-SHA256.json 的 SHA256 为 6d89e82804f0535f999491b487ab192608a6fe1b5cb75674bf71c299c8eb438e。验收前后逐项实读源文件身份均一致。初版 final-source 和相应证据保留；v2 仅纳入 root 登记的两个 XLSX 类型修复文件，不覆盖初版。

隔离 pptx-runtime-final 的 131 个产品输入逐项匹配 v2 源码清单及实际文件 SHA，150 个外部输入全部是 node_modules 依赖，并逐项实读登记。v1/v2 的全部 PPTX 产品输入相同，因此复用同一实际 bundle；归属证明为 pptx-runtime-final/final-input-verification-v2.json，不用目录名推断来源。bundle-identities.json SHA256 为 90401995beb10056967f21bf393a8ca963b9c20006f6ce98fddf4eaea7c627a7；edit-pptx.mjs SHA256 为 b83a939cdc1f6dcee3e10a58c0897511f976f0cac0851c2053bd968e745e5019，render-pptx.mjs 为 9fdffe53f7f1bcb29f2aef70ee6a5b6c6336916d1a9332d656e9043fc45c43ed。

最终静态目录是 final-source-v2/smart_reporting/report_editor/static，.vite/manifest.json SHA256 为 c2d8c235b8ac55347f2cad2d0af09d65a167776c3659f7c98bbb2da48076e203。root 完成 tsc、Vite 与原预算检查均 exit 0，未放宽预算。正式浏览器实际请求的 158 个 JS/CSS 资源逐一与该冻结静态文件 SHA 匹配，errors=[]；root 另行独立核对同一 158 个资源与下载文件。

final-source-v2 不含完整 Python 包初始化文件及虚拟环境，显式夹具复用现有 .venv，并实读核对快照中的 300 个 Python 文件与活跃冻结文件字节一致；实际引擎显式绑定 pptx-runtime-final。该适配仅位于证据 final-harness-v2，未改产品或静态文件，python-snapshot-match.json 记录核对身份。

## 冻结浏览器保存、下载与独立重开

正式证据 pptx/browser/frozen-v2/evidence.json 的 SHA256 为 500216417ea2d4f8dc60850660a9c5c3f35a266ac9d10caef212468c8ff20704；汇总为 pptx/final-formal-summary.json。

- 完整新建/删除/改名/选页/顺序、保留其他 show、撤销/重做、刷新恢复通过；640×360 下列表方向键、滚动、Escape 关闭通过。
- 真实 Canvas 按 [1,3,3] 播放：前后不同页像素不同，重复页像素一致；退出返回来源第 3 页，播放前后 NativeDraft 相同。
- 显式原生修订夹具恰好 1 次 save、1 次 download，158 个实际 HTTP 资源身份一致，0 浏览器/API 错误。
- 实际下载 downloaded.pptx 为 49,857 bytes，SHA256 为 2f476b0ac86bfae59d8a996009cf969cdab9a2d33b6cd5fbdf04af5bc938578b。
- ZIP/lxml、python-pptx 独立回读通过：真实列表为 ID 0“重点改名”=[0,2,2]，ID 1“保留”=[1]。仅 ppt/presentation.xml 改变；其他所有部件、正文及讲稿保持原样，ZIP 完整性检查通过。
- 全新浏览器 context 以同一下载 bytes 作为来源重开，来源 SHA 等于下载 SHA，真实列表与 render-tree 一致，再按 [1,3,3] 播放并退出来源页通过；重开无额外保存、无额外下载。

## 验收限制

本轮结论限于完整 CustomShowDialog 族、本地真实 OOXML 读写及上述最终冻结浏览器链路；不据此宣称其他尚未迁移组件全部完成。授权、组织/用户/任务作用域与修订注册采用显式 native 夹具，writer/reader/render-tree/下载实际执行；没有验证生产权限系统或真实生产修订登记。独立重开夹具 UI 修订号为 1，验证的是实际 revision-2 下载 bytes，不能据 UI 数字宣称生产修订注册。

未验收 Microsoft PowerPoint/LibreOffice GUI 实际打开、桌面 custom-show 超链接执行、录屏/演讲者视图、自动换页或跨文档复制放映配置。默认 showPr 和超链接引用删除保护通过定向测试，正式浏览器没有覆盖桌面应用的活动 show 设置。本轮不新增发布/工作区体系，不修改静态产物或放宽安全边界；无 commit、push、部署操作。
