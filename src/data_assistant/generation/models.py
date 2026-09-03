"""Generated dataset container."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from data_assistant.schema.models import DatabaseSchema


@dataclass(slots=True)
class GeneratedDataset:
    schema: DatabaseSchema
    tables: dict[str, list[dict[str, Any]]]
    source_ddl: str
    name: str = "Generated dataset"
    instructions: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def row_count(self) -> int:
        return sum(len(rows) for rows in self.tables.values())
