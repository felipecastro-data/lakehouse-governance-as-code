#!/usr/bin/env bash
# Create the groups declared in governance/access_policy.yml (one-time, needs admin).
# Free Edition: verify spike item 1 first — groups must be usable in Unity Catalog grants.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
export PYTHONPATH=src
for group in $("$PY" -m gov_engine principals); do
  if databricks groups list --filter "displayName eq '${group}'" --output json | grep -q "\"${group}\""; then
    echo "exists: ${group}"
  else
    databricks groups create --display-name "${group}" >/dev/null
    echo "created: ${group}"
  fi
done
