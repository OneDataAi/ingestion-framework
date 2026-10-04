# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# DBTITLE 1,Generate selected domain bundle
import sys
import importlib

sys.path.insert(0, "/Workspace/Repos/ingestion-framework/ingestion-framework/generator")

# Force reimport so code changes are picked up without restarting the cluster
for mod_name in ["common", "generate_bundles"]:
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])

from generate_bundles import load_config, generate

config = load_config()

# 'domain' must be passed as a parameter at runtime — no default.
# Usage:
#   Job task parameter:          {"domain": "oncology"}
#   From another notebook:       dbutils.notebook.run("run_generator", 600, {"domain": "oncology"})
#   Interactive (Run All → Parameters): domain = oncology
domain = dbutils.widgets.get("domain")
if not domain.strip():
    raise ValueError("'domain' parameter is required but was empty.")

config["domain"] = domain.strip()
print(f"Generating bundle for domain: {config['domain']}\n")
bundle_dirs = generate(config)

# Write bundle paths for the shell deploy cell
with open("/tmp/bundle_dirs.txt", "w") as f:
    for d in bundle_dirs:
        f.write(str(d) + "\n")
print(f"\n{len(bundle_dirs)} bundle(s) ready for deployment.")

# COMMAND ----------

# DBTITLE 1,Deploy bundle
import subprocess, os, stat, zipfile, urllib.request, platform, re, json, requests

# Params
dbutils.widgets.text("domain", "")
dbutils.widgets.text("target", "dev")
domain = dbutils.widgets.get("domain").strip()
target = dbutils.widgets.get("target").strip() or "dev"
assert domain, "'domain' parameter is required."
bundle_dir = f"/Workspace/Repos/ingestion-framework/ingestion-framework/bundles/{domain}"

# Install CLI + Terraform (one-time, needed because neither is on PATH in notebooks)
arch = "linux_arm64" if platform.machine() == "aarch64" else "linux_amd64"
bin_dir = os.path.expanduser("~/bin")
os.makedirs(bin_dir, exist_ok=True)
CLI, TF = f"{bin_dir}/databricks", f"{bin_dir}/terraform"

for binary, url in [
    (CLI, f"https://github.com/databricks/cli/releases/download/v1.18.0/databricks_cli_1.18.0_{arch}.zip"),
    (TF,  f"https://releases.hashicorp.com/terraform/1.5.7/terraform_1.5.7_{arch}.zip"),
]:
    if not os.path.isfile(binary):
        zp = f"/tmp/{os.path.basename(binary)}.zip"
        urllib.request.urlretrieve(url, zp)
        with zipfile.ZipFile(zp) as z:
            z.extract(os.path.basename(binary), bin_dir)
        os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
        print(f"Installed {os.path.basename(binary)}")

# Auth
env = os.environ.copy()
env["DATABRICKS_TF_EXEC_PATH"] = TF
if target == "prod":
    for k in ("DATABRICKS_HOST", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        env[k] = dbutils.widgets.get(k).strip()
else:
    env["DATABRICKS_HOST"]  = f"https://{spark.conf.get('spark.databricks.workspaceUrl')}"
    env["DATABRICKS_TOKEN"] = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()

# Deploy  (≈ databricks bundle deploy -t <target>)
def run(cmd):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True, env=env)
    if r.stdout: print(r.stdout)
    if r.stderr: print(r.stderr)
    return r.returncode, (r.stdout or "") + (r.stderr or "")

deploy_cmd = f"cd {bundle_dir} && {CLI} bundle deploy --target {target}"
rc, out = run(deploy_cmd)

# Auto-fix: if pipelines already exist (state drift), bind them into bundle state and retry
if rc != 0 and "RESOURCE_CONFLICT" in out:
    host = env["DATABRICKS_HOST"]
    if "DATABRICKS_TOKEN" in env:
        hdrs = {"Authorization": f"Bearer {env['DATABRICKS_TOKEN']}"}
    else:
        tok = requests.post(f"{host}/oidc/v1/token", data={
            "grant_type": "client_credentials",
            "client_id": env["DATABRICKS_CLIENT_ID"],
            "client_secret": env["DATABRICKS_CLIENT_SECRET"],
            "scope": "all-apis",
        }).json()
        hdrs = {"Authorization": f"Bearer {tok['access_token']}"}

    # Parse resource keys + pipeline names from Terraform errors
    conflicts = re.findall(
        r"resources\.pipelines\.(\S+?):\s.*?name '([^']+)' (?:already exists|is already used)", out)
    for res_key, pipeline_name in conflicts:
        try:
            # Suffix filter avoids LIKE interpreting [] as char class
            core = pipeline_name.split("] ", 1)[-1] if "] " in pipeline_name else pipeline_name
            data = requests.get(f"{host}/api/2.0/pipelines", headers=hdrs,
                                params={"filter": f"name LIKE '%{core}'"}).json()
            for p in data.get("statuses", []):
                if p.get("name") == pipeline_name:
                    pid = p["pipeline_id"]
                    r = subprocess.run(
                        f"cd {bundle_dir} && {CLI} bundle deployment bind {res_key} {pid} --auto-approve --target {target}",
                        shell=True, text=True, capture_output=True, env=env)
                    if r.returncode == 0:
                        print(f"Bound '{pipeline_name}' ({pid}) -> {res_key}")
                    else:
                        print(f"Bind failed for {res_key}: {r.stderr.strip()}")
        except Exception as e:
            print(f"Could not resolve '{pipeline_name}': {e}")
    print("Retrying deploy...")
    rc, out = run(deploy_cmd)

if rc != 0:
    raise RuntimeError(f"Deploy failed:\n{out}")
print(f"✓ '{domain}' deployed (target: {target})")