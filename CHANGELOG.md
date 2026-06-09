# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

### Changed

### Fixed

## [1.0.0] - 2026-06-09

First public release of the `er` executor — the action half of the recipe-driven
provisioner for local AI engines.

### Added

- **Executor foundation (`er` CLI), stdlib-only.** Reads the verified recipe layer
  (`tensor-engine-knowledge/engines.db`, read-only), detects the live rig
  (`er rig` works with no recipe DB), and resolves a recipe against it — `rig` /
  `list` / `show` / `preflight`, all non-side-effecting. Recipe DB is located via
  `--db`, `$ER_RECIPES_DB`, or a relative default, with a clear error (not a stack
  trace) when missing.
- **Provision reconcile loop** (`provision` / `teardown` / `status`): resolve →
  lock → vendor → materialize → launch → measure. **Dry-run is the default** and
  prints the full plan — every side effect and its named compensator — before
  anything runs. The wired `--execute` path (gated behind `--execute` **and**
  `--model`) materializes the recipe's pinned artifacts into a per-instance
  directory under `ER_HOME` (never the global PATH), launches a local server bound
  to `127.0.0.1`, and measures it.
- **Ledger + compensators.** Every irreversible step is recorded on a ledger
  *before* it runs and carries a named, newest-first compensator, so a crashed run
  still has a rollback handle. Teardown is identity-verified — it only stops a PID
  that is alive *and* whose executable lives under our instance dir, so it never
  kills an unrelated process or a recycled PID.
- **Model + bound + VRAM measure gate.** The launched server is probed against the
  recipe's model-keyed baseline (bound-direction-aware) with an enforced VRAM
  ceiling; below baseline halts and rolls back.
- **Constraint evaluator** with a `(matcher, handler)` dispatch table and a `note`
  status — a constraint whose expression has no evaluator handler renders as
  `note` (with a footer count), legibly distinct from a deliberate `deferred`
  (re-checked at materialize) rather than silently passing.
- **97-test stdlib `unittest` suite** covering resolve, the backend providers, and
  the full provision path (download / materialize / launch / measure / teardown,
  including failure and rollback paths).
- **Control Panel prototype** (`app/`): a self-contained operator UI (mock data +
  timer-simulated side effects, faithful to the real JSON/WS API) to browse recipes
  and run them, with live telemetry, ANDON halts, and rollback. Built by a zero-dep
  builder into a single offline `dist/control-panel.html`, with a captured state
  gallery.
- **Operator docs:** README (with threat model), `executor/README.md`,
  `CONTRIBUTING.md` (the provider contract), and `design/data-contract.md` (the
  durable UI ↔ executor contract).

### Changed

- `er provision` is structured around a backend-agnostic orchestrator; the
  materialize / launch / probe bodies live in the `NativeWinCompile` provider.
  `preflight` shows a provider's real `match` result or `n/a — not implemented`
  for stubs, never a blank `YES` it cannot honor.

### Fixed

- The `conflicts_when cuda_toolkit>=13` gate now evaluates both the CUDA toolkit
  **and** the CUDA runtime and halts on an all-unknown CUDA state, instead of
  passing open on a live CUDA-13.x runtime when `nvcc` was absent.
- Teardown's identity-verified stop uses a tri-state CIM probe instead of the
  removed `wmic`, and the ledger only records `rolled-back` on a verified kill (or
  an already-gone process) — never a dishonest `rolled-back` over a live orphan.
- Downloads are atomic (`.part` + `os.replace` after a full sha256 verify, with a
  self-healing cache); launch raises an ANDON halt on a port already in use or a
  process that dies early (with a `server.log` tail), and the corrupt-ledger path
  degrades durably.

### Security

- `SECURITY.md` with the executor's trust boundary, the `--execute` side-effect
  surface, the "No secrets, no telemetry" statement, and supported-versions /
  private-advisory reporting. The README carries the matching threat-model section.
- The known Goal-1 gap is disclosed honestly: an unpinned artifact or placeholder
  sha is currently accepted without a content check, so the recipe DB and the
  artifact URLs it points at are trusted inputs until content-addressed vendoring
  lands.

[Unreleased]: https://github.com/mcp-tool-shop-org/engine-room/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mcp-tool-shop-org/engine-room/releases/tag/v1.0.0
