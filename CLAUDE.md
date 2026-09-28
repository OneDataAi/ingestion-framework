# Shiba

Two separate config-driven generators, each with its own config folder:

- **`generator/generate_platform_bundle.py`** — reads `config_platform/catalogs.csv` / `schemas.csv` (shared, cross-domain infrastructure) and renders `bundles/platform/databricks.yml`. Deploy this first. Run `databricks bundle validate`/`deploy` from inside `bundles/platform/`.
- **`generator/generate_bundles.py`** — reads `config/` and produces a Databricks Asset Bundle per domain. By default it loops over **every** row of `bundle_domains.csv`: generate that domain's `databricks.yml` **directly to the project root** (plus per-resource YAML under `build/<domain_name>/`), run `databricks bundle validate`/`deploy` against it (from the project root, unless `--no-deploy`), then move to the next domain, which overwrites the same `databricks.yml`. Pass `--domain` to restrict to a single domain; `--target` picks `dev`/`prod` (default `dev`). The two generators don't validate against each other's config at all.

Never hand-edit generated YAML directly. Shared helpers/templates for both scripts live in `generator/common.py`, including `deploy_bundle()` (shells out to the `databricks` CLI). `workspaces.yaml` (project root) holds the dev/prod workspace host and prod `run_as_user` used to build every generated bundle's `targets:` block — both generators read it independently via `common.load_targets()`.

Data flow is strictly `source → bronze_raw (ingest pipeline) → bronze_qualified (etl pipeline)`. There is no "silver" layer.

- `config_platform/catalogs.csv` / `schemas.csv` — Unity Catalog catalogs and schemas. Shared infrastructure, not domain-scoped; domain pipelines reference these **by name only** and never create them. `generate_bundles.py` does not read these CSVs at all.
- `config/bundle_domains.csv` — one row per domain; each domain is a separately deployable bundle (`bundle_name`).
- `config/pipelines.csv` — one row per pipeline, and that pipeline's own scheduled task: `domain_name` FK says which bundle it belongs to; `type` is `ingest` (Managed Ingestion) or `etl` (Lakeflow Declarative Pipeline running one SQL file from `transformations/bronze_qualified/`); `job_name` FK says which job schedules it; `depends_on` (`;`-separated pipeline_name(s)) is the task dependency DAG — this is the only place dependencies are declared, and a dependency must share the same `job_name`. There is no `job_tasks.csv` — job scheduling lives directly on the pipeline row.
- `config/tables.csv` — source tables an `ingest` pipeline pulls in (domain inherited from the pipeline).
- `config/jobs.csv` — job-level scheduling (cron, timezone, status) plus `domain_name` FK.

Current data domain: oncology/healthcare data from a federated Azure SQL Server source (`onc_patients`, `onc_appointments`), migrated from an earlier pension/HR proof-of-concept.
