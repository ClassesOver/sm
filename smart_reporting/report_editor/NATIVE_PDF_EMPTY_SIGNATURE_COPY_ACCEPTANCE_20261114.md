# 空签名字段复制验收（2026-11-14）

本批支持已有安全空签名占位的复制、重复及同文档跨页粘贴。副本保留必填、边框字典与原尺寸，使用一个新引用同时作为 AcroForm 根字段和页面 Widget，不生成签名值或签名数据，不等同证书签署。

## 实现与范围

- census 仅把既有 safeEmptySignature 完整结构/引用检查通过的签名字段授予 copyEditable：根级合并字段-Widget、未保护未签名、无 V/DV/AP、无 Lock/SV/动作、原字段引用恰为 Fields 与 Annots 两处。
- 复制前从临时字典移除 P，避免把原页面图复制；私有复制 MK/BC 等限定辅助内容，再绑定新 T/P/Rect。新引用只登记一次 Fields、一次目标页 Annots，不生成 Kids/Parent。
- 保留原尺寸与属性，未保存副本仅移动/删除/再复制。中文卡片明确“空签名字段，未包含签名数据”，不宣称复制字体、AP 外观流或原签名。空占位原本没有 AP，实际 PDF 预览不新增烘焙签名图像。
- 已有签名值、默认签名值、外观流、锁/种子规则、动作、异常共享引用或其他扩展结构仍拒绝复制；不开放任意来源签名字段、系统/跨文档剪贴板或证书签署。普通文字/日期/单选组复制分支保留。
- 复核失败保留实际 PDF 字节和诚实跳过回执；复用现有预览确认、修订发布及下载，无新签发步骤或发布门禁。

## 定向验证

| 验证 | 结果 |
| --- | --- |
| 引擎 RED | `/tmp/pdf-empty-signature-engine-red.log`：复制能力与批次协议两项失败，拒绝类两项当时通过。 |
| 引擎 GREEN | `/tmp/pdf-empty-signature-engine-final.log`：22 项通过，含空签名复制4、原空签名设计4及单控件/日期/单选组复制受影响专项。验证合并引用、跨页90°/CropBox、必填/私有边框、批次原索引、扩展签名拒绝及复核故障保留实际占位。 |
| 前端 RED | `/tmp/pdf-empty-signature-front-red.log`：剪贴板和真实画布入口两项失败。 |
| 前端 GREEN | `/tmp/pdf-empty-signature-front-final.log`：118 项通过（clipboard12、画布36、创建7、批创建2、公共宿主61），保留原 React act 警告。 |
| 真实服务 | `/tmp/pdf-empty-signature-service.log`：仅新增 signature 参数1项通过，text/date两个旧参数未选。实际 preview/preview_file、确认前拒绝、确认保存、修订登记及授权下载流通过；pypdf 验证根字段/Annots引用相同、无签名值/AP/Kids/Parent，inspect digitalSignatures=[]，原来源不变，validation.ok=false 仍保留下载。保留 imghdr 弃用提示。 |
| 全局类型 | `/tmp/pdf-empty-signature-types.log` 与上一批逐字节相同，仍有既有632条诊断，不称全项目通过。 |
| 独立复核 | 同模型 reviewer 静态复核无 Important；未运行测试，不将其计作运行证据。 |

仅执行新增和受影响专项，没有重复完整套件。测试数与历史批次重叠，不累加为唯一总数。

## 中文真实浏览器及独立回读

`/tmp/pdf-empty-signature-browser/evidence.json` 为 ok:true。实际源码入口、固定 FormDesignLayer、PDF.js 与隔离 CLI；浏览器 API 适配不含生产授权/发布，该部分由上面的真实服务测试承担。

- HTML zh-CN，七个功能区标签均通过中文断言；空签名只读副本卡片无值输入或字体保真误导。
- 快捷键复制/重复、第二页菜单粘贴、删除字段及 Undo/Redo、刷新恢复后，两项实际复制操作保持；来源字段不变。
- 实际预览 applied `[0,1]`、零跳过；pypdf 回读原字段和两副本，页面占位数量 `[2,1]`，每个根字段引用与其页面 Widget 引用完全相同。
- 三字段 FT=/Sig，保留 Required；均无 V/DV/AP/Kids/Parent/ByteRange/Contents/Lock/SV。实际来源正文与原文件 SHA 不变，页面/HTTP错误为空。
- 窄屏与实际预览截图已目视；390px 卡片 left62/right382，clientWidth=scrollWidth318，无卡片横向溢出。正文沿用原宿主横向阅读，副本允许重叠；空占位未在实际预览中凭空显示成签名图像。

隔离 CLI `/tmp/pdf-empty-signature-runtime/dist/cli.mjs` SHA256 为 `77a083d9787f2cf32906701b599067ceb5373f00371f32a829f9e795e5f85063`，6,163,572 字节。Vite sibling 项目 fast-xml-parser/saxes/utif2 预扫描告警保留，实际 PDF 页面正常。未修改共享 static/dist、提交、推送或部署，整体 PDF 对齐仍未完成。
