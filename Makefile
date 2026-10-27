ENV ?= dev
PY  ?= .venv/bin/python
# Don't rely on the editable-install .pth (macOS can flag it hidden, and Python 3.13+ skips hidden .pth files).
export PYTHONPATH := src

.PHONY: setup lint test validate plan matrix docs groups tags bundle-validate deploy apply

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

bundle-validate:
	databricks bundle validate -t $(ENV)

deploy:           ## deploy bundle to ENV
	databricks bundle deploy -t $(ENV)

apply: deploy     ## deploy, then apply governance policy in ENV
	databricks bundle run -t $(ENV) governance_apply
