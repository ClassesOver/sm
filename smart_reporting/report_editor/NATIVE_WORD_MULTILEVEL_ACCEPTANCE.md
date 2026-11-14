# Word 多级列表源增量（2026-11-13）

固定参照 `genspark-ai/genoffice@f8c17004fb730df11f0f743164ffd8b4281bb38c`。本专项只关闭多级列表入口族；不代表 Word 或四格式整体对齐完成。

| 固定源 | 本地实现 | 边界 |
| --- | --- | --- |
| `apps/docs/src/renderer/list-presets.ts` 八套九级定义 | 原样迁移 + `docx-list-gallery` | 预设按来源九级保留，不伪造编号 XML |
| `Ribbon.tsx:4210–4265` 最近/库/文档/级别/定义 | 原生中文图标入口、最近六项、文档定义区、九级入口、完整定义对话框 | 普通项目符号库、普通编号库、设置编号值仍另列缺口 |
| `components/ListDialogs.tsx:601–798` | 原样源 DefineMultilevelDialog | 编号格式/文字、起始、缩进、后缀、对齐、样式关联、级间重启、字体/大小/颜色/粗斜体、法律编号；未接源 DefineBullet 的图片上传 |
| `numbering-actions.ts` create/overlay/style link | `docx-custom-list` PM 原生属性及高优先级编号覆盖层 | 原有可信顶层段落可多段同事务；只读、保护、嵌套或来源缺失拒绝，不扩宽其它对象能力 |
| `docx-engine` CustomNumberingLevel/saveDocx | 新 `setParagraphCustomList` + 既有 append-only numbering writer/styleUpserts | 客户端只传结构化定义和临时 token，桥分配真实 numId；禁止 XML、任意资源路径或伪造图片身份 |

草稿、Undo/Redo、刷新恢复与来源锁均沿用现有 NativeDraft/ProseMirror/保存链。相同 token 的多段共享同一个实际编号，定义冲突整批拒绝；九级重启严格为 `0..ilvl`。标题转换保留样式与原始段落属性，撤销/清除未保存的标题列表可恢复原标题。已保存混合编号/符号定义可再次切换级别，桥独立核对目标级别类型。

新源文件及共享 Dropdown 共七项原样复制，独立身份在 `/tmp/docx-list-gallery-source-20261113/source-copy-identities.json`；原始身份追加到 vendor `SOURCE-SHA256.json`，本地适配另记 LOCAL。宿主只加窄屏滚动/单列布局与 IME Escape 保护，不改源表单文件。固定源完整性与产品宿主适配分别核对。

## 定向验证

- `/tmp/office-word-multilevel-20261113/operations-red.log`：既有 collector 明确拒绝多级定义；后续七项 collector/replay 验证通过。
- `controller-red.log`：原生 controller 尚不存在的 RED；后续真实 Tiptap 多段绑定、同段文字、Undo/Redo、覆盖层恢复、只读/来源拒绝、标题应用与清除四项通过。jsdom 无 canvas 的已知日志保留，不充当真实画布证据。
- `gallery-source-sections-red.log`：最近/文档/级别区缺失的独立 RED；完整图库九项 DOM 验证通过，见 `gallery-source-sections-green.log`。
- `integration.log` 保留旧禁用契约与小型 fixture 的失败；更新为实际源行为后，`integration-green.log` 的 controller/Ribbon 定向 25 项通过。
- 真实 CLI `bridge-linked-green.log` 两项通过：同一编号分配、九级/重启、正文加粗居中、旧编号子元素和非目标 ZIP entry 保留、既有/缺失标题样式关联、重开后混合级别、非法定义不创建输出。测试夹具误读不存在的 Block.text 字段、误要求 append 后旧编号连续相邻的失败均保留；修正为 runs 和逐旧子元素核对。

## 冻结与浏览器证据

工作目录 `/tmp/office-four-format-source-entry-20261113`。前两次构建与失败证据保留：首轮两个 Word chunk 超原预算；第二轮已通过原预算，但 390px 字体行仍裁切。原预算未提高，控件拆为独立 chunk，窄屏修复仅限新对话框。

`frontend/smoke/docx-multilevel-{server.py,smoke.mjs,verify.py}` 使用真实授权/CSRF/文件桥/修订/下载路由，只有仓储复用既有内存宿主。独立回读使用 lxml/python-docx，不使用产品解析器。最终冻结结果与真实保存下载重开证据在完成后追加；在此之前不把专项标记为已验收。

首次真实浏览器已验证两段预设、Undo/Redo、自定义修改，随后 reload 被 Chromium `ERR_INSUFFICIENT_RESOURCES` 中止；当时磁盘只余约 272 MB。后续使用独立内存临时目录与 CDP 禁用缓存，保留原失败日志和截图。该失败没有 HTTP save，不计作成功保存证据。


## 最终冻结与保存续验（2026-11-13）

最终 manifest 为 `68ce99975149470621d980fcf040694372b986a4c037e5463f07d85a8edf67e2`；完整前端类型检查和 Vite 构建退出0，397 JS 原预算无失败，未提高预算。首轮超预算、第二轮390px字体行裁切以及浏览器资源不足的记录均保留。第三次UI探针误用不存在的Word preview按钮，修正烟测等待后才继续，未把该超时归为产品预览缺陷。

真实UI已覆盖八预设、多段应用、UndoRedo、完整字段对话框、最近/文档/级别区、390px无横向裁切、自定义“第%1章”起始4和草稿刷新。随后 `browser-built-saved` 的真实保存返回422，暴露 Python `docx_native._OPERATION_KINDS` 漏登记。新增 `test_docx_custom_list_native.py` 经真实 `patch_docx` RED（docx_operation_unsupported）→GREEN（1 passed），仅给该白名单追加 `setParagraphCustomList`，未扩展AI工具权限。日志为 `/tmp/office-word-multilevel-20261113/python-native-{red,green}.log`。

保存续验 `/tmp/office-word-multilevel-20261113/browser-save-resumed2/evidence.json` 复用失败轮的确切源文件和实际staged operations，按 NativeDraft 原生版本、身份和作用域恢复，再刷新、保存、授权下载、修订重开；没有重复完整UI。150项HTTP资产SHA与最终冻结磁盘一致，页面/控制台/HTTP/资产错误均空。修订4→5，registered=true，下载与重开api/file同SHA。首个resume探针只因误假定桥名cli.mjs在启动前失败，改为实际edit-docx.mjs；原记录保留。

- 来源SHA：`1541ffb654781e0aab0fefde662a85ac4997a50fafec46ed875188ff2e0e3a91`。
- 冻结doc bridge：`0128a24e7cb2789b793d742895b9a1c6e27da295171790533bf279dee4b8c4c2`。
- 修复后Python边界：`aa0ca995059df2c63160cb82a49133c772cfd7c7a10f099c0c440dd14bae1b18`，是前端构建后单独验证的源增量。
- 下载：`f1c39dc2df86d48a91345e484c83c3d5fa445b6d295abf3ab7e7f95d5c36de71`，38161字节。

独立lxml/python-docx回读确认两段共享numId、九级、首级第%1章/start4、原居中/加粗、其余段落、旧编号子元素及其他ZIP内容保留。root另行逐SHA复核150资源、重新独立回读下载并目视重开截图：第4章/第5章、原标题与既有编号显示正常。业务验收依旧 `ok:false/native_source_review_pending`，照常签发已核验身份的文件，未冒称业务事实或完整版式已验收。

该结论只关闭上述多级列表源入口与保存能力，不覆盖普通符号/编号库、设置编号值、图片符号、复杂嵌套对象、桌面Word或整个并发工作区。未重复完整套件，未提交、推送或部署。
