# Contributing

## Workflow

1. Branch from `main` (`feat/<topic>`, `fix/<topic>`, `docs/<topic>`).
2. Open a pull request. CI validates the policy, runs the tests, renders the plan and access matrix,
   validates the bundle for every target and checks the commit subjects.
3. Merge to `main`, which deploys `dev` as the `gov-deployer` service principal.
4. Promote with the `deploy` workflow (`target: prod`): dev → test → prod on the same commit, prod behind
   an environment approval ([ADR-0011](docs/adr/0011-three-stage-promotion.md)).

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>): <summary>`.

| Type | Use for |
|---|---|
| `feat` | New behaviour: a policy capability, a job, an environment |
| `fix` | A bug in the engine, a job or a resource |
| `docs` | ADRs, design docs, README |
| `ci` | GitHub Actions workflows |
| `test` | Tests only |
| `refactor` / `perf` | No behaviour change / faster |
| `build` / `chore` | Packaging, tooling, housekeeping |

Scopes follow the repo layout: `engine`, `jobs`, `bundle`, `governance`, `deploy`, `readme`, `adr`, `design`.

- Summary in the imperative, at most 72 characters, no trailing period.
- The body says **why**, especially for Free Edition workarounds.
- One concern per commit (engine, jobs, resources, tests, docs), under ~500 changed lines.
  Generated files (`docs/generated/`) and images don't count.

Check before pushing:

```bash
make commits
```

The first commits on `main` (up to `5530500`) predate this convention and are left as they are:
rewriting published history would break every clone.
