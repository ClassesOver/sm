# 固定源确定性自动字段检测（2026-11-13）

状态：固定源确定性检测最小能力已完成，统一冻结后唯一完整 HTTP 保存验收一次通过。保存回执仍为业务事实与完整版式待复核（validation.ok=false），不标记业务验收通过。

固定源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。算法 `apps/pdf/src/renderer/form-detect.ts` 原字节移植，SHA256 `79ea4b270abe27051af123c8cede8700e6961ad1e4957c021d622dbe8e015805`。保留 Apache-2.0 LICENSE/NOTICE；浏览器 vendor ipc 仅补同源类型，无桌面 runtime 导入。

## 范围与复用

- 将 `pdf-main.ts` 中原 disabled 自动检测入口接到首次点击动态加载的 `pdf-form-detect.ts`。继续保留源设计预览的禁用入口；不动静态填值、签名、既有 AI/provider。
- 复用源 `collectDetectInput()` 与 `detectFormFields()` 的 PDF.js 文字、下划线、线框和复选符号算法，以及 occupied 排除与全局唯一字段名。不是新识别算法，没有 OCR。
- 复用现有 `showPdfObjectDialog()`、焦点回收、取消行为及提取窗口布局；仅添加检测窗口内的 radio 排版规则。显示名称、类型、原始页序和 PDF 坐标。
- 一次扫描最多 300 个源候选；候选无默认选中。用户明确选择并确认一个候选，才调用已有 `stagePdfFormCreation()`。保留单设计操作单保存契约，未实现或宣传 300 字段原子批量保存。
- 文本、复选与日期映射现有字段类型，签名和不符合既有字段验证的候选明确跳过。日期继续使用已有受限内建 AFDate writer。
- 来源 SHA、当前可信 PDF.js 文档、页面顺序/页号/CropBox/单位/旋转、活动页、草稿和权限均有检查。变化会使已显示候选及异步结果失效，撤销不能复活已失效候选。取消、关闭和未确认不改变草稿。
- 确认后复用现有预览/保存链；刷新失败保留已确认草稿并明确展示原因。没有新增发布步骤或门禁，不改变非阻断产物下载语义。

## 定向验证

证据根 `/dev/shm/office-next-pdf-auto-detect-20261113`。

- 初始 RED：缺少检测模块；`red.log`。
- 实际功能 RED：公开来源命令不存在，4 项断言失败；`red-entry.log`。刷新失败提示缺失的真实断言见 `red-wiring-refresh.log`（另保留该轮 fixture path 配置不足的前置失败，未混为功能 RED）。
- GREEN：`src/pdf-form-detect.test.ts` 11 项、`src/pdf-form-detect-host.test.ts` 4 项、`smoke/pdf-form-detect-real.test.ts` 1 项，合计 16 项；`green.log`。动态 import 调整后仅重跑受影响 host 4 项通过，`green-lazy-host.log`。
- 真实两页 ReportLab fixture SHA256 `8ce43851c3c378ef70d56a2a7a27f5eff571017a9f8339c51d81900098880384`。检测候选：`name` 文本 `[100,439,260,457]`、`date` 日期 `[100,379,260,397]`、`agree` 复选 `[100,320,114,334]`、第二页 `name_1` 文本 `[101,401,239,421]`；签名明确跳过，既有复选占位可排除。
- 四候选分别沿现有 `createDesignField` 实际写入，回执 applied `[0]`、skipped `[]`。输出 PDF、`real-fixture.json` 和独立 `pypdf` 回读在证据根；页数 2、单字段、实际矩形与所在页、原有 Name/Date/Agree/Signature 文字均核对通过。HTTP 保存次数 0。
- 全局 `tsc --noEmit` 明确 exit 2：本 PDF 新代码无剩余诊断；并发新增 XLSX FormatCellsDialog 路径、重复 JSX 属性与导出问题 13 条，见 `tsc-final.log`，已向 root 报告。不声称全局类型检查通过。

## 统一冻结后唯一完整 HTTP 验收（已完成）

本轮冻结 `B=/dev/shm/office-next-page-borders-ribbon-master-fill-detect-20261113`；前端 manifest `5ede4bf0e2689e7427f0e90ea296a912ae56aa4ef124be01a1916d8af55c3c90`，PDF bridge `366cac3cf522c9c58037abe5a5b38a2d9c17dff5681ccd36e386d5028d246af3`。root 的统一构建保留初始失败记录，PPTX 仅类型声明修正经 esbuild 运行时代码字节等价核验，最终 `typecheck-type-narrowing.exit=0`；原预算、预算契约、四桥构建及七桥语法检查通过。PDF 专项没有更改阈值或构建 shared static。

- 一次执行 `browser-frozen-01`，exit 0。首次点击才请求实际 `lazy-pdf-form-detect-DzUGJKeM.js`；扫描、取消、选中未确认均为 0 草稿/0 HTTP 保存。通过实际缩略图监听器合成换页、再强制分发旧确认回调，仍为 0 草稿/0 保存；这项属于换页守卫故障注入，未伪称可在原生模态窗口中手动点到背景。
- 明确确认一个 `name` 文本候选，形成既有单一 `createFormField` 草稿。实际 PDF 预览 applied `[0]`、skipped `[]`；未勾选预览确认时仍 0 保存。
- 唯一 POST `/reports/v1/native/parent-document/4/api/save` 返回 200，修订 4→5。实际浏览器下载 `downloaded.pdf`，3371 bytes，SHA256 `0d8ea293d140442b8fb286905d07b36ecc3dc15073159ac35ac7bbf0f690ff1d`。没有重跑完整保存。
- 独立 pypdf 核对：2 页、仅 `name` 字段、第一页矩形 `[100,439,260,457]`、控件 appearance 存在、原正文及 MediaBox/CropBox/旋转一致；新修订重开后实际字段属性显示 name、X=100/Y=439/W=160/H=18，来源摘要等于下载产物。
- validation.ok 仍为 false，原因 `native_source_review_pending`：原生编辑内容尚未重新核验业务事实与完整版式。下载链接照常签发，不标记验收通过。
- 五张截图均实际目视。桌面候选与字段清晰；390×700 下窗口宽/scrollWidth 均 356，高/scrollHeight 均 527，无横向溢出，首尾无需滚动。
- 浏览器资源 128 条记录、64 unique；server 64 条 200、64 unique。每条实际 JS/CSS 的 SHA 与本轮 manifest 和冻结磁盘匹配，HTML 同样匹配。九个命名 PDF 关键 Python 文件运行前后与物理冻结/登记一致；不扩大为全部后端稳定或 Python 隔离声明。执行 runner/server/继承脚本与 bridge 均有前后身份复核。pageerror/console error/HTTP error 全空。

证据：`browser-frozen-01/evidence.json`（SHA256 `fb00ff99721fc37343938170bbec5b6c1907752d2377af0a04633370d335bf39`）、`independent-verification.json`、`visual-review.json`、`network-counts.json`、`handoff-summary.json`、实际下载 PDF 与五张截图，均在专项 `/dev/shm` 证据根。

没有构建 shared static/dist，没有修改已完成冻结 B，没有提交或推送，也没有重跑旧 merge 保存验收。


验收后只读核对发现其它会话在 live `pdf-main.ts` 新增静态填值接线，冻结该文件仍为 `2a99fbac6605f7861c1474ba641fa9a3b3b644e789adb9492cbbbeeb2785a65e`，live 为 `95a7ead887a9871c532847fc7fe14bcc060553d36740a163d6dd1f7c5b85c8e4`。本验收执行冻结前端；该并发静态填值不属于本次实现或验收，未回滚或覆盖，差异已保存在 `concurrent-live-static-fill-drift.diff`。不能把本轮结果泛化为当前 live 全部 PDF 新逻辑通过。
