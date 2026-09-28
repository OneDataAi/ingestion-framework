"""
Shared helpers used by both generator scripts:
  - generate_platform_bundle.py — the shared catalogs/schemas bundle
  - generate_bundles.py         — the per-domain pipeline/job bundles

Catalogs and schemas are cross-domain infrastructure: they're generated
once by generate_platform_bundle.py from config_platform/catalogs.csv and
config_platform/schemas.csv. Domain bundles only reference them by name
(target_catalog / bronze_raw_schema / bronze_qualified_schema columns) —
they don't create them.

Both scripts also independently read the top-level workspaces.yaml (via
load_targets()) for the `targets:` block's dev/prod workspace host and
prod run_as user — this is a shared input file, not a dependency between
the two scripts.
"""
from __future__ import annotations

import csv
import os
import subprocess
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import yaml


def load_csv(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def require_unique(rows: list[dict], key_fn, csv_name: str, key_label: str) -> None:
    seen: set = set()
    for row in rows:
        key = key_fn(row)
        if key in seen:
            raise ValueError(f"{csv_name}: duplicate {key_label} {key!r}")
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
    """Raise if any row's key_fn(row) isn't in valid_keys.

    row_desc_fn(row) builds the message prefix (e.g. "tables.csv: table 'x'"),
    field_label names the FK column (e.g. "target_catalog"), hint (if given)
    names the CSV the missing value should be added to, and key_label_fn
    formats the missing key itself (default: repr; pass e.g.
    `lambda k: f"'{k[0]}.{k[1]}'"` for composite keys).
    """
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


FILE_HEADER = "# AUTO-GENERATED — do not edit by hand.\n"

# Fallback used when workspaces.yaml is missing or a field is left blank.
_DEFAULT_DEV_HOST = "https://<your-workspace>.azuredatabricks.net"
_DEFAULT_PROD_HOST = "https://<your-workspace>.azuredatabricks.net"
_DEFAULT_PROD_USER = "<your-user>@<your-domain>"


def load_workspaces_config(workspaces_config: Path) -> dict:
    if not workspaces_config.exists():
        return {}
    return yaml.safe_load(workspaces_config.read_text(encoding="utf-8")) or {}


def load_targets(workspaces_config: Path) -> dict:
    """Build the `targets:` block (identical in both generated bundles: only
    `bundle.name` and `resources` ever differ between the platform bundle
    and a domain bundle) from workspaces.yaml, e.g.:

        default_domain: oncology
        dev:
          host: https://my-workspace.azuredatabricks.net
        prod:
          host: https://my-workspace.azuredatabricks.net
          run_as_user: jane.doe@example.com

    Any missing file or field falls back to a placeholder value.
    """
    config = load_workspaces_config(workspaces_config)

    dev = config.get("dev") or {}
    prod = config.get("prod") or {}
    dev_host = dev.get("host", "").strip() if dev.get("host") else _DEFAULT_DEV_HOST
    prod_host = prod.get("host", "").strip() if prod.get("host") else _DEFAULT_PROD_HOST
    prod_user = prod.get("run_as_user", "").strip() if prod.get("run_as_user") else _DEFAULT_PROD_USER

    return {
        "dev": {
            "mode": "development",
            "default": True,
            "workspace": {"host": dev_host},
        },
        "prod": {
            "mode": "production",
            "workspace": {
                "host": prod_host,
                "root_path": f"/Workspace/Users/{prod_user}/.bundle/${{bundle.name}}/${{bundle.target}}",
            },
        },
    }


def deploy_bundle(bundle_root_dir: Path, target: str, profile: str | None = None) -> None:
    """Run `databricks bundle validate` then `databricks bundle deploy` for the
    bundle rooted at bundle_root_dir, against the given target. Raises
    subprocess.CalledProcessError if either step exits non-zero."""
    target_args = ["--target", target]
    profile_args = ["--profile", profile] if profile else []
    for verb in ("validate", "deploy"):
        subprocess.run(["databricks", "bundle", verb, *target_args, *profile_args], cwd=bundle_root_dir, check=True)


def dump_yaml(data: dict) -> str:
    """Render a dict as block-style YAML, preserving insertion order."""
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, width=4096, allow_unicode=True)


def write_yaml_resource(path: Path, resource_type: str, entry_key: str, entry: dict) -> None:
    """Write one per-resource file containing a single resources.<resource_type>.<entry_key> entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = FILE_HEADER + dump_yaml({"resources": {resource_type: {entry_key: entry}}})
    path.write_text(content, encoding="utf-8")


def catalog_dir_for(out_dir: Path, catalog: str) -> Path:
    return out_dir / "resources" / "catalogs" / catalog


def catalog_entry(catalog: dict) -> tuple[str, dict]:
    catalog_name = catalog["catalog_name"]
    entry = {"name": catalog_name, "comment": catalog.get("comment", "")}
    storage_root = catalog.get("storage_root", "").strip()
    if storage_root:
        entry["storage_root"] = storage_root
    return f"{catalog_name}_catalog", entry


def schema_entry(schema: dict) -> tuple[str, dict]:
    catalog_name = schema["catalog_name"]
    schema_name = schema["schema_name"]
    entry = {
        "name": schema_name,
        "catalog_name": catalog_name,
        "comment": schema.get("comment", ""),
    }
    return f"{catalog_name}_{schema_name}_schema", entry


def render_catalogs(catalogs: list[dict], out_dir: Path) -> dict[str, dict]:
    """Writes each catalog's own per-resource file; returns {resource_key: entry} for the aggregated bundle."""
    entries: dict[str, dict] = {}
    for catalog in catalogs:
        key, entry = catalog_entry(catalog)
        entries[key] = entry
        catalog_dir = catalog_dir_for(out_dir, catalog["catalog_name"])
        write_yaml_resource(catalog_dir / f"{catalog['catalog_name']}.catalog.yml", "catalogs", key, entry)
    return entries


def render_schemas(schemas: list[dict], out_dir: Path) -> dict[str, dict]:
    """Writes each schema's own per-resource file; returns {resource_key: entry} for the aggregated bundle."""
    entries: dict[str, dict] = {}
    for schema in schemas:
        key, entry = schema_entry(schema)
        entries[key] = entry
        schemas_dir = catalog_dir_for(out_dir, schema["catalog_name"]) / "schemas"
        write_yaml_resource(schemas_dir / f"{schema['schema_name']}.schema.yml", "schemas", key, entry)
    return entries
