# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |
| < 0.1 | ❌ |

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub: **Security → Report a vulnerability** ([direct link](https://github.com/Restring17/obsidian-agent-backend/security/advisories/new)).

Include the version (`oab-review --version`), the command you ran and the smallest vault or prompt that reproduces it. You can expect a first answer within 7 days. Once a fix is released, the advisory is published with credit to you, unless you prefer otherwise.

## What counts as a vulnerability here

The design assumes the review agent may misbehave, for example because of prompt injection in a note. See the [security model](README.md#security-model). Reports are especially welcome when:

- the agent writes, edits or deletes any file other than its report, and the run still succeeds;
- the verification after the run can be bypassed, or a commit includes changes the tools did not write;
- the agent gets a shell, network access or sub-agents despite the tool flags;
- any command runs through a shell, or with an executable or path that the user did not intend;
- a configuration value (`oab.toml`) can make the tools read or write outside the vault.

## Out of scope

These are documented limits, not vulnerabilities:

- The agent can **read** any file the tools can reach, including notes marked `private: true`.
- The commit bypasses git hooks and signing.
- A failed check does not roll back the files; it only prevents the commit.
- Flaws in Claude Code itself: report those to [Anthropic](https://www.anthropic.com/responsible-disclosure-policy).
