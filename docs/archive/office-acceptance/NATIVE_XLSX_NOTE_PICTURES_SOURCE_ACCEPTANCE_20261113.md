# XLSX 图片批注源族映射与设计（2026-11-13）

固定上游：GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c。范围仅图片批注，不以文本 notes、浮动图片或页眉图片替代。

| 固定源组件/入口 | 真实行为与关联字段 | 本地实施及验收 |
| --- | --- | --- |
| NotePicturesPane.tsx FilePicture | readWorkbookMedia(sessionId,imageId)，加载中与图片不可用提示 | 从当前已授权 XLSX 的规范 VML own image relationship 读取媒体；SHA/尺寸/MIME/bytes身份，失败保留作者与文本，不探测URL |
| Picture | 当前会话 pending dataUrl 优先于已保存 imageId | 统一 NativeDraft 的 setNotePicture bytes操作重放形成当前包；面板/hover使用当前快照，不另建持久化机制 |
| Card | sheet!cell 点击跨表激活并冻结区下方定位，author、image、text，仅移除图 | 沿现有导航API；remove只清图片fill与独占关系，comments文本不改，Undo/Redo沿原链路 |
| Pane | toggle/close/empty，全工作簿按sheet/cell列出有图notes | 中文PC侧面板，read-only/busy/stale/late取消遵从现有编辑锁 |
| NotePictureHoverCard | SheetsNotePopupService.activePopup$，hover/pinned，移入保持、按popup定位与视口避让，移图 | 订阅同一官方service，tooltip图/author/text/移图；卸载取消订阅/释放object URL |
| ribbon insert-note-picture | PNG/JPEG/GIF file picker；thread拒绝；不存在则创建空note；记录mediaType/name/widthPx/heightPx/dataUrl | 显式本地文件选择，实际签名/MIME/尺寸匹配；规范VML picture fill与media；同一草稿保存、重载与撤重做 |

## 已核现状与短设计

现有 note-read 遇 VML own rels即拒绝，notes仅含row/column/author/text；文本writer不提供图片操作。沿现有OOXML引擎增加图片reader/writer，复用EntrySource、关系解析、组包及只改授权part校验。图片身份绑定worksheet/comment/VML shape/relationship/media，过期SHA、外部关系、异命名空间、重复所有权及受保护目标拒绝对应操作，不阻止无关保存。

读取支持Note shape的v:fill type=frame o:relid/r:id，以及源兼容v:imagedata r:id；识别PNG/JPEG/GIF真实bytes，显示失败明确原因。set精准替换目标shape图片元素，保留其余shape/comments；无note时沿既有notes writer创建空note。remove保留文本/作者/shape，仅移除图片元素；关系无其他VML引用才能移除，media全包存续关系证明无人引用才删除，保留共享图片与未知关系。无需新格式或来源sidecar。

## 验证顺序

1. 独立VML/comment/media夹具 → reader/set/remove/共享媒体/namespace/path/stale/protection 定向RED→GREEN。
2. 中文pane/pending/error/jump/hover与真实ribbon/native draft重放定向测试。
3. 真实Python native_office→delivery/xlsx→CLI四层专项，避免mock白名单漏接；独立ZIP/lxml/Pillow回读。
4. root统一冻结后真实浏览器：读取/hover/insert/remove/UndoRedo/save/download/new identity reopen；原输入/实际静态与Python/CLI身份及非阻断validation结果保留。

证据根：/home/junge/codex-evidence/smart_reporting/office-table-ink-notepicture-link-20261113/xlsx。当前阶段仅mapping完成，未标实现或浏览器通过。禁止共享build/static/vite、全仓快照及重复完整测试。
