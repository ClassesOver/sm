# Word 第一层嵌套表文字编辑验收

2026-11-10，固定 GenOffice ref f8c17004fb730df11f0f743164ffd8b4281bb38c；本地操作协议适配，不宣称全量表格对齐。

## 行为与范围

服务端 inspect 对第一层嵌套表和简单叶格签发独立身份，绑定源文件、外层根和全部坐标，重复内容同胞也不共用身份。新 replaceNestedCellText 操作只改签发叶格的段落数组；支持多格、多段、空段、中文、emoji、XML转义和$&。文件桥接整批校验身份、hash、字段和冲突，使用原引擎局部补丁，并重新解析实际DOCX确认内容和未改XML。

前端将DOM输入岛能力绑定已核验清单，diff/replay限定paras变化及对应richParas删除。结构/格式与同根嵌套改字必须分别保存；内层输入活动时拒绝误操作外层行列或重复表头。Ctrl+A仅选择当前内层格。保存/预览入口广播原有commit事件，未离焦文字也进入草稿；非法或被guard拒绝的提交保留dirty并给出错误，不静默保存旧文字。保存锁期间不可输入。原空段fontSlots误判同时修复，全部操作合计仍遵守500条上限。

保守只读：合并、修订、包装/网格映射不可靠、含更深嵌套的格、保护文档、含tab或段内换行等控制字符的源。parser的paras不能往返w:tab/w:br，故不冒充支持。输入最多1000段、总20000 UTF16；超限来源仍可打开并只读。内层结构、合并拆分和重复标题尚未实现。

## 验证

- Bridge 真实DOCX用例由子agent分批执行：原16项、同内表多叶格/旧来源及3个超限源定向通过；helper3项和独立类型检查通过。详见 NATIVE_WORD_NESTED_TABLE_BRIDGE.md。完整bridge依赖检查有既有三处类型问题，未报告全依赖检查通过。
- 前端nested diff/replay27项、相关表格47项通过，并以真实inspect/parse模型验证两同胞映射和第二张改字replay。原操作测试发现的空段fontSlots回归已定向修复，/tmp/word-empty-font-slots-green.log 5项通过。
- 输入岛最终抽取后6项 /tmp/word-nested-input-extracted-final.log 通过，含非法输入保留、guard拒绝反馈、保存锁、段落数组及Ctrl+A；外层命令门控 /tmp/word-nested-command-gate.log 1项通过。真实PM undo/redo另见 /tmp/word-nested-undo-redo.log。
- 最终生产构建 /tmp/office-word-nested-budget-fixed-build.log exit0 (40.28s)，budget/contract同前缀exit0；render 3Z3gu3C- 709.9KiB、main CTiRKV1E 158.3KiB、table-input JY6Wgg3M 1.0KiB。首次render超710预算后，将纯段落读取/比较/坐标遍历抽为独立chunk，未提高预算。bridge最终bundle /tmp/word-nested-bridge-final-bundle.log exit0。
- 最终纯GUI /tmp/word-nested-built-smoke-final.log exit0，Chromium140，118个实际JS响应200并SHA匹配，无页面错误。两个Ctrl+A均验证焦点和选区在第二张格；草稿blur提交/刷新恢复、内层命令禁用、保持焦点公开保存、真实Python patch、下载SHA和明确revision2重开通过。第二张为['第二张最终中文😀$&','第二段','']，第一张same；before/after、非目标XML和所有非目录OPC部件字节一致。
- 最终产物 /tmp/docx-nested-built-F7Vso7/，revision-2-reopened.png 已由root人工查看。来源SHA f097d3d90b971c8ed78805510b76255b901c02c46b49ad46e925ea5f19fe3a82，下载SHA 172e2e8b2949afea430bc89730366f1fd0ef6665df2e6639aa939018c1837c9f。

HTTP context/revision/save由探针替身路由，浏览器及Python文件操作真实执行；没有据此声称生产HTTP、桌面Word或PDF验收。未重复完整测试，未提交推送，未改报告发布签发链路。全量目标继续开放。
