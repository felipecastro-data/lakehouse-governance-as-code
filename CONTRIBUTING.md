# Contributing

## Workflow

1. Branch from `main` (`feat/<topic>`, `fix/<topic>`, `docs/<topic>`).
2. Open a pull request with a conventional title: it becomes the commit subject on `main`. CI validates
   the policy, runs the tests, renders the plan and access matrix, validates the bundle for every target
   and checks the commit subjects and the PR title.
3. Squash-merge to `main` (the only merge method enabled), which deploys `dev` as the `gov-deployer`
   service principal. `main` is protected: no direct pushes, and the `Conventional commits` check must
   pass.
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
- One feature per PR, under ~300 changed lines. Generated files (`docs/generated/`) and images
  don't count.

Check before pushing:

```bash
make commits
```

The first commits on `main` (up to `5530500`) predate this convention and are left as they are:
rewriting published history would break every clone.
