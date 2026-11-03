---
type: dashboard
tags: [dashboard]
---
# Dashboard

Needs the [Dataview](https://blacksmithgu.github.io/obsidian-dataview/) plugin. Run `oab-collect --no-github --date 2026-11-01 --days 7` first, so the daily notes of week 2026-W44 have metrics.

## Week 2026-W44, day by day

```dataview
TABLE WITHOUT ID file.link AS "Day", vault_commits AS "Vault commits",
  vault_notes_edited AS "Notes edited", tasks_completed AS "Tasks done",
  workout_min AS "Workout (min)", reading_min AS "Reading (min)"
FROM "Daily"
WHERE file.day AND file.day >= date(2026-10-26) AND file.day <= date(2026-11-01)
SORT file.day ASC
```

## Weekly totals

```dataview
TABLE WITHOUT ID Week, sum(nonnull(rows.vault_commits)) AS "Vault commits",
  sum(nonnull(rows.tasks_completed)) AS "Tasks done",
  sum(nonnull(rows.workout_min)) AS "Workout (min)",
  sum(nonnull(rows.reading_min)) AS "Reading (min)"
FROM "Daily"
WHERE file.day
GROUP BY dateformat(file.day, "kkkk-'W'WW") AS Week
SORT Week DESC
```

## Weekly reports

```dataview
TABLE WITHOUT ID file.link AS "Report", week AS "Week", summary AS "Summary"
FROM "Agents/Reports"
WHERE type = "agent"
SORT week DESC
```
