"""Office 复杂场景编码任务：基于 Agno CodexAgent 在独立工作目录中编写并运行代码。

简单交互（改写、阅读问答、审阅、表单）继续使用带函数工具的 agno Agent；只有需要
自行编写和执行代码的任务（数据计算、Matplotlib 出图、批量处理）走这里。

边界：
- 每个任务使用调用方提供的独立工作目录，沙箱为 workspace-write，不批准额外权限；
- 模型执行的命令只继承 Codex core 环境变量（shell_environment_policy），业务凭据不可见；
- 产物只是工作目录中的文件，由调用方登记身份后再通过 Office 写入工具进入文档，
  Codex 不直接修改用户文件。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agno.agents.codex import CodexAgent

if TYPE_CHECKING:
    from ..runtime.settings import AgentSettings

OFFICE_CODEX_PROVIDER = "office"

OFFICE_CODEX_BASE_INSTRUCTIONS = (
    "你是 Office 文档的数据处理与制图助手。只在当前工作目录内读写文件，按需编写并运行 Python 脚本完成任务。"
    "图表只使用 Matplotlib 生成 PNG/JPEG 静态图，不生成交互图。"
    "数字必须来自工作目录中的输入文件或脚本计算结果，不得编造；无法完成时在结果中说明原因。"
    "最终只返回满足输出 schema 的结果。"
)


class OfficeCodexUnavailable(RuntimeError):
    """Office 编码任务未开启或配置不完整。"""


def office_codex_settings(settings: AgentSettings) -> tuple[str, str]:
    """返回 (base_url, model)；留空项沿用通用模型配置。"""

    base_url = settings.office_codex_base_url or settings.openai_base_url
    model = settings.office_codex_model or settings.model_standard_id
    return base_url, model


def create_office_codex_agent(
    settings: AgentSettings,
    *,
    cwd: Path,
    output_schema: Any,
    name: str = "office-codex",
    instructions: str | None = None,
) -> CodexAgent:
    """创建单次 Office 编码任务使用的 CodexAgent。"""

    if not settings.office_codex_enabled:
        raise OfficeCodexUnavailable("Office 编码任务尚未开启。")
    base_url, model = office_codex_settings(settings)
    if not base_url or not model:
        raise OfficeCodexUnavailable("Office 编码任务缺少模型接口或模型配置。")
    if not cwd.is_dir():
        raise OfficeCodexUnavailable("Office 编码任务工作目录不存在。")
    interpreter_bin = str(Path(sys.executable).parent)
    search_path = os.pathsep.join([interpreter_bin, os.environ.get("PATH", "")])
    return CodexAgent(
        name=name,
        model=model,
        model_provider=OFFICE_CODEX_PROVIDER,
        config={
            "model_providers": {
                OFFICE_CODEX_PROVIDER: {
                    "name": OFFICE_CODEX_PROVIDER,
                    "base_url": base_url,
                    "env_key": "OPENAI_API_KEY",
                    "wire_api": "responses",
                }
            },
            # 默认 workspace-write 还允许写 /tmp 与 $TMPDIR；Office 任务只允许写自身工作目录。
            # 沙箱只经配置声明：作为启动参数传入时会按默认规则重建策略，忽略下面的排除项。
            "sandbox_mode": "workspace-write",
            "sandbox_workspace_write": {
                "exclude_tmpdir_env_var": True,
                "exclude_slash_tmp": True,
                "network_access": False,
            },
            # 模型执行的命令只拿到基础变量，并使用服务端同一 Python 环境（含 Matplotlib）。
            "shell_environment_policy": {
                "inherit": "core",
                "set": {"MPLBACKEND": "Agg", "PATH": search_path},
            },
        },
        env={"OPENAI_API_KEY": settings.openai_api_key},
        cwd=str(cwd),
        approval_policy="never",
        ephemeral=True,
        base_instructions=OFFICE_CODEX_BASE_INSTRUCTIONS,
        instructions=instructions,
        output_schema=output_schema,
        retries=0,
    )


__all__ = [
    "OFFICE_CODEX_BASE_INSTRUCTIONS",
    "OfficeCodexUnavailable",
    "create_office_codex_agent",
    "office_codex_settings",
]
