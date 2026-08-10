"""医院运营领域结构化数据的基础模型。"""

from pydantic import BaseModel, ConfigDict


class HospitalOperationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


__all__ = ["HospitalOperationSchema"]
