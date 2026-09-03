from sqlalchemy import JSON, BigInteger, Integer, Numeric, String

from data_assistant.persistence.postgres import PostgresDatasetStore, sqlalchemy_type
from data_assistant.schema.models import ColumnSchema


def test_postgres_type_mapping() -> None:
    assert isinstance(sqlalchemy_type(ColumnSchema(name="id", data_type="SERIAL")), Integer)
    assert isinstance(sqlalchemy_type(ColumnSchema(name="id", data_type="BIGINT")), BigInteger)
    assert isinstance(
        sqlalchemy_type(
            ColumnSchema(name="price", data_type="NUMERIC(10, 2)", precision=10, scale=2)
        ),
        Numeric,
    )
    assert isinstance(
        sqlalchemy_type(ColumnSchema(name="name", data_type="VARCHAR(20)", max_length=20)),
        String,
    )
    assert isinstance(sqlalchemy_type(ColumnSchema(name="payload", data_type="JSONB")), JSON)


def test_dataset_namespace_is_safe_and_deterministic() -> None:
    assert (
        PostgresDatasetStore._dataset_schema_name("12345678-1234-1234-1234-123456789abc")
        == "dataset_123456781234123412341234"
    )
