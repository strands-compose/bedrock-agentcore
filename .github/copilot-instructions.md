# strands-compose-agentcore — Copilot Instructions

**Read `AGENTS.md` in the repository root** — it is the single source of truth
for all project rules, architecture, Python conventions, logging style, key APIs,
directory structure, and tooling commands.

This file provides supplementary context for Copilot.
Do not duplicate rules from `AGENTS.md` here.

## Quick Reference

This is **strands-compose-agentcore**: a deployment adapter that runs
[strands-compose](https://github.com/strands-compose/sdk-python) YAML configs
on [AWS Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/).

## Custom Agents

Specialized agents are defined in `.github/agents/`.
Select the right one for your task:

| Agent | Purpose | Tool Access |
|-------|---------|-------------|
| `developer` | Implement features and fix bugs | read, edit, search, execute, agent |
| `reviewer` | Review PRs for correctness and compliance | read, search, execute (read-only) |
| `tester` | Write and improve tests | read, edit, search, execute |
| `docs-writer` | Write and update documentation | read, edit, search, execute |

## Skills

Skills in `.github/skills/` are **automatically activated** when relevant:

| Skill | Triggered When |
|-------|---------------|
| `check-and-test` | Validating, linting, testing, or checking code quality |
| `strands-api-lookup` | Working with strands/strands-compose APIs, checking upstream functionality |

## Path-Specific Instructions

Targeted rules in `.github/instructions/` are applied automatically based on file paths:

| File | Applies To |
|------|-----------|
| `source.instructions.md` | `src/**/*.py` |
| `tests.instructions.md` | `tests/**/*.py` |
| `examples.instructions.md` | `examples/**/*.py`, `examples/**/*.yaml` |
| `docs.instructions.md` | `docs/**/*.md` |
