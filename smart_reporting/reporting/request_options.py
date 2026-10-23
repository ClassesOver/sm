"""在 Agno 原生用户输入字段中保留报告选项的类型和候选值。"""

from typing import Any

from agno.tools.function import UserInputField
from pydantic import TypeAdapter


class ReportOptionInputField(UserInputField):
    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        schema = TypeAdapter(self.field_type).json_schema()
        choices = schema.get("enum") or schema.get("items", {}).get("enum")
        if self.name in {"period_start", "period_end"}:
            result["format"] = "date"
        if self.name == "analysis_dimensions":
            choices = list(dict.fromkeys(["院区", "科室", "类型", "病种", "项目", *(self.value or [])]))
        if choices:
            result["allowed_values"] = choices
        if self.name in {"domains", "analysis_dimensions"}:
            result["required"] = False
        return result
