"""Persist each generated dataset in an isolated PostgreSQL schema."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    create_engine,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import TypeEngine

from data_assistant.generation.models import GeneratedDataset
from data_assistant.schema.models import ColumnSchema, DatabaseSchema


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    id: str
    name: str
    schema_name: str
    created_at: datetime
    row_count: int


def _base_type(data_type: str) -> str:
    return re.split(r"[\s(\[]", data_type.upper(), maxsplit=1)[0]


def sqlalchemy_type(column: ColumnSchema) -> TypeEngine[Any]:
    base = _base_type(column.data_type)
    if base in {"SMALLINT", "SMALLSERIAL"}:
        return SmallInteger()
    if base in {"BIGINT", "BIGSERIAL"}:
        return BigInteger()
    if base in {"INTEGER", "INT", "SERIAL"}:
        return Integer()
    if base in {"DECIMAL", "NUMERIC", "MONEY"}:
        return Numeric(precision=column.precision, scale=column.scale)
    if base in {"REAL", "FLOAT", "DOUBLE"}:
        return Float()
    if base in {"BOOL", "BOOLEAN"}:
        return Boolean()
    if base == "DATE":
        return Date()
    if base in {"TIMESTAMP", "TIMESTAMPTZ"}:
        return DateTime(timezone=base == "TIMESTAMPTZ")
    if base in {"TIME", "TIMETZ"}:
        return Time(timezone=base == "TIMETZ")
    if base == "UUID":
        return Uuid(as_uuid=True)
    if base in {"JSON", "JSONB"} or column.data_type.strip().endswith("[]"):
        return JSON()
    if base in {"BYTEA", "BINARY", "VARBINARY"}:
        return LargeBinary()
    if base in {"CHAR", "VARCHAR", "BPCHAR", "CHARACTER"}:
        return String(length=column.max_length)
    return Text()


class PostgresDatasetStore:
    def __init__(self, database_url: str) -> None:
        connect_args = {"connect_timeout": 3} if database_url.startswith("postgresql") else {}
        self.engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self.catalog_metadata = MetaData()
        self.catalog = Table(
            "data_assistant_datasets",
            self.catalog_metadata,
            Column("id", String(36), primary_key=True),
            Column("name", String(200), nullable=False),
            Column("schema_name", String(63), nullable=False, unique=True),
            Column("source_ddl", Text(), nullable=False),
            Column("instructions", Text(), nullable=False, default=""),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("row_count", Integer(), nullable=False),
            Column("schema_json", JSON(), nullable=False),
        )

    def initialize(self) -> None:
        self.catalog_metadata.create_all(self.engine)

    @staticmethod
    def _dataset_schema_name(dataset_id: str) -> str:
        compact = dataset_id.replace("-", "").lower()
        if not re.fullmatch(r"[0-9a-f]{32}", compact):
            raise ValueError("Dataset id must be a UUID.")
        return f"dataset_{compact[:24]}"

    def _metadata_for(self, schema: DatabaseSchema, namespace: str) -> MetaData:
        metadata = MetaData(schema=namespace)
        for table_schema in schema.generation_order():
            columns = [
                Column(
                    column.name,
                    sqlalchemy_type(column),
                    nullable=column.nullable,
                )
                for column in table_schema.columns
            ]
            constraints: list[Any] = []
            if table_schema.primary_key:
                constraints.append(PrimaryKeyConstraint(*table_schema.primary_key))
            constraints.extend(
                UniqueConstraint(*column_names) for column_names in table_schema.unique_constraints
            )
            constraints.extend(
                ForeignKeyConstraint(
                    foreign_key.columns,
                    [
                        f"{namespace}.{foreign_key.referenced_table}.{target_column}"
                        for target_column in foreign_key.referenced_columns
                    ],
                )
                for foreign_key in table_schema.foreign_keys
            )
            Table(table_schema.name, metadata, *columns, *constraints)
        return metadata

    def save(self, dataset: GeneratedDataset) -> DatasetRecord:
        self.initialize()
        namespace = self._dataset_schema_name(dataset.id)
        metadata = self._metadata_for(dataset.schema, namespace)
        quoted_namespace = self.engine.dialect.identifier_preparer.quote(namespace)

        with self.engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted_namespace}"))
            metadata.create_all(connection)
            for table_schema in dataset.schema.generation_order():
                rows = dataset.tables[table_schema.name]
                if rows:
                    connection.execute(
                        insert(metadata.tables[f"{namespace}.{table_schema.name}"]), rows
                    )
            connection.execute(
                insert(self.catalog).values(
                    id=dataset.id,
                    name=dataset.name,
                    schema_name=namespace,
                    source_ddl=dataset.source_ddl,
                    instructions=dataset.instructions,
                    created_at=dataset.created_at,
                    row_count=dataset.row_count,
                    schema_json=dataset.schema.model_dump(mode="json"),
                )
            )

        return DatasetRecord(
            id=dataset.id,
            name=dataset.name,
            schema_name=namespace,
            created_at=dataset.created_at,
            row_count=dataset.row_count,
        )

    def list(self) -> list[DatasetRecord]:
        self.initialize()
        query = select(
            self.catalog.c.id,
            self.catalog.c.name,
            self.catalog.c.schema_name,
            self.catalog.c.created_at,
            self.catalog.c.row_count,
        ).order_by(self.catalog.c.created_at.desc())
        with self.engine.connect() as connection:
            return [DatasetRecord(**dict(row._mapping)) for row in connection.execute(query)]

    def load(self, dataset_id: str) -> GeneratedDataset:
        self.initialize()
        with self.engine.connect() as connection:
            record = (
                connection.execute(select(self.catalog).where(self.catalog.c.id == dataset_id))
                .mappings()
                .one()
            )
            schema = DatabaseSchema.model_validate(record["schema_json"])
            metadata = self._metadata_for(schema, record["schema_name"])
            tables = {
                table.name: [
                    dict(row._mapping)
                    for row in connection.execute(
                        select(metadata.tables[f"{record['schema_name']}.{table.name}"])
                    )
                ]
                for table in schema.tables
            }
        return GeneratedDataset(
            id=record["id"],
            name=record["name"],
            schema=schema,
            tables=tables,
            source_ddl=record["source_ddl"],
            instructions=record["instructions"],
            created_at=record["created_at"],
        )
