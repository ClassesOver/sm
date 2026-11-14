# CustomShowDialog 来源与真实持久化

固定源 HEAD：f8c17004fb730df11f0f743164ffd8b4281bb38c。
完整源组件 apps/slides/src/renderer/components/CustomShowDialog.tsx，SHA256 6be205018d29915264b549abce674de60bdf276cc8cf5424563c9fe320edcddd。

本地 slides-custom-show-dialog.tsx 保留完整源左右栏：列表、新建、删除、名称、选页、顺序移动、播放。源本身没有新增重复页按钮；已有重复序列照常显示、排序并播放。中文键来自源 renderer/i18n/panes/zh.ts。浏览器宿主补原生 dialog、焦点圈定/恢复、IME 隔离及提交错误显示。

源 show-actions.ts updateCustomShows 仅写状态和 localStorage，App.tsx 仅从 localStorage 恢复；固定源不存在真实 OOXML writer。此限制已在 inventory / negative-searches 记录，不能将源 localStorage 冒称文件持久化。

本地受控扩展 packages/pptx-engine/src/custom-shows.ts 读取/写入真实 ppt/presentation.xml 的 p:custShowLst；bridge/pptx-custom-shows.ts 经既有 runTxn 原子事务执行。客户端只提交来源页索引，服务端绑定实际 slide 部件和 presentation r:id，重排保持引用，删除仅过滤已删页；重复引用保留。既有 show 数字 ID 不变，新建临时 cs-ID 由服务端分配数字 ID。未知 show 扩展与未修改 XML 保留，实际 hyperlink/default show 引用阻止删除相应配置。

全部管理变更走既有 NativeDraft 历史/恢复及授权 save/revision/download 路径。播放读取同一草稿 render-tree/preview 快照，传入固定源 SlideShowView customOrder，退出返回来源页，不制造编辑操作。对话框打开后草稿变化时拒绝过期提交；历史操作关闭对话框。

损坏源/未知命名空间/重复关系 ID 不宣称可编辑；不读取客户端部件路径、不创建任意外部关系。新增入口沿用现有来源文件身份、修订及下载链路，无新增发布系统。
