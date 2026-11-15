# PDF 绘图混合、表单裁切告警与来源 X 验收（2026-11-11）

固定 GenOffice 源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批按用户授权三域并行，不含 OCR，未提交、部署或启用生产开关。整体 PDF 对齐未完成。

## 冻结身份与实际交付

- Static：`/tmp/pdf-three-increment-static`，manifest SHA-256 `860a318130de056a8e41788f9408545987189bec228661a2820da154d872b9d9`。
- Runtime：`/tmp/pdf-three-increment-runtime`，CLI SHA-256 `865b3c80eeffb1e956015c4d2a5af5c09906a2d4f77e9ff5be9b10fc33e7109b`。
- 三条真实浏览器链路均确认 37 个实际 JS 响应 SHA 与该 static 一致，来源保持，page/console/HTTP/asset errors 均为空。fixture 仓储是内存实现，未冒称生产持久化、真实生产身份/网络或完整镜像验收。
- Vite、engine bundle、runtime package 成功，预算检查零超限；PDF main 245357 bytes、form controls 29185 bytes，未提高预算。源码冻结前后 SHA 一致。
- 总证据 `/tmp/pdf-three-increment-final-evidence-20261111.json`。LOCAL 163 项与 converter 48 项 local SHA 均匹配；converter 的 sourceSha256 逐项对固定上游 Git blob 核验，未覆盖上游身份。

文字：样式改字与新增矩形/椭圆、文字标注同批，保留原操作索引、来源坐标及 pending mapping；独立检查真实字体、正文、批注 AP/路径/页引用。实际 PDF `bf04af65f1ac169119fe35eb286a6ff288538ca2f2d8990a69e327b7f2799272`；证据 `/tmp/pdf-three-increment-drawing-browser-root02`。

表单：属性和后续填值增加独立布局溢出告警，保持实际填写值、标准字型/字号与下载；测量故障和损坏告警回执均不阻断。最终 PDF `62123ae6e82f7670a65d74e5d6f0d8819011d1a282b36c47610359c96c817841`；证据 `/tmp/pdf-three-increment-form-browser`。填写风险预览不勾确认也保存，原有属性确认边界保持。未实现自动适配，字体墨迹外伸/下伸不在本布局检测完整覆盖范围。

转换：PDFium 实测来源 originX 贯穿安全水平LTR、多行共同左锚点至 PPTX；合成/旋转/RTL/不一致锚点回退原路径。实际 PPTX `a05f154f8d169e0335924cb53b2c51f12f4158f7da90ae0aa25d963bf0821720`，证据 `/tmp/pdf-three-increment-pptx-browser-root02`。host LO 实际渲染左右列 X 残差 +0.002998/-0.002014pt，行距/表图保持；首行 Y +6.350708pt，整体保真仍 false，继续提供实际下载及告警。

三域最终画面和 host 渲染已目视；图形及下划线仍使用来源坐标，不随新文字重排；表单裁切实际可见且如实告警。

## 专项验证、故障与审阅

- 新 native 专项按阶段 RED→GREEN：绘图混合 5 项、溢出/测量故障 7 项、来源 X 4 项。未重复完整测试；安全边界与非阻断故障由真实 PDF/AP/字体输出验证。
- 前端绘图新 2 + 受影响旧混合 2 项通过；host 受影响旧项与新增属性风险、填值风险两个行为通过，新增项先真实 RED。最终显示逻辑变化后对受影响属性用例作定向重验。
- HTTP 新混合正常复核故障与第二阶段 writer 故障、表单溢出及测量故障共 4 项通过：`/tmp/pdf-three-increment-http-final.log`。交叉审阅发现附加告警元数据若缺键可能阻断签发，新增 null/非列表/缺键三例 RED→GREEN：`/tmp/pdf-three-increment-review-metadata-{red,green}.log`。新 normalize helper 已登记 `_SIGNING_CHAIN`，签发静态守卫通过：`/tmp/pdf-three-increment-signing-guard.log`。
- 绘图首轮 browser 的 pypdf 页结构比较误失败，改为更严格原始页引用比较后，先复验实际下载再重跑通过。PPTX 首轮旧 verifier 硬编码 tight-box 坐标失败，新增显式 source-origin 模式；旧默认、拒绝旧坐标与一单位 X/Y/行距变异检查均保留。没有以放宽保真验收隐藏缺口。
- 新纯读表单模块 strict tsc 通过；未声称全项目 typecheck 通过。引擎依赖闭包仍有既有 operations dispatch/运行资源/UI 类型问题；并行 Word 的旧全量类型错误不在本批改动范围。

详见三个专属验收文档。后续仍有任意编辑混合、完整游标/跨对象重排、复杂字体和首行基线、任意多Widget/XFA/签名；证书服务仍是外部依赖。
