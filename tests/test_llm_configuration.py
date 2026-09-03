import pytest
from pydantic import ValidationError

from data_assistant.config import Settings
from data_assistant.llm.factory import create_llm_provider
from data_assistant.llm.models import OperationKind


def test_offline_is_default_and_needs_no_credentials() -> None:
    settings = Settings(_env_file=None)
    provider = create_llm_provider(settings)

    assert settings.llm_mode == "offline"
    assert settings.allow_paid_llm is False
    assert provider.name == "Offline"


def test_openai_mode_requires_explicit_paid_opt_in() -> None:
    with pytest.raises(ValidationError, match="ALLOW_PAID_LLM=true"):
        Settings(
            _env_file=None,
            llm_mode="openai",
            allow_paid_llm=False,
            openai_api_key="test-key",
        )


def test_openai_mode_requires_key_after_opt_in() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(_env_file=None, llm_mode="openai", allow_paid_llm=True)


def test_offline_provider_parses_supported_edit_without_network() -> None:
    provider = create_llm_provider(Settings(_env_file=None))
    plan = provider.plan_data_edit(
        table="customers",
        instruction="Make email 20% null",
        schema="CREATE TABLE customers (email text);",
    )

    assert plan.operation == OperationKind.SET_NULL_RATE
    assert plan.column == "email"
    assert plan.parameters == {"percentage": 20}


def test_offline_provider_builds_bounded_select() -> None:
    provider = create_llm_provider(Settings(_env_file=None))
    plan = provider.plan_sql_query(
        question="show all customers",
        schema="CREATE TABLE customers (id integer);",
    )

    assert plan.safe_to_execute is True
    assert plan.sql == 'SELECT * FROM "customers" LIMIT 200'

