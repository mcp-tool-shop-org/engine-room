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
import hashlib, json, os, shutil, subprocess, time, urllib.request
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
    """Load the ledger. A MISSING file is the empty ledger ({}). A CORRUPT file is NOT —
    silently returning {} here would let the next put() clobber every prior instance's
    rollback handle (TESTS-A-009). On a decode error we back the file up and RAISE so the
    caller never overwrites durable rollback state with an empty dict."""
    if not os.path.exists(LEDGER):
        return {}
    try:
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as ex:
        bak = LEDGER + ".corrupt-0"
        n = 0
        while os.path.exists(bak):
            n += 1; bak = f"{LEDGER}.corrupt-{n}"
        try:
            os.replace(LEDGER, bak)
        except OSError:
            shutil.copyfile(LEDGER, bak)
        raise RuntimeError(
            f"ledger corrupt — refusing to clobber rollback handles. "
            f"backed up to {bak}; inspect/restore before re-running. ({ex})"
        )

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

def _select_baseline(recipe: Recipe, model: str | None):
    """EXTERNAL_VERIFIER gate input: pick the baseline to judge against.

    Select by (axis AND model) when a model is given — comparing tok/s against an arbitrary
    OTHER model's number is not a verdict, it's noise (PROVISION-A-005). When no model is
    given (or the running model has no recorded baseline) we cannot honestly threshold, so we
    return None == record-only. The lone exception: a single model-independent baseline (model
    is NULL) on the axis can match regardless of the running model."""
    axis = recipe.axis or "tok_s"
    on_axis = [b for b in recipe.baselines if b.axis == axis]
    if not on_axis:
        return None
    indep = [b for b in on_axis if b.model in (None, "")]
    if model is not None:
        exact = [b for b in on_axis if b.model == model]
        if exact:
            return exact[0]
        # no exact match -> a single model-independent (NULL-model) baseline applies to any
        # running model (the documented contract). Otherwise we cannot honestly threshold.
        if len(indep) == 1:
            return indep[0]
        return None
    # no model given: a single model-independent (NULL-model) baseline is the honest fallback —
    # it judges any running model, so absence of a named model does not block it (IF-8).
    if len(indep) == 1:
        return indep[0]
    # otherwise only honest if there is exactly ONE candidate to judge against on the axis.
    if len(on_axis) == 1:
        return on_axis[0]
    return None


def _verdict(measured: float, baseline) -> tuple[bool, str]:
    """Judge a measurement against a baseline, honoring bound direction (PROVISION-A-005):
    'lower' axes (tok/s, higher-is-better) PASS on measured >= value; 'upper' axes
    (s/img, lower-is-better) PASS on measured <= value. No baseline -> record-only (never halts)."""
    if baseline is None:
        return True, "record-only (no model-keyed baseline)"
    val = baseline.value or 0
    bound = (baseline.bound or "lower").lower()
    if bound == "upper":
        ok = measured <= val
        return ok, ("PASS" if ok else f"ABOVE ceiling {val} {baseline.unit or ''}".rstrip())
    ok = measured >= val
    return ok, ("PASS" if ok else f"BELOW baseline {val} {baseline.unit or ''}".rstrip())


def _vram_verdict(sample: float | None, ceiling: float | None) -> tuple[str, str]:
    """Pure VRAM-ceiling decision (EXTERNAL_VERIFIER measure gate — PROVISION-A-005 / IF-7).

    Returns (verdict, msg) where verdict is one of:
      'halt' -> sample is a real number AND breaches the ceiling. run() raises ANDON.
      'warn' -> sample is None (could not sample). Absence of evidence is NOT a pass — the
                ceiling is UNVERIFIED, so we warn rather than silently green-light (honesty half).
      'ok'   -> sample is a real number AND is at/under the ceiling, OR there is no ceiling to
                enforce (ceiling is None) and we DID get a sample.

    Note the asymmetry: a None *sample* warns (we can't see VRAM); a None *ceiling* with a real
    sample is 'ok' (nothing to enforce against, but we observed VRAM)."""
    if sample is None:
        return "warn", "could not sample VRAM (nvidia-smi unavailable) — ceiling unverified"
    if ceiling is not None and sample > ceiling:
        return "halt", f"peak VRAM {sample} GB breached the {ceiling} GB ceiling"
    return "ok", f"peak VRAM {sample} GB <= {ceiling} GB ceiling"


def _sample_vram_gb() -> float | None:
    """Peak VRAM-used sample via nvidia-smi (read-only). Returns GB, or None if unavailable."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        q = subprocess.run([exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        if q.returncode == 0 and q.stdout.strip():
            mib = float(q.stdout.strip().splitlines()[0].strip())
            return round(mib / 1024, 1)
    except Exception:
        return None
    return None

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
    b = _select_baseline(recipe, model)
    if b:
        cmp = "<=" if (b.bound or "lower").lower() == "upper" else ">="
        tgt = f"{cmp} {b.value} {b.unit} on {b.model}"
    else:
        tgt = "(no model-keyed baseline — record-only)"
    p.steps.append(Step("measure", f"{recipe.axis or 'tok_s'} probe vs baseline + VRAM ceiling",
                        f"256-tok probe; {tgt}; peak VRAM <= {rig.vram_gb} GB", False, None, "read-only"))
    return p


# ---------------------------------------------------------------- live execute
def _sha256_file(path: str) -> str:
    """Full sha256 of a file, read in chunks (no whole-file slurp), handle context-managed."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def _download(ref: str, dest: str, sha: str | None) -> str:
    """Atomically vendor `ref` to `dest`, content-addressed. Returns the full sha256.

    PROVISION-B-001 (atomicity): fetch to dest+'.part', verify the sha (when present) on the .part,
    and only THEN os.replace(.part -> dest). A mid-stream failure (or a sha mismatch) leaves the
    .part behind (best-effort removed) and NEVER materializes `dest`, so a truncated/forged body
    can't become a silent cache hit on the next run. An existing `dest` is a real, already-verified
    cache hit -> just re-hash it and return.

    sha absent/placeholder -> skip the compare (honest optional-pin state). sha present -> verify in
    FULL (a 48-bit prefix compare let a forged near-collision pass — PROVISION-A-004)."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    if os.path.exists(dest):
        # a verified cache hit — self-heal any stray .part an earlier crash left mid-fetch, so the
        # cache dir doesn't accumulate orphaned partials. Best-effort; never mask the cache hit.
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass
        return _sha256_file(dest)
    try:
        urllib.request.urlretrieve(ref, part)
        h = _sha256_file(part)
        if sha and sha not in ("<sha256>", "", None) and h != sha:
            raise RuntimeError(f"sha256 mismatch: got {h} expected {sha}")
        os.replace(part, dest)   # only a fully-fetched, sha-verified body becomes the cache entry
        return h
    except BaseException:
        # truncated/aborted fetch or a failed verify: drop the partial so the next run is a clean
        # cache MISS, never a hit on a half-written file. Best-effort — never mask the real error.
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass
        raise

def _alive(pid: int):
    """Is pid running? Parse the PID *column* of tasklist's CSV output, not a raw substring of
    the whole row (PROVISION-A-006: a stray '80' in a memory column must not read as pid 80).

    TRI-STATE (PROVISION-A-001/IF-3), so an unrunnable probe never fails-safe to a dishonest
    'process gone' verdict over a possibly-live orphan:
      True  -> verified ALIVE: the pid appears in the PID column.
      False -> verified GONE: the probe ran, returned a row set (or a clean 'no tasks' result),
               and the pid is NOT in any PID column.
      None  -> INCONCLUSIVE: the probe couldn't run / timed out / OS error / non-zero return.
               Absence of evidence is not evidence the process is gone — the caller must NOT
               treat None as a clean teardown."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return None  # probe tool absent / timed out / OS error -> inconclusive, never a silent gone
    if out.returncode != 0:
        return None  # tasklist failed -> cannot confirm the pid is gone
    text = (out.stdout or "").strip()
    if not text:
        # tasklist with a PID filter that matches nothing prints an "INFO: No tasks..." line to
        # stdout (rc 0). A truly empty stdout on rc 0 is ambiguous -> stay inconclusive.
        return None
    if text.upper().startswith("INFO:"):
        return False  # filter ran, matched no task -> verified gone
    import csv, io
    for row in csv.reader(io.StringIO(text)):
        # CSV columns: Image Name, PID, Session Name, Session#, Mem Usage
        if len(row) >= 2 and row[1].strip() == str(pid):
            return True
    return False  # rows parsed, pid not in any PID column -> verified gone

def _exe_under(pid: int, root: str):
    """Identity check: does the process at pid run an exe inside our instance dir?

    Returns a TRI-STATE (PROVISION-A-001):
      True  -> verified: the exe path lives under `root` (safe to kill — it's ours)
      False -> verified: a path was read and it is NOT under `root` (recycled/unrelated pid)
      None  -> INCONCLUSIVE: the probe couldn't run / returned nothing. Absence of evidence is
               NOT evidence of safety — the caller must NOT kill and must NOT claim rollback.

    Uses PowerShell Get-CimInstance Win32_Process (wmic was removed on Win11 build 26300, so
    the old wmic probe raised -> bare except -> a silent, dishonest False on every call)."""
    ps = (
        "$p = Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" "
        "-ErrorAction SilentlyContinue; if ($p) { $p.ExecutablePath }" % pid
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None  # probe tool absent / failed -> inconclusive, never a silent False
    if out.returncode != 0:
        return None
    exe = (out.stdout or "").strip()
    if not exe:
        return None  # no path read -> can't verify identity -> inconclusive
    return os.path.normcase(os.path.normpath(root)) in os.path.normcase(os.path.normpath(exe))

def compensate(iid: str):
    d = _ledger_load(); e = d.get(iid)
    if not e:
        print(f"no ledger entry for {iid}"); return
    print(f"rolling back {iid} (newest-first)")
    # Track whether every irreversible step actually reached a known-clean post-state. The ledger
    # state is HONEST: only 'rolled-back' when the server is verifiably stopped or already gone
    # (PROVISION-A-002). An inconclusive identity probe or a failed kill records a truthful state
    # and leaves rmtree un-fired so we don't destroy the instance dir of a still-live orphan.
    stop_clean = True   # no 'stop' compensator pending defaults to clean
    fail_states: list[str] = []
    for c in reversed(e.get("compensators", [])):
        kind = c["kind"]
        if kind == "stop":
            pid, port, root = c["pid"], c["port"], e["inst_dir"]
            if not pid:
                # no pid was ever recorded (launch never reached Popen) -> nothing to stop, clean.
                print(f"  stop: no pid recorded — server never launched (nothing to kill)")
                continue
            alive = _alive(pid)
            if alive is False:
                # verified GONE: the probe ran and the pid is not present -> honest no-op.
                print(f"  stop: pid={pid} verified gone — process already exited (nothing to kill)")
                continue
            if alive is None:
                # INCONCLUSIVE: an unrunnable _alive probe must never resolve to a clean teardown
                # over a possibly-live orphan (IF-3). Keep the instance dir; record stop-failed.
                stop_clean = False; fail_states.append(f"pid={pid} liveness INCONCLUSIVE — could not confirm gone")
                print(f"  skip stop: pid={pid} liveness INCONCLUSIVE (tasklist unavailable) — NOT assuming gone; manual check needed")
                continue
            ident = _exe_under(pid, root)
            if ident is True:
                r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                if getattr(r, "returncode", 0) == 0:
                    print(f"  stopped server pid={pid} :{port} (identity-verified)")
                else:
                    stop_clean = False; fail_states.append(f"taskkill pid={pid} FAILED rc={r.returncode}")
                    print(f"  STOP FAILED: pid={pid} :{port} kill returned rc={r.returncode} — manual kill needed")
            elif ident is False:
                # verified NOT ours: a recycled/unrelated pid. Correct to not kill — but the server
                # WE launched is unaccounted for, so this is not a clean rollback.
                stop_clean = False; fail_states.append(f"pid={pid} verified NOT ours (recycled) — our server unaccounted")
                print(f"  skip stop: pid={pid} verified NOT ours — NOT killed (identity guard)")
            else:  # None == inconclusive
                stop_clean = False; fail_states.append(f"pid={pid} identity INCONCLUSIVE — not killed, manual check needed")
                print(f"  skip stop: pid={pid} identity INCONCLUSIVE (probe unavailable) — NOT killed; manual check needed")
        elif kind == "rmtree":
            if stop_clean:
                shutil.rmtree(c["path"], ignore_errors=True); print(f"  removed {c['path']}")
            else:
                print(f"  KEEP {c['path']} — stop not clean; not removing instance dir of a possibly-live orphan")
    if stop_clean:
        e["state"] = "rolled-back"
    else:
        e["state"] = "stop-failed"
        e["rollback_error"] = "; ".join(fail_states)
        print(f"  ROLLBACK INCOMPLETE — state='stop-failed': {e['rollback_error']}")
    _ledger_put(iid, e)


def _run_log_path(inst: str) -> str:
    return os.path.join(inst, "run.log")

def _run_log(inst: str, line: str):
    """Append one timestamped phase line to {inst}/run.log (PROVISION-B-004). Best-effort —
    a logging failure must never mask the real reconcile error / fail a healthy run."""
    try:
        os.makedirs(inst, exist_ok=True)
        with open(_run_log_path(inst), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}  {line}\n")
    except OSError:
        pass


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

    # ---- EXECUTE: backend-agnostic orchestration (PROVISION-B-005) ----
    # run() owns the ledger + run.log + compensator bookkeeping; the provider owns the
    # backend-specific materialize/launch/probe bodies behind the contract.
    if not model:
        raise SystemExit("--model <gguf> required for --execute")
    from . import providers
    provider = providers.provider_for(recipe)
    if provider is None or not provider.reconcile_implemented:
        raise SystemExit(f"provider '{recipe.backend}' not implemented for execute — "
                         f"native-win-compile is the first slice")
    iid, inst = p.instance_id, p.inst_dir
    entry = {"recipe": recipe.slug, "instance_id": iid, "inst_dir": inst, "state": "starting",
             "started_at": time.time(), "compensators": []}
    _ledger_put(iid, entry)                                   # ledger BEFORE side effects

    def update(*, log: str | None = None, artifact: str | None = None,
               artifact_sha: str | None = None, **fields):
        """Ledger-update callback handed to the provider: echo + log each phase, fold artifact
        refs/shas into the ledger, and persist. Keeps the provider free of ledger/log plumbing."""
        if log is not None:
            print(f"  {log}")
            _run_log(inst, log)
        if artifact is not None:
            entry.setdefault("artifacts", []).append({"ref": artifact, "sha256": artifact_sha})
        if fields:
            entry.update(fields)
        _ledger_put(iid, entry)

    try:
        os.makedirs(inst, exist_ok=True)
        entry["compensators"].append({"kind": "rmtree", "path": inst}); _ledger_put(iid, entry)
        _run_log(inst, f"[prepare] instance dir {inst}")

        # materialize (provider)
        engine_dir = provider.materialize(recipe, rig, inst, from_dir=from_dir, update=update)

        # launch (provider) — record the stop compensator the moment we have a pid
        proc, server = provider.launch(recipe, rig, inst, engine_dir, model=model, port=port, update=update)
        entry["pid"] = proc.pid; entry["port"] = port
        entry["compensators"].append({"kind": "stop", "pid": proc.pid, "port": port}); _ledger_put(iid, entry)
        _run_log(inst, f"[activate] pid={proc.pid} :{port} ({os.path.basename(server)})")

        # probe + measure (provider, EXTERNAL_VERIFIER gate)
        result = provider.probe(recipe, rig, proc=proc, model=model, port=port, update=update,
                                inst_dir=inst)

        entry["state"] = "ready"; entry["measured_tok_s"] = result["tok_s"]
        if result.get("vram_gb") is not None:
            entry["measured_vram_gb"] = result["vram_gb"]
        _ledger_put(iid, entry)
        _run_log(inst, f"[measure] READY {result['tok_s']} {result['unit']} "
                       f"vram={result.get('vram_gb')} -> {result['verdict']}")
        print(f"\nREADY — {recipe.slug} on :{port} (instance {iid}). `er teardown {iid}` to roll back.")
    except Exception as ex:
        print(f"\nANDON HALT: {ex}")
        _run_log(inst, f"[ANDON] {ex}")
        compensate(iid)
        raise SystemExit(2)
