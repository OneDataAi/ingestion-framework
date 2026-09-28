"""
Shared helpers for the bundle generator.

Configuration lives in a Unity Catalog schema (default: ariel_test.config)
with four tables: bundle_domains, jobs, pipelines, tables.
All generator settings (catalog, schema, paths) are read from
generator/generator_config.yaml.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import yaml


def load_table(catalog: str, schema: str, table_name: str) -> list[dict]:
    """Load a Unity Catalog table as a list of dicts.

    Mimics the old CSV-reader contract so downstream validation code works
    unchanged:
      - None / NULL  → empty string ""
      - bool         → lowercase string "true" / "false"
      - everything else → str(value)
    """
    from pyspark.sql import SparkSession  # deferred so non-Spark callers don't break

    spark = SparkSession.builder.getOrCreate()
    fqn = f"{catalog}.{schema}.{table_name}"
    df = spark.table(fqn)
    columns = df.columns
    rows = df.collect()

    def _to_str(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    return [{col: _to_str(row[col]) for col in columns} for row in rows]


def require_unique(rows: list[dict], key_fn, source_name: str, key_label: str) -> None:
    seen: set = set()
    for row in rows:
        key = key_fn(row)
        if key in seen:
            raise ValueError(f"{source_name}: duplicate {key_label} {key!r}")
        seen.add(key)


def require_fk(
    rows: list[dict],
    key_fn: Callable[[dict], object],
    valid_keys: set,
    row_desc_fn: Callable[[dict], str],
    field_label: str,
    hint: str | None = None,
    key_label_fn: Callable[[object], str] = repr,
) -> None:
    """Raise if any row's key_fn(row) isn't in valid_keys."""
    for row in rows:
        key = key_fn(row)
        if key not in valid_keys:
            suffix = f" (add it to {hint})" if hint else ""
            raise ValueError(f"{row_desc_fn(row)} references unknown {field_label} {key_label_fn(key)}{suffix}")


def split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


def is_true(value: str) -> bool:
    return value.strip().lower() == "true"


def relative_posix_path(from_dir: Path, to_file: Path) -> str:
    """Path from `from_dir` to `to_file`, as forward-slash text for YAML."""
    return PurePosixPath(*Path(os.path.relpath(to_file, start=from_dir)).parts).as_posix()


def dump_yaml(data: dict) -> str:
    """Render a dict as block-style YAML, preserving insertion order."""
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, width=4096, allow_unicode=True)
