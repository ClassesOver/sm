# 已有单选组复制设计与计划（2026-11-14）

目标：来源同页安全互斥单选组按整组复制/重复及同文档跨页粘贴，保留原字段 V/DV/Ff/Opt、按钮 AS/AP、布局、层级与引用，后续填写副本不影响原组。

方案：复用 createFormField.copyFrom、原来源批次预检与私有辅助图深复制，扩展为多 Widget。以前端投影重建会丢外观/默认值，逐个复制按钮会破坏组语义，因此以既有 radioRequired 安全检查为基础，服务器从真实字段读取整组；源锚点为首个 Widget，radioWidgets 仅声明整组统一平移和目标页，不能改选项、选择或尺寸。共享纯布局验证器供前后端使用。

范围：同页2–64按钮的安全互斥组，默认UserUnit/直角旋转，未保护未签名AcroForm。源跨页组、非互斥/复杂/共享AP/异常默认状态不开放；跨文档与系统剪贴板不开放。点击任意成员复制的是完整字段组，中文卡片/菜单明确提示；副本仅整组平移/删除/再复制，保存后再编辑。

- [x] RED 引擎：真实整组保真、跨页、未选中、源身份/布局/选项伪造零写、复杂来源与复核告警保留字节。
- [x] 最小引擎实现：form-copy-safety、form-source-copy、创建schema、census；新增纯form-copy-radio布局验证器。
- [x] RED 前端：任意成员复制整组、跨页布局、重复复制与未知/部分模板拒绝、整组移动一次提交/删除及中文提示。
- [x] 前端实现：clipboard/create/design-canvas 局部接线，沿用NativeDraft和中文入口。
- [x] 仅新增/受影响专项、真实服务preview/save/download及中文Chromium公共菜单/键盘/Undo/恢复/实际预览与pypdf回读。
- [x] 独立复核、验收与缺口清单更新；不修改共享构建、不提交推送、不重复完整套件。

结果见 NATIVE_PDF_SOURCE_RADIO_COPY_ACCEPTANCE_20261114.md。
