# obsidian-agent-backend

> 🚧 **Work in progress.** Follow the progress on the [project board](https://github.com/users/Restring17/projects/2) and in the [milestones](../../milestones).

Turn an [Obsidian](https://obsidian.md) vault into a **backend for AI agents**: you capture and decide, and the tooling collects facts, keeps them structured and writes a weekly review.

## What it does

- **Daily collector:** gathers exact metrics (GitHub commits, repos and PRs; vault commits; completed and open tasks) and writes them to the frontmatter of your daily note, so Dataview dashboards can query them. No LLM involved: the numbers are deterministic.
- **Weekly review agent:** runs `claude -p` under **least privilege**. It can read notes and write exactly one file, its report, with no shell and no web access. The data is computed beforehand, so the model never invents numbers. Afterwards the tool checks with `git status` that nothing else changed and validates the report before committing it.

## Configuration

Copy [`oab.example.toml`](oab.example.toml) to your vault root as `oab.toml` and adjust it: daily-notes folder and template, the folders you own (*human zone*), the agent folder, timezone, manual metrics, an optional applications note and the review model. Every key has a default and paths cannot leave the vault. Both commands read `./oab.toml` (or `--config PATH`) and exit with code 2 and a one-line message if the file is invalid, for example on an unknown key or timezone.

A fictional vault in [`examples/vault`](examples/vault) shows a working setup and is used by the end-to-end tests.

## Daily collector

```sh
oab-collect                       # yesterday, in the configured timezone
oab-collect --date 2026-11-02 --days 7 --dry-run
oab-collect --no-github           # vault metrics only
```

It writes these keys to the frontmatter of `<daily_notes.folder>/YYYY-MM-DD.md`, creating the note from the template only if the day had activity:

| Key | Source |
|---|---|
| `github_commits`, `github_repos`, `github_prs` | GitHub search API through `gh` (private repos included) |
| `vault_commits`, `vault_notes_edited` | `git log` of the vault |
| `tasks_completed` | `- [x] … ✅ YYYY-MM-DD` tasks in the human zone |
| `tasks_open`, `applications_active` | current state; written only for today and yesterday |
| `collected_at` | timestamp of the run |

Only those lines change: the body and every other key stay as they were, and the file is replaced atomically. If a source fails, its keys are left untouched (never written as zero) and the command exits with code 1.

## Weekly review

```sh
oab-review --dry-run              # print the prompt for last week, no model call
oab-review                        # last ISO week, in the configured timezone
oab-review --week 2026-W45 --model opus --force
oab-review --test                 # write a "(test)" report, no log or commit
```

The tool computes the week's data (metrics per day with totals, AI log, vault commits, open tasks, applications, projects) and passes it to `claude -p`. The agent can only `Read`, `Glob` and `Grep`, plus `Write`/`Edit` on `<agent.folder>/Reports/<week> Weekly review.md`. Bash and web tools are disallowed. Afterwards:

1. `git status --porcelain -z` and content hashes check that no other file changed, including files that were already modified before the run. Otherwise the run fails and nothing is committed.
2. The report frontmatter must have `type: agent`, the right `week` and a `summary`.
3. One line is logged in today's daily note, and only the report and the daily notes are committed (`git commit -- <paths>`, so anything you staged stays out). The tool pushes only if the branch has an upstream.

Notes whose frontmatter has `private: true` (the key is configurable) are left out of the data.

## Scheduling

`oab-timers` runs both commands for you with **systemd user timers** (Linux), with no cron and no root:

```sh
oab-timers print                  # show the four unit files, change nothing
oab-timers install                # write them to ~/.config/systemd/user and enable them
systemctl --user list-timers 'oab-*'
oab-timers uninstall              # disable both timers and remove the files
```

- `oab-collect.timer` runs every day at 09:00 and collects yesterday plus the two previous days.
- `oab-review.timer` runs every Monday at 09:30. It first refreshes the metrics of the past 8 days; if that fails, the review still runs.
- Both timers have `Persistent=true`: when the PC was off at that time, the run happens at the next boot.
- Times are in the **vault timezone** from `oab.toml`, not the system one. Change them with `--collect-at` and `--review-at`, which take [systemd calendar expressions](https://www.freedesktop.org/software/systemd/man/latest/systemd.time.html#Calendar%20Events) such as `"Mon..Fri *-*-* 07:30"`.
- `--no-github` makes the daily collector skip GitHub.
- The services get a minimal `PATH`: the folders of `oab-*`, `git`, `gh` and `claude` found at install time, plus the system folders. Re-run `oab-timers install` if you move them.
- The units are checked with `systemd-analyze --user verify` before anything is written. `install` and `uninstall` only replace or remove files they generated (marked with a header comment); use `--force` to replace your own.
- Logs: `journalctl --user -u oab-collect -u oab-review`.

To pause without uninstalling, run `systemctl --user disable --now oab-collect.timer oab-review.timer`. The units are templates in [`src/obsidian_agent_backend/systemd/`](src/obsidian_agent_backend/systemd), so you can also install them by hand.

## Status

| Milestone | Goal |
|---|---|
| Sprint 1 | Project setup, CI and configurable daily collector |
| Sprint 2 | Weekly review agent, example vault and mutation testing |
| Sprint 3 | Documentation, scheduling and first release `v0.1.0` |

## Quality bar

- ≥ 90 % branch coverage, enforced in CI.
- Mutation testing (`mutmut`) every Monday, non-blocking: score 98 %, every survivor reviewed in [docs/mutation-testing.md](docs/mutation-testing.md).
- Dependabot opens weekly PRs into `develop` for Python packages and GitHub Actions.
- Static analysis: `ruff`, `mypy`, `bandit`; secret scanning with `gitleaks`.

## Development

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                    # create .venv with the dev tools
uv run pytest              # tests + branch coverage (fails under 90 %)
uv run pytest -m e2e       # end-to-end only: examples/vault, real git, fake gh and claude
uv run ruff check          # lint
uv run mypy                # strict type checking
uv run bandit -c pyproject.toml -r src
uv run mutmut run          # mutation testing (about a minute); see docs/mutation-testing.md
uv tool install .          # exposes oab-collect, oab-review and oab-timers
```

## Contributing

The workflow (Scrumban sprints, GitFlow branches and Conventional Commits) is described in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Adrian Ramírez
