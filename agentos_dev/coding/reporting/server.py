"""供 Uvicorn workers/reload 导入的 Reporting AgentOS 应用。"""

from .agentos import create_agentos

agent_os = create_agentos()
app = agent_os.get_app()
