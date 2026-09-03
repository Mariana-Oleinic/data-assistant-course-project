"""Structured contracts shared by offline and hosted LLM providers."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OperationKind(str, Enum):
    REGENERATE_COLUMN = "regenerate_column"
    REPLACE_VALUES = "replace_values"
    SET_NULL_RATE = "set_null_rate"
    FILTER_DATE_RANGE = "filter_date_range"
    UNSUPPORTED = "unsupported"


class DataEditPlan(BaseModel):
    """Validated interpretation of a user's table-edit instruction."""

    operation: OperationKind
    table: str
    column: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    explanation: str
    requires_confirmation: bool = True


class SqlQueryPlan(BaseModel):
    """Structured, inspectable plan for a natural-language data question."""

    sql: str
    explanation: str
    referenced_tables: list[str] = Field(default_factory=list)
    safe_to_execute: bool = False
