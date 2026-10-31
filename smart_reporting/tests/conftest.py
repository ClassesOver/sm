"""应用级测试在模块导入时构建完整 app；未提供 .env 的环境（CI、云端容器）使用测试默认值。

只用 setdefault：真实环境或 .env 已配置的值优先，不覆盖。
"""

import os

os.environ.setdefault("AGENT_WORKSPACE_HMAC_SECRET", "test-only-workspace-secret-0123456789")
os.environ.setdefault("AGENT_REPORT_PUBLIC_BASE_URL", "https://reports.test.invalid")
