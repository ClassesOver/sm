# Word 源尺规任意缩进专项冒烟

不构建，不运行完整测试。root 冻结统一前端和 DOCX engine 后，在 frontend 目录运行：

```sh
DOCX_TEST_DIST=/path/to/frozen-static \
DOCX_TEST_ENGINE=/path/to/frozen-engine \
DOCX_EXPECTED_MANIFEST_SHA256=<冻结 manifest SHA-256> \
DOCX_TEST_OUTPUT=/tmp/sr-word-ruler-indent-20261111 \
node smoke/docx-ruler-indent-smoke.mjs
```

默认端口 4288，可用 `DOCX_TEST_PORT` 覆盖。`DOCX_RULER_CASE=readonly` 或 `editable` 可只跑对应模式。

- 使用 python-docx 创建真实 DOCX：direct left=720/firstLine=360、样式继承 left=540/hanging=180、多 run、汉字/emoji/组合字符、未知缩进属性、未改段、页眉和表格。字符缩进及 RTL 段验证只读。
- 加载真实冻结 preview，核验每份浏览器 JS 的磁盘 SHA-256；显示标尺不改正文、布局、草稿和保存状态。
- 源键盘 left→+90；真实鼠标拖动 firstLine→+90、继承段 hanging→left+90/firstLine−90，首行绝对位置不变；移动期间不写入，松开提交。只读模式另验证三标记真实鼠标不能写回。确认 Undo/Redo、localStorage 草稿持久化和刷新恢复；选区改变后等待异步标尺值／来源锁更新。
- 授权、修订登记响应由浏览器 route fixture 提供；保存捕获实际 operation，交给真实 Python `patch_docx` 和冻结 Node bridge。两个段应合并成两个 `setParagraphRulerIndent`，不能用模拟字节替代 patch。
- 独立 ZIP/lxml 验证 direct left=810/firstLine=450，继承段 left=630/hanging=270；保留未知属性、全部 run、其余正文及所有非正文部件。仅允许 core modified/revision、ZIP 目录项规范化及既有 writer 对目标 w:t 添加 xml:space="preserve"；原有值不得丢失或被替换。
- 验收失败响应仍下载真实 Word，校验文件身份并重开修订 2 校验两段标尺值。原始 DOCX 文件、冻结 manifest 和 bridge 在运行前后身份不变。

证据：`result.json`、原始/下载 DOCX、只读/草稿恢复/重开截图。失败保留 `failure.html` 和 `failure.png`。脚本退出成功才代表浏览器流程通过；`node --check` 仅验证语法。
