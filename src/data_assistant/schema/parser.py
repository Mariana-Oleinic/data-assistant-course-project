"""PostgreSQL CREATE TABLE parser backed by sqlglot."""

from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from data_assistant.schema.models import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySchema,
    TableSchema,
)


class DDLParseError(ValueError):
    """Raised when uploaded DDL cannot be represented safely."""


def _identifier_names(expressions: list[exp.Expression]) -> list[str]:
    names: list[str] = []
    for expression in expressions:
        if isinstance(expression, (exp.Identifier, exp.Column)):
            names.append(expression.name)
    return names


def _reference_parts(reference: exp.Reference) -> tuple[str, list[str]]:
    target = reference.this
    if not isinstance(target, exp.Schema) or not isinstance(target.this, exp.Table):
        raise DDLParseError("Unsupported REFERENCES clause.")
    return target.this.name, _identifier_names(list(target.expressions))


def _data_type_details(kind: exp.DataType) -> tuple[str, int | None, int | None, int | None]:
    sql_type = kind.sql(dialect="postgres")
    params: list[int] = []
    for parameter in kind.expressions:
        value = parameter.this if isinstance(parameter, exp.DataTypeParam) else parameter
        if isinstance(value, exp.Literal) and not value.is_string:
            try:
                params.append(int(value.this))
            except ValueError:
                pass

    upper = sql_type.upper()
    max_length = params[0] if params and ("CHAR" in upper or "BIT" in upper) else None
    precision = params[0] if params and ("DECIMAL" in upper or "NUMERIC" in upper) else None
    scale = params[1] if len(params) > 1 and precision is not None else None
    return sql_type, max_length, precision, scale


def _parse_column(
    definition: exp.ColumnDef,
) -> tuple[ColumnSchema, ForeignKeySchema | None]:
    if not isinstance(definition.kind, exp.DataType):
        raise DDLParseError(f"Column {definition.name!r} has no supported data type.")

    sql_type, max_length, precision, scale = _data_type_details(definition.kind)
    primary_key = False
    nullable = True
    unique = False
    default: str | None = None
    checks: list[str] = []
    foreign_key: ForeignKeySchema | None = None

    for wrapper in definition.constraints:
        constraint = wrapper.kind
        if isinstance(constraint, exp.PrimaryKeyColumnConstraint):
            primary_key = True
            nullable = False
        elif isinstance(constraint, exp.NotNullColumnConstraint):
            nullable = False
        elif isinstance(constraint, exp.UniqueColumnConstraint):
            unique = True
        elif isinstance(constraint, exp.DefaultColumnConstraint):
            default = constraint.this.sql(dialect="postgres")
        elif isinstance(constraint, exp.CheckColumnConstraint):
            checks.append(constraint.this.sql(dialect="postgres"))
        elif isinstance(constraint, exp.Reference):
            target_table, target_columns = _reference_parts(constraint)
            foreign_key = ForeignKeySchema(
                columns=[definition.name],
                referenced_table=target_table,
                referenced_columns=target_columns,
            )

    return (
        ColumnSchema(
            name=definition.name,
            data_type=sql_type,
            nullable=nullable,
            primary_key=primary_key,
            unique=unique,
            default=default,
            max_length=max_length,
            precision=precision,
            scale=scale,
            checks=checks,
        ),
        foreign_key,
    )


def _parse_table(create: exp.Create) -> TableSchema:
    schema_expression = create.this
    if not isinstance(schema_expression, exp.Schema) or not isinstance(
        schema_expression.this, exp.Table
    ):
        raise DDLParseError("CREATE TABLE AS and schemaless CREATE forms are not supported.")

    table_expression = schema_expression.this
    columns: list[ColumnSchema] = []
    primary_key: list[str] = []
    unique_constraints: list[list[str]] = []
    foreign_keys: list[ForeignKeySchema] = []
    checks: list[str] = []

    for item in schema_expression.expressions:
        if isinstance(item, exp.ColumnDef):
            column, foreign_key = _parse_column(item)
            columns.append(column)
            if column.primary_key:
                primary_key.append(column.name)
            if column.unique:
                unique_constraints.append([column.name])
            if foreign_key:
                foreign_keys.append(foreign_key)
        elif isinstance(item, exp.PrimaryKey):
            primary_key.extend(_identifier_names(list(item.expressions)))
        elif isinstance(item, exp.ForeignKey):
            reference = item.args.get("reference")
            if not isinstance(reference, exp.Reference):
                raise DDLParseError("FOREIGN KEY is missing a supported REFERENCES clause.")
            target_table, target_columns = _reference_parts(reference)
            foreign_keys.append(
                ForeignKeySchema(
                    columns=_identifier_names(list(item.expressions)),
                    referenced_table=target_table,
                    referenced_columns=target_columns,
                )
            )
        elif isinstance(item, exp.UniqueColumnConstraint):
            target = item.this
            expressions = list(target.expressions) if isinstance(target, exp.Schema) else []
            unique_constraints.append(_identifier_names(expressions))
        elif isinstance(item, exp.CheckColumnConstraint):
            checks.append(item.this.sql(dialect="postgres"))
        elif isinstance(item, exp.Constraint):
            for constraint in item.expressions:
                if isinstance(constraint, exp.UniqueColumnConstraint):
                    target = constraint.this
                    expressions = list(target.expressions) if isinstance(target, exp.Schema) else []
                    unique_constraints.append(_identifier_names(expressions))
                elif isinstance(constraint, exp.CheckColumnConstraint):
                    checks.append(constraint.this.sql(dialect="postgres"))

    # Table-level primary keys should also update column metadata.
    primary_key = list(dict.fromkeys(primary_key))
    primary_set = set(primary_key)
    columns = [
        column.model_copy(
            update={"primary_key": True, "nullable": False} if column.name in primary_set else {}
        )
        for column in columns
    ]

    return TableSchema(
        name=table_expression.name,
        namespace=table_expression.db or None,
        columns=columns,
        primary_key=primary_key,
        unique_constraints=[constraint for constraint in unique_constraints if constraint],
        foreign_keys=foreign_keys,
        checks=checks,
    )


def _constraint_expressions(expression: exp.Expression) -> list[exp.Expression]:
    if isinstance(expression, exp.Constraint):
        return list(expression.expressions)
    return [expression]


def _apply_alter_constraints(table: TableSchema, alter: exp.Alter) -> None:
    for action in alter.args.get("actions") or []:
        if not isinstance(action, exp.AddConstraint):
            continue
        for wrapper in action.expressions:
            for constraint in _constraint_expressions(wrapper):
                if isinstance(constraint, exp.PrimaryKey):
                    names = _identifier_names(list(constraint.expressions))
                    table.primary_key = list(dict.fromkeys([*table.primary_key, *names]))
                elif isinstance(constraint, exp.ForeignKey):
                    reference = constraint.args.get("reference")
                    if not isinstance(reference, exp.Reference):
                        raise DDLParseError("ALTER FOREIGN KEY has no supported reference.")
                    target_table, target_columns = _reference_parts(reference)
                    table.foreign_keys.append(
                        ForeignKeySchema(
                            columns=_identifier_names(list(constraint.expressions)),
                            referenced_table=target_table,
                            referenced_columns=target_columns,
                        )
                    )
                elif isinstance(constraint, exp.UniqueColumnConstraint):
                    target = constraint.this
                    expressions = list(target.expressions) if isinstance(target, exp.Schema) else []
                    names = _identifier_names(expressions)
                    if names:
                        table.unique_constraints.append(names)
                elif isinstance(constraint, exp.CheckColumnConstraint):
                    table.checks.append(constraint.this.sql(dialect="postgres"))

    primary_set = set(table.primary_key)
    table.columns = [
        column.model_copy(update={"primary_key": True, "nullable": False})
        if column.name in primary_set
        else column
        for column in table.columns
    ]


def parse_ddl(ddl: str) -> DatabaseSchema:
    """Parse up to seven PostgreSQL CREATE TABLE statements."""

    if not ddl.strip():
        raise DDLParseError("DDL input is empty.")
    try:
        statements = parse(ddl, read="postgres")
    except ParseError as exc:
        raise DDLParseError(f"Invalid PostgreSQL DDL: {exc}") from exc

    creates = [
        statement
        for statement in statements
        if isinstance(statement, exp.Create)
        and str(statement.args.get("kind", "")).upper() == "TABLE"
    ]
    if not creates:
        raise DDLParseError("No CREATE TABLE statements were found.")
    if len(creates) > 7:
        raise DDLParseError("A maximum of 7 tables is supported.")

    try:
        tables = [_parse_table(create) for create in creates]
        by_name = {table.name: table for table in tables}
        for statement in statements:
            if not isinstance(statement, exp.Alter) or not isinstance(statement.this, exp.Table):
                continue
            table = by_name.get(statement.this.name)
            if table is not None:
                _apply_alter_constraints(table, statement)
        parsed = DatabaseSchema(tables=tables)
        parsed.generation_order()
        return parsed
    except (ValueError, KeyError) as exc:
        if isinstance(exc, DDLParseError):
            raise
        raise DDLParseError(str(exc)) from exc
