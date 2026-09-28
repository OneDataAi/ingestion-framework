# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# DBTITLE 1,Run the bundle generator
import sys
sys.path.insert(0, "/Workspace/Repos/ingestion-framework/ingestion-framework/generator")

from generate_bundles import load_config, generate

config = load_config()
generate(config)