"""Trusted cumulative policy shared without importing the workflow contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CumulativeSnapshotPolicy(BaseModel):
    """An explicit Profile premise, never inferred from a metric's name."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    version: Literal["1"] = "1"
    reset: Literal["calendar_year_zero"]
    observation: Literal["closed_month_end"]
    changes: Literal["signed_snapshot_delta"]
