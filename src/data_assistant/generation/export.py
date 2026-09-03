"""CSV and ZIP exports for generated datasets."""

from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from data_assistant.generation.models import GeneratedDataset


def table_to_csv(dataset: GeneratedDataset, table_name: str) -> bytes:
    if table_name not in dataset.tables:
        raise KeyError(f"Unknown table {table_name!r}.")
    buffer = StringIO()
    pd.DataFrame(dataset.tables[table_name]).to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def dataset_to_zip(dataset: GeneratedDataset) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for table_name in dataset.tables:
            archive.writestr(f"{table_name}.csv", table_to_csv(dataset, table_name))
        archive.writestr("schema.ddl", dataset.source_ddl.encode("utf-8"))
    return buffer.getvalue()
