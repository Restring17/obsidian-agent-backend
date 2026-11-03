# Mutation testing

Branch coverage shows that the code runs. Mutation testing shows that the tests would
notice a bug: [mutmut](https://github.com/boxed/mutmut) changes the code one small step
at a time (a `<` becomes `<=`, a string gets `XX` around it, an argument is dropped) and
runs the test suite against each change. A mutant that no test catches **survives**.

## How it runs

- **Weekly, not blocking.** The [`Mutation testing`](../.github/workflows/mutation.yml)
  workflow runs every Monday and on demand (*Actions → Mutation testing → Run workflow*).
  The score and the survivors **not listed on this page** appear in the job summary, and
  the full list is kept as the `mutmut-results` artifact for 30 days.
- **Locally:**

  ```bash
  uv run mutmut run --max-children 4   # about a minute; mutants/ is git-ignored
  uv run mutmut results                # the survivors
  uv run mutmut show <name>            # the diff of one mutant
  ```

  The settings live in `[tool.mutmut]` in `pyproject.toml`. Coverage is turned off for
  mutant runs, because the normal suite already checks it.

## Results

| Run | Mutants | Killed | Timeout | Survived | Score |
|---|---|---|---|---|---|
| First run (2026-11-03) | 2208 | 2014 | 4 | 190 | 91.4 % |
| After reviewing survivors | 2208 | 2160 | 4 | 44 | 98.0 % |
| With `oab-timers` (#9) | 2630 | 2568 | 4 | 58 | 97.8 % |
| With exact commits (#24) | 2997 | 2913 | 4 | 80 | 97.3 % |

The score counts timeouts as caught: a mutant that makes the code hang is noticed.

**146 survivors were killed with new tests.** Most of them were gaps, not bugs:

- `--help` texts, the `--test` and `--force` flags through the CLI, and the exact error
  messages for wrong argument and config values;
- boundaries: `--date` today, a week that starts today, exactly 100 commits and exactly
  40 open tasks, and snapshots only for today and yesterday;
- the review's "today" follows the vault timezone, not the system one;
- the temporary file of an atomic write is hidden, sits next to the note and does not end in
  `.md`;
- one-character names in `git status`, a sorted list of files the agent should not have
  touched, and a day without data or with an unsafe path not stopping the next days;
- `run()` kills a command that exceeds its timeout.

For `oab-timers` (#9), 24 of its 38 first survivors were killed the same way. For example,
`systemd-analyze verify` without `--user` must really drop the flag, because CI has no
user session.

For exact commits (#24), a path that starts with `-` must not be read as an option, so
`--` before paths is tested; `ls-files --cached` lost its flag, which is the default anyway.

## Reviewed survivors (equivalent mutants)

The 80 survivors below cannot change behaviour, so no test can kill them. The weekly job
treats a survivor as reviewed when its name is on this page. Mutant numbers move when code
changes, so after a refactor the job may list some of them again: review them and update
this list.

### Text encoding: `"UTF-8"` or the default instead of `"utf-8"`

`"UTF-8"` is the same codec. The default (`encoding=None`) is the locale encoding, which is
UTF-8 on every supported platform (the C locale is coerced to UTF-8 by PEP 538 and 540).

```
obsidian_agent_backend.daily_note.x_atomic_write__mutmut_18
obsidian_agent_backend.daily_note.x_atomic_write__mutmut_22
obsidian_agent_backend.daily_note.x_atomic_write__mutmut_27
obsidian_agent_backend.daily_note.xǁDailyNoteǁfrom_template__mutmut_4
obsidian_agent_backend.daily_note.xǁDailyNoteǁfrom_template__mutmut_7
obsidian_agent_backend.daily_note.xǁDailyNoteǁ_read__mutmut_5
obsidian_agent_backend.daily_note.xǁDailyNoteǁ_read__mutmut_7
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_10
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_13
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_16
obsidian_agent_backend.review.x_load_template__mutmut_3
obsidian_agent_backend.review.x_load_template__mutmut_5
obsidian_agent_backend.review.x_load_template__mutmut_6
obsidian_agent_backend.review.x_load_template__mutmut_9
obsidian_agent_backend.review.x_validate_report__mutmut_5
obsidian_agent_backend.review.x_validate_report__mutmut_7
obsidian_agent_backend.review.xǁWeeklyReviewǁ_publish__mutmut_3
obsidian_agent_backend.review.xǁWeeklyReviewǁ_publish__mutmut_6
obsidian_agent_backend.sources.xǁVaultSourceǁ_applications__mutmut_7
obsidian_agent_backend.sources.xǁVaultSourceǁ_applications__mutmut_9
obsidian_agent_backend.sources.xǁVaultSourceǁcollect__mutmut_10
obsidian_agent_backend.sources.xǁVaultSourceǁcollect__mutmut_12
obsidian_agent_backend.timers.x__ours__mutmut_2
obsidian_agent_backend.timers.x__ours__mutmut_4
obsidian_agent_backend.timers.x_render__mutmut_47
obsidian_agent_backend.timers.x_render__mutmut_50
obsidian_agent_backend.timers.x_verify__mutmut_10
obsidian_agent_backend.timers.x_verify__mutmut_12
obsidian_agent_backend.timers.x_verify__mutmut_14
obsidian_agent_backend.tool_changes.x_daily_note_changes__mutmut_37
obsidian_agent_backend.tool_changes.x_daily_note_changes__mutmut_39
obsidian_agent_backend.weekly_context.xǁWeeklyContextǁ_read__mutmut_2
obsidian_agent_backend.weekly_context.xǁWeeklyContextǁ_read__mutmut_4
```

### Line endings: `newline=None` instead of `newline=""`

On POSIX the line separator is already `\n`, so no translation happens.

```
obsidian_agent_backend.daily_note.x_atomic_write__mutmut_19
obsidian_agent_backend.daily_note.x_atomic_write__mutmut_23
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_11
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_14
```

### Clean-up of the temporary file: `missing_ok=False`

The clean-up only runs after the temporary file was created and before it was renamed,
so the file always exists at that point.

```
obsidian_agent_backend.daily_note.x_atomic_write__mutmut_32
obsidian_agent_backend.daily_note.x_atomic_write__mutmut_34
```

### Output stream `None`

`print(..., file=None)` writes to `sys.stdout`, which is what the CLI passes.

```
obsidian_agent_backend.cli.x_collect_main__mutmut_89
obsidian_agent_backend.cli.x_review_main__mutmut_93
```

### Current time: `datetime.now(None)`

The result is converted with `.astimezone(config.timezone)`, and a naive local time stands
for the same instant, so the day is the same.

```
obsidian_agent_backend.cli.x_collect_main__mutmut_73
obsidian_agent_backend.cli.x_review_main__mutmut_80
```

### Upstream check: `--ABBREV-REF`, `--SYMBOLIC-FULL-NAME`, `@{U}`

Only the exit status of `git rev-parse ... @{u}` is used. Git accepts `@{U}`, and prints
an unknown upper-case "option" back as an argument while still resolving the upstream (or
failing without one).

```
obsidian_agent_backend.review.xǁWeeklyReviewǁ_publish__mutmut_101
obsidian_agent_backend.review.xǁWeeklyReviewǁ_publish__mutmut_103
obsidian_agent_backend.review.xǁWeeklyReviewǁ_publish__mutmut_105
```

### Values that are overwritten or normalised before use

- `_search`: the first page sets `total` before it is read.
- `_active_values`: values are case-folded, so `"APPLIED"` becomes `"applied"`.
- `parse_config`: `None` and `""` both mean "no prefix" for top-level key names.
- `read_frontmatter`: `""` and `"XXXX"` both parse to something that is not a mapping, so
  the result is `{}`.
- `_previous`: `test=None` is falsy, like `test=False`.
- `IsoWeek.__post_init__`: any weekday validates the same year and week number.
- `frontmatter_lines`: `"XXXX"` has no `:`, so like `""` it yields no key.
- `_publish`: the report's `redo` ignores its input, so its `before` is never read.

```
obsidian_agent_backend.config.x__active_values__mutmut_9
obsidian_agent_backend.config.x__active_values__mutmut_11
obsidian_agent_backend.config.x_parse_config__mutmut_2
obsidian_agent_backend.daily_note.x_read_frontmatter__mutmut_9
obsidian_agent_backend.daily_note.x_frontmatter_lines__mutmut_11
obsidian_agent_backend.daily_note.x_frontmatter_lines__mutmut_12
obsidian_agent_backend.review.xǁWeeklyReviewǁ_previous__mutmut_4
obsidian_agent_backend.review.xǁWeeklyReviewǁ_publish__mutmut_17
obsidian_agent_backend.sources.xǁGitHubSourceǁ_search__mutmut_2
obsidian_agent_backend.sources.xǁGitHubSourceǁ_search__mutmut_3
obsidian_agent_backend.week.xǁIsoWeekǁ__post_init____mutmut_7
```

### Inputs that git never produces

- `changed_paths`: tokens shorter than `XY path` only appear at the end of
  `git status -z` (the final empty token), so `break` and `continue` do the same.
- `changed_paths`: `X` is not a git status code, so `"XXRCXX"` matches what `"RC"` does.
- `_git`: commit hashes only separate one commit from the next in the log, and short
  hashes of one day's commits do not collide.

```
obsidian_agent_backend.exact_commit.x_changed_paths__mutmut_28
obsidian_agent_backend.exact_commit.x_changed_paths__mutmut_33
obsidian_agent_backend.sources.xǁVaultSourceǁ_git__mutmut_16
```

### Folder filter in `human_notes`

The check on top-level folders only skips walking folders such as `.git`. Every file is
filtered again with the same rule, so the result is the same (only slower). The probe file
name `_.md` is irrelevant because the zone only looks at folder names.

```
obsidian_agent_backend.sources.x_human_notes__mutmut_5
obsidian_agent_backend.sources.x_human_notes__mutmut_13
obsidian_agent_backend.sources.x_human_notes__mutmut_14
```

### Temporary names in `exact_commit`

The blob source file and the temporary index live in a fresh private folder that is
removed afterwards, so their names (and the folder prefix) are never seen by anyone.

```
obsidian_agent_backend.exact_commit.x_commit_exact__mutmut_12
obsidian_agent_backend.exact_commit.x_commit_exact__mutmut_13
obsidian_agent_backend.exact_commit.x_commit_exact__mutmut_14
obsidian_agent_backend.exact_commit.x_commit_exact__mutmut_20
obsidian_agent_backend.exact_commit.x_commit_exact__mutmut_21
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_1
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_2
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_3
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_7
obsidian_agent_backend.exact_commit.x_write_blob__mutmut_8
```

### `oab-timers`: values that cannot differ

- `install`: `zip(..., strict=...)` pairs the target paths with the units they were built
  from, so both lists always have the same length.
- `render`: `files(None)` infers the package of the calling module, which is the same
  `obsidian_agent_backend`.
- `unit_folder`: a missing `XDG_CONFIG_HOME` read as `None` or `"XXXX"` (empty or relative)
  falls back to `~/.config` exactly like `""`.

```
obsidian_agent_backend.timers.x_install__mutmut_21
obsidian_agent_backend.timers.x_install__mutmut_24
obsidian_agent_backend.timers.x_install__mutmut_25
obsidian_agent_backend.timers.x_render__mutmut_40
obsidian_agent_backend.timers.x_unit_folder__mutmut_3
obsidian_agent_backend.timers.x_unit_folder__mutmut_5
obsidian_agent_backend.timers.x_unit_folder__mutmut_8
```
