# Project Tasks

Just tasks for common project operations, one file per concern.

`just --list` is the authoritative task list — it reads the recipes directly, so
it can never drift from what actually exists.

```bash
uv run just --list          # every task, grouped
uv run just <task>          # run one
```

| File | Covers |
|------|--------|
| `check.just` | format, lint, type, security, test gates |
| `format.just` | auto-format source, tests, examples, and markdown code blocks |
| `test.just` | pytest with the coverage gate; mutation testing |
| `clean.just` | build artifacts and tool caches |
| `install.just` | dependencies and git hooks |
| `commit.just` | Commitizen commits, version bumps, pre-commit hooks |
| `release.just` | build and publish distribution artifacts |

The two you need day to day:

```bash
uv run just check           # the gate — must pass before a change is done
uv run just test            # pytest with the coverage gate
```

If `check` fails on formatting or import order, run `uv run just format` first.

## First-time setup

```bash
uv run just install         # dependencies + git hooks
```

Just itself comes from the dev dependency group (`rust-just`), so `uv run just`
works without a system install.
