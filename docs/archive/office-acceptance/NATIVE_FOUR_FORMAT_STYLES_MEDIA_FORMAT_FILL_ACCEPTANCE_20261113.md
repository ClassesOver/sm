# 样式、媒体、单元格格式与静态填写：本批验收

固定参照 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批按组件族并行推进，并补充键盘/混合状态、窄屏及低高度按钮可达、真实保存回读、撤销恢复和资源身份核验；不将截图接近桌面软件等同于文件功能完整。

| 格式 | 本批交付 | 专项与边界 |
| --- | --- | --- |
| Word | StylesPane/StyleDialog，搜索过滤、新建/修改、匹配选区更新、选择实例、段落及字符样式应用 | [样式窗格专项](NATIVE_WORD_STYLES_PANE_ACCEPTANCE_20261113.md)。v4完整21检查及实际保存下载；v5仅同一下载零保存重开。复杂嵌套目标及未保存相邻段落约束仍按专项保留。 |
| XLSX | 六页签设置单元格格式，混合值保留，组合格式历史及保存 | [单元格格式专项](NATIVE_XLSX_FORMAT_CELLS_ACCEPTANCE_20261113.md)。v4四视口及下载通过、末端资源加载失败保留；下载重导入通过；v5最小一次原请求保存/修订重开通过。未将失败原跑改称完整绿色。 |
| PDF | 静态文字/勾叉填写、管理位置与删除、保存后重编、页序映射、软必填提示 | [静态填写专项](NATIVE_PDF_STATIC_FILL_ACCEPTANCE_20261113.md)。v4两次保存下载独立回读；v5低高度滚动修复后零保存续验。不是新建交互表单字段或复杂PDF无损保证。 |
| PPTX | 音视频插入、编辑及放映实际播放，play/pause/stop，历史恢复与媒体字节保存 | [媒体专项](NATIVE_PPTX_MEDIA_ACCEPTANCE_20261113.md)。v4四视口完整链；v5已有下载零保存重开播放。不包含录屏、3D或不可解码格式的播放保证。 |

统一证据根：`/home/junge/codex-evidence/smart_reporting/office-styles-media-format-fill-20261113`。环境重启曾丢失旧内存盘材料，本恢复批仅依据当前持久证据，不沿用无法回读的历史成功结论。

最终物理副本 `source-v5`：4361份源码身份无漂移，manifest SHA `11c248ae3a4c6fa31fad99f04d2e72437abc4440569e1d846615616b7f442e17`。最终tsc exit0、Vite 46.32秒 exit0、原预算 exit0；预算合同此前通过且脚本未变。首次类型失败和两块超预算记录保留，仅按已有模块边界拆包，没有提高预算。

root独立回执 `root-independent-verification.json` 为 `ok=true`：最终Word160/XLSX283/PDF65/PPTX151个实际HTTP资产分别逐项匹配冻结文件；实际下载由python-docx/openpyxl/pypdf/python-pptx/ZIP独立回读，PPTX新增WAV/WebM逐字节匹配输入。XLSX额外修订5的实际文件也独立回读通过。矩阵与续验有意分层，未在v5重复四份完整保存。

实际Python宿主复用live现有链，各专项的起止身份覆盖范围不同；物理副本不代表整个后端隔离或生产数据库鉴权验收。业务 `validation.ok=false/native_source_review_pending` 保留并给出原因，已核验身份的实际文件照常签发下载。

GitHub直连超时后经代理fetch核对，当前 `code` 与新获取远端均为 `1138887df2541b748ebe5746871e4198bb48a712`，无需合并，本地改动保留。没有提交、推送或部署。完整四格式组件穷尽与桌面能力对齐仍未完成，不给推定完成率。
