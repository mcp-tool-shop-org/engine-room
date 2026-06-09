<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/engine-room/main/app/logo.png" width="380" alt="engine-room">
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT">
  <a href="https://mcp-tool-shop-org.github.io/engine-room/"><img src="https://img.shields.io/badge/docs-handbook-1f7fb8" alt="Docs"></a>
</p>

**Recipe-driven provisioner for local AI engines** — the *action* half of a knowledge/action split.
Browse verified engine recipes, resolve one against your live GPU rig, then **provision → launch →
measure → roll back** — reproducibly and validated.

> **Heads up:** engine-room is a **stdlib-only Python CLI**, not a Node package. This npm entry is a
> thin `npx` discovery wrapper — running it prints how to install and use the real tool. The live
> provisioner targets a **native Windows GPU rig** and needs Python ≥ 3.10 + a separate recipe DB.

## Try it

```sh
npx @mcptoolshop/engine-room      # prints install + usage, then exits
```

## Install the tool

```sh
git clone https://github.com/mcp-tool-shop-org/engine-room
cd engine-room
pip install -e .                  # gives the "er" command
# or, no install:  python -m executor.cli rig
```

## First commands

```sh
er rig                 # detected GPU / driver fingerprint
er list                # browse the recipe catalog
er preflight <slug>    # resolve a recipe against your rig (no side effects)
er provision <slug>    # dry-run plan; add --execute --model <gguf> to run it
```

Provisioning is **dry-run by default** — `--execute` is the only flag that touches the rig.

- **Docs / handbook:** <https://mcp-tool-shop-org.github.io/engine-room/>
- **Source:** <https://github.com/mcp-tool-shop-org/engine-room>

MIT — built by [MCP Tool Shop](https://mcp-tool-shop.github.io/).
