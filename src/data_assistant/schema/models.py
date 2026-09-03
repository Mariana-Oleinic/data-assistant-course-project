"""Serializable representation of a PostgreSQL DDL schema."""

from pydantic import BaseModel, Field, model_validator


class ColumnSchema(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False
    default: str | None = None
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None
    checks: list[str] = Field(default_factory=list)


class ForeignKeySchema(BaseModel):
    columns: list[str]
    referenced_table: str
    referenced_columns: list[str]

    @model_validator(mode="after")
    def matching_arity(self) -> "ForeignKeySchema":
        if len(self.columns) != len(self.referenced_columns):
            raise ValueError("Foreign-key source and target columns must have matching arity.")
        return self


class TableSchema(BaseModel):
    name: str
    namespace: str | None = None
    columns: list[ColumnSchema]
    primary_key: list[str] = Field(default_factory=list)
    unique_constraints: list[list[str]] = Field(default_factory=list)
    foreign_keys: list[ForeignKeySchema] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name

    def column(self, name: str) -> ColumnSchema:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"Unknown column {name!r} in table {self.name!r}.")


class DatabaseSchema(BaseModel):
    tables: list[TableSchema]

    @model_validator(mode="after")
    def validate_references(self) -> "DatabaseSchema":
        if not self.tables:
            raise ValueError("The DDL does not contain any CREATE TABLE statements.")
        if len(self.tables) > 7:
            raise ValueError("A maximum of 7 tables is supported.")

        by_name = {table.name: table for table in self.tables}
        if len(by_name) != len(self.tables):
            raise ValueError("Duplicate table names are not supported.")

        for table in self.tables:
            column_names = {column.name for column in table.columns}
            if not column_names:
                raise ValueError(f"Table {table.name!r} has no columns.")
            for fk in table.foreign_keys:
                if not set(fk.columns).issubset(column_names):
                    raise ValueError(f"Foreign key in {table.name!r} uses an unknown column.")
                target = by_name.get(fk.referenced_table)
                if target is None:
                    raise ValueError(
                        f"Foreign key in {table.name!r} references unknown table "
                        f"{fk.referenced_table!r}."
                    )
                target_columns = {column.name for column in target.columns}
                if not set(fk.referenced_columns).issubset(target_columns):
                    raise ValueError(
                        f"Foreign key in {table.name!r} references an unknown target column."
                    )
        return self

    def table(self, name: str) -> TableSchema:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(f"Unknown table {name!r}.")

    def generation_order(self) -> list[TableSchema]:
        """Return parents before children, rejecting non-self-referential cycles."""

        table_by_name = {table.name: table for table in self.tables}
        dependencies = {
            table.name: {
                fk.referenced_table
                for fk in table.foreign_keys
                if fk.referenced_table != table.name
            }
            for table in self.tables
        }
        ordered: list[TableSchema] = []
        remaining = set(table_by_name)

        while remaining:
            ready = sorted(name for name in remaining if not dependencies[name] & remaining)
            if not ready:
                cycle = ", ".join(sorted(remaining))
                raise ValueError(f"Foreign-key cycle detected between: {cycle}.")
            for name in ready:
                ordered.append(table_by_name[name])
                remaining.remove(name)
        return ordered
