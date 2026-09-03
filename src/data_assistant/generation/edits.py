"""Apply bounded text-derived edits without exposing arbitrary code execution."""

from copy import deepcopy

from data_assistant.generation.engine import GenerationOptions, SyntheticDataGenerator
from data_assistant.generation.models import GeneratedDataset
from data_assistant.generation.validation import validate_dataset
from data_assistant.llm.base import LLMProvider
from data_assistant.llm.models import DataEditPlan, OperationKind


class UnsupportedEdit(ValueError):
    pass


def plan_and_apply_edit(
    dataset: GeneratedDataset,
    *,
    table_name: str,
    instruction: str,
    provider: LLMProvider,
    seed: int = 42,
) -> tuple[GeneratedDataset, DataEditPlan]:
    table = dataset.schema.table(table_name)
    plan = provider.plan_data_edit(
        table=table_name,
        instruction=instruction,
        schema=dataset.source_ddl,
    )
    if plan.table != table_name:
        raise UnsupportedEdit("The edit plan targeted a different table.")
    if plan.operation == OperationKind.UNSUPPORTED:
        raise UnsupportedEdit(plan.explanation)

    protected_columns = set(table.primary_key)
    for foreign_key in table.foreign_keys:
        protected_columns.update(foreign_key.columns)
    if plan.column and plan.column in protected_columns:
        raise UnsupportedEdit("Primary-key and foreign-key columns cannot be edited directly.")

    edited = GeneratedDataset(
        schema=dataset.schema,
        tables=deepcopy(dataset.tables),
        source_ddl=dataset.source_ddl,
        name=f"{dataset.name} (edited)",
        instructions=(dataset.instructions + "\n" + instruction).strip(),
    )
    rows = edited.tables[table_name]

    if plan.operation == OperationKind.SET_NULL_RATE:
        if not plan.column:
            raise UnsupportedEdit("A column is required for a null-rate edit.")
        column = table.column(plan.column)
        if not column.nullable:
            raise UnsupportedEdit(f"Column {column.name!r} is NOT NULL.")
        percentage = int(plan.parameters.get("percentage", 0))
        if not 0 <= percentage <= 100:
            raise UnsupportedEdit("Null percentage must be between 0 and 100.")
        null_count = round(len(rows) * percentage / 100)
        generator = SyntheticDataGenerator(
            GenerationOptions(
                rows_per_table=max(len(rows), 1),
                seed=seed,
                null_probability=0,
            )
        )
        for index, row in enumerate(rows):
            if index < null_count:
                row[column.name] = None
            elif row[column.name] is None:
                row[column.name] = generator.value_for(column, index, table)
    elif plan.operation == OperationKind.REGENERATE_COLUMN:
        if not plan.column:
            raise UnsupportedEdit("A column is required for regeneration.")
        column = table.column(plan.column)
        generator = SyntheticDataGenerator(
            GenerationOptions(rows_per_table=max(len(rows), 1), seed=seed)
        )
        for index, row in enumerate(rows):
            row[column.name] = generator.value_for(column, index, table)
    elif plan.operation == OperationKind.REPLACE_VALUES:
        if not plan.column:
            raise UnsupportedEdit("A column is required for value replacement.")
        table.column(plan.column)
        old_value = plan.parameters.get("old")
        new_value = plan.parameters.get("new")
        for row in rows:
            if row[plan.column] == old_value:
                row[plan.column] = new_value
    else:
        raise UnsupportedEdit(f"Operation {plan.operation.value!r} is not implemented safely.")

    issues = validate_dataset(edited)
    if issues:
        raise UnsupportedEdit(f"Edit violates data integrity: {issues[0].message}")
    return edited, plan
