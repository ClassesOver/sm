from agno.agent import Agent

from .assistant import AgentInstructions

ODOO_COMMAND_ASSISTANT_ID = "odoo-command-assistant"
LEGACY_ODOO_COMMAND_ASSISTANT_IDS = frozenset({"edit-mode-assistant", "menu-navigation-assistant"})


def create_odoo_command_assistant(
    base_agent: Agent,
    instructions: AgentInstructions,
) -> Agent:
    assistant = base_agent.deep_copy(
        update={
            "id": ODOO_COMMAND_ASSISTANT_ID,
            "name": "Odoo Command Assistant",
            "role": "只操作当前请求声明且属于 Odoo 协议的页面或业务 command。",
            "instructions": instructions,
            "skills": None,
            "tools": [],
            "tool_choice": "auto",
        }
    )
    assistant.num_history_runs = None
    return assistant
