"""Optional OpenAI provider. Importing this module does not make API calls."""

from collections.abc import Iterator
from typing import Any

from data_assistant.llm.base import LLMProvider
from data_assistant.llm.models import DataEditPlan, SqlQueryPlan


class OpenAIProvider(LLMProvider):
    """Paid provider instantiated only after the explicit configuration guard passes."""

    def __init__(self, *, api_key: str, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - exercised only with optional extras
            raise RuntimeError(
                "Install the optional OpenAI dependency with: pip install -e '.[openai]'"
            ) from exc

        self._client: Any = OpenAI(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return f"OpenAI ({self._model})"

    def plan_data_edit(self, *, table: str, instruction: str, schema: str) -> DataEditPlan:
        response = self._client.responses.parse(
            model=self._model,
            instructions=(
                "Convert the user's requested data change into a conservative structured plan. "
                "Never invent a table or column absent from the supplied PostgreSQL schema."
            ),
            input=f"Schema:\n{schema}\n\nTable: {table}\nInstruction: {instruction}",
            text_format=DataEditPlan,
        )
        return response.output_parsed

    def plan_sql_query(self, *, question: str, schema: str) -> SqlQueryPlan:
        response = self._client.responses.parse(
            model=self._model,
            instructions=(
                "Produce exactly one read-only PostgreSQL SELECT query. "
                "Never use DDL, DML, multiple statements, or unbounded result sets."
            ),
            input=f"Schema:\n{schema}\n\nQuestion: {question}",
            text_format=SqlQueryPlan,
        )
        return response.output_parsed

    def stream_answer(self, *, question: str, query_result: str) -> Iterator[str]:
        with self._client.responses.stream(
            model=self._model,
            instructions="Answer from the supplied query result only.",
            input=f"Question: {question}\n\nQuery result:\n{query_result}",
        ) as stream:
            yield from stream.text_deltas

