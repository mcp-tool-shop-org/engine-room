---
title: Command Reference
description: The complete er command surface — rig, list, show, preflight, provision, teardown, status — every flag, the global --db option, and exit codes.
sidebar:
  order: 3
---

The full command surface of `er` (equivalently `python -m executor.cli`). Everything here is
grounded in `er --help` and each subcommand's `--help`. **There are no flags beyond the ones
documented below.**

## Synopsis

```
er [-h] [--db DB] {rig,list,show,preflight,provision,teardown,status} …
```

`er` is `executor.cli:main` — installed as a console script by `pip install -e .`, or run as
`python -m executor.cli`.

## Global options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | show help and exit (available on the top-level command and every subcommand). |
| `--db DB` | path to the recipe DB (`tensor-engine-knowledge/engines.db`). Overrides `ER_RECIPES_DB` and the fallback path. Not needed for `rig`. |

The DB is resolved in priority order: `--db` → `ER_RECIPES_DB` → the fallback
`../../readouts/tensor-engine-knowledge/engines.db` relative to the repo. See
[Getting Started](/handbook/getting-started/#getting-the-recipe-layer).

## `er rig`

```
er rig
```

Show the detected rig fingerprint. Reads only the live hardware (`nvidia-smi` + environment) — **no
recipe DB required**. Prints GPU, VRAM, `sm`, driver, CUDA runtime/toolkit, OS surface, WSL2
version, and the semantic **compat-band** that recipes resolve against.

No options beyond `-h/--help`.

## `er list`

```
er list [--all]
```

List recipes from the DB as a table of `KIND`, `BACKEND`, `V` (verified flag), and `SLUG`.

| Flag | Description |
|------|-------------|
| `--all` | include non-executable recipes too. By default `list` shows only executable recipes. |

A recipe whose backend is `null` (a `modifier`) shows `(inherits)` in the BACKEND column.

## `er show`

```
er show <slug>
```

Show one recipe in full: kind / backend / axis / verified / executable, plus its baselines,
constraints, artifacts (with the index-only count), compensators, and cross-KB techniques. This is
a read of the immutable knowledge artifact — no side effects.

| Positional | Description |
|------------|-------------|
| `slug` | the recipe slug (from `er list`). |

An unknown slug prints `no recipe: <slug>` on stderr and exits non-zero.

## `er preflight`

```
er preflight <slug>
```

Resolve the recipe against the live rig and run the capability/constraint checks, the resolvability
floor, and compute the `instance_id` — **no side effects**. Prints each check with a status glyph
(`ok ` / `HALT` / `warn` / `....` / `note`), a count of note-only and deferred checks, the
`reproducible:` verdict, and a final `PREFLIGHT OK` or `PREFLIGHT HALT`. See
[Reading the check statuses](/handbook/usage/#reading-the-check-statuses).

| Positional | Description |
|------------|-------------|
| `slug` | the recipe slug. |

**Exit codes:** `0` on `PREFLIGHT OK`; **`2`** on `PREFLIGHT HALT` (one or more blocking halts).

## `er provision`

```
er provision <slug> [--execute] [--model MODEL] [--from FROM] [--port PORT]
```

Plan (dry-run) or, with `--execute`, materialize → launch → measure. **Dry-run is the default** and
touches nothing — it prints every step and its compensator. `--execute` is **the only flag that
touches the rig**.

| Positional / Flag | Description |
|-------------------|-------------|
| `slug` | recipe slug to provision (see `er list`). |
| `--execute` | run for real. Without it, dry-run plan only — the only flag that touches the rig. |
| `--model MODEL` | path to the model (`.gguf`) to serve/measure. **Required with `--execute`.** |
| `--from FROM` | reuse an existing engine dir already on the rig (skip the download/vendor step). |
| `--port PORT` | `127.0.0.1` port for the launched server. Default **8080**. |

Live execute is implemented for the `native-win-compile` backend on the `launchable-server` kind.
Other backend/kind combinations print a clean `BLOCKED: …` in the plan and a structured exit on
`--execute` rather than running.

**Exit codes:** `0` on a clean dry-run or a `READY` execute; **`2`** on an ANDON halt during execute
(the run stops, compensators fire newest-first, and the instance is never marked ready). Missing
`--model` under `--execute`, or an unimplemented provider, exits non-zero with a one-line message.

## `er teardown`

```
er teardown <instance>
```

Roll back a provisioned instance. Compensators run **newest-first** and each stop is
**identity-verified** (only a PID that is alive *and* whose exe lives under our instance dir is
killed). The ledger state is honest — `rolled-back` only when the server is verifiably stopped or
gone; `stop-failed` (instance dir kept) when liveness/identity is inconclusive.

| Positional | Description |
|------------|-------------|
| `instance` | instance id to roll back (see `er status`). |

An unknown instance id prints `no ledger entry for <instance>` and returns without error.

## `er status`

```
er status
```

Show provisioned instances — the persisted ledger. Each row is `instance-id  state  recipe`, plus
`pid=… :port` and measured `tok/s` for a running server. With nothing provisioned, prints
`no provisioned instances`.

No options beyond `-h/--help`.

## Exit codes — summary

| Code | Meaning |
|------|---------|
| `0` | success — command completed cleanly (clean preflight, clean dry-run, `READY` execute, normal read). |
| `1` | error — a structured one-line message on stderr (e.g. a corrupt-ledger `RuntimeError`, a missing recipe/DB). Never a raw traceback. |
| `2` | **ANDON halt** — a blocking defect: `PREFLIGHT HALT`, or an ANDON during `--execute` (compensators fire, instance not marked ready). |

The `2` exit is the load-bearing one: it distinguishes *the pipeline stopped on a defect* from an
ordinary error. A `RuntimeError` out of any command (notably the corrupt-ledger guard) is caught and
surfaced as `er: error: <message>` on stderr with exit `1`, never as a stack trace.
