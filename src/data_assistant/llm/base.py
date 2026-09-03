"""Provider-neutral interface used by the application."""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from data_assistant.llm.models import DataEditPlan, SqlQueryPlan


class LLMProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def plan_data_edit(self, *, table: str, instruction: str, schema: str) -> DataEditPlan:
        raise NotImplementedError

    @abstractmethod
    def plan_sql_query(self, *, question: str, schema: str) -> SqlQueryPlan:
        raise NotImplementedError

    @abstractmethod
    def stream_answer(self, *, question: str, query_result: str) -> Iterator[str]:
        raise NotImplementedError

