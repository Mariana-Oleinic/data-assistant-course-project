"""No-cost provider with deterministic, deliberately limited behavior."""

import re
from collections.abc import Iterator

from data_assistant.llm.base import LLMProvider
from data_assistant.llm.models import DataEditPlan, OperationKind, SqlQueryPlan


class OfflineProvider(LLMProvider):
    """Supports demos and tests without credentials or network requests."""

    @property
    def name(self) -> str:
        return "Offline"

    def plan_data_edit(self, *, table: str, instruction: str, schema: str) -> DataEditPlan:
        del schema
        normalized = instruction.strip().lower()

        null_match = re.search(r"(?:set|make)\s+(\w+)\s+(\d{1,3})%\s+null", normalized)
        if null_match:
            return DataEditPlan(
                operation=OperationKind.SET_NULL_RATE,
                table=table,
                column=null_match.group(1),
                parameters={"percentage": min(int(null_match.group(2)), 100)},
                explanation="Apply the requested null percentage using a deterministic seed.",
            )

        regenerate_match = re.search(r"regenerate\s+(?:the\s+)?(\w+)", normalized)
        if regenerate_match:
            return DataEditPlan(
                operation=OperationKind.REGENERATE_COLUMN,
                table=table,
                column=regenerate_match.group(1),
                explanation="Regenerate this column while preserving table constraints.",
            )

        return DataEditPlan(
            operation=OperationKind.UNSUPPORTED,
            table=table,
            explanation=(
                "Offline mode could not safely interpret this instruction. "
                "Use a supported template or enable a hosted provider deliberately."
            ),
            requires_confirmation=False,
        )

    def plan_sql_query(self, *, question: str, schema: str) -> SqlQueryPlan:
        del schema
        normalized = question.strip().lower()
        match = re.fullmatch(r"(?:show|list)\s+(?:all\s+)?([a-z_][a-z0-9_]*)", normalized)
        if not match:
            return SqlQueryPlan(
                sql="",
                explanation="Offline mode supports the pattern: 'show all <table>'.",
            )

        table = match.group(1)
        return SqlQueryPlan(
            sql=f'SELECT * FROM "{table}" LIMIT 200',
            explanation=f"Return at most 200 rows from {table}.",
            referenced_tables=[table],
            safe_to_execute=True,
        )

    def stream_answer(self, *, question: str, query_result: str) -> Iterator[str]:
        del question
        message = f"Offline result: {query_result}"
        for word in message.split():
            yield word + " "

