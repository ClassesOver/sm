# Word 审阅预设、段落比较与受支持正文范围

日期：2026-11-14。固定源 genspark-ai/genoffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本记录只关闭明确审阅子能力，完整 Word 对齐仍在进行。

## 实现

- Editor 与22语言翻译接入既有 Native AI/Agno 候选链。选中部分文字按整段／整格授权；没有范围选区时要求用户确认整篇正文的实际目标数。未保存／复杂／只读对象或超过100目标拒绝，不扩大或静默截断范围。无自动生成，候选须显式采纳和保存。
- Native AI 在生成、返回、采纳时冻结指令、目标和完整草稿操作；输入同步后重新核验选区/锁。关闭、换选区、改稿不接受旧回包。
- Compare 复用源 `editor/compare.ts`，浏览器选择另一份DOCX，显示当前未保存正文的段落新增／删除／修改。源本身只做文本比较，不生成合并修订；表格／对象沿用来源预览文本。8MiB文件、2,000,000 LCS单元容量保护；换稿/关窗/再次选文件丢弃异步结果。
- 既有来源绑定的简单正文插入／删除修订支持当前／下一条、全部、当前标记筛选、选区、指定作者，整批单事务、原生UndoRedo。并未放开复杂修订、移动、属性修订或页眉页脚等story。

原样新增 `translate-langs.ts` 与 `editor/compare.ts` 的SOURCE/LOCAL摘要分开登记，源文件未改。宿主适配位于vendor之外。

## 验证

- `/tmp/word-genoffice-related-final.log`：8个相关前端文件109项通过；既有JSDOM Canvas getContext warning保留。新入口、候选过期、输入同步选区/锁、范围操作均有RED→GREEN记录。
- `/tmp/word-genoffice-backend-related.log`：既有Word AI与正文修订host41项通过，保留imghdr弃用warning。
- 审查指出输入同步后的状态复查窗口，已补2条失败测试后修复。额外补Compare实际LCS容量分支测试。
- `/tmp/word-genoffice-build-final` 完整保存链：证据 `/tmp/word-review-presets-20261114-font-fixed`；真实FastAPI授权／cookie／workspace／NativePublication、实际Agno，模型为ScriptedModel、修订与授权仓储为作用域内存夹具，不冒称生产数据库或真实provider质量验收。
- 一次候选生成、一次采纳、一次保存修订1→2；下载38388字节，SHA256 `abe775d71447bf65bcb5357ad4ea3b9a240e56573f7212e64781268cd0f3eea1`。python-docx/ZIP独立回读两段译文与页眉页脚，仅`word/document.xml`和正常更新`docProps/core.xml`变化。182实际JS/CSS响应与冻结磁盘匹配，浏览器错误0。
- 审查修复后的`/tmp/word-genoffice-build-reviewed`另做0save/0模型调用续验：`/tmp/word-review-presets-20261114-reviewed-reimport`，重新导入上次真实下载、实际文字画布和Compare390px可达，182资源身份匹配。此层是下载重新导入，不冒充再次运行完整生成/采纳/保存。
- 两冻结构建前tsc通过；原487 JS块预算检查通过，未提高预算。后续并行功能族源码不属于上述冻结验收。

## 环境与剩余边界

默认系统字体预检`/tmp/word-review-presets-font-default.json`显示6个默认/别名字体宽度和像素为0，DejaVu正对照宽182.01/1062像素。问题与既有`NATIVE_XLSX_CANVAS_FONT_ENVIRONMENT.md`一致；完整链显式使用已有`smoke/canvas-fontconfig.conf`，不改产品字体或系统配置。字体配置身份和7字体实际像素预检保存在证据。

保存仍诚实返回业务`native_source_review_pending`告警，并签发已核验文件下载。真实provider翻译/校对质量、复杂story修订、AI批注整族、气泡与高级修订选项不由本批关闭。未推送、合并或部署，未重复完整测试。
