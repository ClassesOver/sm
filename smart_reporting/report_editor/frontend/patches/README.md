# 3D 组件补丁

`three-render-objects+1.43.0.patch` 修复当前 Vite 使用的 ESM 入口中的快速点击拾取时序。
原实现每50ms更新悬停命中，pointerup 延后一帧发出点击；快速轻触可能在这50ms内结束，
从而把节点点击发给旧的空白命中。补丁在非拖动的 pointerup 后清除拾取节流时间，
让下一渲染帧在点击回调前刷新命中；拖动抑制逻辑和组件相机控制保持原样。

`npm install` / `npm ci` 的 postinstall 使用成熟工具 patch-package 应用补丁，失败时终止。
升级组件时重新验证；上游修复后删除补丁及不再需要的 patch-package。
此补丁只修改当前实际消费的 ESM 入口，不声称修复组件的其他发布格式。

回归：启动 fixture 服务后执行 `node smoke/evidence-3d-touch-fixture.mjs`。
脚本清空鼠标悬停，再用 Playwright 快速触摸点击实际球体；不得用延长按住时间掩盖问题。
现有 `node smoke/evidence-3d-fixture.mjs` 覆盖鼠标点击、双击、旋转/滚轮和相机操作。
