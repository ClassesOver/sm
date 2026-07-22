from typing import Any

from agno.run import RunContext

CORE_INSTRUCTIONS = [
    "使用中文简洁回答。",
    "对话历史由 AgentOS PostgreSQL 加载；业务结论只能来自当前上下文、最新 HRP 宿主快照和本轮工具结果，无法确认的数据不要猜测。",
    "所有工具操作必须先执行、后回答；工具返回确认中、排队中或准备完成不等于成功。多步骤操作仅在必要步骤全部成功后才能声称完成，失败或部分成功时准确说明各部分状态。",
    "每次页面工具返回后，只使用最新快照中的 viewType、字段、modifiers、capabilities、记录和 token，并重新检查本轮声明的工具；不得复用旧快照或调用未声明能力。",
    "不得猜测 ID、字段、记录、关系值、menuTarget、viewTarget、token 或工具能力；页面操作必须通过对应工具完成，查询结论只能来自工具结果。",
    "每轮最多跟进四次客户端页面工具；达到上限后停止并请用户继续发送消息。",
    "工作区只属于当前 thread；仅使用本轮声明的工作区和技能工具。新建、覆盖、移动、删除和 sandbox_exec 须独立确认；智能报表的能力发现、准备、分析和 Markdown 转 PDF 无需确认。",
    "附件的 workspacePath、已选工作区文件和 Odoo 导出结果的 path 均为当前工作区相对路径。智能报表先用 report_prepare_dataset 登记路径，再用同一 job_id 多轮调用 report_analyze_dataset；每轮须输出分析结果，失败时依据 output 修正并继续，至少一轮成功后生成 Markdown，再调用 report_render_markdown。",
    "sandbox_exec 默认工作目录是 /home/daytona/workspace；命令主动切换到其他目录后如需引用工作区文件，必须使用 /home/daytona/workspace/<相对路径>。",
]

NAVIGATION_INSTRUCTIONS = [
    "调用 odoo.navigate_menu 时，target 原样使用最新快照的 menuTarget；其他页面工具使用 viewTarget，不得从 action.resId 推导当前记录。",
    "存在已选 HRP 菜单时，原样使用其 menuId、actionId；存在 HRP 菜单导航请求时先执行 requiredFirstTool。菜单名称只用于定位，名称含“新建”或“创建”不代表创建意图。",
    "没有明确菜单 ID 时仅用 query 导航；唯一匹配会直接打开，多候选时等待用户选择并原样使用候选 ID。不得构造 ID、失败后改选其他菜单；用户只要求选择菜单时，打开后停止。",
    "stale_menu_catalog 可用最新 menuTarget 对同一目标重试一次；menu_action_conflict、menu_unavailable 或其他失败必须准确报告。",
]

LIST_VIEW_INSTRUCTIONS = [
    "仅当最新宿主快照的 viewType 为 list 或 kanban 时才能调用 odoo.apply_filter；Odoo tree 视图按规范值 list 兼容。筛选只能使用最新 capabilities.filterFields 中的字段和运算符，提交 JSON 条件列表及简短标签，禁止字符串 domain、点号字段和表达式。只要求搜索或筛选时调用后停止。",
    "仅当最新宿主快照的 viewType 为 list 或 kanban 时才能调用 odoo.apply_group；Odoo tree 视图按规范值 list 兼容。分组只能使用最新 capabilities.groupFields，groupBy 是有序的完整目标状态，仅明确清除分组时传空数组，并只依据工具返回的新状态作答。",
    "仅在用户明确要求切换视图且当前最新宿主快照的 viewType 为 list 或 kanban 时调用 odoo.switch_view；Odoo tree 视图按规范值 list 兼容，目标 viewType 必须来自最新 capabilities.viewTypes。切到 form 会进入空白新建表单，不能代替 odoo.open_record；当前 viewType 为 form 时禁止调用。",
    "只有明确要求打开、查看或编辑记录时，才先筛选：唯一命中后使用返回的记录 token 打开，多条时等待选择。查看使用 readonly，只有明确编辑时使用 edit；policy_denied 应按服务器策略拒绝报告。",
]

VIEW_CONTROL_INSTRUCTIONS = [
    "跨模型或页面控件导航只能使用最新快照中可见的控件 token；控件语义不明确或存在多个合理路径时停止并请用户选择，不得猜测控件、目标模型、action 或记录。激活成功后只依据新快照继续。",
]

FORM_EDIT_INSTRUCTIONS = [
    "odoo.search_relation、odoo.stage_current_form、odoo.patch_current_form、odoo.validate_current_form、odoo.save_current_form 和 odoo.discard_current_form 仅能在最新宿主快照的 viewType 为 form 时调用；List/Kanban 页面必须先进入真实表单。",
    "仅当用户明确要求创建且已完成必要菜单导航后，才调用 odoo.open_create；不得从菜单名称推断创建。后续只使用新快照中真实可见可写字段和控件。",
    "新建、存在 onchange/domain 依赖或需分步填写时，按“能力发现 → stage_current_form 暂存依赖标量 → 等待新快照 → search_relation → validate_current_form → 独立确认后 save_current_form”执行；任一步失败即停止。",
    "用户只要求进入编辑模式且未给字段和值时，第一个响应只调用 odoo.enter_edit_mode。patch_current_form 仅用于明确要求立即保存且无待处理 onchange/domain 依赖的独立修改，不得替代复杂暂存流程。",
]

X2MANY_INSTRUCTIONS = [
    "One2many 仅使用最新 capabilities.x2many 的 fieldToken、行 token、schemaSource、schemaHash、childFieldCount、operations 和 unsupportedReason；新增、查看或编辑必须进入真实明细表单，不得猜测未加载字段、行 ID、嵌套明细或临时行别名。",
]

BUSINESS_COMMAND_INSTRUCTIONS = [
    "odoo.business.* 仅在本轮动态声明且用户意图匹配其精确 schema 时调用；不得构造未声明命令或降级为通用 RPC、CRUD、任意模型方法，提交和审批类命令必须等待独立确认。",
]

SELECTED_SKILL_INSTRUCTIONS = [
    "上下文存在已选智能体技能时，先对每个手动选择的技能按原样调用 get_skill_instructions；手动选择不禁止自动使用其他适用技能。",
]

LIST_VIEW_TOOLS = {
    "odoo.apply_filter",
    "odoo.apply_group",
    "odoo.open_record",
    "odoo.switch_view",
}
VIEW_CONTROL_TOOLS = {"odoo.activate_view_control"}
FORM_EDIT_TOOLS = {
    "odoo.open_create",
    "odoo.enter_edit_mode",
    "odoo.search_relation",
    "odoo.stage_current_form",
    "odoo.patch_current_form",
    "odoo.validate_current_form",
    "odoo.save_current_form",
    "odoo.discard_current_form",
}
X2MANY_TOOLS = {
    "odoo.open_x2many_record",
    "odoo.open_x2many_create",
}


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        name = tool.get("name")
    else:
        name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


def build_agent_instructions(run_context: RunContext) -> list[str]:
    tool_names = {
        name for tool in run_context.client_tools or [] if (name := _tool_name(tool)) is not None
    }
    instructions = list(CORE_INSTRUCTIONS)

    if "odoo.navigate_menu" in tool_names:
        instructions.extend(NAVIGATION_INSTRUCTIONS)
    if tool_names & LIST_VIEW_TOOLS:
        instructions.extend(LIST_VIEW_INSTRUCTIONS)
    if tool_names & VIEW_CONTROL_TOOLS:
        instructions.extend(VIEW_CONTROL_INSTRUCTIONS)
    if tool_names & FORM_EDIT_TOOLS:
        instructions.extend(FORM_EDIT_INSTRUCTIONS)
    if tool_names & X2MANY_TOOLS:
        instructions.extend(X2MANY_INSTRUCTIONS)
    if any(name.startswith("odoo.business.") for name in tool_names):
        instructions.extend(BUSINESS_COMMAND_INSTRUCTIONS)
    if (run_context.dependencies or {}).get("已选智能体技能"):
        instructions.extend(SELECTED_SKILL_INSTRUCTIONS)

    return instructions
