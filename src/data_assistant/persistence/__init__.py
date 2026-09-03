"""PostgreSQL persistence for generated datasets."""

from data_assistant.persistence.postgres import DatasetRecord, PostgresDatasetStore

__all__ = ["DatasetRecord", "PostgresDatasetStore"]
