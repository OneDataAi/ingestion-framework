# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# DBTITLE 1,Generate all domain bundles
import sys
import importlib

sys.path.insert(0, "/Workspace/Repos/ingestion-framework/ingestion-framework/generator")

# Force reimport so code changes are picked up without restarting the cluster
for mod_name in ["common", "generate_bundles"]:
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])

from generate_bundles import load_config, generate

config = load_config()
bundle_dirs = generate(config)

# Write bundle paths for the shell deploy cell
with open("/tmp/bundle_dirs.txt", "w") as f:
    for d in bundle_dirs:
        f.write(str(d) + "\n")
print(f"\n{len(bundle_dirs)} bundle(s) ready for deployment.")

# COMMAND ----------

# DBTITLE 1,Deploy all generated bundles
# DEPLOY INSTRUCTIONS:
# Requires a classic cluster (CLI is blocked on serverless).
# Option 1 (recommended): Attach a classic cluster and run this cell.
# Option 2: Run from the Web Terminal (Clusters > Web Terminal):
#       cd /Workspace/Repos/ingestion-framework/ingestion-framework/bundles/oncology
#       databricks bundle validate --target dev
#       databricks bundle deploy --target dev

import subprocess, os, stat, zipfile, urllib.request

# Install Databricks CLI from a pinned GitHub release (the pre-installed
# binary on classic clusters is restricted to the web terminal).
CLI_VERSION = "0.237.0"
cli_dir = os.path.expanduser("~/bin")
cli_path = os.path.join(cli_dir, "databricks")

if not os.path.isfile(cli_path):
    os.makedirs(cli_dir, exist_ok=True)
    url = f"https://github.com/databricks/cli/releases/download/v{CLI_VERSION}/databricks_cli_{CLI_VERSION}_linux_amd64.zip"
    zip_path = "/tmp/databricks_cli.zip"
    print(f"Downloading Databricks CLI v{CLI_VERSION}...")
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extract("databricks", cli_dir)
    os.chmod(cli_path, os.stat(cli_path).st_mode | stat.S_IEXEC)
    print(f"CLI installed at {cli_path}\n")

# Pass notebook credentials to the CLI via environment variables
token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
host = f"https://{spark.conf.get('spark.databricks.workspaceUrl')}"

env = os.environ.copy()
env["DATABRICKS_HOST"] = host
env["DATABRICKS_TOKEN"] = token

target = "dev"

for bundle_dir in bundle_dirs:
    print(f"\n{'='*60}")
    print(f"Deploying bundle at {bundle_dir} (target: {target})...")
    print(f"{'='*60}")

    for verb in ("validate", "deploy"):
        print(f"\n--- {verb.title()} ---")
        result = subprocess.run(
            f"cd {bundle_dir} && {cli_path} bundle {verb} --target {target}",
            shell=True, text=True, capture_output=True, env=env,
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode != 0:
            raise RuntimeError(f"'databricks bundle {verb}' failed for {bundle_dir}")

    print(f"\nDeployed {bundle_dir.name} successfully.")