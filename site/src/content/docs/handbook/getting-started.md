---
title: Getting Started
description: Install engine-room, point er at the tensor-engine-knowledge recipe DB, and run your first commands — er rig and er list.
sidebar:
  order: 1
---

This guide gets you from a fresh clone to your first recipe listing. engine-room is a CLI tool —
there's nothing to deploy, and the core has **zero third-party dependencies**.

## Requirements

- **Python 3.10 or newer.** The core is stdlib-only (`sqlite3` + `subprocess`).
- A clone of the engine-room repo. (It is a public GitHub repo, not a PyPI/npm package — there is
  no `pip install engine-room` from an index.)
- For most commands: the **tensor-engine-knowledge** recipe DB (`engines.db`) — see
  [Getting the recipe layer](#getting-the-recipe-layer) below. `er rig` works without it.
- For `--execute` only: an NVIDIA GPU and the recipe's backend toolchain. Detection uses
  `nvidia-smi`.

## Install

Two ways to run the CLI:

```bash
# 1. Editable install — gives you the `er` command on PATH
pip install -e .

er rig
er list
```

```bash
# 2. No install — run the module directly from the repo root
python -m executor.cli rig
python -m executor.cli list
```

The two are interchangeable; this handbook writes `er <cmd>` for brevity. Everything in the core is
importable from a clone with no `pip install` at all — the only thing `pip install -e .` adds is the
`er` entry point.

## Getting the recipe layer

engine-room is the **action** half of the
[knowledge / action split](/handbook/#the-knowledge--action-split). It does **not** ship the
recipes. The **knowledge** half is the separately-provided, verified **tensor-engine-knowledge**
recipe DB (`engines.db`). Cloning this repo alone gives you the executor, not the catalog.

There are three ways `er` finds the DB, in priority order:

1. **`--db <path>`** on any command — explicit, wins over everything.
2. **The `ER_RECIPES_DB` environment variable** — set it once for your shell.
3. **The fallback path** `../../readouts/tensor-engine-knowledge/engines.db` relative to the repo,
   used when neither of the above is set.

```powershell
# PowerShell — point at the DB for the session
$env:ER_RECIPES_DB = "E:\AI\readouts\tensor-engine-knowledge\engines.db"
er list
```

```bash
# Or pass it per-command
er --db /path/to/engines.db list
```

If the DB is missing you get a **clear, structured error**, not a stack trace:

```
recipe DB not found: … — set $ER_RECIPES_DB or pass --db
```

engine-room reads `engines.db` **read-only** and never writes it. The recipe layer is **trusted
input** — see [Security](/handbook/security/).

## First commands

### `er rig` — detect your hardware (no DB needed)

`er rig` reads only the live hardware (`nvidia-smi` + environment), so it works immediately after
cloning, with or without a recipe DB:

```
$ er rig
GPU         NVIDIA GeForce RTX 5090
VRAM        31.8 GB
sm          sm_120
driver      610.47
cuda(rt)    13.3    cuda(toolkit) None
os          windows    wsl2 2.7.3.0
compat-band {'gpu_arch': 'sm_120', 'cuda_toolkit': None, 'os_surface': 'windows', 'driver_floor': 'R570'}
```

The last line — the **compat-band** — is the semantic fingerprint engine-room resolves recipes
against. It is deliberately coarser than the exact driver string, so a routine driver bump doesn't
churn your instance identity. (More in [Architecture](/handbook/architecture/).)

### `er list` — browse the catalog (needs the DB)

Once the DB is pointed at, list the executable recipes:

```
$ er list
KIND               BACKEND              V  SLUG
launchable-server  native-win-compile   Y  diffusion-engines-sdcpp-flux2-dev-q8-ram-offload-32gb
batch-producer     venv                 Y  quantization-calibration-free-quick-shrink-with-hqq
...

N executable recipes
```

`V` is the verified flag (`Y` = claims grounded in a cited source). By default `er list` shows only
*executable* recipes; add `--all` to include the rest. Use a slug from this list with
`er show`, `er preflight`, and `er provision`.

## What "reproducible: no" means

When you preflight a recipe you'll often see:

```
reproducible: no (vendor pins — Goal 1)
```

This is **honest framing, not a bug.** Today, pinned artifacts are resolved against an index, and
an unpinned artifact (or a placeholder `<sha256>`) is still accepted without a content check. That
means the install is *not yet* content-reproducible. Content-addressed vendoring — copying each pin
into a local store and rejecting placeholder shas so `reproducible` is *earned* — is **Goal 1** of
the roadmap. Until it lands, treat the recipe DB and the artifact URLs it points at as trusted
inputs. engine-room tells you the truth about its own state rather than overclaiming.

## Next

Head to **[Usage](/handbook/usage/)** for the dry-run-first workflow that takes a recipe from
preflight to a running, measured engine.
