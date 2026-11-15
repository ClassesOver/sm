# 四格式 HTML 模板控件定位

原生入口可达的 src 相对导入闭包及 Vite 本地 UI/i18n/font-metrics 别名；含本地 vendor。展开innerHTML与createModal content的静态HTML控件；动态插值不执行、不假定穷尽，单独登记。控件line是模板表达式的源码行，htmlLine是解析片段行。仍不含外部npm/引擎包、运行时计算出的入口和桌面原生菜单。声明点不是功能或运行验收分母。

本表只定位源码声明，不根据标签、按钮存在或回调存在推断功能通过。声明名称是静态标签/文本摘要，不是完整的运行时可访问名称计算。所有条目仍待映射具体构建的运行证据；历史已验收组件不会因此变为失败。模板行用于跳到表达式，片段行不是源码行；重复声明不是独立功能。

| 格式 | 文件 | 模板行 | 片段行 | 元素 | 声明名称 | 定位/状态属性 | 含动态内容 | 运行证据 |
| --- | --- | ---: | ---: | --- | --- | --- | --- | --- |
| shared | src/ask-ai-panel.ts | 15 | 3 | nav | 编辑会话 | {} | 否 | 待映射 |
| shared | src/chart-ai-edit.ts | 603 | 13 | button | 更多模板与调整 | {"type":"button","data-action":"show-chart-actions"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 603 | 15 | textarea |  | {"id":"__OFFICE_UI_EXPRESSION_5__"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 603 | 17 | button | 让 AI 修改 | {"type":"button","data-action":"submit"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 690 | 3 | input |  | {"id":"__OFFICE_UI_EXPRESSION_1__","type":"checkbox"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 901 | 2 | div | [动态表达式] [动态表达式] 已用时 00:00 通常需要 20–60 秒。可以收起侧栏继续改正文，完成后会提示你。 取消改图 | {"role":"status"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 901 | 6 | ol | 生成阶段 | {"data-role":"timeline"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 901 | 10 | button | 取消改图 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 2 | div | 选择预览图 | {"role":"group"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 3 | button | 新图 | {"type":"button","data-action":"view-new"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 4 | button | 对比 | {"type":"button","data-action":"view-both"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 5 | button | 原图 | {"type":"button","data-action":"view-original"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 6 | button | 原图与新图交替显示，便于发现细微差别 | {"type":"button","data-action":"view-blink"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 8 | div | 改图前后对比 | {"role":"group"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 13 | div | 全部改图结果 | {} | 否 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 16 | div | 闪烁对比画布，点击暂停或继续 | {"data-frame":"new","role":"button"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 21 | div | 闪烁对比分页 | {"data-role":"blink-nav","role":"group","hidden":true} | 否 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 24 | div | 审阅摘要 | {"data-role":"review-summary"} | 否 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 25 | ul | 变更清单 | {} | 否 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 30 | button | 采用到正文 | {"type":"button","data-action":"accept"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 31 | button | 继续调整 | {"type":"button","data-action":"continue"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1041 | 32 | button | 放弃 | {"type":"button","data-action":"discard"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1327 | 1 | p | 已放弃本轮结果。继续编辑时，请在正文选择图表。 | {"role":"status"} | 否 | 待映射 |
| shared | src/chart-ai-edit.ts | 1364 | 2 | div | 正在读取图表信息… | {"role":"status"} | 否 | 待映射 |
| shared | src/chart-ai-edit.ts | 1375 | 2 | div | 关闭 | {"role":"alert"} | 是 | 待映射 |
| shared | src/chart-ai-edit.ts | 1375 | 5 | button | 关闭 | {"type":"button","data-action":"close"} | 是 | 待映射 |
| shared | src/conflict-panel.ts | 17 | 12 | textarea | 合并后的 Markdown | {"data-conflict":"merge"} | 否 | 待映射 |
| shared | src/conflict-panel.ts | 17 | 14 | button | 保留本地 | {"type":"button","data-conflict":"local"} | 否 | 待映射 |
| shared | src/conflict-panel.ts | 17 | 14 | button | 采用远端 | {"type":"button","data-conflict":"remote"} | 否 | 待映射 |
| shared | src/conflict-panel.ts | 17 | 14 | button | 合并后重试 | {"type":"button","data-conflict":"merge-retry"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 1 | span |  | {"role":"status"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 2 | div |  | {"role":"status","hidden":true} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 3 | button | 载入远端设计 | {"type":"button","data-design-action":"reload"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 3 | button | 保留本地并重新保存 | {"type":"button","data-design-action":"retry-local"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 4 | button | 恢复本地草稿 | {"type":"button","data-design-action":"recover"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 4 | button | 忽略草稿 | {"type":"button","data-design-action":"discard-recovery"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 5 | nav | 设计分类 | {} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 5 | button | 封面 | {"type":"button","data-design-tab":"cover"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 5 | button | 水印 | {"type":"button","data-design-tab":"watermark"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 5 | button | 正文样式 | {"type":"button","data-design-tab":"typography"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 5 | button | 个人模板 | {"type":"button","data-design-tab":"templates"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 6 | section | 设计属性 | {} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 6 | section | 即时设计预览 | {} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 6 | button | 撤销 | {"type":"button","data-design-action":"undo"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 6 | button | 重做 | {"type":"button","data-design-action":"redo"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 6 | div | A4 封面画布 | {} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 7 | button | 立即保存 / 重试 | {"type":"button","data-design-action":"retry"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 7 | button | 生成 PDF 预览 | {"type":"button","data-design-action":"preview"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 7 | span |  | {"data-design-preview-status":true,"role":"status"} | 否 | 待映射 |
| shared | src/design-panel.ts | 51 | 7 | input | 版本备注 | {"name":"design.note"} | 否 | 待映射 |
| docx | src/docx-bookmarks.ts | 68 | 1 | input | 书签名称 | {"data-bookmark-name":true} | 否 | 待映射 |
| docx | src/docx-bookmarks.ts | 68 | 1 | button | 添加书签 | {"type":"button","data-bookmark-add":true} | 否 | 待映射 |
| docx | src/docx-bookmarks.ts | 68 | 1 | button | 关闭书签 | {"type":"button","data-bookmark-close":true} | 否 | 待映射 |
| docx | src/docx-bookmarks.ts | 68 | 1 | p |  | {"role":"status"} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | p | 题注保存说明 | {"role":"region"} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | select | 题注标签 | {"data-caption-label":true} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | option | 图 | {} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | option | 表 | {} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | option | 公式 | {} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | input | 题注描述 | {"data-caption-text":true} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | fieldset | 预览 | {} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | p | 题注预览 | {"data-caption-preview":true,"role":"region"} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | p | 题注状态 | {"role":"status"} | 否 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | button | 取消 | {"type":"button","data-caption-cancel":true} | 是 | 待映射 |
| docx | src/docx-caption-dialog.ts | 7 | 1 | button | 插入题注 | {"type":"button","data-caption-confirm":true} | 是 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | button | 应用并关闭已有批注 | {"type":"button","data-comment-title-close":true} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | select | 选择已有批注 | {"data-comment-target":true} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | textarea | 批注文字 | {"data-comment-text":true} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | p |  | {"role":"status"} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | section | 批注操作 | {} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | button | 应用文字 | {"type":"button","data-comment-apply":true} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | button | 回复此批注 | {"type":"button","data-comment-reply":true} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | button | 解决线程 | {"type":"button","data-comment-resolve":true,"hidden":true} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | button | 删除批注 | {"type":"button","data-comment-delete":true,"hidden":true} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | button | 放弃未应用输入并重新载入 | {"type":"button","data-comment-reload":true,"hidden":true} | 否 | 待映射 |
| docx | src/docx-comment-controls.ts | 21 | 1 | button | 关闭批注 | {"type":"button","data-comment-close":true} | 否 | 待映射 |
| docx | src/docx-comment-create.ts | 81 | 1 | button | 取消并关闭新建批注 | {"type":"button","data-new-comment-close":true} | 否 | 待映射 |
| docx | src/docx-comment-create.ts | 81 | 1 | blockquote | 所选文字 | {"data-new-comment-selection":true,"role":"region","hidden":true} | 否 | 待映射 |
| docx | src/docx-comment-create.ts | 81 | 1 | textarea | 新批注文字 | {"data-new-comment-text":true} | 否 | 待映射 |
| docx | src/docx-comment-create.ts | 81 | 1 | button | 添加批注 | {"type":"button","data-new-comment-submit":true} | 否 | 待映射 |
| docx | src/docx-comment-create.ts | 81 | 1 | button | 取消新建 | {"type":"button","data-new-comment-cancel":true} | 否 | 待映射 |
| docx | src/docx-comment-create.ts | 81 | 1 | p |  | {"role":"status"} | 否 | 待映射 |
| docx | src/docx-comment-create.ts | 81 | 1 | section | 批注草稿 | {} | 否 | 待映射 |
| docx | src/docx-comment-create.ts | 81 | 1 | ul | 待保存的新批注 | {"data-new-comment-list":true,"hidden":true} | 否 | 待映射 |
| docx | src/docx-comment-reply.ts | 51 | 1 | button | 取消并关闭批注回复 | {"type":"button","data-comment-reply-close":true} | 否 | 待映射 |
| docx | src/docx-comment-reply.ts | 51 | 1 | blockquote | 回复的根批注 | {"data-comment-reply-parent":true,"role":"region"} | 否 | 待映射 |
| docx | src/docx-comment-reply.ts | 51 | 1 | textarea | 批注回复文字 | {"data-comment-reply-text":true} | 否 | 待映射 |
| docx | src/docx-comment-reply.ts | 51 | 1 | button | 添加回复 | {"type":"button","data-comment-reply-submit":true} | 否 | 待映射 |
| docx | src/docx-comment-reply.ts | 51 | 1 | button | 取消回复 | {"type":"button","data-comment-reply-cancel":true} | 否 | 待映射 |
| docx | src/docx-comment-reply.ts | 51 | 1 | p |  | {"role":"status"} | 否 | 待映射 |
| docx | src/docx-comment-reply.ts | 51 | 1 | section | 批注回复草稿 | {} | 否 | 待映射 |
| docx | src/docx-comment-reply.ts | 51 | 1 | ul | 待保存的批注回复 | {"data-comment-reply-list":true,"hidden":true} | 否 | 待映射 |
| docx | src/docx-cross-reference.ts | 60 | 1 | button | 关闭交叉引用 | {"type":"button","data-cross-reference-close":true} | 否 | 待映射 |
| docx | src/docx-cross-reference.ts | 60 | 1 | p | 交叉引用状态 | {"role":"status"} | 否 | 待映射 |
| docx | src/docx-cross-reference.ts | 60 | 1 | ul | 已保存书签 | {"data-cross-reference-list":true} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | div | 查找方式 | {"role":"tablist"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | button | 查找 | {"type":"button","role":"tab","data-find-tab":"find"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | button | 替换 | {"type":"button","role":"tab","data-find-tab":"replace"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | button | 关闭查找 | {"type":"button","data-find-action":"close"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | input | 查找内容 | {"data-find-query":true} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | button | 上一个匹配 | {"type":"button","data-find-action":"previous"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | button | 下一个匹配 | {"type":"button","data-find-action":"next"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | input | 替换为 | {"data-find-replacement":true} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | button | 替换当前 | {"type":"button","data-find-action":"replace"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | button | 全部替换 | {"type":"button","data-find-action":"replace-all"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | input | 区分大小写 | {"type":"checkbox","data-find-option":"matchCase"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | input | 全字匹配 | {"type":"checkbox","data-find-option":"wholeWord"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | input | 区分全半角 | {"type":"checkbox","data-find-option":"matchWidth"} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | select | 查找模式 | {"data-find-mode":true} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | option | 普通文字 | {} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | option | Word 通配符 | {} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | option | 正则表达式 | {} | 否 | 待映射 |
| docx | src/docx-find-replace.ts | 55 | 1 | p |  | {"role":"status","data-find-status":true} | 否 | 待映射 |
| docx | src/docx-font-dialog.ts | 38 | 2 | div | 字体设置页签 | {"role":"tablist"} | 是 | 待映射 |
| docx | src/docx-font-dialog.ts | 38 | 3 | div | [动态表达式][动态表达式][动态表达式][动态表达式][动态表达式][动态表达式] | {"role":"tabpanel","data-panel":"font","id":"__OFFICE_UI_EXPRESSION_1__-font-panel"} | 是 | 待映射 |
| docx | src/docx-font-dialog.ts | 38 | 5 | div | [动态表达式][动态表达式][动态表达式][动态表达式][动态表达式][动态表达式][动态表达式] | {"role":"tabpanel","data-panel":"advanced","id":"__OFFICE_UI_EXPRESSION_9__-advanced-panel","hidden":true} | 是 | 待映射 |
| docx | src/docx-font-dialog.ts | 38 | 7 | div | 字体预览 | {} | 否 | 待映射 |
| docx | src/docx-font-dialog.ts | 38 | 7 | p |  | {"role":"alert","hidden":true} | 否 | 待映射 |
| docx | src/docx-font-dialog.ts | 38 | 7 | button | 取消 | {"type":"button","data-font-cancel":true} | 是 | 待映射 |
| docx | src/docx-font-dialog.ts | 38 | 7 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 3 | select | 行距类型 | {} | 否 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 3 | option | 倍数 | {} | 否 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 3 | option | 最小值 | {} | 否 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 3 | option | 固定值 | {} | 否 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 4 | input | 行距倍数 | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 5 | input | 行距值（pt） | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 6 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 7 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-line-spacing.ts | 26 | 7 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-link-dialog.ts | 16 | 3 | input | Link URL | {"type":"text"} | 否 | 待映射 |
| docx | src/docx-link-dialog.ts | 16 | 4 | p | 超链接错误 | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-link-dialog.ts | 16 | 6 | button | 取消 | {"type":"button","data-action":"cancel","data-command":"cancelLink"} | 是 | 待映射 |
| docx | src/docx-link-dialog.ts | 16 | 7 | button | 应用 | {"type":"submit","data-command":"applyLink"} | 是 | 待映射 |
| docx | src/docx-main.tsx | 180 | 1 | div | Word 编辑 | {"role":"toolbar"} | 否 | 待映射 |
| docx | src/docx-main.tsx | 180 | 1 | p | 支持正文、基础样式、表格文字及符合条件表格的增删行列。每张表的结构修改需保存并重开后继续；不支持的编辑会提示原因。 | {"role":"status"} | 否 | 待映射 |
| docx | src/docx-navigation-search.ts | 10 | 1 | input | 搜索正文和表格 | {"type":"search","data-navigation-query":true} | 否 | 待映射 |
| docx | src/docx-navigation-search.ts | 10 | 1 | button | 清除导航搜索 | {"type":"button","data-navigation-search-action":"clear"} | 否 | 待映射 |
| docx | src/docx-navigation-search.ts | 10 | 1 | button | 上一个搜索结果 | {"type":"button","data-navigation-search-action":"previous"} | 否 | 待映射 |
| docx | src/docx-navigation-search.ts | 10 | 1 | button | 下一个搜索结果 | {"type":"button","data-navigation-search-action":"next"} | 否 | 待映射 |
| docx | src/docx-navigation-search.ts | 10 | 1 | output | 搜索结果计数 | {"data-navigation-search-count":true} | 否 | 待映射 |
| docx | src/docx-navigation-search.ts | 10 | 1 | p | 请输入搜索文字 | {"data-navigation-search-status":true,"role":"status"} | 否 | 待映射 |
| docx | src/docx-navigation.ts | 24 | 1 | button | 关闭导航窗格 | {"type":"button","data-navigation-action":"close"} | 否 | 待映射 |
| docx | src/docx-navigation.ts | 24 | 1 | div | 正文标题 | {"role":"tree"} | 否 | 待映射 |
| docx | src/docx-navigation.ts | 34 | 1 | button | 标题 | {"type":"button","role":"tab","data-navigation-tab":"headings"} | 否 | 待映射 |
| docx | src/docx-navigation.ts | 34 | 1 | button | 页面 | {"type":"button","role":"tab","data-navigation-tab":"pages"} | 否 | 待映射 |
| docx | src/docx-notes-source.tsx | 48 | 3 | textarea | 注释内容 | {} | 否 | 待映射 |
| docx | src/docx-notes-source.tsx | 48 | 4 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-notes-source.tsx | 48 | 5 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| docx | src/docx-notes-source.tsx | 48 | 5 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 2 | div | 段落设置页签 | {"role":"tablist"} | 是 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 2 | button | 缩进和间距 | {"type":"button","role":"tab","id":"__OFFICE_UI_EXPRESSION_0__-indents-tab","data-tab":"indents"} | 是 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 2 | button | 换行和分页 | {"type":"button","role":"tab","id":"__OFFICE_UI_EXPRESSION_2__-pagination-tab","data-tab":"pagination"} | 是 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 3 | div | 对齐方式混合（保持原样）左对齐居中右对齐两端对齐 大纲级别混合（保持原样）正文文本[动态表达式] [动态表达式] 特殊缩进混合（保持原样）无首行悬挂 单位pt字符缩进值 行距混合（保持原样）单倍1.5 倍双倍最小值固定值多倍设置值 | {"role":"tabpanel","id":"__OFFICE_UI_EXPRESSION_4__-indents-panel","data-panel":"indents"} | 是 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 4 | select | 段落对齐 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 4 | option | 混合（保持原样） | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 4 | option | 左对齐 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 4 | option | 居中 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 4 | option | 右对齐 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 4 | option | 两端对齐 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 5 | select | 大纲级别 | {} | 是 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 5 | option | 混合（保持原样） | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 5 | option | 正文文本 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 7 | select | 特殊缩进类型 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 7 | option | 混合（保持原样） | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 7 | option | 无 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 7 | option | 首行 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 7 | option | 悬挂 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 8 | select | 特殊缩进单位 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 8 | option | pt | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 8 | option | 字符 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 8 | input | 特殊缩进值 | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | select | 段落行距类型 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | option | 混合（保持原样） | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | option | 单倍 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | option | 1.5 倍 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | option | 双倍 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | option | 最小值 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | option | 固定值 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | option | 多倍 | {} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 9 | input | 段落行距倍数 | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 10 | div | [动态表达式] | {"role":"tabpanel","id":"__OFFICE_UI_EXPRESSION_8__-pagination-panel","data-panel":"pagination","hidden":true} | 是 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 11 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 11 | button | 取消 | {"type":"button","data-paragraph-cancel":true} | 是 | 待映射 |
| docx | src/docx-paragraph-dialog.ts | 33 | 11 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 3 | select | 特殊缩进类型 | {} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 3 | option | 无 | {} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 3 | option | 首行 | {} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 3 | option | 悬挂 | {} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 4 | select | 特殊缩进单位 | {} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 4 | option | pt | {} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 4 | option | 字符 | {} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 5 | input | 缩进值（pt） | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 8 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 8 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-special-indent.ts | 26 | 8 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-alignment-controls.ts | 6 | 2 | select | 整表对齐方式 | {} | 否 | 待映射 |
| docx | src/docx-table-alignment-controls.ts | 6 | 2 | option | 起始侧 | {} | 否 | 待映射 |
| docx | src/docx-table-alignment-controls.ts | 6 | 2 | option | 居中 | {} | 否 | 待映射 |
| docx | src/docx-table-alignment-controls.ts | 6 | 2 | option | 右对齐 | {} | 否 | 待映射 |
| docx | src/docx-table-alignment-controls.ts | 6 | 5 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-table-alignment-controls.ts | 6 | 5 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-alignment-controls.ts | 6 | 5 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-alt-text-controls.ts | 5 | 1 | input | 标题 | {"type":"text"} | 否 | 待映射 |
| docx | src/docx-table-alt-text-controls.ts | 5 | 1 | textarea | 说明 | {} | 否 | 待映射 |
| docx | src/docx-table-alt-text-controls.ts | 5 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-table-alt-text-controls.ts | 5 | 1 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-alt-text-controls.ts | 5 | 1 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-cell-margin-overrides-controls.ts | 10 | 4 | fieldset | 自定义边距 | {} | 是 | 待映射 |
| docx | src/docx-table-cell-margin-overrides-controls.ts | 10 | 5 | p | 来源边距状态 | {"data-source-state":true,"role":"status"} | 否 | 待映射 |
| docx | src/docx-table-cell-margin-overrides-controls.ts | 10 | 6 | section | 边距设置说明 | {"role":"region"} | 否 | 待映射 |
| docx | src/docx-table-cell-margin-overrides-controls.ts | 10 | 8 | p | 边距设置错误 | {"role":"alert","hidden":true} | 否 | 待映射 |
| docx | src/docx-table-cell-margin-overrides-controls.ts | 10 | 9 | button | 恢复继承 | {"type":"button","data-action":"inherit"} | 是 | 待映射 |
| docx | src/docx-table-cell-margin-overrides-controls.ts | 10 | 9 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-cell-margin-overrides-controls.ts | 10 | 9 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-cell-margins-controls.ts | 10 | 5 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-table-cell-margins-controls.ts | 10 | 5 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-cell-margins-controls.ts | 10 | 5 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-cell-shape-controls.ts | 6 | 3 | input | 列数 | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-table-cell-shape-controls.ts | 6 | 4 | input | 行数 | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-table-cell-shape-controls.ts | 6 | 5 | input | 拆分前合并单元格 | {"type":"checkbox","checked":true} | 否 | 待映射 |
| docx | src/docx-table-cell-shape-controls.ts | 6 | 6 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-table-cell-shape-controls.ts | 6 | 6 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-cell-shape-controls.ts | 6 | 7 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-cell-wrap-controls.ts | 5 | 1 | input | 自动换行 | {"type":"checkbox"} | 否 | 待映射 |
| docx | src/docx-table-cell-wrap-controls.ts | 5 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-table-cell-wrap-controls.ts | 5 | 1 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-cell-wrap-controls.ts | 5 | 1 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-column-width-controls.ts | 5 | 3 | input | 列宽（twip） | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-table-column-width-controls.ts | 5 | 4 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-table-column-width-controls.ts | 5 | 4 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-column-width-controls.ts | 5 | 5 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-row-breaks-controls.ts | 6 | 3 | input | 允许行内跨页 | {"type":"checkbox","data-action":"allow-break"} | 否 | 待映射 |
| docx | src/docx-table-row-breaks-controls.ts | 6 | 6 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-table-row-breaks-controls.ts | 6 | 6 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-row-breaks-controls.ts | 6 | 6 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-table-row-breaks-controls.ts | 27 | 2 | button | 单元格边距 | {"type":"button","data-action":"margins","disabled":true} | 否 | 待映射 |
| docx | src/docx-table-row-breaks-controls.ts | 27 | 3 | button | 行跨页 | {"type":"button","data-action":"row-breaks"} | 否 | 待映射 |
| docx | src/docx-table-row-height-controls.ts | 6 | 3 | input | 行高（twip） | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-table-row-height-controls.ts | 6 | 5 | p |  | {"role":"alert"} | 否 | 待映射 |
| docx | src/docx-table-row-height-controls.ts | 6 | 5 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-table-row-height-controls.ts | 6 | 6 | button | 确定 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-text-revision-controls.ts | 155 | 1 | p |  | {"role":"status"} | 否 | 待映射 |
| docx | src/docx-text-revision-controls.ts | 155 | 1 | button | 下一条待处理 | {"type":"button","data-action":"next"} | 否 | 待映射 |
| docx | src/docx-text-revision-controls.ts | 155 | 1 | button | 接受所有支持的正文修订 | {"type":"button","data-action":"accept-all"} | 否 | 待映射 |
| docx | src/docx-text-revision-controls.ts | 155 | 1 | button | 拒绝所有支持的正文修订 | {"type":"button","data-action":"reject-all"} | 否 | 待映射 |
| docx | src/docx-view.ts | 70 | 3 | input | 显示比例（%） | {"type":"number"} | 否 | 待映射 |
| docx | src/docx-view.ts | 70 | 5 | p |  | {"id":"docx-zoom-error","role":"alert"} | 否 | 待映射 |
| docx | src/docx-view.ts | 70 | 6 | button | 取消 | {"type":"button","data-action":"cancel"} | 是 | 待映射 |
| docx | src/docx-view.ts | 70 | 6 | button | 应用 | {"type":"submit"} | 是 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | button | 关闭水印设置 | {"type":"button"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | div | 水印类型 | {"role":"radiogroup"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 无水印 | {"type":"radio","name":"mode"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 文字 | {"type":"radio","name":"mode"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | fieldset | 文字水印 | {} | 是 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 水印文字 | {"name":"text"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | select | 水印字体 | {"name":"font"} | 是 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | select | 水印字号 | {"name":"size"} | 是 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | option | 自动 | {} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 粗体 | {"type":"checkbox","name":"bold"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 斜体 | {"type":"checkbox","name":"italic"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 水印透明度 | {"name":"transparency","type":"number"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 水印字体颜色 | {"name":"color","type":"color"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | fieldset | 版式 | {} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 斜式 | {"type":"radio","name":"layout"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | input | 水平 | {"type":"radio","name":"layout"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | p | 水印设置错误 | {"role":"alert","hidden":true} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| docx | src/docx-watermark-dialog.ts | 13 | 1 | button | 确定 | {"type":"button"} | 否 | 待映射 |
| shared | src/draft.ts | 11 | 1 | button | 恢复草稿 | {"type":"button","data-draft":"restore"} | 否 | 待映射 |
| shared | src/draft.ts | 11 | 1 | button | 放弃 | {"type":"button","data-draft":"discard"} | 否 | 待映射 |
| shared | src/enhancements.ts | 238 | 12 | div |  | {"role":"alert","hidden":true} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 4 | div | 核对任务 | {"role":"tablist"} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 6 | summary | 全部任务 | {} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 7 | div | 全部核对任务 | {} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 9 | button | 来源目录 | {"type":"button"} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 13 | button | 后退 | {"type":"button","data-evidence":"back"} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 14 | button | 前进 | {"type":"button","data-evidence":"forward"} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 16 | nav | 探索路径 | {} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 18 | summary | 完整探索路径 | {} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 19 | div | 完整探索路径 | {} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 23 | p |  | {"role":"status","hidden":true} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 25 | aside | 来源目录 | {"id":"evidence-directory"} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 28 | button | 全部收起 | {"type":"button","hidden":true} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 31 | input | 搜索来源目录 | {"type":"search"} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 33 | p |  | {"role":"status","hidden":true} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 36 | button | 复核已保存正文与原计算快照；不重新取数或批准业务结论 | {"type":"button","hidden":true} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 40 | button | 下载溯源清单（CSV） | {"type":"button","hidden":true} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 163 | 44 | div | 证据对象 | {} | 否 | 待映射 |
| shared | src/evidence-browser.ts | 1013 | 1 | h1 | 证据浏览器 | {} | 否 | 待映射 |
| shared | src/export-settings.ts | 21 | 10 | input | 包含封面 | {"type":"checkbox","name":"cover"} | 否 | 待映射 |
| shared | src/export-settings.ts | 21 | 10 | input | 包含目录 | {"type":"checkbox","name":"toc","checked":true} | 否 | 待映射 |
| shared | src/export-settings.ts | 21 | 10 | input | 页眉页脚 | {"type":"checkbox","name":"headerFooter","checked":true} | 否 | 待映射 |
| shared | src/export-settings.ts | 21 | 10 | input | 页码 | {"type":"checkbox","name":"pageNumbers","checked":true} | 否 | 待映射 |
| shared | src/export-settings.ts | 21 | 10 | input | 来源编号与附录 | {"type":"checkbox","name":"sources"} | 否 | 待映射 |
| shared | src/export-settings.ts | 21 | 10 | textarea | 版本备注 | {"name":"note"} | 否 | 待映射 |
| shared | src/export-settings.ts | 21 | 11 | button | 取消 | {"type":"button","data-export-settings":"cancel"} | 否 | 待映射 |
| shared | src/export-settings.ts | 21 | 11 | button | 继续导出 | {"type":"button","data-export-settings":"confirm"} | 否 | 待映射 |
| shared | src/history.ts | 159 | 11 | section | 版本列表 | {} | 否 | 待映射 |
| shared | src/history.ts | 159 | 13 | select | 按来源筛选 | {} | 否 | 待映射 |
| shared | src/history.ts | 159 | 13 | option | 全部来源 | {} | 否 | 待映射 |
| shared | src/history.ts | 159 | 13 | option | 人工修订 | {} | 否 | 待映射 |
| shared | src/history.ts | 159 | 13 | option | 系统发布 | {} | 否 | 待映射 |
| shared | src/history.ts | 159 | 14 | input | 按日期筛选 | {"type":"date"} | 否 | 待映射 |
| shared | src/history.ts | 159 | 17 | button | 加载更多 | {"type":"button","hidden":true} | 否 | 待映射 |
| shared | src/history.ts | 159 | 19 | section | 版本差异 | {} | 否 | 待映射 |
| shared | src/history.ts | 159 | 31 | select | 选择基准版本 | {} | 否 | 待映射 |
| shared | src/history.ts | 159 | 33 | select | 选择对比版本 | {} | 否 | 待映射 |
| shared | src/history.ts | 159 | 35 | div | 左右版本差异 | {"role":"group"} | 否 | 待映射 |
| shared | src/history.ts | 159 | 37 | button | 恢复为当前草稿 | {"type":"button","hidden":true} | 否 | 待映射 |
| shared | src/preflight.ts | 66 | 11 | button | 返回编辑 | {"type":"button","data-preflight":"cancel"} | 否 | 待映射 |
| shared | src/preflight.ts | 66 | 11 | button | 仍然导出 | {"type":"button","data-preflight":"continue"} | 否 | 待映射 |
| shared | src/search.ts | 58 | 1 | input | 搜索文本 | {} | 否 | 待映射 |
| shared | src/search.ts | 58 | 1 | button | 上一个匹配 | {"type":"button","data-search":"prev","disabled":true} | 否 | 待映射 |
| shared | src/search.ts | 58 | 1 | button | 下一个匹配 | {"type":"button","data-search":"next","disabled":true} | 否 | 待映射 |
| shared | src/search.ts | 58 | 1 | input | 替换为 | {} | 否 | 待映射 |
| shared | src/search.ts | 58 | 1 | button | 替换 | {"type":"button","data-search":"replace","disabled":true} | 否 | 待映射 |
| shared | src/search.ts | 58 | 1 | button | 全部替换 | {"type":"button","data-search":"all","disabled":true} | 否 | 待映射 |
| shared | src/search.ts | 58 | 1 | button | 关闭搜索 | {"type":"button","data-search":"close"} | 否 | 待映射 |
| shared | src/share.ts | 14 | 13 | input | 分享编辑链接 | {"data-share":"url","readonly":true} | 否 | 待映射 |
| shared | src/share.ts | 14 | 14 | button | 复制链接 | {"type":"button","data-share":"copy"} | 否 | 待映射 |
| shared | src/share.ts | 14 | 21 | button | 生成并复制链接 | {"type":"button","data-share":"create"} | 否 | 待映射 |
| shared | src/share.ts | 14 | 22 | p |  | {"data-share":"status","role":"status"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 10 | div | 载入中 重试 | {"role":"status"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 12 | button | 重试 | {"type":"button","hidden":true} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 14 | nav | 报告操作 | {} | 是 | 待映射 |
| shared | src/shell.ts | 44 | 15 | button | 显示或隐藏目录 | {"type":"button","data-action":"outline"} | 是 | 待映射 |
| shared | src/shell.ts | 44 | 20 | div | 编辑与视图 | {"id":"report-secondary-actions"} | 是 | 待映射 |
| shared | src/shell.ts | 44 | 23 | button | 更多操作 | {"type":"button","data-action":"more"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 28 | button | 保存 | {"type":"button","data-action":"save"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 31 | button | 导出 PDF | {"type":"button","data-action":"pdf"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 34 | button | 导出 Word | {"type":"button","data-action":"word"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 38 | button | 导出设置 | {"type":"button","data-action":"export-settings"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 39 | button | 快捷键帮助 | {"type":"button","data-action":"shortcuts"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 41 | span | 报告阅读进度 | {"role":"progressbar"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 43 | div | 编辑状态说明 | {} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 53 | aside | 报告目录 | {"id":"report-outline"} | 是 | 待映射 |
| shared | src/shell.ts | 44 | 57 | button | 关闭目录 | {"type":"button"} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 61 | nav | 章节导航 | {} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 63 | section | [动态表达式] | {} | 是 | 待映射 |
| shared | src/shell.ts | 44 | 67 | button | 回到报告顶部 | {"type":"button","hidden":true} | 否 | 待映射 |
| shared | src/shell.ts | 44 | 68 | button | 退出专注 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-chart-tools.ts | 14 | 2 | select | 已登记数据图表 | {} | 否 | 待映射 |
| pptx | src/slides-chart-tools.ts | 14 | 3 | textarea | 图表调整要求 | {} | 否 | 待映射 |
| pptx | src/slides-chart-tools.ts | 14 | 4 | button | 生成候选 | {"type":"submit"} | 否 | 待映射 |
| pptx | src/slides-chart-tools.ts | 14 | 4 | button | 取消 | {"type":"button","hidden":true} | 否 | 待映射 |
| pptx | src/slides-chart-tools.ts | 14 | 5 | p | 正在读取已登记图表… | {"role":"status"} | 否 | 待映射 |
| pptx | src/slides-chart-tools.ts | 14 | 6 | button | 采纳候选 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-chart-tools.ts | 14 | 7 | ul | 待保存图表修改 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 2 | section | Ask AI | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 2 | textarea | Ask AI | {"id":"ai-instruction"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 2 | button | 生成候选 | {"type":"submit"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 2 | button | 取消 AI 任务 | {"type":"button","hidden":true} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 2 | div |  | {"role":"status"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 2 | button | 采纳候选 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 3 | section | AI 配图 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 3 | textarea | AI 配图 | {"id":"image-prompt"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 3 | select | 目标页 | {"id":"image-target"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 3 | button | 生成预览 | {"type":"submit"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 3 | span | 尚未生成配图 | {"role":"status"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 3 | button | 加入待保存配图 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 5 | aside | 幻灯片列表 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 6 | section | 幻灯片预览 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 6 | div | 可编辑幻灯片画布 | {"role":"group","hidden":true} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 6 | p | 画布载入中 | {"role":"status"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | aside | 对象编辑 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | select | 当前页版式 | {"id":"layout-select"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | select | 可编辑对象 | {"id":"object-select"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | textarea | 文字 | {"id":"object-text"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | input | X | {"name":"x","type":"number"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | input | Y | {"name":"y","type":"number"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | input | 宽 | {"name":"width","type":"number"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | input | 高 | {"name":"height","type":"number"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | input | 当前页背景颜色 | {"id":"background-color","type":"color"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | button | 恢复原背景 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | button | 新增文本 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | button | 新增水印 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | button | 删除对象 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | ul | 待保存的页面结构修改 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | select | 商务主题 | {"id":"theme-select"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 保持当前主题 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 执行汇报 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 临床医疗 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 现代商务 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | select | 页面转场 | {"id":"transition-select"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 无 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 淡化 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 推进 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 擦除 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 分割 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 圆形 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 覆盖 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 拉伸 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 溶解 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 缩放 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 变形 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 随机 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | select | 动画效果 | {"id":"animation-effect"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 淡化 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 出现 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 飞入 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 擦除 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 向下擦除 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 分割进入 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 弹跳 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 翻转进入 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 缩放进入 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 脉冲 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 旋转 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 放大 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 摇摆 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 消失 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 淡出 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 飞出 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 擦除退出 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 缩小退出 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 缩小退出 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 路径 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | select | 触发方式 | {"id":"animation-trigger"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 点击时 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 与上一动画同时 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | option | 上一动画后 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | input | 持续 ms | {"id":"animation-duration","type":"number"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | input | 延迟 ms | {"id":"animation-delay","type":"number"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 144 | 7 | button | 添加对象动画 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | input | 日期和时间 | {"name":"dateOn","type":"checkbox"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | input | 自动更新 | {"name":"dateAuto","type":"checkbox"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | input | 日期文字 | {"name":"date","type":"text"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | input | 幻灯片编号 | {"name":"slideNum","type":"checkbox"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | input | 页脚 | {"name":"footerOn","type":"checkbox"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | input | 页脚文字 | {"name":"footer","type":"text"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | p | 页眉和页脚错误 | {"role":"alert"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 291 | 1 | button | 全部应用 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | select | 背景填充类型 | {"name":"fill"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | option | 图片 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | option | 渐变 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | select | 背景图片填充方式 | {"name":"mode"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | option | 拉伸 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | option | 平铺 | {} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | input | 渐变起始颜色 | {"name":"from","type":"color"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | input | 渐变结束颜色 | {"name":"to","type":"color"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | select | 渐变方向 | {"name":"direction"} | 是 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | input | 隐藏背景图形 | {"name":"graphics","type":"checkbox"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | input | 应用到全部页面 | {"name":"all","type":"checkbox"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | p | 背景设置状态 | {"role":"status"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | p | 背景设置错误 | {"role":"alert"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | button | 重置背景 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 322 | 1 | button | 确定 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 396 | 1 | input | 节名称 | {"name":"name","type":"text"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 396 | 1 | p | 新增节错误 | {"role":"alert"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 396 | 1 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 396 | 1 | button | 确定 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 414 | 1 | input | 列数 | {"name":"cols","type":"number"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 414 | 1 | input | 行数 | {"name":"rows","type":"number"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 414 | 1 | p | 插入表格错误 | {"role":"alert"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 414 | 1 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-main.ts | 414 | 1 | button | 确定 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-master-text.tsx | 16 | 1 | nav | 母版和版式部件 | {} | 否 | 待映射 |
| pptx | src/slides-master-text.tsx | 16 | 1 | select | 文字对象 | {"data-master-element":true} | 否 | 待映射 |
| pptx | src/slides-master-text.tsx | 16 | 1 | textarea | 文字 | {"data-master-text":true} | 否 | 待映射 |
| pptx | src/slides-master-text.tsx | 16 | 1 | p |  | {"data-master-status":true,"role":"status"} | 否 | 待映射 |
| pptx | src/slides-master-text.tsx | 16 | 1 | button | 关闭母版视图 | {"type":"button","data-master-close":true} | 否 | 待映射 |
| pptx | src/slides-master-text.tsx | 16 | 1 | button | 应用文字到草稿 | {"type":"button","data-master-apply":true} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | textarea | AI 助手 | {} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | select | AI 授权范围 | {} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | option | 当前对象 | {} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | option | 当前页可编辑对象 | {} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | option | 整份演示文稿画布 | {} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | option | 当前页演讲者备注 | {} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | option | 整稿演讲者备注 | {} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | button | 生成候选 | {"type":"submit"} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | button | 取消任务 | {"type":"button","hidden":true} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | p |  | {"role":"status"} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | button | 采纳到草稿 | {"type":"button"} | 否 | 待映射 |
| pptx | src/slides-native-ai.ts | 43 | 1 | button | 放弃候选 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 2 | select | 高级筛选字段 | {} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 3 | select | 第一条件运算符 | {} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 3 | input | 第一条件值 | {} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 4 | select | 条件连接 | {} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 4 | option | 并且（AND） | {} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 4 | option | 或者（OR） | {} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 5 | select | 第二条件运算符 | {} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 5 | input | 第二条件值 | {} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 6 | p | 高级筛选说明 | {"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 6 | p | 高级筛选范围 | {"data-target":true,"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 6 | p | 高级筛选状态 | {"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 6 | p | 高级筛选错误 | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 7 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-advanced-filter-dialog.ts | 6 | 7 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-axis-size.ts | 61 | 3 | input |  | {"type":"text"} | 否 | 待映射 |
| xlsx | src/workbook-axis-size.ts | 61 | 5 | p |  | {"id":"workbook-ribbon-axis-error","role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-axis-size.ts | 61 | 6 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-axis-size.ts | 61 | 6 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-cell-shift.ts | 79 | 3 | fieldset | [动态表达式] | {"role":"radiogroup"} | 是 | 待映射 |
| xlsx | src/workbook-cell-shift.ts | 79 | 4 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-cell-shift.ts | 79 | 5 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-cell-shift.ts | 79 | 5 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-chart-data-dialog.ts | 51 | 1 | button | 添加系列 | {"type":"button","data-chart-data-add":true} | 否 | 待映射 |
| xlsx | src/workbook-chart-data-dialog.ts | 51 | 1 | button | 切换行/列 | {"type":"button","data-chart-data-switch":true} | 否 | 待映射 |
| xlsx | src/workbook-chart-data-dialog.ts | 51 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-chart-data-dialog.ts | 51 | 1 | p | 正在读取或应用图表数据… | {"role":"status","data-chart-data-progress":true,"hidden":true} | 否 | 待映射 |
| xlsx | src/workbook-chart-data-dialog.ts | 51 | 1 | button | 取消 | {"type":"button","data-chart-data-cancel":true} | 否 | 待映射 |
| xlsx | src/workbook-chart-data-dialog.ts | 51 | 1 | button | 确定 | {"type":"submit","data-chart-data-submit":true} | 否 | 待映射 |
| xlsx | src/workbook-chart-descriptions.ts | 15 | 1 | div | 图表说明列表 | {"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-chart-descriptions.ts | 15 | 1 | button | 关闭 | {"type":"button","data-chart-descriptions-close":true} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | input | 图表轴标题 | {"type":"text"} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | select | 数据标签 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | option | 无 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | option | 值 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | option | 百分比 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | option | 分类和百分比 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | select | 图表分组 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | option | 簇状 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | option | 堆积 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | option | 百分比堆积 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | input | 显示主网格线 | {"type":"checkbox"} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | button | 取消 | {"type":"button","data-chart-design-cancel":true} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 29 | 1 | button | 确定 | {"type":"submit","data-chart-design-submit":true} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 41 | 1 | select | 图例位置 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 41 | 1 | option | 请选择 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 41 | 1 | option | 无 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 41 | 1 | option | 左侧 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 41 | 1 | option | 右侧 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 41 | 1 | option | 顶部 | {} | 否 | 待映射 |
| xlsx | src/workbook-chart-design-dialog.ts | 41 | 1 | option | 底部 | {} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 3 | select | 函数 | {} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 4 | input | 引用位置 | {} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 4 | button | 添加 | {"type":"button","data-action":"add"} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 5 | ul | 所有引用位置 | {} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 6 | input | 使用左列标签 | {"type":"checkbox"} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 7 | p | 合并计算说明 | {"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 8 | p | 合并计算引用状态 | {"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 8 | p | 合并计算范围 | {"data-target":true,"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 8 | p | 合并计算错误 | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 9 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-consolidate-dialog.ts | 10 | 9 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-data-table-dialog.ts | 11 | 3 | input | 表格区域 | {} | 否 | 待映射 |
| xlsx | src/workbook-data-table-dialog.ts | 11 | 4 | input | 行输入单元格 | {} | 否 | 待映射 |
| xlsx | src/workbook-data-table-dialog.ts | 11 | 5 | input | 列输入单元格 | {} | 否 | 待映射 |
| xlsx | src/workbook-data-table-dialog.ts | 11 | 6 | p | 模拟运算表说明 | {"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-data-table-dialog.ts | 11 | 7 | p | 模拟运算表结果 | {"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-data-table-dialog.ts | 11 | 7 | p | 模拟运算表错误 | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-data-table-dialog.ts | 11 | 8 | button | 关闭 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-data-table-dialog.ts | 11 | 8 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-dedupe.ts | 36 | 4 | input | 数据包含标题 | {"type":"checkbox","checked":true} | 否 | 待映射 |
| xlsx | src/workbook-dedupe.ts | 36 | 5 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-dedupe.ts | 36 | 6 | button | 取消 | {"type":"button","data-cancel":true} | 否 | 待映射 |
| xlsx | src/workbook-dedupe.ts | 36 | 6 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-defined-names.ts | 202 | 3 | select | 已定义名称 | {} | 否 | 待映射 |
| xlsx | src/workbook-defined-names.ts | 202 | 4 | select | 名称作用域 | {} | 否 | 待映射 |
| xlsx | src/workbook-defined-names.ts | 202 | 5 | input | 名称 | {} | 否 | 待映射 |
| xlsx | src/workbook-defined-names.ts | 202 | 6 | input | 引用 | {} | 否 | 待映射 |
| xlsx | src/workbook-defined-names.ts | 202 | 7 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-defined-names.ts | 202 | 9 | button | 删除 | {"type":"button","disabled":true} | 否 | 待映射 |
| xlsx | src/workbook-defined-names.ts | 202 | 10 | button | 更新 | {"type":"button","disabled":true} | 否 | 待映射 |
| xlsx | src/workbook-defined-names.ts | 202 | 11 | button | 新建 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-editable-ranges-dialog.ts | 10 | 3 | p | 允许编辑区域说明 | {"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-editable-ranges-dialog.ts | 10 | 4 | button | 新增区域 | {"type":"button","data-action":"add"} | 否 | 待映射 |
| xlsx | src/workbook-editable-ranges-dialog.ts | 10 | 5 | p | 允许编辑区域状态 | {"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-editable-ranges-dialog.ts | 10 | 5 | p | 允许编辑区域错误 | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-editable-ranges-dialog.ts | 10 | 6 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-editable-ranges-dialog.ts | 10 | 6 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-fill-series.ts | 321 | 4 | input | 预测趋势 | {"type":"checkbox","data-fill-trend":true} | 否 | 待映射 |
| xlsx | src/workbook-fill-series.ts | 321 | 5 | input | 步长值 | {"type":"text","data-fill-step":true} | 否 | 待映射 |
| xlsx | src/workbook-fill-series.ts | 321 | 6 | input | 终止值 | {"type":"text","data-fill-stop":true} | 否 | 待映射 |
| xlsx | src/workbook-fill-series.ts | 321 | 7 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-fill-series.ts | 321 | 8 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-fill-series.ts | 321 | 8 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-format.ts | 181 | 3 | input | 格式代码 | {} | 否 | 待映射 |
| xlsx | src/workbook-format.ts | 181 | 5 | p |  | {"id":"workbook-ribbon-format-error","role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-format.ts | 181 | 6 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-format.ts | 181 | 6 | button | 应用 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-goal-seek-dialog.ts | 11 | 3 | input | 目标公式单元格 | {} | 否 | 待映射 |
| xlsx | src/workbook-goal-seek-dialog.ts | 11 | 4 | input | 目标值 | {} | 否 | 待映射 |
| xlsx | src/workbook-goal-seek-dialog.ts | 11 | 5 | input | 可变单元格 | {} | 否 | 待映射 |
| xlsx | src/workbook-goal-seek-dialog.ts | 11 | 6 | p | 单变量求解说明 | {"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-goal-seek-dialog.ts | 11 | 7 | p | 单变量求解结果 | {"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-goal-seek-dialog.ts | 11 | 7 | p | 单变量求解错误 | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-goal-seek-dialog.ts | 11 | 8 | button | 关闭 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-goal-seek-dialog.ts | 11 | 8 | button | 求解 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-goto.ts | 116 | 3 | input | 引用位置 | {"type":"text","data-goto-reference":true} | 否 | 待映射 |
| xlsx | src/workbook-goto.ts | 116 | 6 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-goto.ts | 116 | 7 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-goto.ts | 116 | 7 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-header-footer-editor.ts | 76 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-header-footer-editor.ts | 76 | 1 | button | 取消 | {"type":"button","data-header-footer-cancel":true} | 否 | 待映射 |
| xlsx | src/workbook-header-footer-editor.ts | 76 | 1 | button | 确定 | {"type":"submit","data-header-footer-apply":true} | 否 | 待映射 |
| xlsx | src/workbook-main.ts | 183 | 2 | section | 工作簿 AI 编辑 | {} | 否 | 待映射 |
| xlsx | src/workbook-main.ts | 183 | 2 | textarea | Ask AI | {"id":"workbook-instruction"} | 否 | 待映射 |
| xlsx | src/workbook-main.ts | 183 | 2 | button | 生成候选 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-main.ts | 183 | 2 | button | 撤销 AI 采纳 | {"type":"button","disabled":true} | 否 | 待映射 |
| xlsx | src/workbook-main.ts | 183 | 2 | div |  | {"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-main.ts | 183 | 2 | button | 采纳到草稿 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-main.ts | 183 | 2 | button | 拒绝 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-main.ts | 183 | 4 | div | 报告工作簿 | {"id":"workbook-grid"} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | textarea | AI 助手 | {} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | select | AI 授权范围 | {} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | option | 当前选区 | {} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | option | 整份工作簿 | {} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | button | 生成候选 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | button | 取消任务 | {"type":"button","hidden":true} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | p |  | {"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | button | 采纳到草稿 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | button | 放弃候选 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | button | 撤销草稿 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-native-ai.ts | 40 | 1 | button | 重做草稿 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-notes.ts | 182 | 4 | textarea | 批注内容 | {} | 否 | 待映射 |
| xlsx | src/workbook-notes.ts | 182 | 5 | p |  | {"id":"workbook-ribbon-note-error","role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-notes.ts | 182 | 6 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-notes.ts | 182 | 6 | button | 应用 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 3 | div | 分类 | {"role":"listbox"} | 是 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 5 | input | 小数位数 | {"type":"number","data-numfmt-decimals":true} | 否 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 6 | select | 货币符号 | {"data-numfmt-symbol":true} | 是 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 7 | input | 使用千位分隔符 | {"type":"checkbox","data-numfmt-thousands":true} | 否 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 8 | select | 负数 | {"data-numfmt-negative":true} | 是 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 9 | select | 类型 | {"data-numfmt-date":true} | 否 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 10 | select | 类型 | {"data-numfmt-time":true} | 是 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 11 | select | 类型 | {"data-numfmt-fraction":true} | 是 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 12 | input | 类型 | {"type":"text","data-numfmt-custom":true} | 否 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 14 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 15 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | 15 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | select | 选择透视表 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | input | 透视表名称 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | select | 来源表 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | option | 使用单元格区域 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | select | 来源工作表 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | input | 来源区域 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | button | 读取来源字段 | {"type":"button","data-action":"fields"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | select | 目标工作表 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | input | 目标起点 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-dialog.ts | 13 | 1 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | section | 筛选条件 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | select | 筛选透视表 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | select | 筛选字段 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | fieldset | 成员筛选 | {"data-selection":true} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | button | 全选 | {"type":"button","data-action":"all"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | div | 可选筛选成员 | {"data-members":true,"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | fieldset | 日期区间 | {"data-dates":true} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | input | 开始日期 | {"type":"date"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | input | 结束日期 | {"type":"date"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | button | 清除当前字段的成员筛选 | {"type":"button","data-action":"reset"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | fieldset | Excel 原生控件 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | input | 保存原生控件 | {"type":"checkbox","data-native-control":true} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | input | 控件名称 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | input | 控件标题 | {} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | input | 控件左上角单元格 | {"data-control-geometry":true} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | input | 控件宽度（像素） | {"type":"number","data-control-geometry":true} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | input | 控件高度（像素） | {"type":"number","data-control-geometry":true} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | button | 删除原生控件，保留当前筛选 | {"type":"button","data-action":"delete-control","hidden":true} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | p | 筛选保存说明 | {"data-notice":true,"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | p |  | {"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-pivot-filters-dialog.ts | 13 | 1 | button | 应用筛选 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | select | 打印范围 | {"data-print-scope":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 当前工作表 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 选定区域 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 整个工作簿 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | select | 打印页码 | {"data-print-pages-mode":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 全部页 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 指定页 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | input | 起始页 | {"data-print-from":true,"type":"number","disabled":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | input | 结束页 | {"data-print-to":true,"type":"number","disabled":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | fieldset | 当前工作表页面设置 | {"data-print-settings":true,"disabled":true} | 是 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | select | 方向 | {"data-print-orientation":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 纵向 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 横向 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | select | 纸张 | {"data-print-paper":true} | 是 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | select | 页边距 | {"data-print-margins":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 常规 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 宽 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 窄 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | select | 缩放 | {"data-print-scaling":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 无缩放 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 将工作表调整为一页 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 将所有列调整为一页 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 将所有行调整为一页 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | option | 自定义比例 | {} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | input | 自定义比例（%） | {"data-print-scale":true,"type":"number"} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | input | 打印网格线 | {"data-print-gridlines":true,"type":"checkbox"} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | input | 打印行号列标 | {"data-print-headings":true,"type":"checkbox"} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | button | 上一页 | {"type":"button","data-print-prev":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | button | 下一页 | {"type":"button","data-print-next":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | button | 实际大小 | {"type":"button","data-print-zoom":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | button | 刷新预览 | {"type":"button","data-print-refresh":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | div | 打印预览区域 | {"data-print-pane":true,"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | iframe | 打印页面预览 | {"data-print-preview":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | p |  | {"data-print-error":true,"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | button | 页面设置（页眉页脚） | {"type":"button","data-print-page-setup":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | button | 取消 | {"type":"button","data-print-cancel":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | button | 打开系统打印，在目标打印机中选择另存为 PDF | {"type":"button","data-print-pdf":true} | 否 | 待映射 |
| xlsx | src/workbook-print-preview.ts | 125 | 1 | button | 打印 | {"type":"button","data-print-submit":true} | 否 | 待映射 |
| xlsx | src/workbook-print-scale.ts | 21 | 1 | input | 打印缩放比例 | {"data-print-scale-input":true,"type":"number"} | 否 | 待映射 |
| xlsx | src/workbook-print-scale.ts | 21 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-print-scale.ts | 21 | 1 | button | 取消 | {"type":"button","data-print-scale-cancel":true} | 否 | 待映射 |
| xlsx | src/workbook-print-scale.ts | 21 | 1 | button | 确定 | {"type":"submit","data-print-scale-apply":true} | 否 | 待映射 |
| xlsx | src/workbook-queries.ts | 17 | 1 | p |  | {"role":"alert","hidden":true} | 否 | 待映射 |
| xlsx | src/workbook-queries.ts | 17 | 1 | button | 关闭 | {"type":"button","data-query-close":true} | 否 | 待映射 |
| xlsx | src/workbook-recommended-charts-dialog.tsx | 254 | 1 | button | 关闭 | {"type":"button","data-recommended-close":true} | 否 | 待映射 |
| xlsx | src/workbook-ribbon.ts | 799 | 2 | header | Excel 功能区 | {} | 否 | 待映射 |
| xlsx | src/workbook-ribbon.ts | 799 | 3 | nav | 工作簿工具 | {"role":"tablist"} | 否 | 待映射 |
| xlsx | src/workbook-ribbon.ts | 799 | 4 | div |  | {"role":"tabpanel","id":"workbook-ribbon-panel"} | 否 | 待映射 |
| xlsx | src/workbook-sort-dialog.ts | 45 | 3 | input | 数据包含标题 | {"type":"checkbox","data-sort-header":true,"checked":true} | 否 | 待映射 |
| xlsx | src/workbook-sort-dialog.ts | 45 | 5 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-sort-dialog.ts | 45 | 6 | button | 取消 | {"type":"button"} | 否 | 待映射 |
| xlsx | src/workbook-sort-dialog.ts | 45 | 6 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | select | 迷你图类型 | {} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | option | 折线 | {} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | option | 柱形 | {} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | option | 盈亏 | {} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | input | 系列颜色 | {"type":"color"} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | input | 负值颜色 | {"type":"color"} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | input | 显示标记 | {"type":"checkbox"} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | input | 显示坐标轴 | {"type":"checkbox"} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | button | 取消 | {"type":"button","data-sparkline-cancel":true} | 否 | 待映射 |
| xlsx | src/workbook-sparkline-dialog.ts | 8 | 1 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 2 | select | 分组列 | {} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 2 | select | 汇总方式 | {} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 2 | option | 求和 | {} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 2 | option | 计数 | {} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 2 | option | 平均值 | {} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 3 | select | 汇总列 | {} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 4 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 4 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-subtotal-dialog.ts | 8 | 4 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-symbol-dialog.ts | 41 | 4 | nav | 符号分类 | {"role":"tablist"} | 否 | 待映射 |
| xlsx | src/workbook-symbol-dialog.ts | 41 | 5 | div |  | {"id":"__OFFICE_UI_EXPRESSION_0__-panel","role":"tabpanel"} | 是 | 待映射 |
| xlsx | src/workbook-symbol-dialog.ts | 41 | 5 | div | 符号 | {"role":"group"} | 否 | 待映射 |
| xlsx | src/workbook-symbol-dialog.ts | 41 | 6 | p | 符号插入说明 | {"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-symbol-dialog.ts | 41 | 7 | p | 符号插入错误 | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-symbol-dialog.ts | 41 | 8 | p | 符号插入结果 | {"data-symbol-status":true,"role":"status"} | 否 | 待映射 |
| xlsx | src/workbook-symbol-dialog.ts | 41 | 10 | button | 关闭 | {"type":"button","data-symbol-close":true} | 否 | 待映射 |
| xlsx | src/workbook-table-create-dialog.ts | 6 | 3 | input | 表格范围 | {"type":"text"} | 否 | 待映射 |
| xlsx | src/workbook-table-create-dialog.ts | 6 | 4 | input | 表包含标题 | {"type":"checkbox","checked":true} | 否 | 待映射 |
| xlsx | src/workbook-table-create-dialog.ts | 6 | 6 | p |  | {"id":"table-create-error","role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-table-create-dialog.ts | 6 | 7 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-table-create-dialog.ts | 6 | 7 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-table-resize-dialog.ts | 6 | 3 | input | 新的表格范围 | {"type":"text"} | 否 | 待映射 |
| xlsx | src/workbook-table-resize-dialog.ts | 6 | 5 | p |  | {"id":"table-resize-error","role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-table-resize-dialog.ts | 6 | 6 | button | 取消 | {"type":"button","data-action":"cancel"} | 否 | 待映射 |
| xlsx | src/workbook-table-resize-dialog.ts | 6 | 6 | button | 确定 | {"type":"submit"} | 否 | 待映射 |
| xlsx | src/workbook-watch-window.ts | 77 | 1 | button | 添加选区 | {"type":"button","data-watch-add":true} | 否 | 待映射 |
| xlsx | src/workbook-watch-window.ts | 77 | 1 | button | 关闭监视窗口 | {"type":"button","data-watch-close":true} | 否 | 待映射 |
| xlsx | src/workbook-watch-window.ts | 77 | 1 | div | 监视单元格表格 | {"role":"region"} | 否 | 待映射 |
| xlsx | src/workbook-zoom-dialog.ts | 25 | 2 | fieldset | 缩放比例 | {} | 是 | 待映射 |
| xlsx | src/workbook-zoom-dialog.ts | 25 | 4 | input | 适合选定区域 | {"type":"radio","name":"workbook-zoom-choice"} | 否 | 待映射 |
| xlsx | src/workbook-zoom-dialog.ts | 25 | 5 | input | 自定义 % | {"type":"radio","name":"workbook-zoom-choice"} | 否 | 待映射 |
| xlsx | src/workbook-zoom-dialog.ts | 25 | 5 | input | 自定义缩放比例 | {"data-zoom-custom":true,"type":"number"} | 否 | 待映射 |
| xlsx | src/workbook-zoom-dialog.ts | 25 | 6 | p |  | {"role":"alert"} | 否 | 待映射 |
| xlsx | src/workbook-zoom-dialog.ts | 25 | 7 | button | 取消 | {"type":"button","data-zoom-cancel":true} | 否 | 待映射 |
| xlsx | src/workbook-zoom-dialog.ts | 25 | 7 | button | 确定 | {"type":"submit","data-zoom-apply":true} | 否 | 待映射 |

## 动态模板待核查

这里只列摘要，不求值。完整表达式与来源见同次生成的inventory.json；变量、条件分支、循环生成及外部组件需另做运行核查。

| 格式 | 文件 | 模板行 | 来源 | 已声明静态控件 | 动态表达式摘要 |
| --- | --- | ---: | --- | ---: | --- |
| shared | src/ask-ai-panel.ts | 177 | innerHTML | 0 | options.content |
| shared | src/chart-ai-edit.ts | 603 | innerHTML | 3 | assetUrl(basePath, current.imagePath); note ? `&lt;p class="chart-ai-note" role="status"&gt;&lt;/p&gt;` : ''; fieldId('chart-ai-instruction'); retainReview ? '继续调整新图' : '描述你的修改'; buttonClasses('secondary'); fieldId('chart-ai-instruction'); buttonClasse |
| shared | src/chart-ai-edit.ts | 690 | innerHTML | 1 | fieldId('chart-ai-standard-reset'); fieldId('chart-ai-standard-reset'); fieldId('chart-ai-standard-reset-help'); fieldId('chart-ai-standard-reset-help') |
| shared | src/chart-ai-edit.ts | 901 | innerHTML | 3 | assetUrl(basePath, current.imagePath); STAGE_LABELS.queued; STAGE_GROUPS.map((group, index) =&gt; `&lt;li data-step-state="${index === 0 ? 'current' : 'pending'}"&gt;&lt;span class="ai-stage-dot" aria-hidden="true"&gt;&lt;/span&gt;${group.label}&lt;/li&gt;`).join('') |
| shared | src/chart-ai-edit.ts | 1041 | innerHTML | 14 | buttonClasses('quiet'); buttonClasses('quiet'); buttonClasses('quiet'); buttonClasses('quiet'); assetUrl(basePath, current.imagePath); assetUrl(basePath, current.imagePath); assetUrl(basePath, pages[0]!.imagePath); pages.length &gt; 1 ? '多页可用页 |
| shared | src/chart-ai-edit.ts | 1375 | innerHTML | 2 | buttonClasses('quiet') |
| docx | src/docx-caption-dialog.ts | 7 | modal-content | 11 | buttonClasses(); buttonClasses('primary') |
| docx | src/docx-font-dialog.ts | 38 | modal-content | 7 | [['font','字体'],['advanced','高级']].map(([key,label],i) =&gt; `&lt;button type="button" role="tab" data-tab="${key}" id="${id}-${key}-tab" aria-controls="${id}-${key}-panel" aria-selected="${i === 0}" tabindex="${i ? -1 : 0}"&gt;${label}&lt;/button&gt;`).jo |
| docx | src/docx-line-spacing.ts | 26 | modal-content | 9 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-link-dialog.ts | 16 | modal-content | 4 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-paragraph-dialog.ts | 33 | modal-content | 35 | tabId; tabId; tabId; tabId; tabId; tabId; Array.from({ length: 9 }, (_, i) =&gt; `&lt;option value="${i + 1}"&gt;${i + 1} 级&lt;/option&gt;`).join(''); [['indentLeft','左缩进'],['indentRight','右缩进'],['spaceBefore','段前间距'],['spaceAfter','段后间距']].map(([key,labe |
| docx | src/docx-special-indent.ts | 26 | modal-content | 11 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-table-alignment-controls.ts | 6 | modal-content | 7 | floating ? '&lt;p role="note"&gt;当前表格使用浮动或抑制浮动定位。浮动定位优先；对齐值保存后，当前位置仍保持原浮动定位。&lt;/p&gt;' : ''; buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-table-alt-text-controls.ts | 5 | modal-content | 5 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-table-cell-margin-overrides-controls.ts | 10 | modal-content | 7 | rows ? '&lt;button type="button" data-action="row-breaks"&gt;行跨页&lt;/button&gt;&lt;p data-row-reason&gt;&lt;/p&gt;' : ''; alignment ? '&lt;button type="button" data-action="table-alignment"&gt;整表对齐&lt;/button&gt;&lt;p data-alignment-reason&gt;&lt;/p&gt;' : ''; sides.map(side =&gt; `&lt;label&gt;$ |
| docx | src/docx-table-cell-margins-controls.ts | 10 | modal-content | 3 | sides.map(side =&gt; `&lt;label&gt;${labels[side]}（pt）&lt;input data-margin="${side}" aria-label="${labels[side]}边距（pt）" type="text"&gt;${inherited.includes(side) ? '&lt;small&gt;使用来源默认值&lt;/small&gt;' : ''}&lt;/label&gt;`).join(''); buttonClasses('secondary'); buttonClass |
| docx | src/docx-table-cell-shape-controls.ts | 6 | modal-content | 6 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-table-cell-wrap-controls.ts | 5 | modal-content | 4 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-table-column-width-controls.ts | 5 | modal-content | 4 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-table-row-breaks-controls.ts | 6 | modal-content | 4 | top; 1; bottom &gt; top + 1 ? `–${bottom}` : ''; initial === null ? '&lt;p&gt;多个值：所选行的跨页设置不同，未操作时保持原值。&lt;/p&gt;' : ''; buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-table-row-breaks-controls.ts | 27 | modal-content | 2 | alignment ? '&lt;button type="button" data-action="table-alignment"&gt;整表对齐&lt;/button&gt;&lt;p data-alignment-reason&gt;&lt;/p&gt;' : '' |
| docx | src/docx-table-row-height-controls.ts | 6 | modal-content | 4 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-view.ts | 70 | modal-content | 4 | buttonClasses('secondary'); buttonClasses('primary') |
| docx | src/docx-watermark-dialog.ts | 13 | innerHTML | 19 | DOCX_WATERMARK_PRESETS.map(text =&gt; `&lt;option value="${text}"&gt;&lt;/option&gt;`).join(''); fonts.map(font =&gt; `&lt;option value="${font}"&gt;${font}&lt;/option&gt;`).join(''); DOCX_WATERMARK_SIZES.map(size =&gt; `&lt;option value="${size}"&gt;${size}&lt;/option&gt;`).join('') |
| shared | src/enhancements.ts | 163 | modal-content | 0 | options.onChartEdit ? '&lt;div class="image-preview-actions"&gt;&lt;button type="button" class="image-preview-chart-ai"&gt;AI 改图&lt;/button&gt;&lt;/div&gt;' : '' |
| shared | src/enhancements.ts | 238 | modal-content | 1 | exportFormats.map(format =&gt; `&lt;div class="export-format-row"&gt;&lt;a data-format="${format}" target="_blank" rel="noreferrer"&gt;下载 ${exportLabels[format]}&lt;/a&gt;&lt;span data-artifact-meta="${format}"&gt;&lt;/span&gt;&lt;button type="button" data-copy="${format}"&gt;复制 |
| shared | src/history.ts | 94 | innerHTML | 0 | renderDiffHtml(patch, {     outputFormat: 'side-by-side',     drawFileList: false,     matching: 'lines',   }) |
| shared | src/modal.ts | 45 | innerHTML | 0 | options.content |
| shared | src/office-ai-entry.tsx | 16 | innerHTML | 0 | renderToStaticMarkup(&lt;&gt;&lt;IconAiPanel size={28} /&gt;&lt;span&gt;AI 助手&lt;/span&gt;&lt;/&gt;) |
| shared | src/office-assistant-panel.ts | 19 | innerHTML | 0 | renderToStaticMarkup(createElement(IconAiPanel,{size:20})) |
| shared | src/office-assistant-panel.ts | 21 | innerHTML | 0 | renderToStaticMarkup(createElement(IconClose,{size:18})) |
| shared | src/office-assistant-panel.ts | 55 | innerHTML | 0 | renderToStaticMarkup(createElement(component,{size:16})) |
| shared | src/preflight.ts | 66 | modal-content | 2 | warnings.length; warnings.map((warning, index) =&gt; `&lt;li&gt;&lt;button type="button" data-preflight-target="${index}"&gt;&lt;svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width= |
| shared | src/shell.ts | 44 | innerHTML | 19 | isBinary ? ' hidden' : ''; mode === 'full'; isBinary ? `&lt;button type="button" data-action="search" aria-label="搜索和替换" hidden&gt;&lt;/button&gt;           &lt;button type="button" data-action="history" aria-label="版本历史" hidden&gt;&lt;/button&gt;           &lt;butto |
| pptx | src/slides-comments-pane.ts | 49 | innerHTML | 0 | renderToStaticMarkup(createElement(IconSidebarCollapse, { size: 15 })) |
| pptx | src/slides-comments-pane.ts | 79 | innerHTML | 0 | renderToStaticMarkup(createElement(IconComment, { size: 22 })) |
| pptx | src/slides-main.ts | 144 | innerHTML | 76 | embedded ? '' : `   &lt;header class="slides-topbar"&gt;     &lt;a class="slides-brand" href="#" aria-label="报告幻灯片"&gt;&lt;span class="brand-mark"&gt;&lt;/span&gt;&lt;span&gt;报告幻灯片&lt;/span&gt;&lt;/a&gt;     &lt;div class="slides-topbar-meta"&gt;&lt;span class="revision"&gt;&lt;/span&gt;&lt;span class= |
| pptx | src/slides-main.ts | 322 | innerHTML | 16 | GRADIENT_DIRECTIONS.map(([label], index) =&gt; `&lt;option value="${index}"&gt;${label}&lt;/option&gt;`).join('') |
| pptx | src/slides-main.ts | 1714 | innerHTML | 0 | position; 1 |
| pptx | src/slides-native-chart-gallery.ts | 52 | innerHTML | 0 | renderToStaticMarkup(createElement(ChartStyleThumb, { kind: info?.kind, style: preset.style })) |
| docx | src/vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions.ts | 917 | innerHTML | 0 | mathml |
| docx | src/vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions.ts | 5129 | innerHTML | 0 | mathml |
| docx | src/vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions.ts | 5131 | innerHTML | 0 | inlineMathML(host.getAttribute('data-omml') ?? '') |
| docx | src/vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-dom.ts | 1594 | innerHTML | 0 | wordArtSvgMarkup(img) |
| docx | src/vendor/genoffice-docs/apps/docs/src/renderer/editor/margin-annotations.ts | 169 | innerHTML | 0 | html |
| docx | src/vendor/genoffice-docs/apps/docs/src/renderer/editor/script-fonts.ts | 130 | innerHTML | 0 | html |
| docx | src/vendor/genoffice-docs/apps/docs/src/renderer/editor/table-handle.ts | 115 | innerHTML | 0 | MOVE_SVG |
| docx | src/vendor/genoffice-docs/apps/docs/src/renderer/editor/table-handle.ts | 124 | innerHTML | 0 | RESIZE_SVG |
| xlsx | src/workbook-cell-shift.ts | 79 | modal-content | 4 | CELLS_CHOICES.map(choice =&gt;         `&lt;label&gt;&lt;input type="radio" name="workbook-cells-choice" value="${choice}"&gt;&lt;span data-choice-label="${choice}"&gt;&lt;/span&gt;&lt;/label&gt;`).join('') |
| xlsx | src/workbook-fill-series.ts | 321 | modal-content | 6 | group('direction', '序列产生在', DIRECTIONS); group('type', '类型', TYPES); group('unit', '日期单位', DATE_UNITS) |
| xlsx | src/workbook-header-footer-editor.ts | 76 | modal-content | 3 | fields |
| xlsx | src/workbook-numfmt-dialog.ts | 292 | modal-content | 12 | NUMFMT_CATEGORIES.map(category =&gt;         `&lt;button type="button" role="option" data-numfmt-category="${category}"&gt;${CATEGORY_LABELS[category]}&lt;/button&gt;`).join(''); ['', ...CURRENCY_SYMBOLS].map(symbol =&gt; `&lt;option value="${symbol}"&gt;${symbol  |
| xlsx | src/workbook-print-preview.ts | 125 | modal-content | 38 | papers.map(([code, label]) =&gt; `&lt;option value=${code}&gt;${label}&lt;/option&gt;`).join('') |
| xlsx | src/workbook-ribbon.ts | 1159 | innerHTML | 0 | workbookCommandIcon('', glyph) ?? '' |
| xlsx | src/workbook-ribbon.ts | 1348 | innerHTML | 0 | icon |
| xlsx | src/workbook-sort-dialog.ts | 45 | modal-content | 4 | levels |
| xlsx | src/workbook-symbol-dialog.ts | 41 | modal-content | 7 | id |
| xlsx | src/workbook-zoom-dialog.ts | 25 | modal-content | 7 | WORKBOOK_ZOOM_PRESETS.map(value =&gt; `&lt;label&gt;&lt;input type="radio" name="workbook-zoom-choice" value="${value}"&gt;${value}%&lt;/label&gt;`).join('') |
