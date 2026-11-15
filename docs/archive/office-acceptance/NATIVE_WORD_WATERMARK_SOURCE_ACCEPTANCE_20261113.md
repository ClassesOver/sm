# Word完整水印组件族冻结验收（2026-11-13）

结论：固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的完整 `WatermarkDialog` none/picture/text 组件族已接入并完成本轮冻结验收。保留现有文字预设与删除入口，图片选取通过浏览器授权文件输入；图片自动/指定缩放、冲蚀、同源预览和原生保存均复用引擎，未另写XML writer。

## 实现范围

- `frontend/src/docx-watermark-dialog-source.tsx`：完整源三模式、文字全部控件、图片选取/缩放/冲蚀、WatermarkPagePreview，宿主生命周期、焦点与IME、异步选图取消和失败apply留窗。
- `docx-watermark.ts`、`docx-ribbon.ts`、`docx-main.tsx`：图片union草稿、来源回读种子与同来源撤回、正文/草稿/节快照、画布与分页预览、原生单操作undo/redo和草稿恢复。
- `reporting/doc_engine/bridge/docx-watermark.ts`、`edit-docx.ts`：来源页眉摘要；真实图片bytes/MIME/尺寸/scale/washout校验；来源内部关系读取；auto恢复；复用原生 `saveDocx watermark` 后独立回读实际header关系、媒体字节、显示尺寸与冲蚀。

## 定向验证

- 新原生测试8项通过，另字段顺序回读回归1项通过；没有重复全套测试。记录 `word/watermark/native-v2.log`、`native-v3-key-order.log`。
- 新UI测试5项通过：三模式完整控件、图片草稿种子、异步迟到结果/模式切换/卸载、IME、失败apply留窗；记录 `dialog-v3.log`。最终类型检查 `tsc-final-watermark.log` exit0。
- 唯一正式冻结浏览器 `browser-final.log` exit0，13检查/0错误/161实际HTTP资产/1次保存。覆盖完整三模式、取消/Escape、焦点/IME、授权选图、150%/不冲蚀、1440×900/390×640/640×320页脚命中、单原生操作、undo/redo、草稿重载、真实下载和明确revision2图片种子重开、只读禁用。窄屏与矮屏截图已人工核看。
- Python独立ZIP回读：正文XML原字节、正文粗体/表格/原页眉及其他原部件保持；图片135×90pt且无冲蚀；header→rels→media实际字节与选择文件一致。
- 保存fixture明确返回 `validation.ok=false` / `fixture_validation_warning`，仍签发下载，HTTP200，未标记验收通过。

## 冻结身份

证据根：`/home/junge/codex-evidence/smart_reporting/office-component-inventory-20261113/word/watermark`。

| 身份 | SHA-256 / 数量 |
|---|---|
| final-source-v2清单 | `6d89e82804f0535f999491b487ab192608a6fe1b5cb75674bf71c299c8eb438e` |
| 最终static manifest | `c2d8c235b8ac55347f2cad2d0af09d65a167776c3659f7c98bbb2da48076e203` |
| 本轮新建DOCX bridge | `86c3c7feb20bea55f09609abcb8f7d3234eafde57991bb4dc56119360fafdb24`，2,899,532 bytes |
| 原生构建输入 | 257项全部独立核验；126冻结源逐项匹配清单，131第三方依赖逐SHA |
| browser runner | `fa78706676279d6cb2cf72229826d3dd3dc30b8d4d337964e29eae8931d650b9`，与v2物理源相同 |
| frozen-browser/result.json | `88e352aa55550074d6322b5747f5c8c5678f86568322d7c0b3daecfab9a83b1a` |
| 实际下载revision2.docx | `d0d4619d036d283545d6ca4bfb98584961a084f73d5770a6d235748b3cf0848e`，39,191 bytes |

正式闭环记录：`frozen-browser/closure.json`；原生输入独立核验：`docx-runtime-final-v2/independent-input-verification.json`。

## 历史失败保留

`browser-v1.log` 为runner标签少冒号失败；`browser-v2.log` 业务链12项通过后，source-map守卫捕获运行期间注释变化，未冒充正式PASS。两者保留，正式结论只来自上述最终v2冻结验收。此记录不宣称全量63组件盘点均完成运行时验收。
