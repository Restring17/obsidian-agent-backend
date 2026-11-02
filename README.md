# obsidian-agent-backend

> 🚧 **Work in progress.** Follow the progress on the [project board](https://github.com/users/Restring17/projects) and in the [milestones](../../milestones).

Turn an [Obsidian](https://obsidian.md) vault into a **backend for AI agents**: you capture and decide, and the tooling collects facts, keeps them structured and writes a weekly review.

## What it does

- **Daily collector:** gathers exact metrics (GitHub commits, repos and PRs; vault commits; completed and open tasks) and writes them to the frontmatter of your daily note, so Dataview dashboards can query them. No LLM involved: the numbers are deterministic.
- **Weekly review agent:** runs `claude -p` under **least privilege**. It can read notes and write exactly one file, its report, with no shell and no web access. The data is computed beforehand, so the model never invents numbers. Afterwards the tool checks with `git status` that nothing else changed and validates the report before committing it.

## Status

| Milestone | Goal |
|---|---|
| Sprint 1 | Project setup, CI and configurable daily collector |
| Sprint 2 | Weekly review agent, example vault and mutation testing |
| Sprint 3 | Documentation, scheduling and first release `v0.1.0` |

## Quality bar

- ≥ 90 % branch coverage, enforced in CI.
- Mutation testing (`mutmut`) every week.
- Static analysis: `ruff`, `mypy`, `bandit`; secret scanning with `gitleaks`.

## Contributing

The workflow (Scrumban sprints, GitFlow branches and Conventional Commits) is described in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Adrian Ramírez
