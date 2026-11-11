# PPTX 隐藏幻灯片增量验收

日期：2026-11-11。固定参考：GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c。完整四格式对齐仍未完成，本文件只记录隐藏页子能力。

## 实现范围

- 源 App.tsx 的 toggleHidden 调用 showActions.setSlidesHidden，pptx-ops 的 setHidden 使用 pptx-engine.setSlideHidden。本地复用同一引擎属性写入，不删除页、不把隐藏页转换为图片。
- 幻灯片放映功能区的“隐藏幻灯片”使用既有中文语言包与固定源 IconHideSlide SVG；按当前页的原始 hidden 与草稿覆盖同步 aria-pressed，缩略列表显示“已隐藏”及划线页码。
- 新 hiddenSlides journal 逐项携带来源 slideIndex 与严格 boolean hidden。Python 与 Node 检查数量、唯一索引、字段、原始页范围；与同批删页冲突拒绝。页面重排后仍作用于原始来源对象。
- 接入同一 NativeDraft、UndoRedo、刷新恢复与原生保存；非法恢复保留原草稿。原生 Agno 候选合并保留人工隐藏属性与原始 base。
- 仅针对已保存来源页。新建页沿用既有“保存并重新打开后编辑”的来源身份约束。多选批量隐藏、放映播放器/演讲者视图/排练计时仍未交付，隐藏属性不等于这些能力完成。

## 已执行验证

1. 失败日志 /tmp/pptx-hidden-red-20261111.log：inspect缺hidden、保存字段被拒绝等3个预期失败；/tmp/pptx-hidden-ui-red-20261111.log：按钮禁用及无当前状态2个预期失败。
2. Python新增12项定向通过：/tmp/pptx-hidden-boundaries-final-20261111.log；随后收紧直接桥错误断言并新增AI保全，3项通过、10项未重复运行：/tmp/pptx-hidden-ai-and-direct-final-20261111.log。
3. 界面新增6项+受影响既有功能区26项通过：/tmp/pptx-hidden-ui-final-20261111.log。后续修正参数化案例的tuple类型及实际传入数组，3个非法恢复场景单独验证：/tmp/pptx-hidden-invalid-draft-final-20261111.log。
4. 真实文件独立python-pptx/lxml/ZIP回读：/tmp/pptx-hidden-files-green2-20261111/。原3页中第二页预隐藏，第一页隐藏/第二页取消隐藏再按[2,0,1]重排，输出hidden=[false,true,false]；文字来源正确，除允许的两页XML/顺序与core元数据外文件内容不变；两页删除show属性后的XML C14N与原始相同。
5. 桥打包日志 /tmp/pptx-hidden-bridge-build-green-20261111.log。未调整引擎隐藏属性实现。

最初测试夹具语言未设置、ZIP目录条目集合、原生保存体误按非原生扁平请求断言等失败保留原日志；按实际宿主契约修正夹具，不放宽文件内容/操作身份断言。

## 待最终构建验证

smoke/pptx-native-save-smoke.mjs 新增 hidden-slides 专属模式，覆盖中文图标、隐藏/取消隐藏、UndoRedo、刷新草稿、原页重排、保存下载独立回读及修订2重开。node --check已通过。最终统一构建、预算、实际浏览器与资产身份尚待追加；当前不能将专项测试称为built-browser完成。

未提交、推送或部署；未运行完整项目测试。


## 971b 完整浏览器与独立审阅

- 统一构建41.04秒、原预算与预算契约均exit0；manifest 971b7a2a8eb3461e2cee46a38af23f544631c519c786902ac9d52e9106b646d9。真实 /tmp/pptx-hidden-built-final2-20261111/evidence.json 为ok=true、修订2、108个实际JS逐响应字节核对；96个功能区按钮真SVG审计invalid=[]。
- 中文隐藏按钮切换、来源预隐藏页取消隐藏、UndoRedo、草稿恢复、原页重排、真实引擎保存/下载与明确新修订重开通过。输出顺序[1,0]，隐藏属性[false,true]。下载SHA 5b3f9b66ec59eed0b5383a859fc89e29def003e9fda61b332f1d4663945b0297；root独立python-pptx/ZIP/lxml回读，仅两页show与presentation顺序改变；其余部件字节保留，两页去show后的C14N与来源一致。
- 第一轮 /tmp/pptx-hidden-built-final-20261111.log 在history业务路径page.reload时404超时。最小HTTP探针证明Vite preview只提供静态入口，业务路径返回404；仅smoke改按既有场景导航native.html保留原草稿，不改产品或放宽断言。修正后的单场景实际exit0，页面与HTTP错误断言通过。
- 独立审阅发现固定源引擎未处理合法show=false/单引号，可能输出重复show；generate.ts仅两行兼容修复。新测试先RED3项，再与旧隐藏测试合并14/14通过；四种真实PPTX来源8份输出独立lxml/python-pptx回读通过，证据 /tmp/pptx-hidden-boolean-proof-20261111。最终slides桥SHA 5d0e59595d4029295579511350d8182293c501b3fc451fad7bad08cabb6e0b0e。
- root另发现复制预隐藏页的Ribbon状态与列表不一致，单项先RED后GREEN，仅改为读取slideAt投影；副本仍遵守保存后才编辑约束。日志 /tmp/pptx-hidden-copy-{red,green}-20261111.log。

root目视revision-2.png发现新增“已隐藏”标识在窄侧栏被挤成竖排；上述功能闭环虽通过，但该视觉问题尚待最后CSS修复与仅重开既有下载文件的窄补验，不将971b截图声称视觉全部通过。

## 624aae 标签布局窄补验

- 专属只读脚本 smoke/pptx-hidden-badge-reopen-smoke.mjs 使用上述 971b 完整流程实际下载的 downloaded.pptx，来源 SHA 仍为 5b3f9b66ec59eed0b5383a859fc89e29def003e9fda61b332f1d4663945b0297。inspect_office 与 render_pptx_tree 均实际读取该文件；PDF iframe 仅采用既有 smoke 的只读占位响应，不将其声称为实际 PDF 渲染验收。
- 修复前 971b 真实 RED：Range.getClientRects 为 3 行，badge 11×48 px。/tmp/pptx-hidden-badge-red-20261111/failure.json 记录明确单行断言失败、pageErrors=[]、空草稿、0 save/export，以及 108 JS、6 CSS 实际 HTTP 响应与磁盘 SHA 匹配；保留日志和截图。
- 生产仅改 slides.css 末尾两行：隐藏行 position:relative；badge absolute 到行底部，white-space:nowrap，从 flex 正文布局移出，不再挤占页标题。未改业务逻辑、按钮或保存链路。
- root 统一构建及预算链 exit0 后，manifest 624aaed06ec55f25ca06ec97bb6b04085bf4ddda5b46415fd0eadcb674733e84 的窄重开实际 exit0；/tmp/pptx-hidden-badge-final3-20261111/evidence.json 为 ok=true。108 JS、6 CSS 实际 HTTP 200 响应逐份与磁盘 SHA 一致。
- 隐藏标签 Range 为单行 33×16 px，位于 207×59 px 的 row 内；隐藏页标题宽 38 px，与可见页相同。标签不覆盖标题及四个操作按钮。中文隐藏按钮带真实 SVG，来源可见／隐藏页 aria-pressed 分别 false／true。pageErrors=[]、failedResponses=[]、draftOperations=[]、saveRequests=[]、exportRequests=[]；截图 revision-2-layout.png 已目视确认水平标签与完整按钮。
- 最初窄脚本在 about:blank 子 frame 误改 history，保留 /tmp/pptx-hidden-badge-red-first-harness-20261111；仅收紧初始化路由后重新取得上述纯几何 RED。624aae 首次窄跑几何已通过，但因 harness 漏设 preview.pdf 占位导致 404，保留 /tmp/pptx-hidden-badge-final3-first-harness-20261111；补齐与既有 smoke 一致的路由后窄重跑通过，未改生产或放宽几何／错误断言。

本次仅重开已验证的修订2产物补验布局，没有重新执行已通过的隐藏／取消隐藏／UndoRedo／恢复／保存下载完整流程；完整交互证据仍归属于 971b，最终 624aae 的补充仅覆盖此处列明的只读边界。未自行构建、提交、推送或部署。

root 已独立复读最终 evidence.json、manifest 与实际下载文件 SHA，并目视 revision-2-layout.png；确认隐藏标识水平显示、中文按钮完整。
