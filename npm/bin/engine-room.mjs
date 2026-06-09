#!/usr/bin/env node
// `npx @mcptoolshop/engine-room` — discovery wrapper. engine-room itself is a
// stdlib-only Python CLI; this prints how to install + run it, then exits.
const repo = 'https://github.com/mcp-tool-shop-org/engine-room';
const docs = 'https://mcp-tool-shop-org.github.io/engine-room/';

process.stdout.write(`
engine-room — recipe-driven provisioner for local AI engines

  Browse verified engine recipes, resolve one against your live GPU rig, then
  provision -> launch -> measure -> roll back, reproducibly and validated.

This is a stdlib-only PYTHON CLI (not a Node package). Install it:

  git clone ${repo}
  cd engine-room
  pip install -e .                 # gives the "er" command
  # or run without installing:
  python -m executor.cli rig

First commands:

  er rig                  detected GPU / driver fingerprint
  er list                 browse the recipe catalog
  er preflight <slug>     resolve a recipe against your rig (no side effects)
  er provision <slug>     dry-run plan; add --execute --model <gguf> to run it

Docs & handbook:  ${docs}
Source:           ${repo}

Note: the live provisioner targets a native Windows GPU rig. Requires Python >=3.10
and a separate recipe DB (set ER_RECIPES_DB). See the handbook for details.
`);
