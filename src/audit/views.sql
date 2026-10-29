-- Curated views over system tables for one catalog (docs/adr/0009-audit-views-and-scorecard.md).
-- Run by an account admin, once per environment and after every change: `make audit-views ENV=dev`.
-- Only account admins can read system.access, and nobody can grant it further. A view reads its source
-- with its owner's access, so the admin owns these views and readers need only SELECT on them:
-- gov-auditors get it through their grant on the audit schema and never touch system.*.
-- {{catalog}} is the environment's catalog; {{deployer}} is its owner, the gov-deployer service principal.

CREATE OR REPLACE VIEW {{catalog}}.audit.column_lineage
COMMENT 'Column lineage into {{catalog}}, from system.access.column_lineage. Owned by an account admin (ADR-0008, ADR-0009).'
AS SELECT * FROM system.access.column_lineage WHERE target_table_catalog = '{{catalog}}';

-- The pii_propagation task reads lineage as the deployer (ADR-0008). Drift ignores grants to the catalog owner.
GRANT SELECT ON VIEW {{catalog}}.audit.column_lineage TO `{{deployer}}`;

-- One row per table read or write, from table lineage. `by_pipeline` marks the deployer's own jobs.
CREATE OR REPLACE VIEW {{catalog}}.audit.table_access
COMMENT 'Reads and writes of {{catalog}} tables by principal, from system.access.table_lineage (ADR-0009).'
AS
SELECT DISTINCT event_time, event_date, created_by AS principal, created_by = '{{deployer}}' AS by_pipeline,
       'read' AS access, source_table_full_name AS table_full_name, source_table_schema AS table_schema,
       entity_type, entity_id, statement_id
FROM system.access.table_lineage
WHERE source_table_catalog = '{{catalog}}' AND source_table_schema <> 'information_schema'
UNION ALL
SELECT DISTINCT event_time, event_date, created_by, created_by = '{{deployer}}',
       'write', target_table_full_name, target_table_schema,
       entity_type, entity_id, statement_id
FROM system.access.table_lineage
WHERE target_table_catalog = '{{catalog}}';

-- One row per principal per GRANT/REVOKE on the catalog or anything in it. `by_engine` marks gov_engine's
-- own applies (it re-grants the declared state on every run); the rest are people.
CREATE OR REPLACE VIEW {{catalog}}.audit.grant_changes
COMMENT 'GRANT and REVOKE on {{catalog}} securables, from system.access.audit (ADR-0009).'
AS
SELECT a.event_time, a.event_date, a.user_identity.email AS actor, a.user_identity.email = '{{deployer}}' AS by_engine,
       a.request_params['securable_type'] AS securable_type, a.request_params['securable_full_name'] AS securable,
       c.principal, coalesce(c.add, array()) AS added, coalesce(c.remove, array()) AS removed,
       a.response.status_code AS status_code
FROM system.access.audit a
LATERAL VIEW explode(from_json(a.request_params['changes'],
                               'array<struct<principal:string, add:array<string>, remove:array<string>>>')) t AS c
WHERE a.service_name = 'unityCatalog' AND a.action_name = 'updatePermissions'
  AND (a.request_params['securable_full_name'] = '{{catalog}}'
       OR a.request_params['securable_full_name'] LIKE '{{catalog}}.%');

-- ABAC policy create/update/delete on the catalog. gov_engine runs CREATE OR REPLACE on every apply.
CREATE OR REPLACE VIEW {{catalog}}.audit.policy_changes
COMMENT 'ABAC policy changes on {{catalog}}, from system.access.audit (ADR-0009).'
AS
SELECT event_time, event_date, user_identity.email AS actor, user_identity.email = '{{deployer}}' AS by_engine,
       regexp_replace(action_name, 'Policy$', '') AS action, request_params['name'] AS policy_name,
       get_json_object(request_params['policy_info'], '$.policy_type') AS policy_type,
       from_json(get_json_object(request_params['policy_info'], '$.except_principals'), 'array<string>')
         AS except_principals,
       response.status_code AS status_code
FROM system.access.audit
WHERE service_name = 'unityCatalog' AND action_name IN ('createPolicy', 'updatePolicy', 'deletePolicy')
  AND request_params['on_securable_fullname'] = '{{catalog}}';

-- Requests on the catalog that Unity Catalog refused: someone tried to reach data they may not see.
CREATE OR REPLACE VIEW {{catalog}}.audit.access_denied
COMMENT 'Denied Unity Catalog requests on {{catalog}} securables, from system.access.audit (ADR-0009).'
AS
SELECT event_time, event_date, user_identity.email AS principal, action_name,
       coalesce(request_params['full_name_arg'], request_params['table_full_name'],
                request_params['securable_full_name'], request_params['on_securable_fullname'],
                request_params['name_arg'], request_params['name']) AS securable,
       response.status_code AS status_code, response.error_message AS error_message
FROM system.access.audit
WHERE service_name = 'unityCatalog' AND response.status_code IN ('401', '403')
  AND to_json(request_params) LIKE '%{{catalog}}%';
