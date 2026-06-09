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
from .providers import provider_for, REGISTRY

_ICON = {"pass": "ok ", "halt": "HALT", "warn": "warn", "deferred": "...."}


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
        ok, why = prov.match(r, g)
        print(f"provider {prov.backend}  match={'YES' if ok else 'no'} — {why}")
    else:
        print("provider (modifier — inherits target's backend)")
    print(f"instance {res.instance_id}")
    print("checks:")
    for c in res.checks:
        print(f"  [{_ICON[c.status]}] {c.name}  — {c.detail}")
    for n in res.notes:
        print(f"  note: {n}")
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
    pv.add_argument("slug"); pv.add_argument("--execute", action="store_true"); pv.add_argument("--model")
    pv.add_argument("--from", dest="from_dir", help="reuse an existing engine dir (skip download)")
    pv.add_argument("--port", type=int, default=8080); pv.set_defaults(fn=cmd_provision)
    pt = sub.add_parser("teardown", help="roll back a provisioned instance (compensators, newest-first)")
    pt.add_argument("instance"); pt.set_defaults(fn=cmd_teardown)
    sub.add_parser("status", help="show provisioned instances (the ledger)").set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
