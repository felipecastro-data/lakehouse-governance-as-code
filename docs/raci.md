# RACI — data ownership

R = Responsible · A = Accountable · C = Consulted · I = Informed

| Activity | Platform admins | Domain stewards | Data engineers | Analysts | Auditors |
|---|---|---|---|---|---|
| Define classification levels & controls | A | R | C | I | C |
| Classify columns in a data contract | C | A/R | R | I | I |
| Approve access to confidential/restricted data | I | A/R | I | C | I |
| Change `access_policy.yml` | A | R (own domain) | C | I | I |
| Build/modify pipelines | I | C | A/R | I | – |
| Deploy to prod | A/R | I | C | I | I |
| Review drift & scorecard | R | A (own domain) | C | – | I |
| Audit access to restricted data | I | C | – | – | A/R |
| Execute right-to-erasure request | C | A | R | – | I |
