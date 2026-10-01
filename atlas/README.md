# engine-room: how it works

Mapped at 2026-10-01 from commit d11ed2b by Atlas 1.24.0.

## What this is

8 parts, in Python (12 files), JavaScript (7 files), CSS (3 files), HTML (2 files), TypeScript (2 files) and Astro (1 file). Work enters through 5 doors; the busiest is CI, which reaches 2 parts. It publishes @mcptoolshop/engine-room to npm. It deploys a site to GitHub Pages. People run engine-room and er.

## What changed since the last map

This is the first map.

## What comes in

1. **CI.** On a pull request; on a push touching 8 paths; or by hand. Runs tests/.
2. **Deploy site to GitHub Pages.** On a push to main touching 2 paths; or by hand. Runs site/astro.config.mjs and site/src/.
3. **Release.** When a tag matching `v*` is pushed; or by hand. Checks npm/bin/engine-room.mjs.
4. **engine-room** (a command people run). Runs npm/bin/engine-room.mjs.
5. **er** (a command people run). Runs executor/cli.py.

## What happens through CI

1. The workflow runs tests/ in tests.
2. That reaches executor (7 files).

## Who reads the results

CI writes nothing this map can see.

## The other doors

**Deploy site to GitHub Pages** runs site/astro.config.mjs and site/src/, and deploys the site.

**Release** checks npm/bin/engine-room.mjs, publishes @mcptoolshop/engine-room to npm, and creates a GitHub release on a tag push.

**engine-room** (a command people run) runs npm/bin/engine-room.mjs.

**er** (a command people run) runs executor/cli.py.

## What breaks what

- **executor** is imported by 1 part (the repository root), and by 1 more only from tests, is run as a child process by 1 part (the repository root), and sits on the path of 2 doors.
- **npm** is imported by no other part and sits on the path of 2 doors.

## What tends to change together

No two source files changed together often enough to name.

Window: 180 days; a pair counts from 3 shared commits, since the window holds fewer than 30 qualifying commits.

## What no test touches

- **app** is imported by no test.
- **npm** is imported by no test.

verify.py runs in no workflow.

## Written but never read

- **app/dist/control-panel.html** is written by app/build.mjs and read by nothing else in this repository.
- **app/screenshots/*-catalog-dark.png** is written by app/screenshots/capture.mjs and read by nothing else in this repository.

## Helpers that look duplicated

No two parts export a helper that looks alike.

## Generated, never hand-edited

- **app/dist/control-panel.html** is written by app/build.mjs.
- **app/screenshots/*-catalog-dark.png** is written by app/screenshots/capture.mjs.

## Hand-authored

People write .github/, design/, the repository root and site/; 2 writes with paths built at run time may land here.

## Where to start

executor/cli.py → executor/resolve.py → executor/recipes.py

Read those in order to follow one run of er end to end. This path follows er (a command people run) from its entry, since CI runs only tests.

## What this map cannot see

- 1 import could not be resolved: `verify.py` imports a path built at run time.
- 2 writes use paths built at run time and are not named here.
- 13 writes and 5 reads go to a path their caller passes, not to this repository.
- 1 command is built at run time and not followed.
- Statistics confidence is low: fewer than 30 qualifying commits in the window, and fewer than 20 source files reach 10 revisions.

Regenerate with `npx --yes @dogfood-lab/atlas map`.
