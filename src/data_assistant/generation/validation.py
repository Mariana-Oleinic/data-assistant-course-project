"""In-memory structural and relational validation."""

from dataclasses import dataclass
from typing import Any

from data_assistant.generation.checks import check_passes
from data_assistant.generation.models import GeneratedDataset


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    table: str
    message: str
    row_index: int | None = None


def validate_dataset(dataset: GeneratedDataset) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for table in dataset.schema.tables:
        rows = dataset.tables.get(table.name)
        if rows is None:
            issues.append(ValidationIssue(table.name, "Generated table is missing."))
            continue

        expected_columns = {column.name for column in table.columns}
        for row_index, row in enumerate(rows):
            if set(row) != expected_columns:
                issues.append(
                    ValidationIssue(table.name, "Row columns do not match the schema.", row_index)
                )
            for column in table.columns:
                if not column.nullable and row.get(column.name) is None:
                    issues.append(
                        ValidationIssue(
                            table.name,
                            f"Column {column.name!r} cannot be null.",
                            row_index,
                        )
                    )
                for check in column.checks:
                    if check_passes(check, row) is False:
                        issues.append(
                            ValidationIssue(
                                table.name,
                                f"Column {column.name!r} violates CHECK ({check}).",
                                row_index,
                            )
                        )
            for check in table.checks:
                if check_passes(check, row) is False:
                    issues.append(
                        ValidationIssue(
                            table.name,
                            f"Row violates CHECK ({check}).",
                            row_index,
                        )
                    )

        unique_constraints = list(table.unique_constraints)
        if table.primary_key:
            unique_constraints.append(table.primary_key)
        for columns in unique_constraints:
            seen: set[tuple[Any, ...]] = set()
            for row_index, row in enumerate(rows):
                key = tuple(row.get(column) for column in columns)
                # PostgreSQL permits multiple NULL values in ordinary UNIQUE constraints.
                if any(value is None for value in key) and columns != table.primary_key:
                    continue
                if key in seen:
                    issues.append(
                        ValidationIssue(
                            table.name,
                            f"Duplicate value for unique constraint {columns}.",
                            row_index,
                        )
                    )
                seen.add(key)

        for foreign_key in table.foreign_keys:
            referenced_rows = dataset.tables.get(foreign_key.referenced_table, [])
            allowed = {
                tuple(row.get(column) for column in foreign_key.referenced_columns)
                for row in referenced_rows
            }
            for row_index, row in enumerate(rows):
                value = tuple(row.get(column) for column in foreign_key.columns)
                if all(item is None for item in value):
                    continue
                if value not in allowed:
                    issues.append(
                        ValidationIssue(
                            table.name,
                            f"Foreign key {foreign_key.columns} has no matching "
                            f"{foreign_key.referenced_table} row.",
                            row_index,
                        )
                    )

    return issues
