ENV ?= dev
PY  ?= .venv/bin/python
# Don't rely on the editable-install .pth (macOS can flag it hidden, and Python 3.13+ skips hidden .pth files).
export PYTHONPATH := src
# Job id by name. Jobs run as their owner (the deployer), so anyone with CAN_MANAGE_RUN can start them
# without deploying the bundle as themselves.
job_id = $$(databricks jobs list --name $(1)-$(ENV) --output json | $(PY) -c "import json,sys; print(json.load(sys.stdin)[0]['job_id'])")

.PHONY: setup lint test validate plan matrix docs groups tags catalog drift pii scorecard erasure-check demo erase audit-views bundle-validate deploy apply pipeline

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

erasure-check:    ## registered erasure requests: residual rows and tables erasure can't reach in ENV
	$(PY) -m gov_engine erasure-check --env $(ENV)

demo:             ## scripted walkthrough: declare -> apply -> enforce -> verify -> measure (read-only)
	$(PY) -m gov_engine demo --env $(ENV)

erase:            ## erase a data subject in ENV: make erase ENV=dev REQUEST=DSR-0001 SUBJECT=C000042
	@test -n "$(REQUEST)" -a -n "$(SUBJECT)" || (echo "usage: make erase ENV=dev REQUEST=<id> SUBJECT=<customer_id>"; exit 1)
	databricks jobs run-now --json "{\"job_id\": $(call job_id,right-to-erasure), \
	  \"job_parameters\": {\"request_id\": \"$(REQUEST)\", \"subject_id\": \"$(SUBJECT)\"}}"

audit-views:      ## create the audit views over system tables in ENV (account admin, once per env)
	$(PY) -m gov_engine audit-views --env $(ENV)

bundle-validate:
	databricks bundle validate -t $(ENV)

deploy: catalog   ## create the catalog, then deploy the bundle to ENV
	databricks bundle deploy -t $(ENV)

apply: deploy     ## deploy, then apply governance policy in ENV
	databricks bundle run -t $(ENV) governance_apply

pipeline:         ## run the lakehouse pipeline in ENV (governance, data, checks, scorecard)
	databricks jobs run-now $(call job_id,lakehouse-pipeline)
