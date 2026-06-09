"""engine-room CLI (`er`) — the executor entry point.

This first slice is the SAFE foundation: read the recipe layer, detect the rig, and resolve/preflight
a recipe (capability + resolvability + instance_id) — all non-side-effecting. `provision` (materialize
→ launch → measure, with lock/ledger/compensators) is the next increment and is intentionally guarded.
"""
from __future__ import annotations
import argparse, sys
from . import recipes as R
from . import rig as RIG
from .resolve import resolve
from .providers import provider_for

# Render glyphs for resolve Check statuses. "note" (BACKEND-B-001) is a constraint whose expr the
# evaluator has NO handler for — legibly distinct from "deferred" (a deliberate re-check-at-
# materialize) and from "pass". Unknown/future statuses fall back to the raw status string via
# _ICON.get(status, status) so the CLI NEVER KeyErrors on a status the backend adds later.
_ICON = {"pass": "ok ", "halt": "HALT", "warn": "warn", "deferred": "....", "note": "note"}


def cmd_rig(args):
    g = RIG.detect()
    print(f"GPU         {g.gpu}")
    print(f"VRAM        {g.vram_gb} GB")
    print(f"sm          {g.sm}")
    print(f"driver      {g.driver}")
    print(f"cuda(rt)    {g.cuda_runtime}    cuda(toolkit) {g.cuda_toolkit}")
    print(f"os          {g.os_surface}    wsl2 {g.wsl2_version}")
    print(f"compat-band {g.compat_band()}")


def cmd_list(args):
    recs = R.list_recipes(args.db, executable_only=not args.all)
    print(f"{'KIND':18s} {'BACKEND':20s} {'V':2s} SLUG")
    for r in recs:
        print(f"{r.kind:18s} {(r.backend or '(inherits)'):20s} {('Y' if r.verified else '-'):2s} {r.slug}")
    print(f"\n{len(recs)} {'executable' if not args.all else 'total'} recipes")


def cmd_show(args):
    r = R.load_recipe(args.slug, args.db)
    if not r:
        sys.exit(f"no recipe: {args.slug}")
    print(f"{r.slug}\n  {r.summary or ''}")
    print(f"  kind={r.kind}  backend={r.backend}  axis={r.axis}  verified={'Y' if r.verified else '-'}  executable={'Y' if r.executable else '-'}")
    if r.baselines:
        print("  baselines:")
        for b in r.baselines:
            print(f"    {b.model or '(model-indep)'}: {b.value} {b.unit or ''} ({b.bound}) [{b.compat_band or ''}]")
    if r.constraints:
        print("  constraints:")
        for c in r.constraints:
            print(f"    [{c.ctype}] {c.expr}")
    if r.artifacts:
        print(f"  artifacts: {len(r.artifacts)} ({sum(1 for a in r.artifacts if a.store_expect=='index')} index-only)")
    if r.compensators:
        print("  compensators:")
        for c in r.compensators:
            print(f"    {c.step} -> {c.undo_cmd} [{c.compensatable}]")
    if r.techniques:
        print("  cross-KB techniques (training-knowledge):")
        for t in r.techniques:
            print(f"    [{t.category}] {t.name}")


def cmd_preflight(args):
    r = R.load_recipe(args.slug, args.db)
    if not r:
        sys.exit(f"no recipe: {args.slug}")
    g = RIG.detect()
    res = resolve(r, g)
    prov = provider_for(r)
    print(f"recipe   {r.slug}  ({r.kind})")
    if prov:
        if prov.match_implemented:
            # the backend has a REAL match() — show it (wsl2-docker qualifies even though its
            # reconcile bodies aren't wired; run() still guards --execute on reconcile_implemented).
            ok, why = prov.match(r, g)
            print(f"provider {prov.backend}  match={'YES' if ok else 'no'} — {why}")
        else:
            # BACKEND-B-004: a provider with only a stub match() must not advertise a 'YES' it can't
            # honor. Say so plainly instead of implying it will run.
            print(f"provider {prov.backend}  match=n/a — provider not implemented "
                  f"(native-win-compile is the first slice)")
    else:
        print("provider (modifier — inherits target's backend)")
    print(f"instance {res.instance_id}")
    print("checks:")
    for c in res.checks:
        # BACKEND-B-001: render via .get(status, status) — an unknown status (a future KB expr
        # shape resolve() learns to emit) prints its raw name, never KeyErrors the whole command.
        print(f"  [{_ICON.get(c.status, c.status)}] {c.name}  — {c.detail}")
    for n in res.notes:
        print(f"  note: {n}")
    # BACKEND-B-001 footer: count note-only (unhandled-expr) + deferred (re-check-at-materialize)
    # constraints so an operator sees, at a glance, what preflight could NOT decide here.
    n_note = sum(1 for c in res.checks if c.status == "note")
    n_deferred = sum(1 for c in res.checks if c.status == "deferred")
    if n_note or n_deferred:
        print(f"\n{n_note} note-only / {n_deferred} deferred — see notes "
              f"(note = no evaluator handler for the expr; deferred = re-checked at materialize)")
    print(f"\nreproducible: {'yes' if res.reproducible else 'no (vendor pins — Goal 1)'}")
    if res.ok:
        print("PREFLIGHT OK — no halts. (provision is the next executor increment)")
    else:
        print(f"PREFLIGHT HALT — {len(res.halts)} blocking: " + "; ".join(c.name for c in res.halts))
        sys.exit(2)


def cmd_provision(args):
    from . import provision
    r = R.load_recipe(args.slug, args.db)
    if not r:
        sys.exit(f"no recipe: {args.slug}")
    provision.run(r, RIG.detect(), execute=args.execute, model=args.model, port=args.port, from_dir=getattr(args, "from_dir", None))


def cmd_teardown(args):
    from . import provision
    provision.compensate(args.instance)


def cmd_status(args):
    from . import provision
    d = provision._ledger_load()
    if not d:
        print("no provisioned instances"); return
    for iid, e in d.items():
        extra = f"  pid={e.get('pid')} :{e.get('port')}" if e.get("pid") else ""
        tps = f"  {e.get('measured_tok_s')} tok/s" if e.get("measured_tok_s") else ""
        print(f"  {iid}  {e.get('state'):12s} {e.get('recipe','')[:46]}{extra}{tps}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="er", description="engine-room — recipe-driven local-AI engine provisioner")
    p.add_argument("--db", default=R.DEFAULT_DB, help="recipe DB (tensor-engine-knowledge/engines.db)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rig", help="show the detected rig fingerprint").set_defaults(fn=cmd_rig)
    pl = sub.add_parser("list", help="list recipes"); pl.add_argument("--all", action="store_true"); pl.set_defaults(fn=cmd_list)
    ps = sub.add_parser("show", help="show a recipe"); ps.add_argument("slug"); ps.set_defaults(fn=cmd_show)
    pp = sub.add_parser("preflight", help="resolve + capability/resolvability check (no side effects)"); pp.add_argument("slug"); pp.set_defaults(fn=cmd_preflight)
    pv = sub.add_parser("provision", help="plan (dry-run) or --execute materialize->launch->measure")
    pv.add_argument("slug", help="recipe slug to provision (see `er list`)")
    pv.add_argument("--execute", action="store_true",
                    help="run for real; without it, dry-run plan only — the only flag that touches the rig")
    pv.add_argument("--model", help="path to the model (.gguf) to serve/measure — required with --execute")
    pv.add_argument("--from", dest="from_dir",
                    help="reuse an existing engine dir already on the rig (skip the download/vendor step)")
    pv.add_argument("--port", type=int, default=8080,
                    help="127.0.0.1 port for the launched server (default 8080)")
    pv.set_defaults(fn=cmd_provision)
    pt = sub.add_parser("teardown", help="roll back a provisioned instance (compensators, newest-first)")
    pt.add_argument("instance", help="instance id to roll back (see `er status`)")
    pt.set_defaults(fn=cmd_teardown)
    sub.add_parser("status", help="show provisioned instances (the ledger)").set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    # PROVISION-B-006 (shipcheck gate B): a RuntimeError out of a command (notably the corrupt-
    # ledger guard) must surface as a STRUCTURED one-line message on stderr + a non-zero exit, NOT
    # a raw traceback. SystemExit (argparse / deliberate exits) passes through untouched.
    try:
        args.fn(args)
    except RuntimeError as ex:
        print(f"er: error: {ex}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
