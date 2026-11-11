# Word Home 全选源入口调查

固定源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，`apps/docs/src/renderer/components/Ribbon.tsx:4534–4544`。

源 Home 是直接“全选”按钮，并非“选择”下拉菜单。它仅由 `!hasDoc` 禁用；只读文档仍能选择全文。命令是 `ed.chain().focus().selectAll().run()`，使用 `IconSelectAll` 和 `ribbonSelectAll` / `ribbonSelectAllTip`。本地图标和中文词条已在固定源 vendor 中。

本地 `docx-home-source.tsx` 的编辑组仍为永久禁用的 `select` / “选择”占位。`docx-ribbon.ts` 未传全选回调。基础 Tiptap 已有 `selectAll` 命令，无需增加原生文件操作、后端或自制选择算法。

真实渲染 RED：`frontend/src/docx-select-all.test.ts` 创建真实 Editor 和 Home Ribbon，分别加载可编辑与只读双段正文，断言按钮可用、按钮名称“全选”、点击产生 AllSelection 且文档 JSON 不变。2026-11-10 首次两项均在 `button.disabled === true` 失败，日志 `/tmp/word-select-all-red.log`。该失败来自实际入口未接，不是快照或源码字符串检查。

最小实现：Home Props 新增 `onSelectAll`；直接按钮复用源图标、全选名称和提示，未提供回调时禁用。Ribbon 在 editor 未销毁时传入源 `focus().selectAll().run()`，不以可编辑性限制读取选择。无需改变 docx-main 或写回协议。两项真实 Editor/Ribbon 测试 RED→GREEN，`/tmp/word-select-all-green.log`，点击后产生全文 AllSelection，文档 JSON 不变。

定向dev GUI入口 `smoke/docx-select-all-gui-smoke.mjs`，默认可编辑，`DOCX_SELECT_READONLY=1` 独立验证只读。两场景均实际点击源Home“全选”，得到 `from:0,to:24,size:24`，正文JSON和NativeDraft对应localStorage前后相同、保存按钮状态前后相同、零保存请求、`pageErrors=[]`。日志 `/tmp/word-select-all-gui-final.log`、`/tmp/word-select-all-readonly-gui-final.log`。首次可编辑探针错误假定零修改保存按钮必须禁用而失败（`/tmp/word-select-all-gui.log`）；修为比较前后状态，无产品行为改动。使用真实Tiptap和Chromium，身份/文件HTTP为替身，未声称生产HTTP验收；最终统一构建及built验证待root。

生产仅改 `docx-home-source.tsx` 的回调/按钮和 `docx-ribbon.ts` 的源命令回调，未build/commit/push。

最终静态：editable全选/tmp/word-select-all-built-root.log与readonly全选/tmp/word-select-all-readonly-final-built.log均exit0，真实按钮选择0..24、正文JSON/草稿不变、saveRequests=0，pageErrors=[]；静态JS200/SHA由smoke验证。选择事务不受只读编辑权限禁用，与固定源!hasDoc一致。HF源三入口与此项独立，未称完成。
