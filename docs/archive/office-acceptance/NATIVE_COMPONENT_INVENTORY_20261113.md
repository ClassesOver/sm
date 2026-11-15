# 四格式功能组件逐源盘点（2026-11-13）

原始目标保持四格式完整功能区/中文/图标/交互、原生文件持久化和Agno AI，不以已完成的小批次重定义目标。上一轮是有状态变更与真实文件证据的进展；本轮进一步用固定源建立可核对的组件宇宙，避免仅凭历史缺口或文件名选择容易完成的项目。

固定源 /home/junge/pros/genoffice-source-full，commit f8c17004fb730df11f0f743164ffd8b4281bb38c。

| 格式 | 此轮盘点口径 | 证据目录 | 当前限制 |
|---|---|---|---|
| Word | renderer/components下63文件（44UI、19support），逐源控件/host/native保存与证据状态 | office-component-inventory-20261113/word | host适配不等于完整控件族；历史文档仅pointer，raw冻结证据另标 |
| XLSX | renderer全部363文件、147TSX PascalCase函数（含内部控件/图标helper），控件keys/callbacks/本地锚点 | office-component-inventory-20261113/xlsx | 文件/函数穷举不等于每个工具完成；host_wired与完整family区分 |
| PPTX | renderer/components下39文件，逐源控件/持久化/旧证据 | office-component-inventory-20261113/pptx | 源localStorage也须明确，不能以schema当writer或原生保存完成 |
| PDF | renderer全部85TS/TSX文件、34TSX，exports、vendor身份、初步host映射 | office-component-inventory-20261113/pdf | 未手工逐控件审核行明确unknown；文件清单完成不等于功能完成 |

持久根 /home/junge/codex-evidence/smart_reporting/，inventory-index.json关联机器JSON。不同格式目录结构不同，上述数字不可合并成总功能数、完成率或直接相互比较。后续需继续逐入口、回调、writer、真实交互及文件验收补证。

## 本轮推进

- Word完整WatermarkDialog：源None/Text/Picture与引擎现有PictureWatermarkSpec，补真实图片水印保存和预览，不再只文字。
- XLSX完整ChartFormatPane：series/point颜色、labels、axes、gap/hole/explosion；现有writer可复用，但reader/宿主/圆环预览有真缺口。
- PPTX完整CustomShowDialog：源仅localStorage，本地明确扩展真实p:custShowLst读取/修改；重复页、重排删页、未知扩展与关系身份必须保持。
- PDF完整StampDialog：双页签、实时预览、共享色板，复用现有setStamps真实保存；保留草稿重开/清除，增加取消/过期/IME/焦点与小高度。

本批次已统一冻结 final-source-v2（4439文件），tsc / Vite 44.94秒 / 未调整的原预算均exit0。Word水印与PDF双页签正式保存重开及独立文件回读已通过；XLSX图表格式v2实际文件闭环及v3修复后的真实点选专项均已通过；PPTX自定义放映正式重开及实际重复页播放已通过。各agent只负责自身域，root独立核对，不重复完整测试，不覆盖共享static/dist。

## 专家额外会做什么

逐控件追踪到真实writer，核验导出而非只看截图；验证键盘/IME/色板焦点、低高度真实命中、取消与异步选区；对比目标之外的ZIP部件/正文/媒体；冻结输入、实际HTTP资产和下载身份，区分模拟权限仓储、真实模型与生产验收。上述工作逐批落地，未知项继续公开保留。

## 冻结与当前工作区的边界

持久证据 office-component-inventory-20261113/frozen-build-identity.json：源码清单6d89e82804f0535f999491b487ab192608a6fe1b5cb75674bf71c299c8eb438e；静态manifest c2d8c235b8ac55347f2cad2d0af09d65a167776c3659f7c98bbb2da48076e203，共720文件。冻结期间外部工作区另有XLSX打印页眉图像和runner变更，逐项记录workspace-current-drift.json；本批次结果只归属冻结输入，不能声称当前所有并发改动均通过或已部署。

PDF额外逐控件审核明确：证书签名与数字签名验证面板仍为disabled缺口；可视签名现有手写/键入不足源图像/黑白/保存复用完整族；测量已有校准回调但本轮未补完整source dialog和真实保存证据。状态见pdf/signature-measure-control-audit.json，禁止以入口或文件存在当作完成。

单项正式文档：[Word水印](NATIVE_WORD_WATERMARK_SOURCE_ACCEPTANCE_20261113.md)、[PDF水印页眉页脚](NATIVE_PDF_STAMP_SOURCE_ACCEPTANCE_20261113.md)、[PPTX自定义放映](NATIVE_PPTX_CUSTOM_SHOW_SOURCE_ACCEPTANCE_20261113.md)、[XLSX图表格式](NATIVE_XLSX_CHART_FORMAT_SOURCE_ACCEPTANCE_20261113.md)。完整穷举盘点与未知项仍持续，尚未全部完成。

XLSX真实点选补充：正式r2证明完整侧栏编辑/原生保存/下载重开（仅四个chart XML变化），但r6真实鼠标点选暴露window捕获的对象交互先消费事件，root元素命中未执行，不能认定完整族已完成。正在以既有坐标/命中逻辑显式委托修复；孤立单测通过不足以代替宿主集成。失败证据保留xlsx/browser-final-v2-r6。

## XLSX 真实点选修复版

window捕获对象交互已在目标校验后显式委托既有元素选择方法，排除resize控制点；新增双控制器真实DOM回归覆盖两次完整点击缩窄到原index2、空白清空、保护与resize。final-source-v3仅三产品文件+两测试变动，保留v2旧证据；源码manifest 6f88215fdd66b5ec194b0ed03e9b445d3dae667041e1055722f907b357526ffb，静态manifest fffa484afba22adf36d470529e5305ad858a19a7f3ce91b43e0503373fa61c52，tsc/Vite45.70秒/原预算均exit0。仅补真实点选与单点保存专项，不重复四格式整批浏览器。Word/PDF/PPTX正式运行证据仍明确属于v2；v3同名资源未变但部分文件因入口依赖摘要更名，不能把v2运行自动称为v3运行。

真实点选专项最终已通过：point-browser-final-v3-r1，实际截图定位(1182,788)后两次真实mouse缩窄到原index2，单点蓝色保存/下载/新修订回显；284HTTP资源与v3静态逐项匹配、0browser/console错误。root独立确认仅chart4.xml变化、dPt idx2=0070C0，8826字节SHA256 8e25f63590a52ac75e7ad0a829b0c79c505ab8a1aaf4e21dcf6c744831e7043f。此补丁已关闭此前捕获事件缺口；其余未盘完/未验收组件仍保持未知或partial，不代表四格式全部完成。

最终workspace-current-drift-v3.json另记录并发PDF图片签名、管理偏好预览及打印页眉图像等10项输入变化；它们保留在共享工作区，未纳入本批验收。PDF签名缺口静态盘点只描述当时冻结源，后续新增图片入口不自动视为完整签名族已验收。

下一轮完整图片/外链/测量标定推进见[NATIVE_IMAGE_LINKS_MEASURE_PROGRESS_20261113.md](NATIVE_IMAGE_LINKS_MEASURE_PROGRESS_20261113.md)，source阶段与最终冻结验收分开，不继承为全量完成。

## 图片、外链与测量批次更新

office-image-links-measure-20261113 已落完整Word图片、PPTX去背景、XLSX外链与PDF测量控件族。统一v3构建及原预算通过；PDF/PPTX唯一正式浏览器通过，Word限定续段补齐未保存图片与只读，XLSX原浏览器保存422经真实桥接回归修复后仅补等价重建草稿保存专项。原失败不改写成整轮PASS，XLSX资源请求异常及PPTX并发import漂移分别登记。PDF测量完整source dialog与实际保存缺口本批已补；早前签名/测量审计只是当时状态，其余证书/数字签名及未知组件仍需继续。详细身份、产物和验收边界以本批文档及root-batch-status.json为准；总目标保持active。
