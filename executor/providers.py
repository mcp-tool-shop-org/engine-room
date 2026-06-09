"""Provider contract — the one non-leaky seam over heterogeneous backends.

Each backend implements a 4-function interface (match / materialize / launch / probe). The core
executor (provision.run) carries ZERO backend-specific reconcile code; it dispatches on
recipe.backend and drives the provider through the three side-effecting phases. Capability is
split across TWO orthogonal flags so the CLI never overstates what a backend can do:
  * match_implemented     — the backend has a REAL match() (read-only capability probe).
  * reconcile_implemented — the backend has REAL materialize/launch/probe bodies (side effects).
Only the native-win-compile slice is fully REAL today (both True). wsl2-docker has a real match()
but no reconcile bodies (match_implemented=True, reconcile_implemented=False), so the CLI shows its
real match in preflight while run() still refuses to --execute it. The remaining stubs are both
False so the CLI says 'match=n/a — provider not implemented' instead of a misleading 'YES'.

PROVISION-B-005 / BACKEND-B-004: the materialize/launch/probe BODIES live here, behind the
contract — run() is now backend-agnostic orchestration. The shared, individually-unit-tested
helpers (_download, _alive, _exe_under, _select_baseline, _verdict, _vram_verdict,
_sample_vram_gb) stay in provision.py; provider methods call them via a lazy `from . import
provision` (provision imports this module at top level, so the import is one-directional at load
time and only resolved at call time here).
"""
from __future__ import annotations
import json, os, socket, subprocess, time, urllib.request, zipfile
from .recipes import Recipe
from .rig import Rig

_NEXT = "provisioning (materialize/launch/probe) is not wired for this backend yet — native-win-compile is the first slice"

_DIRECT_SUFFIXES = (".zip", ".whl", ".tar.gz", ".7z")


class Provider:
    backend: str = ""
    summary: str = ""
    # BACKEND-B-004: capability is TWO orthogonal flags, not one overloaded bit. A backend can have
    # a real match() (read-only) without a real reconcile path (side effects) — wsl2-docker is
    # exactly that. cmd_preflight gates the 'match=n/a' line on match_implemented; run()'s
    # execute-guard gates on reconcile_implemented.
    match_implemented: bool = False      # the backend has a REAL match()
    reconcile_implemented: bool = False  # the backend has REAL materialize/launch/probe bodies

    def match(self, recipe: Recipe, rig: Rig) -> tuple[bool, str]:
        """Read-only: can this backend run on this rig? (no side effects)"""
        return True, "ok"

    def materialize(self, recipe, rig, inst_dir, *, from_dir, update):  # side-effecting
        raise NotImplementedError(_NEXT)

    def launch(self, recipe, rig, inst_dir, engine_dir, *, model, port, update):  # side-effecting
        raise NotImplementedError(_NEXT)

    def probe(self, recipe, rig, *, proc, model, port, update):  # reads the running endpoint
        raise NotImplementedError(_NEXT)


class NativeWinCompile(Provider):
    backend = "native-win-compile"
    summary = "from-source / prebuilt-wheel build on native Windows (llama.cpp, ExLlamaV3, mistral.rs)"
    match_implemented = True       # the first REAL slice — real match()
    reconcile_implemented = True   # ...and real materialize/launch/probe

    def match(self, recipe, rig):
        if rig.os_surface != "windows":
            return False, "needs native Windows"
        if rig.sm != "sm_120":
            return False, f"expects sm_120, rig={rig.sm}"
        return True, "native-Windows Blackwell"

    # ---- side-effecting reconcile phases (moved out of provision.run) -------------------------
    def materialize(self, recipe, rig, inst_dir, *, from_dir, update):
        """Vendor + extract pins into the instance dir (or reuse --from). Returns the engine dir.

        PROVISION-B-001 atomicity lives inside provision._download (dest+'.part' -> os.replace
        only after fetch+verify). An imprecise artifact (a releases PAGE, not a direct file) ANDONs
        BEFORE any download. update(log=...) records each phase to {inst}/run.log."""
        from . import provision
        if from_dir:
            if not os.path.isdir(from_dir):
                raise RuntimeError(f"--from dir not found: {from_dir}")
            update(log=f"[materialize] reuse existing engine dir: {from_dir}")
            return from_dir
        for ref, vpath, sha in provision._vendor_targets(recipe):
            if not ref.lower().endswith(_DIRECT_SUFFIXES):
                raise RuntimeError(
                    f"ANDON: artifact is not a direct file (a releases page): {ref}\n"
                    f"  fix the recipe's pin to a concrete asset URL, or use --from <existing dir>")
            update(log=f"[materialize] vendor {ref}")
            h = provision._download(ref, vpath, sha)
            update(log=f"[materialize] pinned {ref} -> {vpath} (sha256 {h[:16]}…)",
                   artifact=ref, artifact_sha=h)
            if ref.lower().endswith(".zip"):
                with zipfile.ZipFile(vpath) as z:
                    z.extractall(inst_dir)
        return inst_dir

    def launch(self, recipe, rig, inst_dir, engine_dir, *, model, port, update):
        """Locate llama-server.exe, port-guard, write the per-instance shim, Popen.

        Returns (proc, server_path). The 'stop' compensator (pid/port) is appended to the ledger
        by run() the moment proc.pid is known — launch only does the side effects.

        PROVISION-B-002: a bound 127.0.0.1:{port} ANDONs BEFORE Popen with an actionable message.

        The server's stdout+stderr are redirected to {inst}/server.log (NOT a subprocess.PIPE):
        an undrained PIPE on a long-lived server fills the ~64KB OS pipe buffer and DEADLOCKS the
        server the moment it writes that much to stderr — and nobody ever read it on the happy
        path. A logfile can never fill, AND the operator gets the server's output for free; probe()
        reads its TAIL to enrich the early-death ANDON."""
        from . import provision
        server = None
        for r, _, files in os.walk(engine_dir):
            if "llama-server.exe" in files:
                server = os.path.join(r, "llama-server.exe"); break
        if not server:
            raise RuntimeError(f"ANDON: llama-server.exe not found under {engine_dir}")

        # PROVISION-B-002: refuse to launch onto an already-bound port (else a second instance
        # silently fails the health probe 60s later, or worse collides with an unrelated server).
        if not _port_free(port):
            raise RuntimeError(
                f"ANDON: 127.0.0.1:{port} is already in use — refusing to launch.\n"
                f"  stop whatever holds it (`er status` / Task Manager) or pass --port <free>.")

        shim = os.path.join(inst_dir, "run.cmd")
        cmd = [server, "-m", model, "-ngl", "99", "-fa", "--host", "127.0.0.1", "--port", str(port)]
        with open(shim, "w", encoding="utf-8") as f:
            f.write(" ".join(f'"{c}"' for c in cmd) + "\n")
        update(log=f"[activate] launch {os.path.basename(server)} :{port} (-> server.log)")
        # Redirect to a per-instance logfile so the pipe buffer can NEVER fill a long-lived server.
        # The child inherits a duplicated handle; the parent's copy is closed once Popen has spawned.
        os.makedirs(inst_dir, exist_ok=True)
        logf = open(_server_log_path(inst_dir), "ab")
        try:
            proc = subprocess.Popen(cmd, cwd=os.path.dirname(server),
                                    stdout=logf, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        finally:
            logf.close()
        return proc, server

    def probe(self, recipe, rig, *, proc, model, port, update, inst_dir=None):
        """Health-wait, then the 256-tok completion probe + VRAM ceiling (EXTERNAL_VERIFIER gate).

        Returns {'tok_s', 'vram_gb' (or None), 'verdict', 'dt', 'ntok', 'unit'} on a PASS; raises
        a contextual ANDON on any failure. Honors:
          PROVISION-B-003: break early if proc died before becoming healthy (code + server.log tail
                           echoed), never a 60s wait on a corpse.
          PROVISION-B-007: a non-JSON completion response -> contextual ANDON (first 200 chars),
                           not a raw JSONDecodeError.
          PROVISION-A-005: model-keyed baseline + bound-direction verdict + VRAM ceiling halt.
        """
        from . import provision
        # ---- health wait (B-003: bail the moment the process exits) ----
        ok = False
        for _ in range(60):
            rc = proc.poll()
            if rc is not None:
                tail = _server_log_tail(inst_dir)
                raise RuntimeError(
                    f"ANDON: server process exited with code {rc} before becoming healthy"
                    + (f" — last server.log lines:\n{tail}" if tail else ""))
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2); ok = True; break
            except Exception:
                time.sleep(1)
        if not ok:
            raise RuntimeError("ANDON: server did not become healthy within 60s")

        # ---- measure (EXTERNAL_VERIFIER gate) ----
        N_PREDICT = 256
        t0 = time.time()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/completion",
            data=json.dumps({"prompt": "Count: 1 2 3", "n_predict": N_PREDICT}).encode(),
            headers={"Content-Type": "application/json"})
        # PROVISION-B-007: a server that answers with HTML/an error page must produce a contextual
        # ANDON, not a raw json.JSONDecodeError bubbling out of the reconcile loop.
        try:
            raw = urllib.request.urlopen(req, timeout=120).read()
        except Exception as ex:
            raise RuntimeError(f"measure probe failed: completion request errored — {ex}")
        try:
            resp = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            snippet = _first_chars(raw, 200)
            raise RuntimeError(
                f"measure probe failed: server did not return JSON — got {snippet!r}")
        dt = time.time() - t0

        # VRAM ceiling
        ceiling = rig.vram_gb
        vram = provision._sample_vram_gb()
        vverdict, vmsg = provision._vram_verdict(vram, ceiling)
        if vverdict == "halt":
            raise RuntimeError(f"ANDON: {vmsg}")
        elif vverdict == "warn":
            update(log=f"[measure] WARNING: {vmsg}")
        else:
            update(log=f"[measure] {vmsg}")

        ntok = resp.get("tokens_predicted")
        if ntok is None:
            raise RuntimeError("ANDON: server response had no tokens_predicted — cannot measure tok/s")
        if not dt:
            raise RuntimeError("ANDON: zero elapsed time on the probe — cannot measure tok/s")
        toks = ntok / dt
        b = provision._select_baseline(recipe, model)
        passed, verdict = provision._verdict(toks, b)
        unit = (b.unit if b else recipe.axis) or "tok/s"
        update(log=f"[measure] {toks:.0f} {unit} over {dt:.1f}s ({ntok} tok)  -> {verdict}")
        if not passed:
            raise RuntimeError(f"ANDON: {toks:.0f} {unit} fails baseline ({verdict})")
        return {"tok_s": round(toks, 1), "vram_gb": vram, "verdict": verdict,
                "dt": dt, "ntok": ntok, "unit": unit}


class Wsl2Docker(Provider):
    backend = "wsl2-docker"
    summary = "Linux-first engines under WSL2 + Docker (vLLM, SGLang, TEI)"
    match_implemented = True        # match() is real today...
    reconcile_implemented = False   # ...the reconcile bodies arrive with the WSL2 slice
    def match(self, recipe, rig):
        if not rig.wsl2_version:
            return False, "WSL2 not detected"
        return True, f"WSL2 {rig.wsl2_version}"


class PortableBundle(Provider):
    backend = "portable-bundle"
    summary = "zip-distributed engine with its own embedded interpreter (ComfyUI portable)"


class Venv(Provider):
    backend = "venv"
    summary = "pip/uv venv engines (kohya, Unsloth, TRL)"


class OnnxCompile(Provider):
    backend = "onnx-compile"
    summary = "ahead-of-time compiled artifact (TensorRT-RTX ONNX→.engine)"


class PythonProxy(Provider):
    backend = "python-proxy"
    summary = "stateless routing front (LiteLLM, llama-swap)"


class RawCmd(Provider):
    backend = "raw-cmd"
    summary = "opaque launch command escape hatch"


REGISTRY = {p.backend: p() for p in (
    NativeWinCompile, Wsl2Docker, PortableBundle, Venv, OnnxCompile, PythonProxy, RawCmd)}


def provider_for(recipe: Recipe) -> Provider | None:
    if recipe.kind == "modifier":
        return None   # a modifier inherits its target recipe's backend
    return REGISTRY.get(recipe.backend or "raw-cmd")


# ---------------------------------------------------------------- small stdlib helpers
def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    """PROVISION-B-002: is host:port free? Attempt a bind (no listen, no long-lived socket).

    Returns True only if the bind succeeds; any OSError (EADDRINUSE etc.) -> taken/unusable. The
    socket is closed immediately (context-managed), so this never leaks a bound port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            s.bind((host, port))
        return True
    except OSError:
        return False


def _server_log_path(inst_dir: str) -> str:
    """Per-instance server log: the server's stdout+stderr land here so a long-lived process can
    never deadlock on a full OS pipe buffer (the bug an undrained subprocess.PIPE introduced)."""
    return os.path.join(inst_dir, "server.log")


def _server_log_tail(inst_dir, max_bytes: int = 4000) -> str:
    """Best-effort tail of {inst}/server.log for the early-death ANDON (B-003). Never raises.

    Reads the last ~max_bytes so a huge log doesn't get slurped whole; returns the trailing
    lines (decoded, stripped). A missing inst_dir / missing log / read error -> '' (the ANDON
    still carries the exit code, just without enrichment)."""
    if not inst_dir:
        return ""
    try:
        path = _server_log_path(inst_dir)
        if not os.path.exists(path):
            return ""
        with open(path, "rb") as f:
            try:
                f.seek(-max_bytes, os.SEEK_END)
            except OSError:
                f.seek(0)  # log smaller than the window -> read it whole
            data = f.read() or b""
        text = data.decode("utf-8", "replace").strip()
        return "\n".join(text.splitlines()[-20:])
    except Exception:
        return ""


def _first_chars(raw, n: int) -> str:
    """First n characters of a bytes/str response body, for a contextual parse-failure ANDON."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return raw[:n]
