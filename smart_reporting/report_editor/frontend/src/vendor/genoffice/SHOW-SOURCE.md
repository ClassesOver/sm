# 固定源放映组件族

来源：`/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。逐文件身份见 `SHOW-SOURCE-SHA256.json`。

本次将源 PC 放映核心接入现有原生 PPTX 编辑器。`slides-main.ts::startSlidesShow` 将同一完整 NativeDraft 同时提交给既有 `render-tree` 和 `preview` 只读接口；来源身份、草稿、当前页发生变化时不打开过时快照。保留全部页面及隐藏标志，播放顺序由源 `computePlayOrder` 计算。放映不保存、不导出、不更改草稿。

| 源功能族 | 当前接入与边界 |
| --- | --- |
| `SlideShowView` / `show-keys` 前后、Home/End、数字+Enter、结束屏、B/W、点击 | 源状态机与导航保留；进入结束屏后再次前进退出；跳转与返回显示动画完成态。 |
| 隐藏页、从隐藏当前页起播 | 完整页数组交给源顺序函数；通常跳过隐藏页，从隐藏当前页起播时保留该页。 |
| `AnimatedSlide` / `animation-play` 逐步对象动画 | 复用前项迁入的完整播放组件和运行时；用实际补丁产物模型构造序列，保留同时/之后触发、方向、段落和动作路径。未建模预设、媒体和渲染中缺失对象明确告警并跳过。 |
| fade/push/wipe/split/circle/cover/pull/dissolve/zoom/random | 保留源 CSS、随机选择和前进触发。源本身为 CSS 近似效果，不宣称 PowerPoint 像素级一致。 |
| `MorphStage` | 源几何插值与匹配算法保留；当前 inspect 没有 cNvPr 键，仅传实际对象名称与 `spid:null`，明确告警，不生成伪造稳定 ID。 |
| `show-menu` / `ContextMenu` / `SlideThumb` | 保留下一页、上一页、上次查看、看全部页、屏幕子菜单与结束；主播放为动态画布，仅“看全部页”使用源静态缩略图。 |
| 菜单键盘与焦点 | 在源组件基础上补初始焦点、上下/Home/End、Tab 限制、卸载恢复；子菜单保留源点击/hover和原生按钮 Tab/Enter。Escape 仅关闭当前菜单或网格层。 |
| 对象级链接、命名动作 | 实际 `elementLink` 接源 hit-test、合法页号及源六种命名动作；URL只接受 http/https/mailto，拒绝控制字符、空白和反斜杠。 |
| 浏览器全屏与生命周期 | 原生 dialog、焦点限制和退出恢复由宿主提供；全屏拒绝时继续窗口内放映；清理 resize/键盘/图片晚到回调与 React 根。隔离编辑器快捷键与 IME。 |
| 桌面 IPC、liftShowCurtain | 用启动前已核验的只读快照代替 IPC；不引入 Electron 模拟接口。 |
| `ShowMediaLayer`、媒体指令、录音旁白播放 | 未接入。当前接口仅提供图片，不提供授权音视频 URL；不以静态海报声称媒体已播放。 |
| `useNarrationRecording` / `RecordingBar`、排练计时、已保存 advanceMs | 未接入。缺少工作流授权录制/持久化 API 和 inspect 字段，界面明确缺口；保留的 `slideshow-utils` 纯函数不构成排练功能接入。 |
| 演讲者视图、多窗口、逐文字运行链接、自定义放映配置 | 未接入相应宿主 API/模型。核心可接受 customOrder，但本宿主未暴露自定义放映入口；runLinks为空，不伪造元数据。 |

`SlideShowView.tsx` 的适配集中在输入 props、去除未授权桌面/媒体/计时执行、焦点与键盘隔离；Morph、动画、导航、菜单、hit-test 算法不重写。`show-keys.ts`、`slideshow-utils.ts`、`SlideThumb.tsx` 原样迁入；其余 import 与 type 调整见身份清单。

测试证据位于 `/dev/shm/office-show-source-20261113`。定向单测覆盖源键盘状态机、菜单状态、隐藏顺序、完整草稿快照、动画分步、结束屏、焦点、转场类、元数据缺口与链接过滤。真实 native runner `smoke/pptx-show-source-smoke.mjs` 记录 fade/wipe/动作路径/pulse 的画布像素轨迹、push 的 CSS 实际进度及 Morph 多个中间几何位置；这些有界证据不等于所有动画或转场已逐项视觉验收。最终冻结资源、四视口结果与来源原字节身份以最终 evidence 为准。
