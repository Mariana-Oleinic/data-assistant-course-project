"""Deterministic Faker-based generator that never requires an LLM."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from faker import Faker

from data_assistant.generation.checks import allowed_values, check_columns, check_passes
from data_assistant.generation.models import GeneratedDataset
from data_assistant.generation.validation import validate_dataset
from data_assistant.schema.models import ColumnSchema, DatabaseSchema, TableSchema


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    rows_per_table: int = 100
    seed: int = 42
    locale: str = "en_US"
    null_probability: float = 0.08
    start_date: date = date(2020, 1, 1)
    end_date: date = date(2026, 12, 31)

    def __post_init__(self) -> None:
        if not 1 <= self.rows_per_table <= 10_000:
            raise ValueError("rows_per_table must be between 1 and 10,000.")
        if not 0 <= self.null_probability <= 1:
            raise ValueError("null_probability must be between 0 and 1.")
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date.")


class SyntheticDataGenerator:
    def __init__(self, options: GenerationOptions) -> None:
        self.options = options
        self.random = random.Random(options.seed)
        try:
            self.fake = Faker(options.locale)
        except AttributeError as exc:
            raise ValueError(f"Unsupported Faker locale: {options.locale}") from exc
        self.fake.seed_instance(options.seed)

    def generate(
        self,
        schema: DatabaseSchema,
        *,
        source_ddl: str,
        name: str = "Generated dataset",
        instructions: str = "",
    ) -> GeneratedDataset:
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in schema.generation_order():
            rows = [
                {column.name: self._value_for(column, row_index, table) for column in table.columns}
                for row_index in range(self.options.rows_per_table)
            ]
            self._apply_foreign_keys(table, rows, tables)
            self._ensure_unique_constraints(table, rows)
            tables[table.name] = rows

        dataset = GeneratedDataset(
            schema=schema,
            tables=tables,
            source_ddl=source_ddl,
            name=name,
            instructions=instructions,
        )
        issues = validate_dataset(dataset)
        if issues:
            details = "; ".join(issue.message for issue in issues[:5])
            raise ValueError(f"Generated data failed validation: {details}")
        return dataset

    def _apply_foreign_keys(
        self,
        table: TableSchema,
        rows: list[dict[str, Any]],
        generated_tables: dict[str, list[dict[str, Any]]],
    ) -> None:
        for foreign_key in table.foreign_keys:
            if foreign_key.referenced_table == table.name:
                referenced_rows = rows
            else:
                referenced_rows = generated_tables[foreign_key.referenced_table]
            if not referenced_rows:
                raise ValueError(
                    f"Cannot populate {table.name}: referenced table "
                    f"{foreign_key.referenced_table} is empty."
                )
            for row in rows:
                target = self.random.choice(referenced_rows)
                for source_column, target_column in zip(
                    foreign_key.columns,
                    foreign_key.referenced_columns,
                    strict=True,
                ):
                    row[source_column] = target[target_column]

    def _ensure_unique_constraints(self, table: TableSchema, rows: list[dict[str, Any]]) -> None:
        constraints = list(table.unique_constraints)
        if table.primary_key:
            constraints.append(table.primary_key)

        for columns in constraints:
            seen: set[tuple[Any, ...]] = set()
            for index, row in enumerate(rows):
                key = tuple(row[column] for column in columns)
                if key in seen:
                    last_column = table.column(columns[-1])
                    row[columns[-1]] = self._unique_value(last_column, index, table)
                    key = tuple(row[column] for column in columns)
                seen.add(key)

    def _unique_value(self, column: ColumnSchema, index: int, table: TableSchema) -> Any:
        base = self._base_type(column.data_type)
        if base in {"SMALLINT", "INTEGER", "INT", "BIGINT", "SERIAL", "BIGSERIAL"}:
            return index + 1
        if base == "UUID":
            return UUID(int=((self.options.seed + 1) << 96) + index + 1)
        if base == "DATE":
            return self.options.start_date + timedelta(days=index)
        if base in {"TIMESTAMP", "TIMESTAMPTZ"}:
            value = datetime.combine(self.options.start_date, time()) + timedelta(seconds=index)
            return value.replace(tzinfo=UTC) if base == "TIMESTAMPTZ" else value
        if base in {"DECIMAL", "NUMERIC", "REAL", "FLOAT", "DOUBLE", "MONEY"}:
            return Decimal(index + 1)
        value = f"{table.name}_{column.name}_{index + 1}"
        return value[: column.max_length] if column.max_length else value

    @staticmethod
    def _base_type(data_type: str) -> str:
        return re.split(r"[\s(\[]", data_type.upper(), maxsplit=1)[0]

    def _value_for(self, column: ColumnSchema, index: int, table: TableSchema) -> Any:
        is_unique = column.primary_key or column.unique

        if (
            column.nullable
            and not is_unique
            and self.random.random() < self.options.null_probability
        ):
            return None

        applicable_checks = [
            check
            for check in [*column.checks, *table.checks]
            if check_columns(check).issubset({column.name})
        ]
        for check in applicable_checks:
            choices = allowed_values(check, column.name)
            if choices:
                return self.random.choice(choices)

        value = self._raw_value_for(column, index, table)
        for _ in range(100):
            if all(
                check_passes(check, {column.name: value}) is not False
                for check in applicable_checks
            ):
                return value
            value = self._raw_value_for(column, index, table)
        return value

    def _raw_value_for(self, column: ColumnSchema, index: int, table: TableSchema) -> Any:
        base_type = self._base_type(column.data_type)
        is_unique = column.primary_key or column.unique

        if base_type in {"SERIAL", "BIGSERIAL", "SMALLSERIAL"}:
            return index + 1
        if column.primary_key and base_type in {"SMALLINT", "INTEGER", "INT", "BIGINT"}:
            return index + 1
        if column.primary_key and base_type == "UUID":
            return UUID(int=(self.options.seed << 96) + index + 1)

        name = column.name.lower()
        if column.data_type.strip().endswith("[]"):
            return [self.fake.word(), self.fake.word()]
        if base_type in {"CHAR", "VARCHAR", "TEXT", "BPCHAR", "CHARACTER"}:
            value = self._semantic_text(name, index, table, is_unique)
            return value[: column.max_length] if column.max_length else value
        if base_type in {"SMALLINT", "INTEGER", "INT", "BIGINT"}:
            if "year" in name:
                return self.random.randint(self.options.start_date.year, self.options.end_date.year)
            if any(token in name for token in ("age", "quantity", "count", "stock")):
                return self.random.randint(1, 100)
            return self.random.randint(1, 100_000)
        if base_type in {"DECIMAL", "NUMERIC", "REAL", "FLOAT", "DOUBLE", "MONEY"}:
            scale = column.scale if column.scale is not None else 2
            value = Decimal(str(round(self.random.uniform(1, 10_000), scale)))
            return value
        if base_type in {"BOOL", "BOOLEAN"}:
            return self.fake.boolean()
        if base_type == "DATE":
            return self.fake.date_between(self.options.start_date, self.options.end_date)
        if base_type in {"TIMESTAMP", "TIMESTAMPTZ"}:
            day = self.fake.date_between(self.options.start_date, self.options.end_date)
            generated = datetime.combine(
                day,
                time(
                    hour=self.random.randrange(24),
                    minute=self.random.randrange(60),
                    second=self.random.randrange(60),
                ),
            )
            return generated.replace(tzinfo=UTC) if base_type == "TIMESTAMPTZ" else generated
        if base_type in {"TIME", "TIMETZ"}:
            generated_time = time(
                hour=self.random.randrange(24),
                minute=self.random.randrange(60),
                second=self.random.randrange(60),
            )
            return generated_time.replace(tzinfo=UTC) if base_type == "TIMETZ" else generated_time
        if base_type == "UUID":
            return self.fake.uuid4(cast_to=None)
        if base_type in {"JSON", "JSONB"}:
            return {"label": self.fake.word(), "score": self.random.randint(1, 100)}
        if base_type in {"BYTEA", "BINARY", "VARBINARY"}:
            return f"sample-{index + 1}".encode()
        return self._semantic_text(name, index, table, is_unique)

    def value_for(self, column: ColumnSchema, index: int, table: TableSchema) -> Any:
        """Generate one value for safe, targeted column regeneration."""

        return self._value_for(column, index, table)

    def _semantic_text(self, name: str, index: int, table: TableSchema, is_unique: bool) -> str:
        if name in {"first_name", "firstname"}:
            return self.fake.first_name()
        if name in {"last_name", "lastname", "surname"}:
            return self.fake.last_name()
        if name in {"name", "full_name", "customer_name", "employee_name"}:
            return self.fake.name()
        if "email" in name:
            return f"user{index + 1}@example.com" if is_unique else self.fake.email()
        if any(token in name for token in ("phone", "mobile")):
            return self.fake.phone_number()
        if "address" in name:
            return self.fake.address().replace("\n", ", ")
        if name == "city" or name.endswith("_city"):
            return self.fake.city()
        if "country" in name:
            return self.fake.country()
        if any(token in name for token in ("company", "employer", "publisher")):
            return self.fake.company()
        if "url" in name or "website" in name:
            return self.fake.url()
        if "isbn" in name:
            return self.fake.isbn13(separator="")
        if any(token in name for token in ("description", "summary", "notes", "bio")):
            return self.fake.sentence(nb_words=12)
        if "title" in name:
            return self.fake.sentence(nb_words=5).rstrip(".")
        if is_unique:
            return f"{table.name}_{name}_{index + 1}"
        return self.fake.word()


def json_compatible(value: Any) -> Any:
    """Convert generated scalar values for JSON persistence or display."""

    if isinstance(value, (date, datetime, time, Decimal, UUID)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value
