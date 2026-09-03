from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from data_assistant.generation import GenerationOptions, SyntheticDataGenerator, validate_dataset
from data_assistant.generation.edits import UnsupportedEdit, plan_and_apply_edit
from data_assistant.generation.export import dataset_to_zip, table_to_csv
from data_assistant.llm.offline import OfflineProvider
from data_assistant.schema import DDLParseError, parse_ddl


@pytest.fixture
def library_ddl() -> str:
    return Path("examples/library.ddl").read_text(encoding="utf-8")


@pytest.fixture
def dataset(library_ddl: str):
    schema = parse_ddl(library_ddl)
    return SyntheticDataGenerator(
        GenerationOptions(rows_per_table=50, seed=7, null_probability=0.1)
    ).generate(schema, source_ddl=library_ddl, name="Test library")


def test_parser_extracts_constraints_and_dependency_order(library_ddl: str) -> None:
    schema = parse_ddl(library_ddl)

    assert [table.name for table in schema.generation_order()] == [
        "authors",
        "members",
        "books",
        "loans",
    ]
    books = schema.table("books")
    assert books.primary_key == ["id"]
    assert books.column("title").nullable is False
    assert books.column("isbn").max_length == 13
    assert books.foreign_keys[0].referenced_table == "authors"
    assert books.foreign_keys[0].columns == ["author_id"]


def test_parser_rejects_more_than_seven_tables() -> None:
    ddl = "\n".join(f"CREATE TABLE t{i} (id INT PRIMARY KEY);" for i in range(8))
    with pytest.raises(DDLParseError, match="maximum of 7"):
        parse_ddl(ddl)


def test_parser_rejects_foreign_key_cycles() -> None:
    ddl = """
    CREATE TABLE left_table (
      id INT PRIMARY KEY,
      right_id INT REFERENCES right_table(id)
    );
    CREATE TABLE right_table (
      id INT PRIMARY KEY,
      left_id INT REFERENCES left_table(id)
    );
    """
    with pytest.raises(DDLParseError, match="cycle"):
        parse_ddl(ddl)


def test_parser_applies_alter_table_constraints() -> None:
    ddl = """
    CREATE TABLE authors (id INT);
    CREATE TABLE books (id INT, author_id INT, title TEXT);
    ALTER TABLE authors ADD PRIMARY KEY (id);
    ALTER TABLE books ADD CONSTRAINT books_pk PRIMARY KEY (id);
    ALTER TABLE books ADD CONSTRAINT books_author_fk
      FOREIGN KEY (author_id) REFERENCES authors(id);
    ALTER TABLE books ADD CONSTRAINT books_title_uq UNIQUE (title);
    """
    schema = parse_ddl(ddl)

    books = schema.table("books")
    assert books.primary_key == ["id"]
    assert books.column("id").nullable is False
    assert books.unique_constraints == [["title"]]
    assert books.foreign_keys[0].referenced_table == "authors"
    assert [table.name for table in schema.generation_order()] == ["authors", "books"]


def test_generation_and_validation_honor_common_check_constraints() -> None:
    ddl = """
    CREATE TABLE products (
      id SERIAL PRIMARY KEY,
      status VARCHAR(12) NOT NULL CHECK (status IN ('active', 'retired')),
      quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 100),
      price NUMERIC(8, 2) NOT NULL CHECK (price >= 0)
    );
    """
    schema = parse_ddl(ddl)
    generated = SyntheticDataGenerator(GenerationOptions(rows_per_table=30)).generate(
        schema, source_ddl=ddl
    )

    assert {row["status"] for row in generated.tables["products"]} <= {
        "active",
        "retired",
    }
    assert validate_dataset(generated) == []

    generated.tables["products"][0]["price"] = -1
    assert any("violates CHECK" in issue.message for issue in validate_dataset(generated))


def test_postgresql_arrays_generate_as_lists() -> None:
    ddl = "CREATE TABLE items (id SERIAL PRIMARY KEY, tags TEXT[] NOT NULL);"
    generated = SyntheticDataGenerator(GenerationOptions(rows_per_table=2)).generate(
        parse_ddl(ddl), source_ddl=ddl
    )

    assert isinstance(generated.tables["items"][0]["tags"], list)


def test_generation_is_deterministic_and_referentially_valid(library_ddl: str) -> None:
    schema = parse_ddl(library_ddl)
    options = GenerationOptions(rows_per_table=100, seed=99)

    first = SyntheticDataGenerator(options).generate(schema, source_ddl=library_ddl)
    second = SyntheticDataGenerator(options).generate(schema, source_ddl=library_ddl)

    assert first.tables == second.tables
    assert validate_dataset(first) == []
    author_ids = {row["id"] for row in first.tables["authors"]}
    assert {row["author_id"] for row in first.tables["books"]} <= author_ids


def test_exports_include_each_table_and_schema(dataset) -> None:
    csv_bytes = table_to_csv(dataset, "books")
    assert csv_bytes.startswith(b"id,author_id,title,isbn")

    with ZipFile(BytesIO(dataset_to_zip(dataset))) as archive:
        assert set(archive.namelist()) == {
            "authors.csv",
            "books.csv",
            "members.csv",
            "loans.csv",
            "schema.ddl",
        }


def test_offline_edit_creates_valid_new_version(dataset) -> None:
    edited, plan = plan_and_apply_edit(
        dataset,
        table_name="authors",
        instruction="Make country 20% null",
        provider=OfflineProvider(),
    )

    assert edited.id != dataset.id
    assert plan.parameters["percentage"] == 20
    assert sum(row["country"] is None for row in edited.tables["authors"]) == 10
    assert validate_dataset(edited) == []


def test_edit_rejects_protected_foreign_key(dataset) -> None:
    with pytest.raises(UnsupportedEdit, match="key columns"):
        plan_and_apply_edit(
            dataset,
            table_name="books",
            instruction="Regenerate author_id",
            provider=OfflineProvider(),
        )
