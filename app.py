"""Streamlit entry point for the Data Assistant course project."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from data_assistant.config import get_settings
from data_assistant.generation.edits import UnsupportedEdit, plan_and_apply_edit
from data_assistant.generation.engine import GenerationOptions, SyntheticDataGenerator
from data_assistant.generation.export import dataset_to_zip, table_to_csv
from data_assistant.generation.models import GeneratedDataset
from data_assistant.generation.validation import validate_dataset
from data_assistant.llm.factory import create_llm_provider
from data_assistant.persistence.postgres import PostgresDatasetStore
from data_assistant.schema.parser import DDLParseError, parse_ddl

st.set_page_config(page_title="Data Assistant", page_icon="🗄️", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1250px;}
    [data-testid="stSidebar"] {border-right: 1px solid #e5e7eb;}
    .status-pill {display: inline-block; padding: .25rem .65rem; border-radius: 999px;
      background: #ecfdf5; color: #065f46; font-size: .82rem; font-weight: 600;}
    .muted {color: #6b7280; font-size: .92rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

settings = get_settings()
provider = create_llm_provider(settings)


@st.cache_resource
def get_store(database_url: str) -> PostgresDatasetStore:
    return PostgresDatasetStore(database_url)


def current_dataset() -> GeneratedDataset | None:
    value = st.session_state.get("dataset")
    return value if isinstance(value, GeneratedDataset) else None


def render_schema_summary(dataset: GeneratedDataset) -> None:
    with st.expander("Parsed schema", expanded=False):
        for table in dataset.schema.generation_order():
            foreign_keys = ", ".join(
                f"{','.join(fk.columns)} → {fk.referenced_table}({','.join(fk.referenced_columns)})"
                for fk in table.foreign_keys
            )
            st.markdown(
                f"**{table.name}** — {len(table.columns)} columns"
                + (f" · Foreign keys: {foreign_keys}" if foreign_keys else "")
            )


def render_dataset(dataset: GeneratedDataset) -> None:
    issues = validate_dataset(dataset)
    left, middle, right = st.columns(3)
    left.metric("Tables", len(dataset.tables))
    middle.metric("Total rows", f"{dataset.row_count:,}")
    right.metric("Validation", "Passed" if not issues else f"{len(issues)} issues")
    render_schema_summary(dataset)

    table_name = st.selectbox("Preview table", list(dataset.tables), key="preview_table")
    frame = pd.DataFrame(dataset.tables[table_name])
    st.dataframe(frame.head(200), width="stretch", hide_index=True)
    if len(frame) > 200:
        st.caption(f"Showing the first 200 of {len(frame):,} rows.")

    csv_col, zip_col = st.columns(2)
    csv_col.download_button(
        "Download table CSV",
        table_to_csv(dataset, table_name),
        file_name=f"{table_name}.csv",
        mime="text/csv",
        width="stretch",
    )
    zip_col.download_button(
        "Download complete ZIP",
        dataset_to_zip(dataset),
        file_name=f"{dataset.name.replace(' ', '_').lower()}.zip",
        mime="application/zip",
        width="stretch",
    )

    st.subheader("Modify this table")
    st.caption(
        "Offline examples: “Regenerate email” or “Make notes 20% null”. Key columns are protected."
    )
    with st.form("edit_table_form"):
        instruction = st.text_input("Edit instruction")
        submitted = st.form_submit_button("Apply changes", type="primary")
    if submitted:
        if not instruction.strip():
            st.warning("Enter an edit instruction first.")
        else:
            try:
                edited, plan = plan_and_apply_edit(
                    dataset,
                    table_name=table_name,
                    instruction=instruction,
                    provider=provider,
                )
                st.session_state.dataset = edited
                try:
                    get_store(settings.database_url).save(edited)
                    st.success(plan.explanation + " A new dataset version was saved.")
                except SQLAlchemyError:
                    st.success(
                        plan.explanation + " The edited version is available in this session."
                    )
                st.rerun()
            except (UnsupportedEdit, KeyError, ValueError) as exc:
                st.error(str(exc))


def data_generation_page() -> None:
    st.title("Data Generation")
    st.markdown(
        '<span class="status-pill">Offline mode · no API charges</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="muted">Upload PostgreSQL DDL, generate constraint-aware synthetic data, '
        "then preview, edit, store, or export it.</p>",
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        uploaded = st.file_uploader(
            "Upload DDL schema",
            type=["sql", "ddl", "txt"],
            help="Up to seven PostgreSQL CREATE TABLE statements.",
        )
        use_example = st.checkbox("Use built-in library example", value=uploaded is None)
        instructions = st.text_area(
            "Data instructions",
            placeholder="Example: Generate realistic library data for a university.",
        )
        dataset_name = st.text_input("Dataset name", value="Library demo")

        with st.expander("Generation parameters", expanded=True):
            col1, col2, col3 = st.columns(3)
            rows_per_table = col1.number_input(
                "Rows per table", min_value=1, max_value=10_000, value=100, step=10
            )
            seed = col2.number_input("Random seed", min_value=0, value=42, step=1)
            variation = col3.slider(
                "Data variation", min_value=0.0, max_value=1.0, value=0.35, step=0.05
            )
            date_col1, date_col2, locale_col = st.columns(3)
            start_date = date_col1.date_input("Earliest date", value=date(2020, 1, 1))
            end_date = date_col2.date_input("Latest date", value=date(2026, 12, 31))
            locale = locale_col.selectbox("Data locale", ["en_US", "ro_RO", "en_GB", "de_DE"])

        save_to_database = st.checkbox("Save to PostgreSQL", value=True)
        generate = st.button("Generate", type="primary", width="stretch")

    if generate:
        try:
            if uploaded is not None:
                ddl = uploaded.getvalue().decode("utf-8-sig")
            elif use_example:
                ddl = Path("examples/library.ddl").read_text(encoding="utf-8")
            else:
                raise ValueError("Upload a DDL file or select the built-in example.")
            schema = parse_ddl(ddl)
            generator = SyntheticDataGenerator(
                GenerationOptions(
                    rows_per_table=int(rows_per_table),
                    seed=int(seed),
                    locale=locale,
                    # Variation controls the frequency of optional null values.
                    null_probability=variation * 0.25,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            with st.spinner("Generating and validating related tables…"):
                dataset = generator.generate(
                    schema,
                    source_ddl=ddl,
                    name=dataset_name.strip() or "Generated dataset",
                    instructions=instructions,
                )
            st.session_state.dataset = dataset
            if save_to_database:
                try:
                    get_store(settings.database_url).save(dataset)
                    st.success("Dataset generated, validated, and saved to PostgreSQL.")
                except SQLAlchemyError as exc:
                    st.warning(
                        "Data was generated successfully but PostgreSQL is unavailable. "
                        "Start Docker Compose to enable persistence."
                    )
                    st.session_state.persistence_error = str(exc)
            else:
                st.success("Dataset generated and validated in this session.")
        except (UnicodeDecodeError, DDLParseError, ValueError) as exc:
            st.error(str(exc))

    dataset = current_dataset()
    if dataset:
        st.divider()
        st.header("Data Preview")
        render_dataset(dataset)


def talk_to_data_page() -> None:
    st.title("Talk to your data")
    st.caption("The current offline milestone supports the bounded pattern: “show all <table>”.")
    dataset = current_dataset()
    try:
        records = get_store(settings.database_url).list()
    except SQLAlchemyError:
        records = []
    if records:
        labels = {f"{record.name} · {record.row_count:,} rows": record for record in records}
        selected_label = st.selectbox("Saved PostgreSQL datasets", list(labels))
        if st.button("Load selected dataset"):
            try:
                st.session_state.dataset = get_store(settings.database_url).load(
                    labels[selected_label].id
                )
                st.rerun()
            except SQLAlchemyError as exc:
                st.error(f"Could not load the dataset: {exc}")
    dataset = current_dataset()
    if dataset is None:
        st.info("Generate a dataset in the Data Generation tab first.")
        return

    st.write(f"Active dataset: **{dataset.name}**")
    question = st.text_input("Ask a question", placeholder="show all books")
    if st.button("Run question", type="primary"):
        plan = provider.plan_sql_query(question=question, schema=dataset.source_ddl)
        if not plan.safe_to_execute or not plan.referenced_tables:
            st.warning(plan.explanation)
            return
        table_name = plan.referenced_tables[0]
        if table_name not in dataset.tables:
            st.error("The requested table is not part of the active dataset.")
            return
        st.code(plan.sql, language="sql")
        st.dataframe(
            pd.DataFrame(dataset.tables[table_name]).head(200),
            width="stretch",
            hide_index=True,
        )


with st.sidebar:
    st.title("Data Assistant")
    page = st.radio(
        "Navigation", ["Data Generation", "Talk to your data"], label_visibility="collapsed"
    )
    st.divider()
    st.caption(f"Provider: {provider.name}")
    st.caption("OpenAI and Langfuse are disabled by default.")

if page == "Data Generation":
    data_generation_page()
else:
    talk_to_data_page()
