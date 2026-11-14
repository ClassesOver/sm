"""已核对读取链路的配置清单；不枚举进程环境，也不动态改写环境。"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlsplit

from ..runtime.settings import AgentSettings


@dataclass(frozen=True)
class ConfigurationItem:
    key: str
    attribute: str
    label: str
    category: str
    value_type: Literal["text", "integer", "number", "boolean", "list"] = "text"
    activation: Literal["restart", "deployment", "preferences"] = "restart"
    sensitive: bool = False
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    choices: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    nullable: bool = False
    dependencies: tuple[str, ...] = ()


def _item(key, attribute, label, category="报告运行", **kwargs):
    return ConfigurationItem(key, attribute, label, category, **kwargs)


def _integer(key, attribute, label, category="报告运行", *, maximum=None, unit=None, **kwargs):
    return _item(key, attribute, label, category, value_type="integer", minimum=1,
        maximum=maximum, unit=unit, **kwargs)


def _flag(key, attribute, label, category="报告运行", **kwargs):
    return _item(key, attribute, label, category, value_type="boolean", **kwargs)


# attribute 对应实际启动后的 AgentSettings；不从 os.environ 重读值。
CONFIGURATION_CATALOG = (
    _item("AGENT_MODEL_FAST", "model_fast_id", "快速模型", "模型与服务"),
    _item("AGENT_MODEL_STANDARD", "model_standard_id", "标准模型", "模型与服务"),
    _item("AGENT_MODEL_STRONG", "model_strong_id", "强模型", "模型与服务"),
    _integer("AGENT_MODEL_TIMEOUT_SECONDS", "model_timeout_seconds", "模型请求超时", "模型与服务", maximum=3600, unit="秒"),
    _flag("AGENT_MODEL_VLLM_REASONING", "model_vllm_reasoning", "vLLM 推理请求", "模型与服务"),
    _flag("AGENT_MODEL_VLLM_THINKING_BUDGET", "model_vllm_thinking_budget", "vLLM 思考预算请求", "模型与服务"),
    _flag("AGENT_MODEL_LITELLM_PROXY", "model_litellm_proxy", "LiteLLM 代理", "模型与服务"),
    _item("OPENAI_BASE_URL", "openai_base_url", "兼容模型服务地址", "模型与服务"),
    _item("OPENAI_API_KEY", "openai_api_key", "模型服务凭据", "模型与服务", sensitive=True),
    _item("AGENT_MODEL_FAST_STRUCTURED_MODE", "model_fast_structured_mode", "快速模型结构化输出", "模型与服务", choices=("json_object", "json_schema")),
    _item("AGENT_MODEL_STANDARD_STRUCTURED_MODE", "model_standard_structured_mode", "标准模型结构化输出", "模型与服务", choices=("json_object", "json_schema")),
    _item("AGENT_MODEL_STRONG_STRUCTURED_MODE", "model_strong_structured_mode", "强模型结构化输出", "模型与服务", choices=("json_object", "json_schema")),
    _flag("AGENT_MODEL_STRUCTURED_STRICT", "model_structured_strict", "严格结构化输出", "模型与服务"),
    _flag("AGENT_ENABLE_TOOL_RESULT_COMPRESSION", "enable_tool_result_compression", "工具结果压缩"),
    _flag("AGENT_ENABLE_SESSION_SUMMARIES", "enable_session_summaries", "会话摘要"),
    _flag("AGENT_REPORT_CODING_ENABLE_THINKING", "report_phase_enable_thinking", "分析阶段思考"),
    _item("AGENT_REPORT_CODING_TEMPERATURE", "report_phase_temperature", "分析温度", value_type="number", minimum=0, maximum=2),
    _item("AGENT_REPORT_CODING_REASONING_EFFORT", "report_phase_reasoning_effort", "分析推理强度", choices=("low", "high", "max")),
    _integer("AGENT_REPORT_CODING_THINKING_BUDGET", "report_phase_thinking_budget", "分析思考预算", maximum=131072, unit="token"),
    _flag("AGENT_REPORT_ENABLE_THINKING", "report_enable_thinking", "报告规划思考"),
    _item("AGENT_REPORT_PLANNER_REASONING_EFFORT", "report_planner_reasoning_effort", "规划推理强度", choices=("low", "high", "max")),
    _integer("AGENT_REPORT_PLANNER_THINKING_BUDGET", "report_planner_thinking_budget", "规划思考预算", maximum=131072, unit="token"),
    _flag("AGENT_REPORT_ENABLE_VISION", "report_enable_vision", "视觉审查"),
    _item("AGENT_REPORT_VISION_MODEL", "report_vision_model", "视觉审查模型", "模型与服务", dependencies=("AGENT_REPORT_ENABLE_VISION",)),
    _integer("AGENT_REPORT_CONTEXT_TOKEN_BUDGET", "report_context_token_budget", "上下文预算", unit="token"),
    _integer("AGENT_REPORT_OUTPUT_TOKEN_RESERVE", "report_output_token_reserve", "输出预留预算", unit="token", dependencies=("AGENT_REPORT_CONTEXT_TOKEN_BUDGET",)),
    _integer("AGENT_REPORT_ANALYSIS_CONCURRENCY", "report_analysis_concurrency", "分析并发上限", maximum=5, unit="项", dependencies=("AGENT_REPORT_CODING_EXECUTION_MODE",)),
    _integer("AGENT_REPORT_SECTION_CONCURRENCY", "report_section_concurrency", "章节并发上限", maximum=5, unit="项"),
    _item("AGENT_REPORT_CODING_EXECUTION_MODE", "reporting_execution_mode", "分析执行方式", choices=("sequential", "parallel")),
    _flag("AGENT_REPORT_SECTION_WHOLE_GENERATION", "report_section_whole_generation", "整章生成"),
    _integer("AGENT_REPORT_VISUALIZATION_SECTION_DEADLINE_SECONDS", "report_visualization_section_deadline_seconds", "单章可视化时限", maximum=7200, unit="秒"),
    _integer("AGENT_REPORT_VISUALIZATION_TOTAL_DEADLINE_SECONDS", "report_visualization_total_deadline_seconds", "全报告可视化时限", maximum=14400, unit="秒"),
    _flag("AGENT_REPORT_STANDARD_SUPPLEMENTAL_ENABLED", "report_standard_supplemental_enabled", "标准补充分析"),
    _flag("AGENT_REPORT_LINEAGE_REGISTRATION_ENABLED", "report_lineage_registration_enabled", "追溯登记"),
    _flag("AGENT_REPORT_LINEAGE_PANEL_ENABLED", "report_lineage_panel_enabled", "追溯面板", "编辑与导出"),
    _flag("AGENT_REPORT_LINEAGE_DOWNLOAD_ENABLED", "report_lineage_download_enabled", "追溯下载", "编辑与导出"),
    _flag("AGENT_REPORT_LINEAGE_DRILLDOWN_ENABLED", "report_lineage_drilldown_enabled", "追溯下钻", "编辑与导出"),
    _flag("AGENT_REPORT_LINEAGE_EXPORT_SOURCES_ENABLED", "report_lineage_export_sources_enabled", "导出来源附录", "编辑与导出"),
    _integer("AGENT_REPORT_EDITOR_EXPORT_TIMEOUT_SECONDS", "report_editor_export_timeout_seconds", "编辑器导出超时", "编辑与导出", maximum=3600, unit="秒"),
    *(_flag(f"AGENT_REPORT_EDITOR_{name}_ENABLED", attribute, label, "编辑与导出",
        aliases=(f"AGENT_NATIVE_{name}_ENABLED",)) for name, attribute, label in (
        ("DOCX", "native_docx_enabled", "Word 原生编辑"), ("PDF", "native_pdf_enabled", "PDF 原生编辑"),
        ("AI", "native_ai_enabled", "原生 AI 编辑"), ("PDF_TEXT", "native_pdf_text_enabled", "PDF 文本编辑"),
        ("UPLOAD", "native_upload_enabled", "原生文件上传"))),
    _flag("AGENT_REPORT_EDITOR_CHART_AI_ENABLED", "report_editor_chart_ai_enabled", "AI 改图", "编辑与导出"),
    _integer("AGENT_REPORT_EDITOR_CHART_AI_HOURLY_LIMIT", "report_editor_chart_ai_hourly_limit", "每小时改图上限", "编辑与导出", maximum=1000, unit="次"),
    _integer("AGENT_REPORT_EDITOR_CHART_AI_TIMEOUT_SECONDS", "report_editor_chart_ai_timeout_seconds", "单次改图超时", "编辑与导出", maximum=900, unit="秒"),
    _flag("AGENT_REPORT_EDITOR_TABLE_AI_ENABLED", "report_editor_table_ai_enabled", "AI 改表", "编辑与导出"),
    _integer("AGENT_REPORT_EDITOR_TABLE_AI_HOURLY_LIMIT", "report_editor_table_ai_hourly_limit", "每小时改表上限", "编辑与导出", maximum=1000, unit="次"),
    _integer("AGENT_REPORT_EDITOR_TABLE_AI_TIMEOUT_SECONDS", "report_editor_table_ai_timeout_seconds", "单次改表超时", "编辑与导出", maximum=900, unit="秒"),
    _item("AGENT_REPORT_SLIDES_IMAGE_MODEL", "report_slides_image_model", "幻灯片图像模型", "模型与服务"),
    _item("AGENT_REPORT_COMPLETION_TEMPLATE", "report_completion_template", "完成消息模板", "编辑与导出", nullable=True),
    _item("AGENT_REPORT_METADATA_URL", "report_metadata_url", "业务元数据服务地址", "模型与服务", nullable=True),
    _item("AGENT_REPORT_METADATA_TOKEN", "report_metadata_token", "元数据服务凭据", "模型与服务", sensitive=True),
    _item("AGENT_REPORT_PUBLIC_BASE_URL", "report_public_base_url", "报告公开地址", "部署与启动", activation="deployment", nullable=True),
    _flag("AGENT_DEBUG", "debug", "调试日志", "日志与诊断"),
    _flag("AGENT_TRACING_ENABLED", "tracing_enabled", "调用追踪", "日志与诊断"),
    _flag("AGENT_OS_ACCESS_LOG", "access_log", "访问日志", "日志与诊断"),
    _item("AGENT_LOG_FILE", "log_file_path", "日志文件路径", "日志与诊断", nullable=True),
    _integer("AGENT_LOG_FILE_MAX_BYTES", "log_file_max_bytes", "日志轮转大小", "日志与诊断", unit="字节"),
    _integer("AGENT_LOG_FILE_BACKUP_COUNT", "log_file_backup_count", "日志备份数量", "日志与诊断", unit="份"),
    _item("AGENT_ENV_FILE", "env_file", "部署环境文件", "部署与启动", activation="deployment"),
    _item("AGENT_OS_HOST", "host", "监听地址", "部署与启动", activation="deployment"),
    _integer("AGENT_OS_PORT", "port", "监听端口", "部署与启动", maximum=65535, activation="deployment"),
    _integer("AGENT_OS_WORKERS", "workers", "工作进程数", "部署与启动", maximum=1, activation="deployment"),
    _flag("AGENT_OS_RELOAD", "reload", "开发自动重载", "部署与启动", activation="deployment"),
    _item("AGENTOS_CORS_ORIGINS", "cors_allowed_origins", "允许的跨域来源", "部署与启动", value_type="list", activation="deployment"),
    _item("AGENT_REPORTING_MCP_ALLOWED_HOSTS", "reporting_mcp_allowed_hosts", "MCP 允许主机", "部署与启动", value_type="list", activation="deployment"),
    _item("AGENT_DB_URL", "database_url", "系统数据库连接", "部署与启动", sensitive=True, activation="deployment", aliases=("DATABASE_URL",)),
    _item("AGENT_WORKSPACE_HMAC_SECRET", "workspace_hmac_secret", "工作区签名密钥", "部署与启动", sensitive=True, activation="deployment"),
    _item("AGENT_SKILLS_DIR", "skills_dir", "技能目录", "部署与启动", nullable=True, activation="deployment"),
    _item("AGENT_REPORT_DATA_SOURCES_DIR", "report_data_sources_dir", "数据源兼容目录", "部署与启动", nullable=True, activation="deployment"),
    _item("REPORTING_HOST_WORKSPACE_ROOT", "reporting_host_workspace_root", "报告宿主工作区", "部署与启动", activation="deployment"),
    _item("AGENT_REPORT_EDITOR_STATIC_DIR", "report_editor_static_dir", "编辑器静态资源目录", "部署与启动", nullable=True, activation="deployment"),
    _item("AGENT_REPORT_CONFIGURATION_MODE", "report_configuration_mode", "业务配置存储方式", "部署与启动", activation="deployment", choices=("database",)),
    *(_item(f"DINGYI_PLATFORM_{suffix}", f"platform_settings.{attribute}", label,
        "模型与服务", activation="deployment", sensitive=sensitive,
        value_type="number" if suffix == "REQUEST_TIMEOUT" else "text",
        unit="秒" if suffix == "REQUEST_TIMEOUT" else None)
        for suffix, attribute, label, sensitive in (
            ("URL", "platform_url", "中台服务地址", False),
            ("SERVICE_TOKEN", "service_token", "中台服务凭据", True),
            ("DATABASE_URL", "database_url", "中台共享数据库", True),
            ("DB_SCHEMA", "db_schema", "中台共享数据库 Schema", False),
            ("REQUEST_TIMEOUT", "request_timeout", "中台请求超时", False),
            ("GENERATION_KEY", "generation_key", "中台代际标识", False))),
    *(_item(f"AGENT_REPORT_{suffix}", f"report_build_identity.{attribute}", label,
        "部署与启动", activation="deployment") for suffix, attribute, label in (
        ("BUILD_COMMIT", "commit", "构建提交"), ("SOURCE_HASH", "source_hash", "源码身份"),
        ("DEPENDENCY_HASH", "dependency_hash", "依赖身份"), ("COMPILER_VERSION", "compiler_version", "编译器版本"))),
    *(_item(f"AGENT_REPORT_{suffix}", f"report_delivery_settings.{attribute}", label,
        "报告外观", activation="preferences") for suffix, attribute, label in (
        ("ORGANIZATION_NAME", "branding.organization_name", "落款署名"),
        ("GENERATED_BY_LABEL", "branding.generated_by_label", "生成说明"),
        ("WATERMARK_TEXT", "branding.watermark_text", "水印文字"),
        ("HEADER_LEFT", "page_layout.header_left", "页眉左侧"),
        ("HEADER_RIGHT", "page_layout.header_right", "页眉右侧"),
        ("FOOTER_LEFT", "page_layout.footer_left", "页脚左侧"),
        ("FOOTER_RIGHT", "page_layout.footer_right", "页脚右侧"))),
)
_BY_KEY = {item.key: item for item in CONFIGURATION_CATALOG}


def _value(settings, attribute):
    for name in attribute.split("."):
        if settings is None:
            return None
        settings = getattr(settings, name)
    return settings


def configuration_inventory(settings: AgentSettings, *, deployment_keys: frozenset[str] | None = None) -> list[dict]:
    """读取冻结的实际部署来源键名；没有来源记录时如实标为启动值。"""
    if deployment_keys is None:
        deployment_keys = settings.deployment_keys
    items = []
    for item in CONFIGURATION_CATALOG:
        value = _value(settings, item.attribute)
        configured = value is not None and value != ""
        redacted = item.sensitive
        if item.key in {"OPENAI_BASE_URL", "AGENT_REPORT_METADATA_URL", "AGENT_REPORT_PUBLIC_BASE_URL", "DINGYI_PLATFORM_URL"} and value:
            try:
                parsed = urlsplit(value)
                redacted = redacted or bool(parsed.username or parsed.password or parsed.query or parsed.fragment)
            except ValueError:
                redacted = True
        source_key = next((key for key in (item.key, *item.aliases) if key in (deployment_keys or ())), None)
        items.append({"key": item.key, "label": item.label, "category": item.category,
            "type": item.value_type, "unit": item.unit, "minimum": item.minimum, "maximum": item.maximum,
            "choices": list(item.choices), "dependencies": list(item.dependencies),
            "owner": "preferences" if item.activation == "preferences" else "system",
            "activation": item.activation, "sensitive": item.sensitive, "redacted": redacted,
            "configured": configured, "value": None if redacted else list(value) if isinstance(value, tuple) else value,
            "source": "deployment" if source_key else "startup" if deployment_keys is None else "default", "sourceKey": source_key})
    return items


def validate_system_values(values: dict) -> dict:
    """只校验可纳管普通值；部署基础项、偏好和凭据不走此文档。"""
    result = {}
    for key, value in values.items():
        item = _BY_KEY.get(key)
        if item is None or item.activation != "restart" or item.sensitive:
            raise ValueError("此配置不允许作为普通系统值修改")
        if value is None and item.nullable:
            result[key] = None
            continue
        if item.value_type == "boolean":
            valid = type(value) is bool
        elif item.value_type == "integer":
            valid = type(value) is int
        elif item.value_type == "number":
            valid = type(value) is int or type(value) is float and math.isfinite(value)
        else:
            valid = isinstance(value, str) and bool(value.strip()) and len(value) <= 4096
        if not valid:
            raise ValueError("配置值类型或长度无效")
        if item.minimum is not None and value < item.minimum or item.maximum is not None and value > item.maximum:
            raise ValueError("配置值超出允许范围")
        if item.choices and value not in item.choices:
            raise ValueError("配置值不属于支持的选项")
        if key in {"OPENAI_BASE_URL", "AGENT_REPORT_METADATA_URL"}:
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or any(char.isspace() for char in parsed.hostname)
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise ValueError("服务地址必须是无嵌入凭据的 HTTP(S) 地址")
            # urlsplit 只有访问 port 时才校验端口类型及范围。
            parsed.port
        result[key] = value.strip() if isinstance(value, str) else value
    return result


def resolve_system_settings(settings: AgentSettings, values: dict) -> AgentSettings:
    """构造独立的下一启动配置；不修改既有对象、环境或正在运行的任务。"""
    validated = validate_system_values(values)
    result = replace(settings, **{_BY_KEY[key].attribute: value for key, value in validated.items()})
    if result.report_output_token_reserve >= result.report_context_token_budget:
        raise ValueError("输出预留预算必须小于上下文预算")
    return result
