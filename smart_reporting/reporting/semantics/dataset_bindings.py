"""登记指标到探索数据集的列级身份绑定，不重新定义公式。"""

from pydantic import Field

from .request_types import FieldRef, MetricVersionRef, SemanticModel


class DatasetFieldBinding(SemanticModel):
    field_ref: FieldRef
    dataset_field: str = Field(min_length=1, max_length=256)


class MetricDatasetBinding(SemanticModel):
    metric_version: MetricVersionRef
    unit: str = Field(min_length=1, max_length=32)
    measure: DatasetFieldBinding
    time: DatasetFieldBinding
    grain: tuple[DatasetFieldBinding, ...] = Field(min_length=1, max_length=20)
