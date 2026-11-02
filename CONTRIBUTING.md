# Contributing

This project follows a **Scrumban** workflow on GitHub with **GitFlow** branches.

## Planning

- **Backlog:** every piece of work is an [issue](../../issues) with a *Definition of Done*.
- **Sprints:** one-week [milestones](../../milestones), Monday to Sunday, also mirrored as the *Iteration* field of the project board.
- **Board:** Backlog → Ready → In progress → In review → Done. Keep **at most 2 items in progress**.
- **Labels:**
  - `type:*`: what kind of work (`feature`, `bug`, `chore`, `docs`, `ci`, `test`).
  - `area:*`: which part (`collector`, `review`, `config`, `infra`).
  - `priority:*`: `p0` must ship this sprint, `p1` should ship, `p2` nice to have.
  - `ready-for-agent` / `ready-for-human`: an AI coding agent can implement it from the issue alone, or it needs a person.

## Branches

```
main      ← releases only (tagged vX.Y.Z)
develop   ← integration branch
feature/<issue>-<slug>, fix/<issue>-<slug>, docs/…, ci/…, chore/…   → PR into develop
hotfix/<slug>   → from main, PR into main and back into develop
```

- No direct pushes to `main` or `develop`; both are protected by rulesets.
- Start work from the issue: `gh issue develop <n> --base develop --checkout`.
- Open the PR into `develop` with `Closes #<n>` in the description.
- Merge only when CI is green.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`, `refactor:`. Example: `feat(collector): read metrics from the GitHub search API`.

## Releases

At the end of a sprint, if there is something to ship:

1. Open a PR `develop → main` titled `Release vX.Y.Z` with a summary.
2. After merging: `gh release create vX.Y.Z --target main --generate-notes`.

Versioning follows [SemVer](https://semver.org/). Before `1.0.0`, minor versions may break compatibility.

## Definition of Done (every PR)

- [ ] Tests for success paths and edge cases; branch coverage ≥ 90 %.
- [ ] `ruff`, `mypy` and `bandit` pass.
- [ ] Inputs validated and no internal errors leaked.
- [ ] Docs updated if behavior or configuration changed.
