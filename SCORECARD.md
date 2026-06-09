# Scorecard

> Post-shipcheck snapshot of where engine-room stands against the gate.

**Repo:** engine-room
**Date:** 2026-06-09
**Type tags:** `[pypi]` `[cli]` (stdlib-only Python; not npm/mcp/vsix/desktop)
**Version:** 1.0.0 · **Tests:** 97 (stdlib `unittest`, all passing)

## Hard gates (A–D) — block release

| Category | Result | Notes |
|----------|--------|-------|
| A. Security | PASS | SECURITY.md (trust boundary, supported versions, private advisories) + README threat model; no secrets; no telemetry (stated); `--execute` gates the only rig-touching action (dry-run default); file ops scoped to per-instance dirs under `ER_HOME`. A7/A8 SKIP (not an MCP server). |
| B. Error Handling | PASS | Structured CLI errors (message + hint + exit codes); `cli.main` catches `RuntimeError` → `er: error:` (no raw stack); ANDON halts carry contrastive cause + recovery; exit codes 0/1/2 verified. B4–B7 SKIP (not mcp/desktop/vscode). |
| C. Operator Docs | PASS | README current; CHANGELOG (Keep a Changelog, released 1.0.0); LICENSE (MIT) + support status (README Support + SECURITY.md); `--help` accurate. C5 SKIP (single-verbosity by design, no secrets to redact, per-instance `run.log`); C6 SKIP (not mcp); C7 SKIP (focused tool — ops in README + handbook). |
| D. Shipping Hygiene | PASS | `verify.py` (tests + import smoke + `--help`); version 1.0.0 matches the `v1.0.0` tag; CI asserts the stdlib-only invariant (the ecosystem-appropriate dependency scan); `requires-python >=3.10`; clean wheel + sdist (`python -m build`). D4 SKIP (zero deps, no Dependabot per org rule); D5/D8/D9 SKIP (not npm/vsix/desktop). |

**Hard-gate verdict:** A–D all pass (checked or justified SKIP). Ready to tag `v1.0.0`.

## Soft gate (E) — Identity (does not block ship)

| Item | Status |
|------|--------|
| Logo in README header | ✅ done — centered logo + CI/MIT/Landing badges |
| Translations (ja/zh/es/fr/hi/it/pt-BR) | ✅ done — local TranslateGemma |
| Landing page (@mcptoolshop/site-theme) | ✅ done — live at mcp-tool-shop-org.github.io/engine-room/ + Starlight handbook |
| GitHub repo metadata (description, homepage, topics) | ✅ done |

All gates complete — `shipcheck audit` exits 0 (23 checked, 14 SKIP, 0 unchecked, 100%).
engine-room v1.0.0 is shipped: tag + GitHub release, landing page + handbook live, CI green.

## Evidence

- Test suite: `python -m unittest discover -s tests` → `Ran 97 tests … OK`.
- One-command verify: `python verify.py` → `VERIFY PASS` (exit 0).
- CI: `.github/workflows/ci.yml` — paths-gated, Python 3.11 + 3.12, runs the suite, asserts
  zero third-party deps, builds wheel + sdist.
