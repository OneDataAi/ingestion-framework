# Shiba

A single config-driven generator that reads from Unity Catalog and produces one Databricks Asset Bundle per domain.

## Generator

**`generator/generate_bundles.py`** — reads five configuration tables from Unity Catalog (`ariel_test.config`) and writes a self-contained `databricks.yml` per domain to `bundles/<domain>/databricks.yml` (inside the Git repo). Deployment is performed from the `run_generator` notebook using the Databricks CLI (`bundle deploy --target dev`). A `targets:` block is included, configured in `generator_config.yaml`.

All settings live in **`generator/generator_config.yaml`**:
- `catalog` / `schema` — Unity Catalog location of the five config tables (default: `ariel_test.config`)
- `bundle_output_root` — where per-domain bundle directories are written (default: `/Workspace/Repos/ingestion-framework/ingestion-framework/bundles`)
- `sql_source_dir` — where ETL SQL transformation files live (default: `/Workspace/Shared/transformations/bronze_qualified`)
- `domain` — optional; restrict generation to a single domain name

Shared helpers live in **`generator/common.py`**: `load_table()` (reads a UC table as list of dicts), validation helpers (`require_unique`, `require_fk`), and YAML utilities (`dump_yaml`).

## Data flow

Strictly `source → bronze_raw (ingest pipeline) → bronze_qualified (etl pipeline)`. There is no "silver" layer.

## Configuration tables (`ariel_test.config`)

- **`bundle_domains`** — one row per domain; each domain produces a separately deployable bundle (`bundle_name`).
- **`pipelines`** — one row per pipeline: `domain_name` FK says which bundle it belongs to; `type` is `ingest` (Managed Ingestion) or `etl` (Lakeflow Declarative Pipeline running one SQL file from `sql_source_dir`); `job_name` FK says which job schedules it; `depends_on` (`;`-separated pipeline names) is the task dependency DAG — a dependency must share the same `job_name`; `serverless` (boolean) controls compute mode. When `serverless=false`, the generator emits a `clusters` block using cluster variables (`node_type_id`, `driver_node_type_id`, `num_workers`) from the `variables` table.
- **`tables`** — source tables an `ingest` pipeline pulls in (domain inherited from the pipeline). `primary_keys` + `cursor_columns` must be set together: both set = incremental merge ingestion; both empty = **full replace** (the table object gets `scd_type: APPEND_ONLY` and the pipeline's job task gets `full_refresh: true`, so each run truncates the destination and re-reads the whole source table). Because full refresh is per-pipeline, an ingest pipeline can't mix full-replace and incremental tables.
- **`jobs`** — job-level scheduling (cron, timezone, status) plus `domain_name` FK.
- **`variables`** — bundle variables with per-environment values. Columns: `variable_name` (unique key, also the config-table column it auto-substitutes), `description`, and `env_<target>` columns (e.g. `env_dev`, `env_prod`). The generator auto-discovers `env_*` columns — adding `env_staging` is all that's needed for a new target. Any `variable_name` that matches a column in `pipelines` or `tables` is automatically emitted as `${var.<name>}` in the generated YAML, with per-target overrides in the `targets:` block.

## Key paths

- Generator: `/Repos/ingestion-framework/ingestion-framework/generator/`
- Config file: `generator/generator_config.yaml`
- Generated bundles: `/Repos/ingestion-framework/ingestion-framework/bundles/<domain>/databricks.yml`
- SQL transformations: `/Workspace/Shared/transformations/bronze_qualified/`

## Current data domain

Oncology/healthcare data from a federated Azure SQL Server source (`onc_patients`, `onc_appointments`).
