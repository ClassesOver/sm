# Word 图片格式独立模块验收

日期：2026-11-14。固定 GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。仅记录独立模块；主 Ribbon、HTTP、Python 白名单、PM schema 与画布接线由主线程负责，本文不代表完整 Word 已对齐或已上线。

## 实际来源

固定提交 Git tree 中不存在 `ribbon-picture-tab.tsx`，图片格式真实入口在 `apps/docs/src/renderer/components/Ribbon.tsx`：`rotatePicture`、`flipPicture`、`setPictureSize`、`resetPictureSize`、图片环绕与段落对齐；九宫格位置在 `ribbon-layout-tab.tsx::applyPositionPreset`，保存链为 `editor/convert.ts::imagePatchOf` → `patchImageParagraphXml` / `applyImageWrap`。

远程固定提交文件 SHA256：

| 文件 | SHA256 |
| --- | --- |
| Ribbon.tsx | e4edc64326a46a64f48878e3b89472d2239fc308ddc1c13cda63e234449e5f66 |
| ribbon-layout-tab.tsx | 7cc9686689ef0f3693ad9437ed3e7deb50d8c180f212a9620c594ed16016bb8b |
| editor/convert.ts | 7b05f77cd9d6a4859ad51993170d22252f9798c0dc62dddb726b6b99be8781fa |
| packages/docx-engine/src/generate.ts | a339c97330a1551f3ca657f96b5abfd6d41473f9bdabddade3d62208be74e624 |

本地引擎 `generate.ts` 全文件已有宿主适配；本批未修改引擎。直接比较固定源与本地以下源片段字节一致：`patchImageParagraphXml` 至 `const WRAP_ELEMENT_RE` 前（SHA256 `2fc7734851686fc18d642ba9fac2d956edbc27c6c68849ea74d49efb4f8ec8db`）；`applyImageWrap` 至下一 `export function` 前（SHA256 `a1cc0120ae10dc16f803caaa88cfc440d01c3300f87355f99c5c851ef5779d17`）。新模块只调用这些实际写入器，不自行构造图片 XML，不将属性编辑烘焙为位图。

## 接口

- `bridge/docx-picture-format.ts`: `readDocxPictureFormat(value)`；`inspectDocxPictureFormats(bytes, parsed?)` 返回三身份；`patchDocxPictureFormat(bytes,value,parsed?)` 返回实际 DOCX。为避免外部传入过期 ParsedDoc 身份，始终重新解析实际 bytes。
- `formatImage` 操作使用 `blockId`、`expectedObjectSha256`、`expectedImageSha256`；支持成对 `widthPx/heightPx`、`rotDeg`、`flipH/flipV`、`align`、`wrap`；九宫格 `posH/posV` 成对且携带源对应的 `square-right/left`。
- `frontend/src/docx-picture-format.ts`: `projectDocxPictureFormat`、`normalizeDocxPictureFormats`、尺寸纯函数。`imageFormat` 是可撤销的草稿标记；归一化核验预览并恢复原始属性，另发真实原生操作。
- `createDocxPictureFormatControls(editor,anchors,host,locked,reportError,contentWidth?)` 返回 `reason/open/dispose`；`open` 接收 `rotateRight/rotateLeft/flipH/flipV/size/wrap/align/resetSize/position`。数字尺寸与环绕、对齐、位置有独立 DOM 对话框；Reset Size 真实解码自然尺寸，按宿主实际栏宽缩放，且拒绝迟到结果。

## 已验证

TDD：先新增测试运行，因目标模块不存在而 RED；实现后 GREEN。

- doc_engine 根：`node_modules/.bin/vitest run packages/docx-engine/tests/docx-picture-format.test.ts`：5 项通过。原生尺寸、旋转、翻转、对齐、环绕、行内恢复和九宫格位置重开；源/对象/图片身份及未知字段边界；外链组合拒绝；ZIP部件清单一致、媒体与所有其他部件逐字节保全、相邻正文 XML 原字节保全。
- frontend 根：`node_modules/.bin/vitest run src/docx-picture-format.test.ts src/docx-picture-format-controls.test.ts`：6 项通过。投影归一化、篡改拒绝、尺寸比例、自然尺寸适应栏宽、选择与撤销、源位置预设、异步 reset 迟到保护。

## 精确边界

1. 本批仅现有安全整块图片；新增 genImage、run 内联、组合、外链、缺少自身 pic:spPr/a:xfrm 的来源保持只读。
2. 图片字节替换/裁剪/去背景与格式编辑须分别保存；控制器拒绝已有 imageReplace，归一化拒绝双草稿。宿主也应阻止 imageFormat 存在时再打开图片字节工具。
3. 若文档含 `imageZOrderNormalized`，本批拒绝环绕/位置修改，保留尺寸、旋转、翻转、对齐；固定源完整保存对此会同步全图层级，本批没有冒充已移植该同步。
4. 固定源 `ImageEffects` 在 types.ts 明确为 display-only；图片格式 Ribbon 没有颜色/透明度编辑入口。本批不将解析属性冒充持久化能力，也不增加未经来源支持的写入器。
5. 本批不声称 textbox/shape 几何或环绕已支持。它们的原生结构与图片不同。
6. 未运行全套测试、未更改预算、未打包共享 dist、未提交推送或部署。

## 主线程接线后的实际浏览器 / HTTP / 下载 / 重开证据

主线程完成接线与独立 build 后，新增独立 harness `frontend/smoke/word-picture-format-smoke.mjs`，复用 `word-review-presets-server.py` 的实际 FastAPI / NativeEditorService / NativePublicationService 保存链与下载服务。执行：

```sh
cd smart_reporting/report_editor/frontend
FONTCONFIG_FILE=/workspace/sm/smart_reporting/report_editor/frontend/smoke/canvas-fontconfig.conf node smoke/word-picture-format-smoke.mjs
```

运行成功，证据目录 `/tmp/word-picture-format-20261114`：

- `fixture.json` / `picture-source.docx`：用 python-docx `add_picture` 生成整块图片，图片为 Pillow 生成的不对称蓝矩形/红三角。python-docx 自身生成真实 `pic:spPr/a:xfrm`；没有为开放能力而注入 XML。正文前后与页眉页脚均有保全标记。
- `font-preflight.json`：显式使用指定 Fontconfig 文件，浏览器 canvas 字形 preflight 通过。
- 实际页面点击选图 → 图片格式 Ribbon → 旋转90° → 水平翻转。`preview.json` 与 `rotated-preview.png` 记录实际 CSS `rotate(90deg)` / `scaleX(-1)`。
- `save-request.json`：真实 POST `/reports/v1/native/word-presets/1/api/save`，唯一 `formatImage` 操作携带文档/块/媒体身份及 `rotDeg:90,flipH:true`。
- `rotated-flipped-saved.json`：HTTP 200，`revisionRegistered:true`，revision 2。已实际 GET 下载并核对 39127 字节和 SHA256 `8d52c7c54db4153e11e559df4d5c62fd71ad2f5b316d4655f8abd791fb028aff`，保存为 `rotated-flipped-r2.docx`。保留完整回执和工作区产物。
- 从真实回执的 `editor.openUrl` 重新打开修订2，图片仍为原始媒体 URL，实际 CSS 仍为90°旋转和水平翻转；`reopened.png` 已人工检查，图形可见、正文完整。
- `independent.json`：独立 lxml + python-docx 读取下载 DOCX，断言 `pic:spPr/a:xfrm rot="5400000" flipH="1"`，仍只有一个可编辑图片 drawing。唯一变化 ZIP 部件为 `word/document.xml`；其他所有 ZIP 部件与图片媒体逐字节相同，前后正文 XML、页眉页脚保全。图片媒体 SHA256 `60104441cd00e3926ca37f558dbe02ad99819a53ef98b9ec48d85d050f6bbae7`。
- `result.json`：`ok:true`，181 个实际 JS/CSS HTTP 响应均与所运行 build 磁盘文件 SHA256 一致，`pageerror=[]`。build 为 `/tmp/word-genoffice-integrated-build`，manifest SHA256 `d0b18441cb743de37ef9d7065e5506e3bf9d8e5cbda57943e7d4487257005e97`。

此回执的 `validation.ok` 为 **false**，明确原因 `native_source_review_pending`（业务事实和完整版式尚未重新核验）；未冒称业务/完整版式验收通过。实际保存、修订登记、下载签发和重开成功与这项软告警分别记录。此浏览器闭环只覆盖旋转与水平翻转；尺寸/重置/环绕/位置的完整浏览器保存链、所有图片对象类型及所有复杂版式均不由本次 smoke 证明。
