# 已有同页单选组复制验收（2026-11-14）

后续扩展：本记录保留该批同页范围；跨页来源支持及新的逐页移动边界见 [跨页单选组复制验收](NATIVE_PDF_MULTIPAGE_RADIO_COPY_ACCEPTANCE_20261114.md)。

本批支持来源同页的安全互斥单选组复制、重复和同文档跨页粘贴。点击任意成员复制完整字段组，保留全部选项、当前选择、默认选择、必填、相对布局、按钮 AS/AP 和原父级。副本移动/删除一次进入 NativeDraft，Undo/Redo 与恢复沿用原链。

## 实现与边界

- 仅2–64按钮、全部来源按钮位于同页的安全互斥组。复用既有 radioRequired 的引用/状态/选项/页面检查，并对全部 Widget 和辅助图执行来源复制检查；原跨页组、非互斥/共享AP/异常状态/复杂结构拒绝复制，不复制部分组。
- copyFrom 精确绑定首 Widget 与原字段身份。radioWidgets 只声明完整组的目标页及统一平移；服务端从实际 PDF 复核全部成员，客户端不能改选项/选择、漏成员、改单个按钮尺寸或把目标成员分散到多页。
- 字段、Kids、Widget 及辅助 AP 图使用新引用，Parent/P/Rect 单独绑定。后续选择副本不改变原值/原 AP 资源闭包。保留原尺寸和同父层级命名，默认选择与当前选择可以不同。
- 副本保存前仅可整组平移、删除或再复制；移动超出页面时拒绝该次变化并保留旧草稿。中文卡片说明整组行为，菜单提示复制整个组；保存后再使用已有字段设计能力。
- 系统/跨文档剪贴板、原跨页 radio 组复制、任意复杂多 Widget 与实际签名字段复制仍未支持。副本可与原组重叠，不保证自动避让。原 Widget 迁页的固定源支持仍待核实。
- 复核失败继续保留实际 PDF 字节和诚实回执，复用原修订签发链，无新发布门禁或签发步骤。

## 定向测试

| 验证 | 结果 |
| --- | --- |
| 引擎 RED | `/tmp/pdf-source-radio-engine-red.log`：原组未获 copyEditable；另外两个拒绝类测试当时通过。 |
| 引擎 GREEN | `/tmp/pdf-source-radio-engine-final.log`：23 项通过，新 radio 5 项与原单控件/日期复制、批创建、radio 必填等受影响专项。覆盖已选择/未选择且有默认值、层级多副本原索引、全批零写、非法来源、后置复核故障保留实际组和后续选择隔离。 |
| 前端 RED | `/tmp/pdf-source-radio-front-red.log`：来源整组 clipboard 和画布两项失败。 |
| 前端 GREEN | `/tmp/pdf-source-radio-front-final.log`：116 项通过（clipboard 11、画布35、创建7、批创建2、公共宿主61）；保留原 React act 警告。多选移动只累加一次，单成员移动仍原子平移全组，整组删除可撤销。 |
| 真实服务 | `/tmp/pdf-source-radio-service.log`：1 项通过。真实引擎生成层级来源组，preview/preview_file、确认前拒绝、确认保存、新修订/授权下载流及 pypdf/inspect 独立回读；原值 No 与三按钮、必填、层级及页面 `[3,3]` 保留，原来源不变。validation.ok=false 仍保留实际下载。 |
| 全局类型 | `/tmp/pdf-source-radio-types.log` 与上一批逐字节相同，仍为既有632条诊断，不称全项目类型通过。 |
| 独立复核 | 同模型 reviewer 静态复核无 Critical/Important；未运行测试，不将其当运行证据。 |

没有重复全项目套件，测试数包含关联覆盖，不与历史批次相加计唯一总数。

## 中文真实浏览器与 PDF 回读

`/tmp/pdf-source-radio-browser/evidence.json` 为 ok:true。真实源码入口、固定 FormDesignLayer、PDF.js 与隔离 CLI；浏览器适配不含生产授权/发布，真实服务验证由上述 Python 测试承担。

- HTML 为 zh-CN，七个功能区标签通过中文断言；实际窄屏卡片和实际预览截图均已目视，未再使用无语言声明的英文回退夹具。
- 从来源第二个按钮 Ctrl+C/Ctrl+D，实际以首 Widget 为来源锚点复制完整三按钮组；只选中副本中一个按钮移动时三个按钮一起平移。
- 菜单粘贴到第二页，整组删除、Undo/Redo 与刷新恢复后，两项实际复制操作保持。
- 真实预览回执 applied `[0,1]`、零跳过；pypdf 回读原组和两副本，页面 Widget 数 `[6,3]`，每组 Kids=3。
- 当前值 `/1`、默认值 `/0` 不同，三组均准确保留；AS 为 `[/Off,/1,/Off]`，Opt、必填和 AP 保留。来源正文和原来源 SHA 不变，页面/HTTP错误为空。
- 390px 卡片 left62/right382、clientWidth=scrollWidth318，无卡片横向溢出；正文沿用原宿主横向阅读，副本重叠属允许范围。

隔离 CLI `/tmp/pdf-source-radio-runtime/dist/cli.mjs` SHA256 为 `ffe77b0f1266d734968752e99fbe21a1f650f134e84c9b4e452298534b8c6a86`，6,162,786 字节。未修改共享 static/dist、提交、推送或部署。Vite sibling 项目 fast-xml-parser/saxes/utif2 预扫描告警与 Python imghdr 弃用提示保留；不据此声称所有依赖/部署验收通过。
