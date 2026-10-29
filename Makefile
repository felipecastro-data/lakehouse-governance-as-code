ENV ?= dev
PY  ?= .venv/bin/python
# Don't rely on the editable-install .pth (macOS can flag it hidden, and Python 3.13+ skips hidden .pth files).
export PYTHONPATH := src

.PHONY: setup lint test validate plan matrix docs groups tags catalog drift pii scorecard audit-views bundle-validate deploy apply

setup:            ## create .venv and install dev dependencies
	python3 -m venv .venv && $(PY) -m pip install -q -e ".[dev]"

lint:
	$(PY) -m ruff check src tests

test:
	$(PY) -m pytest -q

validate:         ## validate governance/*.yml
	$(PY) -m gov_engine validate

plan:             ## print SQL for ENV (make plan ENV=prod)
	$(PY) -m gov_engine plan --env $(ENV)

matrix:           ## print the access matrix for ENV
	$(PY) -m gov_engine matrix --env $(ENV)

docs:             ## regenerate docs/generated/
	$(PY) -m gov_engine matrix --env prod > docs/generated/access-matrix-prod.md
	$(PY) -m gov_engine plan --env prod > docs/generated/plan-prod.sql

groups:           ## create missing account groups (needs `databricks auth login`)
	$(PY) -m gov_engine sync-groups

tags:             ## create/update governed tags (needs `databricks auth login`)
	$(PY) -m gov_engine sync-tags

catalog:          ## create the ENV catalog via SQL (Default Storage rejects the bundle catalogs API)
	$(PY) -m gov_engine ensure-catalog --env $(ENV)

drift:            ## declared vs actual state in ENV; complete only as the catalog owner
	$(PY) -m gov_engine drift --env $(ENV)

pii:              ## untagged columns fed by PII in ENV (column lineage)
	$(PY) -m gov_engine pii-propagation --env $(ENV)

scorecard:        ## print the governance scorecard for ENV; complete only as the catalog owner
	$(PY) -m gov_engine scorecard --env $(ENV)

audit-views:      ## create the audit views over system tables in ENV (account admin, once per env)
	$(PY) -m gov_engine audit-views --env $(ENV)

bundle-validate:
	databricks bundle validate -t $(ENV)

deploy: catalog   ## create the catalog, then deploy the bundle to ENV
	databricks bundle deploy -t $(ENV)

apply: deploy     ## deploy, then apply governance policy in ENV
	databricks bundle run -t $(ENV) governance_apply
