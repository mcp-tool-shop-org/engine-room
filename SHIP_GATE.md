# Ship Gate

> No repo is "done" until every applicable line is checked.
> Copy this into your repo root. Check items off per-release.

**Tags:** `[all]` every repo · `[npm]` `[pypi]` `[vsix]` `[desktop]` `[container]` published artifacts · `[mcp]` MCP servers · `[cli]` CLI tools

**Repo:** engine-room · **Type:** `[pypi]` `[cli]` (stdlib-only Python; not npm/mcp/vsix/desktop) · **Version:** 1.0.0 · **Date:** 2026-06-09

---

## A. Security Baseline

- [x] `[all]` SECURITY.md exists (report path, supported versions, response posture) (2026-06-09)
- [x] `[all]` README includes threat model paragraph (data touched, data NOT touched, permissions required) (2026-06-09)
- [x] `[all]` No secrets, tokens, or credentials in source or diagnostics output (2026-06-09)
- [x] `[all]` No telemetry by default — stated explicitly in SECURITY.md ("No secrets, no telemetry") (2026-06-09)

### Default safety posture

- [x] `[cli|mcp|desktop]` Dangerous actions require an explicit flag — `--execute` gates the only rig-touching action (dry-run is the default); teardown is explicit; the wsl-update path is human-gated (2026-06-09)
- [x] `[cli|mcp|desktop]` File operations constrained to known directories — per-instance dirs under `ER_HOME`, never the global PATH (2026-06-09)
- [ ] `[mcp]` SKIP: not an MCP server — no network egress surface (the only network access is artifact downloads on the explicit `--execute` path)
- [ ] `[mcp]` SKIP: not an MCP server — CLI structured errors are covered under section B

## B. Error Handling

- [x] `[all]` Structured Error Shape — CLI errors carry a message + hint + exit codes; ANDON halts carry a contrastive cause + recovery; no raw stacks on deliberate error paths (2026-06-09)
- [x] `[cli]` Exit codes: 0 ok · 1 user/runtime error · 2 halt — verified in the suite (2026-06-09)
- [x] `[cli]` No raw stack traces without `--debug` — `cli.main` catches `RuntimeError` → structured `er: error:`; deliberate error paths never raw-stack (2026-06-09)
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[desktop]` SKIP: not a desktop app
- [ ] `[vscode]` SKIP: not a VS Code extension

## C. Operator Docs

- [x] `[all]` README is current — what it does, install, usage, supported platforms + runtime versions (2026-06-09)
- [x] `[all]` CHANGELOG.md (Keep a Changelog format) with a released 1.0.0 entry (2026-06-09)
- [x] `[all]` LICENSE present (MIT) and repo states support status (README Support section + SECURITY.md supported versions) (2026-06-09)
- [x] `[cli]` `--help` output accurate for all commands and flags (2026-06-09)
- [ ] `[cli|mcp|desktop]` SKIP: single-verbosity CLI by design — no secrets in output to redact; the per-instance `run.log` gives debug-level detail on the side-effecting path
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[complex]` SKIP: focused tool — daily ops (provision/teardown/status) are covered in the README and the Starlight handbook, not a separate HANDBOOK.md

## D. Shipping Hygiene

- [x] `[all]` `verify` script exists — `python verify.py` (tests + import smoke + `--help`, one command) (2026-06-09)
- [x] `[all]` Version in manifest matches git tag — 1.0.0 (`v1.0.0` tag cut at release) (2026-06-09)
- [x] `[all]` Dependency scanning runs in CI — CI asserts the stdlib-only invariant (zero third-party deps), the ecosystem-appropriate check for a zero-dep tool (2026-06-09)
- [ ] `[all]` SKIP: stdlib-only — zero dependencies to update, so Dependabot is omitted per the org GitHub Actions rule (no `dependabot.yml`)
- [ ] `[npm]` SKIP: not an npm package
- [x] `[pypi]` `requires-python` set — `>=3.10` (2026-06-09)
- [x] `[pypi]` Clean wheel + sdist build — `python -m build` succeeds (2026-06-09)
- [ ] `[vsix]` SKIP: not a VS Code extension
- [ ] `[desktop]` SKIP: not a desktop app

## E. Identity (soft gate — does not block ship)

- [x] `[all]` Logo in README header (2026-06-09)
- [x] `[all]` Translations (polyglot-mcp — ja/zh/es/fr/hi/it/pt-BR) (2026-06-09)
- [x] `[org]` Landing page (@mcptoolshop/site-theme — live) (2026-06-09)
- [x] `[all]` GitHub repo metadata: description, homepage, topics (2026-06-09)

---

## Gate Rules

**Hard gate (A–D):** Must pass before any version is tagged or published.
If a section doesn't apply, mark `SKIP:` with justification — don't leave it unchecked.

**Soft gate (E):** Should be done. Product ships without it, but isn't "whole."
Section E is completed in the later treatment phases.

**Checking off:**
```
- [x] `[all]` SECURITY.md exists (2026-02-27)
```

**Skipping:**
```
- [ ] `[pypi]` SKIP: not a Python project
```
