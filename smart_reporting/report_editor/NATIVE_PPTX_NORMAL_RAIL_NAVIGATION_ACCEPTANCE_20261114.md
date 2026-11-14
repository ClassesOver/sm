# PPTX Normal幻灯片栏键盘导航增量

基线：`code` b65c5e8（#237）。固定源：GenOffice f8c17004，
[源keyboard-actions.ts:328起](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/slides/src/renderer/keyboard-actions.ts#L328)。本切片不是PPTX/四格式完整对齐。

## 实现范围

Normal视图直接聚焦页按钮时，ArrowUp/Down、PageUp/Down按真实当前页在最新DOM页序移动，Home/End首尾。边界消费但不重复点击或冲刷备注。通过现有同步click路径，只有切页成功后重新查询已重建的按钮并恢复焦点、nearest滚动。原click中的notes.flush→selectedSlide→renderSlides→renderInspector完全保留；不新造导航状态或保存协议。

仅接直接焦点，忽略修饰键/Shift、IME、已消费事件、modal、隐藏/禁用按钮、非Normal、管理按钮和dispose后的事件。保留native ol/button、Tab次序和CSS；当前页加aria-current=page。无脏备注时不更改草稿或保存；脏备注导航会沿既有click合同flush，不能宣称所有导航零写入。

## 分层验证

证据：`/tmp/office-next-evidence`。本工作区从原前端package-lock执行npm ci --ignore-scripts，595包，锁文件未改；不更新全局环境。

- `rail-integration-red.log`：真实slides-main DOM入口ArrowDown未被消费，期望true实际false；不是静态源码断言。
- `rail-green.log`：最小接线后controller与真实宿主2文件9项通过。
- `rail-related.log`：controller、Normal/Sorter视图、大纲/阅读、notes宿主与notes组件5文件47项通过；覆盖备注输入法否决、合法未提交备注归原页、重建焦点、Tab焦点不同仍按selected计算、DOM重排/非连续ID、边界、modal/IME/修饰键/管理按钮/dispose。Canvas在集成fixture中模拟，不能据此称真实画布验收。
- 新controller及其测试独立strict TypeScript检查通过（`rail-focused-tsc.log`）。
- 完整前端tsc未完成：默认进程被kill，2GB限制OOM，3GB限制exit137且无诊断。已停止重复尝试，需可配置云环境复核完整tsc/构建/原预算；本批不声称完整类型检查通过。
- Chromium辅助长列表实际可见性验证未执行成功：运行环境socket() Operation not permitted，允许范围内一次提权重试同样失败，已停止。DOM测试只验证nearest调用，不冒称长列表像素可见或真实浏览器通过。

没有修改XLSX产品代码、PDF导航、slides-find-replace、AI或#236 task_execution/Word绑定。没有真实Codex连接、保存下载重开、生产鉴权、推送、PR、合并或部署；纯视图导航不要求生成PPTX保存回执。独立审查结论另补，当前仍待阶段整合及完整前端云验证。

## 独立审查与冻结

Astra实际审阅代码与测试，确认无重大/重要代码阻断；独立复跑controller 5项与slides-view-modes 7项，12/12通过，diff-check通过。随后按建议仅修测试卫生：afterEach可靠恢复scrollIntoView原prototype descriptor，删除测试名中未实测的detached声明；该controller 5项再次通过（rail-review-hygiene.log）。产品代码未因审查变化。最后ARIA专项2项通过（rail-final-aria.log）；focused strict tsc最终退出0（rail-focused-tsc-final.log）。这仍是可阶段冻结交云复验，不是完整构建或真实宿主浏览器验收完成。
