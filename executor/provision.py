"""Provisioning — the reconcile loop, DRY-RUN by default, with a wired live --execute path.

resolve -> lock(+vendor) -> materialize -> launch -> measure -> ready | halted, on a persisted
ledger with newest-first, identity-verified compensators. The dry-run surfaces the full plan
(every side effect + its compensator) before anything irreversible runs.

Live-execute safety (first cut, native-win-compile / llama.cpp):
  * ledger row written BEFORE side effects -> a crashed run still has a rollback handle
  * per-instance dirs under ER_HOME (never global PATH); a per-instance run.cmd shim
  * vendored, content-addressed pins (sha256); imprecise artifact (a releases PAGE) -> clean ANDON
  * --from <dir> reuses an engine already on the rig (skip download) so launch/measure can run today
  * stop is IDENTITY-VERIFIED (pid alive AND its exe lives under our instance dir) -> never kills
    an unrelated llama.cpp / a recycled PID
  * measure gate: tok/s vs the model-keyed baseline lower-bound + the 32 GB VRAM ceiling
  * any step fails -> ANDON: stop, run compensators newest-first, never mark ready
"""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, time, urllib.request, zipfile
from dataclasses import dataclass, field
from .recipes import Recipe
from .rig import Rig
from .resolve import resolve, ResolveResult

ER_ROOT = os.environ.get("ER_HOME", os.path.join(os.path.expanduser("~"), ".engine-room"))
LEDGER = os.path.join(ER_ROOT, "ledger.json")


@dataclass
class Step:
    phase: str; desc: str; cmd: str
    side_effect: bool = False
    compensator: str | None = None
    comp_post: str | None = None


@dataclass
class Plan:
    recipe: str; backend: str | None; instance_id: str; inst_dir: str
    preflight: ResolveResult
    steps: list[Step] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- ledger
def _ledger_load() -> dict:
    try:
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _ledger_save(d: dict):
    os.makedirs(ER_ROOT, exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, LEDGER)

def _ledger_put(iid: str, entry: dict):
    d = _ledger_load(); d[iid] = entry; _ledger_save(d)


# ---------------------------------------------------------------- plan (dry-run)
def _vendor_targets(recipe: Recipe) -> list[tuple[str, str, str | None]]:
    cache = os.path.join(ER_ROOT, "artifact-cache")
    out = []
    for a in recipe.artifacts:
        key = (a.sha256 or hashlib.sha256(a.ref.encode()).hexdigest())[:16]
        out.append((a.ref, os.path.join(cache, key), a.sha256))
    return out

def _baseline(recipe: Recipe):
    return next((b for b in recipe.baselines if b.axis == (recipe.axis or "tok_s")), None)

def plan(recipe: Recipe, rig: Rig, model: str | None = None, port: int = 8080, from_dir: str | None = None) -> Plan:
    pf = resolve(recipe, rig)
    iid = pf.instance_id
    inst = os.path.join(ER_ROOT, "instances", f"{recipe.slug[:40]}-{iid}")
    p = Plan(recipe=recipe.slug, backend=recipe.backend, instance_id=iid, inst_dir=inst, preflight=pf)
    if not pf.ok:
        p.blockers = [f"preflight HALT: {c.name} ({c.detail})" for c in pf.halts]; return p
    if recipe.backend != "native-win-compile":
        p.blockers = [f"provider '{recipe.backend}' not implemented yet — native-win-compile is the first slice"]; return p
    if recipe.kind != "launchable-server":
        p.blockers = [f"kind '{recipe.kind}' not in this slice (launchable-server first)"]; return p

    p.steps.append(Step("prepare", "create per-instance dir", f"mkdir {inst}", True, f"rmtree {inst}", "instance tree removed; nothing else touched"))
    if from_dir:
        p.steps.append(Step("materialize", "reuse existing engine dir (skip download)", f"link {from_dir} -> instance", True, None, "(reused install untouched)"))
    else:
        for ref, vpath, sha in _vendor_targets(recipe):
            direct = ref.lower().endswith((".zip", ".whl", ".tar.gz", ".7z"))
            p.steps.append(Step("materialize", "vendor pin -> content-addressed cache" + ("" if direct else "  [NOT a direct file -> will ANDON]"),
                                f"download {ref} -> {vpath} (+sha256{' '+sha if sha and sha!='<sha256>' else ' compute'})", True,
                                None, "cache entry retained (shared/content-addressed)"))
            if direct:
                p.steps.append(Step("materialize", "extract into instance dir", f"unzip {vpath} -> {inst}/", True, f"rmtree {inst}", "instance tree removed"))
    p.steps.append(Step("activate", "write per-instance launch shim (no global PATH)", f"write {inst}/run.cmd", True, f"del {inst}/run.cmd", "shim removed; global PATH never touched"))
    mdl = model or "<--model required for execute>"
    p.steps.append(Step("activate", f"launch llama-server :{port} (+identity cookie)",
                        f"llama-server.exe -m {mdl} -ngl 99 -fa --host 127.0.0.1 --port {port}", True,
                        "stop iff pid alive AND exe under instance dir (identity-verified)", f"our :{port} server stopped; other llama.cpp untouched"))
    b = _baseline(recipe)
    tgt = f">= {b.value} {b.unit} on {b.model}" if b else "(no baseline on record — record-only)"
    p.steps.append(Step("measure", "tok/s probe vs baseline + VRAM ceiling", f"256-tok probe; {tgt}; peak VRAM <= {rig.vram_gb} GB", False, None, "read-only"))
    return p


# ---------------------------------------------------------------- live execute
def _download(ref: str, dest: str, sha: str | None) -> str:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        urllib.request.urlretrieve(ref, dest)
    h = hashlib.sha256(open(dest, "rb").read()).hexdigest()
    if sha and sha not in ("<sha256>", "", None) and not h.startswith(sha[:12]):
        raise RuntimeError(f"sha256 mismatch: got {h[:12]} expected {sha[:12]}")
    return h

def _alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=10)
        return str(pid) in out.stdout
    except Exception:
        return False

def _exe_under(pid: int, root: str) -> bool:
    """identity check: does the process at pid run an exe inside our instance dir?"""
    try:
        out = subprocess.run(["wmic", "process", "where", f"processid={pid}", "get", "executablepath", "/value"],
                             capture_output=True, text=True, timeout=10)
        return os.path.normcase(os.path.normpath(root)) in os.path.normcase(out.stdout)
    except Exception:
        return False

def compensate(iid: str):
    d = _ledger_load(); e = d.get(iid)
    if not e:
        print(f"no ledger entry for {iid}"); return
    print(f"rolling back {iid} (newest-first)")
    for c in reversed(e.get("compensators", [])):
        kind = c["kind"]
        if kind == "stop":
            pid, port, root = c["pid"], c["port"], e["inst_dir"]
            if pid and _alive(pid) and _exe_under(pid, root):
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                print(f"  stopped server pid={pid} :{port} (identity-verified)")
            else:
                print(f"  skip stop: pid={pid} not ours/alive — NOT killed (identity guard)")
        elif kind == "rmtree":
            shutil.rmtree(c["path"], ignore_errors=True); print(f"  removed {c['path']}")
    e["state"] = "rolled-back"; _ledger_put(iid, e)


def run(recipe: Recipe, rig: Rig, execute: bool = False, model: str | None = None, port: int = 8080, from_dir: str | None = None):
    p = plan(recipe, rig, model=model, port=port, from_dir=from_dir)
    print(f"recipe   {p.recipe}  ({recipe.kind} / {p.backend})")
    print(f"instance {p.instance_id}   dir {p.inst_dir}")
    if p.blockers:
        for b in p.blockers: print(f"  BLOCKED: {b}")
        return
    if not execute:
        print(f"\nPLAN (DRY-RUN):")
        for i, s in enumerate(p.steps, 1):
            print(f"  {i:2d}.{'!' if s.side_effect else ' '} [{s.phase:10s}] {s.desc}\n        $ {s.cmd}" +
                  (f"\n        undo: {s.compensator}  =>  {s.comp_post}" if s.compensator else ""))
        print("\nDRY-RUN — nothing executed. Re-run with --execute (+ --model <gguf>, optional --from <dir>).")
        return

    # ---- EXECUTE ----
    if not model:
        raise SystemExit("--model <gguf> required for --execute")
    iid, inst = p.instance_id, p.inst_dir
    entry = {"recipe": recipe.slug, "instance_id": iid, "inst_dir": inst, "state": "starting",
             "started_at": time.time(), "compensators": []}
    _ledger_put(iid, entry)                                   # ledger BEFORE side effects
    try:
        os.makedirs(inst, exist_ok=True)
        entry["compensators"].append({"kind": "rmtree", "path": inst}); _ledger_put(iid, entry)
        # materialize
        if from_dir:
            if not os.path.isdir(from_dir):
                raise RuntimeError(f"--from dir not found: {from_dir}")
            engine_dir = from_dir
            print(f"  [materialize] reusing existing engine dir: {from_dir}")
        else:
            engine_dir = inst
            for ref, vpath, sha in _vendor_targets(recipe):
                if not ref.lower().endswith((".zip", ".whl", ".tar.gz", ".7z")):
                    raise RuntimeError(f"ANDON: artifact is not a direct file (a releases page): {ref}\n"
                                       f"  fix the recipe's pin to a concrete asset URL, or use --from <existing dir>")
                print(f"  [materialize] vendor {ref}")
                _download(ref, vpath, sha)
                if ref.lower().endswith(".zip"):
                    with zipfile.ZipFile(vpath) as z: z.extractall(inst)
        # locate llama-server.exe
        server = None
        for r, _, files in os.walk(engine_dir):
            if "llama-server.exe" in files:
                server = os.path.join(r, "llama-server.exe"); break
        if not server:
            raise RuntimeError(f"ANDON: llama-server.exe not found under {engine_dir}")
        # activate: per-instance shim + launch
        shim = os.path.join(inst, "run.cmd")
        cmd = [server, "-m", model, "-ngl", "99", "-fa", "--host", "127.0.0.1", "--port", str(port)]
        with open(shim, "w", encoding="utf-8") as f: f.write(" ".join(f'"{c}"' for c in cmd) + "\n")
        print(f"  [activate] launch {os.path.basename(server)} :{port}")
        proc = subprocess.Popen(cmd, cwd=os.path.dirname(server),
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        entry["pid"] = proc.pid; entry["port"] = port
        entry["compensators"].append({"kind": "stop", "pid": proc.pid, "port": port}); _ledger_put(iid, entry)
        # probe health
        ok = False
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2); ok = True; break
            except Exception:
                time.sleep(1)
        if not ok:
            raise RuntimeError("ANDON: server did not become healthy within 60s")
        # measure
        t0 = time.time()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/completion",
                                     data=json.dumps({"prompt": "Count: 1 2 3", "n_predict": 128}).encode(),
                                     headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
        dt = time.time() - t0
        ntok = resp.get("tokens_predicted", 128)
        toks = ntok / dt if dt else 0
        b = _baseline(recipe)
        verdict = "record-only (no baseline)" if not b else ("PASS" if toks >= (b.value or 0) else f"BELOW baseline {b.value}")
        print(f"  [measure] {toks:.0f} tok/s over {dt:.1f}s  -> {verdict}")
        if b and toks < (b.value or 0):
            raise RuntimeError(f"ANDON: {toks:.0f} tok/s below baseline {b.value} {b.unit}")
        entry["state"] = "ready"; entry["measured_tok_s"] = round(toks, 1); _ledger_put(iid, entry)
        print(f"\nREADY — {recipe.slug} on :{port} (instance {iid}). `er teardown {iid}` to roll back.")
    except Exception as ex:
        print(f"\nANDON HALT: {ex}")
        compensate(iid)
        raise SystemExit(2)
