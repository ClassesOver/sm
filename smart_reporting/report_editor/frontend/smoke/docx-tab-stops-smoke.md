# Word 标尺制表位真实浏览器专项

在 frontend 目录使用已冻结、已构建的产物运行，不在脚本内构建或运行完整测试：

```sh
DOCX_TEST_DIST=/path/to/frozen-static \
DOCX_TEST_ENGINE=/path/to/frozen-engine \
DOCX_EXPECTED_MANIFEST_SHA256=<64位SHA-256> \
DOCX_TEST_OUTPUT=/tmp/word-tab-stops-evidence \
node smoke/docx-tab-stops-smoke.mjs
```

默认依次验证 readonly、editable；`DOCX_TABS_CASE=readonly`、`editable` 可单独执行。`DOCX_TABS_CASE=zoom` 仅补验110%只读／100%恢复，0保存。默认端口4293，可用 `DOCX_TEST_PORT` 覆盖。

夹具含真实 w:tab、多run、直接制表位及引导符、样式继承制表位、未知制表位属性、RTL、Unicode、表格、页眉。授权和修订HTTP由fixture提供，文件解析／写回由真实Python和冻结Node执行。

覆盖类型循环、键盘微调、UndoRedo、鼠标拖动仅松开提交、点击新增、继承位拖出删除后的clear、草稿恢复、未知来源拒绝、验收失败仍下载、独立ZIP/XML回读、明确修订2重开。核对实际JS响应、manifest／bridge及原始文件身份。

证据包含result.json、各模式result、原始／下载DOCX和截图。失败保留failure.html／failure.png；语法检查不能替代浏览器执行。
