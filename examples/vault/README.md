# Example vault

A small, fictional Obsidian vault for demos and end-to-end tests. Nothing here is real personal data.

It covers ISO week **2026-W44** (Monday 2026-10-26 to Sunday 2026-11-01):

| Path | What it shows |
|---|---|
| `Daily/` | Daily notes with manual habits (`workout_min`, `reading_min`) and an `## AI log` section |
| `Notes/` | Notes with open and completed tasks (`✅ YYYY-MM-DD`), plus a `private: true` note the review skips |
| `Projects/` | Project notes with a `status` field |
| `Career/Applications.md` | Job applications as inline Dataview fields (`[status:: applied]`) |
| `Templates/Daily.md` | Template for new daily notes (excluded from the human zone) |
| `Agents/Reports/` | Last week's report, so the review can check continuity |

Try it on a copy, since both commands write into the vault and commit:

```sh
cp -r examples/vault /tmp/oab-demo && cd /tmp/oab-demo
git init -q && git add . && git commit -qm "example vault"
oab-collect --no-github --date 2026-10-28 --dry-run
oab-review --week 2026-W44 --dry-run
```
