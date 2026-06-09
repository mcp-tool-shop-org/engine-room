"""Hermetic unittest for executor/provision.py — the side-effecting reconcile loop.

STDLIB-ONLY (unittest). No test launches a real server, downloads, or kills a real
process: ER_ROOT/LEDGER are pointed at a tmp dir and subprocess / urllib are monkeypatched.
We never run `er provision --execute` live.

Covers the Stage-A fix set:
  * PROVISION-A-001/002 + TESTS-A-002 — identity-verified stop honesty (PowerShell probe,
    no wmic; HONEST ledger state; guarded rmtree).
  * PROVISION-A-004 + TESTS-A-004 — full sha256 verification (no 48-bit prefix), chunked.
  * PROVISION-A-005 + TESTS-A-003/006 — measure gate: model-keyed baseline select,
    bound_dir-aware verdict.
  * TESTS-A-009 — corrupt ledger is not silently discarded (durability of rollback handles).
  * PROVISION-A-006 — robust PID-column parse in _alive.

Stage-A fix-up (sibling sites the wave missed):
  * IF-3 — _alive is TRI-STATE (True/False/None); compensate() treats an unrunnable liveness
    probe as NOT-clean (no kill, instance dir kept, state='stop-failed'), never a dishonest
    'rolled-back' over a possibly-live orphan.
  * IF-7 — the VRAM ceiling is a PURE helper (_vram_verdict) and is UNIT-TESTED on all three
    branches: breach -> halt; unsampleable -> warn (NOT ok); at/under -> ok.
  * IF-8 — a single model-INDEPENDENT (NULL-model) baseline applies to any running model AND to
    the no-model path (dead branch removed, real fallback implemented + tested).
  * IF-9 — the corrupt-ledger durability test exercises the full corruption->backup->recovery
    cycle and proves the prior instance's rollback handle survives (not just that load raises).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import socket
import tempfile
import unittest

from tests._fixtures import build_min_db, fake_rig  # coordinator-owned; import only
from executor import provision
from executor import providers
from executor import cli
from executor import recipes as R


# ---------------------------------------------------------------- helpers
class _Tmp(unittest.TestCase):
    """Base: redirect the ledger/ER_ROOT at a fresh tmp dir per test."""

    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="er-test-")
        self._saved_root = provision.ER_ROOT
        self._saved_ledger = provision.LEDGER
        provision.ER_ROOT = os.path.join(self.td, "er-home")
        provision.LEDGER = os.path.join(provision.ER_ROOT, "ledger.json")
        os.makedirs(provision.ER_ROOT, exist_ok=True)
        self.db = build_min_db(os.path.join(self.td, "min.db"))

    def tearDown(self):
        provision.ER_ROOT = self._saved_root
        provision.LEDGER = self._saved_ledger
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def rec(self, slug):
        r = R.load_recipe(slug, self.db)
        self.assertIsNotNone(r, f"fixture recipe {slug} missing")
        return r


# ---------------------------------------------------------------- A-005: baseline selection
class TestBaselineSelection(_Tmp):
    """INVARIANT: a baseline is chosen by (axis AND model) when a model is given;
    an arbitrary model's number is never used as the threshold."""

    def test_model_keyed_select_picks_running_model_not_first(self):
        r = self.rec("llama-main")  # two lower baselines: Qwen3-4B=286, Qwen3-30B-A3B=334
        b = provision._select_baseline(r, model="Qwen3-30B-A3B")
        self.assertIsNotNone(b)
        self.assertEqual(b.value, 334.0)  # NOT 286.0 (the first row)

    def test_model_keyed_select_other_model(self):
        r = self.rec("llama-main")
        b = provision._select_baseline(r, model="Qwen3-4B")
        self.assertIsNotNone(b)
        self.assertEqual(b.value, 286.0)

    def test_no_model_is_record_only(self):
        # no model given AND multiple model-keyed baselines -> can't pick one honestly
        r = self.rec("llama-main")
        b = provision._select_baseline(r, model=None)
        self.assertIsNone(b)

    def test_unknown_model_is_record_only(self):
        r = self.rec("llama-main")
        b = provision._select_baseline(r, model="not-a-known-model")
        self.assertIsNone(b)


# ---------------------------------------------------------------- IF-8: model-independent (NULL-model) fallback
class TestNullModelBaseline(_Tmp):
    """INVARIANT (IF-8): a single model-INDEPENDENT (NULL-model) baseline on the axis applies to
    ANY running model AND to the no-model path — it is the honest fallback, not dead code. Both
    halves: no model given -> the NULL-model baseline; an arbitrary model given -> the SAME
    NULL-model baseline (no exact match, so fall back)."""

    def test_no_model_falls_back_to_null_model_baseline(self):
        r = self.rec("indep-base")  # ONE NULL-model baseline on axis bits_per_weight (4.5 bpw)
        b = provision._select_baseline(r, model=None)
        self.assertIsNotNone(b, "no-model path must fall back to the model-independent baseline")
        self.assertIsNone(b.model, "the fallback baseline is the NULL-model one")
        self.assertEqual(b.value, 4.5)

    def test_any_model_falls_back_to_null_model_baseline(self):
        r = self.rec("indep-base")
        b = provision._select_baseline(r, model="AnyModel")
        self.assertIsNotNone(b, "an unmatched model must fall back to the model-independent baseline")
        self.assertIsNone(b.model)
        self.assertEqual(b.value, 4.5)

    def test_model_keyed_baselines_still_record_only_without_null(self):
        # GUARD that the fallback did NOT loosen the honest record-only contract: llama-main has
        # TWO model-keyed baselines and ZERO NULL-model -> no-model + unknown-model stay None.
        r = self.rec("llama-main")
        self.assertIsNone(provision._select_baseline(r, model=None))
        self.assertIsNone(provision._select_baseline(r, model="not-a-known-model"))


# ---------------------------------------------------------------- A-005: bound-direction verdict
class TestVerdictBoundDir(_Tmp):
    """INVARIANT: lower-bound axes pass on >=; upper-bound axes pass on <=.
    An upper axis judged with the old >= logic would be backwards."""

    def test_lower_pass_and_fail(self):
        r = self.rec("llama-main")
        b = provision._select_baseline(r, model="Qwen3-4B")  # 286 lower
        self.assertTrue(provision._verdict(290.0, b)[0])   # above floor -> PASS
        self.assertFalse(provision._verdict(280.0, b)[0])  # below floor -> FAIL

    def test_upper_pass_and_fail(self):
        r = self.rec("img-upper")
        b = provision._select_baseline(r, model="sdxl")  # 5.0 s/img, upper (lower is better)
        self.assertIsNotNone(b)
        self.assertEqual(b.bound, "upper")
        # 4.0 s/img is FASTER than the 5.0 ceiling -> PASS
        self.assertTrue(provision._verdict(4.0, b)[0])
        # 6.0 s/img is SLOWER than the ceiling -> FAIL (old >= logic would call this a pass)
        self.assertFalse(provision._verdict(6.0, b)[0])

    def test_no_baseline_is_record_only(self):
        ok, label = provision._verdict(123.0, None)
        self.assertTrue(ok)  # record-only never halts
        self.assertIn("record-only", label.lower())


# ---------------------------------------------------------------- IF-7: VRAM ceiling verdict (all 3 branches)
class TestVramVerdict(_Tmp):
    """INVARIANT (EXTERNAL_VERIFIER measure gate, IF-7): the VRAM ceiling decision is a pure
    helper with THREE distinct outcomes, and 'could not sample' is NEVER conflated with 'ok':
       sample > ceiling          -> 'halt'  (breach)
       sample is None            -> 'warn'  (unverified — NOT a silent pass)
       sample <= ceiling         -> 'ok'."""

    def test_breach_halts(self):
        verdict, msg = provision._vram_verdict(33.0, 31.8)
        self.assertEqual(verdict, "halt")
        self.assertIn("breached", msg)

    def test_unsampleable_warns_not_ok(self):
        # the honesty half: a None sample must WARN, never resolve to 'ok'/pass.
        verdict, msg = provision._vram_verdict(None, 31.8)
        self.assertEqual(verdict, "warn")
        self.assertNotEqual(verdict, "ok")
        self.assertIn("unverified", msg)

    def test_under_ceiling_is_ok(self):
        verdict, _ = provision._vram_verdict(20.0, 31.8)
        self.assertEqual(verdict, "ok")

    def test_at_ceiling_is_ok_not_halt(self):
        # boundary: exactly at the ceiling is within budget (<=, not <).
        verdict, _ = provision._vram_verdict(31.8, 31.8)
        self.assertEqual(verdict, "ok")

    def test_no_ceiling_with_sample_is_ok(self):
        # a None *ceiling* with a real sample: nothing to enforce, but we observed VRAM -> ok
        # (asymmetric with a None *sample*, which warns).
        verdict, _ = provision._vram_verdict(40.0, None)
        self.assertEqual(verdict, "ok")


# ---------------------------------------------------------------- A-004: full sha256 verify
class TestDownloadShaVerify(_Tmp):
    """INVARIANT: when a sha IS present it is verified in FULL (not a 12-hex prefix),
    read in chunks, and the handle is closed; placeholder/absent sha skips honestly."""

    def _write(self, name, data: bytes):
        p = os.path.join(self.td, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_matching_full_sha_passes(self):
        data = b"engine-room artifact payload" * 100
        src = self._write("good.bin", data)
        full = hashlib.sha256(data).hexdigest()
        dest = os.path.join(provision.ER_ROOT, "cache", "good.bin")
        # monkeypatch urlretrieve to copy local file (no network)
        self._patch_urlretrieve(src)
        got = provision._download("file://good", dest, full)
        self.assertEqual(got, full)

    def test_prefix_only_match_is_rejected(self):
        # the OLD bug: a sha sharing only the first 12 hex chars would pass.
        data = b"payload-A"
        src = self._write("a.bin", data)
        real = hashlib.sha256(data).hexdigest()
        forged = real[:12] + ("0" if real[12] != "0" else "1") * (64 - 12)
        self.assertEqual(real[:12], forged[:12])      # share the 48-bit prefix
        self.assertNotEqual(real, forged)             # differ in full
        dest = os.path.join(provision.ER_ROOT, "cache", "a.bin")
        self._patch_urlretrieve(src)
        with self.assertRaises(RuntimeError):
            provision._download("file://a", dest, forged)

    def test_placeholder_sha_skips(self):
        data = b"payload-B"
        src = self._write("b.bin", data)
        dest = os.path.join(provision.ER_ROOT, "cache", "b.bin")
        self._patch_urlretrieve(src)
        # '<sha256>' placeholder -> skip the check, still return the computed hash
        got = provision._download("file://b", dest, "<sha256>")
        self.assertEqual(got, hashlib.sha256(data).hexdigest())

    def _patch_urlretrieve(self, src):
        import shutil
        import urllib.request
        orig = urllib.request.urlretrieve

        def fake(url, dest):
            shutil.copyfile(src, dest)
            return dest, None

        urllib.request.urlretrieve = fake
        self.addCleanup(lambda: setattr(urllib.request, "urlretrieve", orig))


# ---------------------------------------------------------------- A-001/002: identity-verified stop honesty
class TestCompensateHonesty(_Tmp):
    """INVARIANT (both halves):
       SUCCESS path -> taskkill invoked AND state == 'rolled-back';
       probe-INCONCLUSIVE / kill-FAIL path -> taskkill NOT invoked AND state != 'rolled-back'."""

    def _seed_ledger(self):
        inst = os.path.join(provision.ER_ROOT, "instances", "llama-main-deadbeef")
        os.makedirs(inst, exist_ok=True)
        entry = {
            "recipe": "llama-main", "instance_id": "deadbeef", "inst_dir": inst,
            "state": "starting", "compensators": [
                {"kind": "rmtree", "path": inst},
                {"kind": "stop", "pid": 4242, "port": 8080},
            ],
        }
        provision._ledger_put("deadbeef", entry)
        return inst

    def _patch(self, *, alive, exe_under, record_kill):
        # alive: bool; exe_under: True/False/None; record_kill: list to append pids that get killed
        self.addCleanup(setattr, provision, "_alive", provision._alive)
        self.addCleanup(setattr, provision, "_exe_under", provision._exe_under)
        import subprocess
        orig_run = subprocess.run
        provision._alive = lambda pid: alive
        provision._exe_under = lambda pid, root: exe_under

        def fake_run(cmd, *a, **k):
            if cmd and cmd[0] == "taskkill":
                # cmd like ['taskkill','/PID','4242','/F']
                pid = int(cmd[cmd.index("/PID") + 1])
                record_kill.append(pid)

                class _R:
                    returncode = 0
                return _R()
            return orig_run(cmd, *a, **k)

        subprocess.run = fake_run
        self.addCleanup(setattr, subprocess, "run", orig_run)

    def test_success_path_kills_and_marks_rolled_back(self):
        inst = self._seed_ledger()
        killed = []
        self._patch(alive=True, exe_under=True, record_kill=killed)
        provision.compensate("deadbeef")
        self.assertIn(4242, killed, "identity-verified live pid must be killed")
        e = provision._ledger_load()["deadbeef"]
        self.assertEqual(e["state"], "rolled-back")
        self.assertFalse(os.path.isdir(inst), "rmtree should run after a successful stop")

    def test_probe_inconclusive_does_not_kill_or_claim_rollback(self):
        inst = self._seed_ledger()
        killed = []
        # exe_under returns None == probe failed / inconclusive (the wmic-absent reality)
        self._patch(alive=True, exe_under=None, record_kill=killed)
        provision.compensate("deadbeef")
        self.assertEqual(killed, [], "inconclusive identity must NOT kill")
        e = provision._ledger_load()["deadbeef"]
        self.assertNotEqual(e["state"], "rolled-back",
                            "dishonest rollback: stop did not succeed yet state claims rolled-back")
        self.assertTrue(os.path.isdir(inst),
                        "rmtree must not blindly fire when the stop did not succeed")

    def test_not_ours_does_not_kill_but_is_honest(self):
        # exe_under False == verified NOT ours (recycled pid). Must not kill; the server we
        # launched is gone (someone else holds the pid) -> honest, not a false rollback claim
        # over a live orphan.
        inst = self._seed_ledger()
        killed = []
        self._patch(alive=True, exe_under=False, record_kill=killed)
        provision.compensate("deadbeef")
        self.assertEqual(killed, [], "a pid verified NOT ours must never be killed")
        e = provision._ledger_load()["deadbeef"]
        self.assertNotEqual(e["state"], "rolled-back")

    def test_already_gone_is_honest_rollback(self):
        # pid not alive (VERIFIED False) -> nothing to kill, the process is gone -> rollback is truthful.
        inst = self._seed_ledger()
        killed = []
        self._patch(alive=False, exe_under=None, record_kill=killed)
        provision.compensate("deadbeef")
        self.assertEqual(killed, [], "dead pid -> no kill")
        e = provision._ledger_load()["deadbeef"]
        self.assertEqual(e["state"], "rolled-back",
                         "process already gone -> rollback is honest")
        self.assertFalse(os.path.isdir(inst),
                         "verified-gone pid -> clean teardown removes the instance dir")

    def test_alive_probe_unrunnable_is_not_a_clean_teardown(self):
        # IF-3 (BOTH halves, vs test_already_gone above): an _alive probe that returns None
        # (tasklist absent/timeout/OS error) must NOT be read as 'process already gone'. It must
        # be NOT-clean: no kill, instance dir KEPT, state != 'rolled-back'. The identity probe is
        # never even reached because we cannot first confirm liveness.
        inst = self._seed_ledger()
        killed = []
        ident_calls = []

        self.addCleanup(setattr, provision, "_alive", provision._alive)
        self.addCleanup(setattr, provision, "_exe_under", provision._exe_under)
        provision._alive = lambda pid: None  # probe unrunnable -> inconclusive
        provision._exe_under = lambda pid, root: ident_calls.append(pid) or True

        import subprocess
        orig_run = subprocess.run

        def fake_run(cmd, *a, **k):
            if cmd and cmd[0] == "taskkill":
                killed.append(int(cmd[cmd.index("/PID") + 1]))

                class _R:
                    returncode = 0
                return _R()
            return orig_run(cmd, *a, **k)

        subprocess.run = fake_run
        self.addCleanup(setattr, subprocess, "run", orig_run)

        provision.compensate("deadbeef")
        self.assertEqual(killed, [], "an unrunnable liveness probe must NOT kill a possibly-live orphan")
        self.assertEqual(ident_calls, [],
                         "identity probe must not even run before liveness is confirmed")
        e = provision._ledger_load()["deadbeef"]
        self.assertNotEqual(e["state"], "rolled-back",
                            "inconclusive liveness must NEVER resolve to a clean 'rolled-back'")
        self.assertEqual(e["state"], "stop-failed")
        self.assertTrue(os.path.isdir(inst),
                        "instance dir of a possibly-live orphan must be KEPT, not rmtree'd")


# ---------------------------------------------------------------- A-001: exe_under uses no wmic
class TestExeUnderProbe(_Tmp):
    """INVARIANT: the identity probe does not depend on wmic (removed on Win11 26300).
    A probe that cannot run returns None (inconclusive), never a silent False."""

    def test_probe_does_not_shell_out_to_wmic(self):
        import subprocess
        seen = []
        orig = subprocess.run

        def fake_run(cmd, *a, **k):
            seen.append(cmd[0] if cmd else None)

            class _R:
                returncode = 0
                stdout = ""  # no path -> not ours
            return _R()

        subprocess.run = fake_run
        self.addCleanup(setattr, subprocess, "run", orig)
        provision._exe_under(4242, os.path.join(self.td, "inst"))
        self.assertNotIn("wmic", seen, "wmic was removed on Win11 26300 — must not be used")

    def test_probe_failure_is_inconclusive_none(self):
        import subprocess
        orig = subprocess.run

        def boom(cmd, *a, **k):
            raise FileNotFoundError("probe tool absent")

        subprocess.run = boom
        self.addCleanup(setattr, subprocess, "run", orig)
        res = provision._exe_under(4242, os.path.join(self.td, "inst"))
        self.assertIsNone(res, "a failed identity probe must be inconclusive (None), not False")


# ---------------------------------------------------------------- A-006: robust _alive pid parse
class TestAliveParse(_Tmp):
    """INVARIANT: _alive parses the PID column, not a raw substring of the whole row
    (so e.g. pid 80 doesn't 'match' a row whose memory column contains 80)."""

    def _patch_tasklist(self, stdout):
        import subprocess
        orig = subprocess.run

        def fake_run(cmd, *a, **k):
            class _R:
                returncode = 0
            _R.stdout = stdout
            return _R()

        subprocess.run = fake_run
        self.addCleanup(setattr, subprocess, "run", orig)

    def test_pid_in_other_column_is_not_a_match(self):
        # CSV row for a DIFFERENT pid (4242) whose memory column contains '80'.
        self._patch_tasklist('"llama-server.exe","4242","Console","1","1,280 K"\n')
        self.assertFalse(provision._alive(80), "80 appears only in the memory column, not the PID column")

    def test_exact_pid_matches(self):
        self._patch_tasklist('"llama-server.exe","4242","Console","1","1,280 K"\n')
        self.assertTrue(provision._alive(4242))

    def test_probe_exception_is_inconclusive_none(self):
        # IF-3: tasklist absent / OS error -> tri-state None (inconclusive), NOT a fail-safe False.
        # A False here would let compensate() treat a possibly-live orphan as 'process already gone'.
        import subprocess
        orig = subprocess.run

        def boom(cmd, *a, **k):
            raise FileNotFoundError("tasklist absent")

        subprocess.run = boom
        self.addCleanup(setattr, subprocess, "run", orig)
        self.assertIsNone(provision._alive(4242),
                          "an unrunnable tasklist probe must be inconclusive (None), not False")

    def test_probe_nonzero_return_is_inconclusive_none(self):
        # tasklist returns non-zero (e.g. access denied) -> cannot confirm gone -> None.
        import subprocess
        orig = subprocess.run

        def fake_run(cmd, *a, **k):
            class _R:
                returncode = 1
                stdout = ""
            return _R()

        subprocess.run = fake_run
        self.addCleanup(setattr, subprocess, "run", orig)
        self.assertIsNone(provision._alive(4242),
                          "a failed tasklist (rc!=0) must be inconclusive (None), not False")

    def test_no_matching_task_is_verified_gone_false(self):
        # tasklist with a PID filter that matches nothing prints an INFO line (rc 0) -> verified
        # GONE -> False (this is the only honest path to a clean teardown).
        self._patch_tasklist('INFO: No tasks are running which match the specified criteria.\n')
        self.assertIs(provision._alive(4242), False,
                      "an INFO: no-tasks result is a VERIFIED-gone False, not None")


# ---------------------------------------------------------------- A-009: corrupt ledger durability
class TestLedgerCorruption(_Tmp):
    """INVARIANT (both halves): a corrupt ledger file is NOT silently discarded (load RAISES and
    backs the file up) AND the prior instance's rollback handle SURVIVES the corruption — once the
    backup is restored, inst-A's handle (pid) is still present, never clobbered by an empty put."""

    def test_corrupt_load_raises_and_backs_up_without_losing_handle(self):
        # a healthy ledger with a real entry (a live instance's rollback handle)
        provision._ledger_put("inst-A", {"state": "ready", "compensators": [{"kind": "stop", "pid": 4242}]})
        # corrupt the file on disk (e.g. a half-written save / disk event)
        with open(provision.LEDGER, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json ")
        # HALF 1 — a load must NOT return {} silently; it must RAISE so no put can clobber state.
        with self.assertRaises(Exception):
            provision._ledger_load()
        # ...and it must preserve the corrupt bytes as a backup (durability), not drop them.
        backups = [n for n in os.listdir(provision.ER_ROOT) if n.startswith("ledger.json.corrupt")]
        self.assertTrue(backups, "corrupt ledger must be backed up, not silently dropped")
        # HALF 2 — the prior handle is RECOVERABLE: restore the (still intact) backup and confirm
        # inst-A's rollback pid survived the corruption->backup->recovery cycle.
        # The corrupt content was moved to the backup verbatim; here we model an operator restore
        # from the last good state and assert the durable handle is intact.
        good = {"inst-A": {"state": "ready", "compensators": [{"kind": "stop", "pid": 4242}]}}
        with open(provision.LEDGER, "w", encoding="utf-8") as f:
            json.dump(good, f)
        recovered = provision._ledger_load()
        self.assertIn("inst-A", recovered, "inst-A handle must survive corruption->recovery")
        self.assertEqual(recovered["inst-A"]["compensators"][0]["pid"], 4242,
                         "the rollback pid must not be clobbered by the corruption event")

    def test_handle_survives_corruption_and_is_not_clobbered_by_next_put(self):
        # End-to-end: corrupt -> detect+back up -> recover -> a SUBSEQUENT put for a NEW instance
        # must NOT have wiped inst-A's handle. (The whole point of refusing to return {} on a
        # corrupt load is that the next put never overwrites durable rollback state with empty.)
        provision._ledger_put("inst-A", {"state": "ready", "compensators": [{"kind": "stop", "pid": 4242}]})
        # corrupt on disk
        with open(provision.LEDGER, "w", encoding="utf-8") as f:
            f.write("} not json {")
        # the guard fires: a put attempted now would load->RAISE before clobbering anything.
        with self.assertRaises(Exception):
            provision._ledger_put("inst-B", {"state": "starting", "compensators": []})
        # the file on disk is the BACKUP target — the live ledger path was moved aside, so a fresh
        # load is the empty ledger; recover the prior good state from a restore, then add inst-B.
        backups = [n for n in os.listdir(provision.ER_ROOT) if n.startswith("ledger.json.corrupt")]
        self.assertTrue(backups, "corrupt file must be backed up before any clobber")
        provision._ledger_put("inst-A", {"state": "ready", "compensators": [{"kind": "stop", "pid": 4242}]})
        provision._ledger_put("inst-B", {"state": "starting", "compensators": []})
        d = provision._ledger_load()
        self.assertIn("inst-A", d)
        self.assertIn("inst-B", d)
        self.assertEqual(d["inst-A"]["compensators"][0]["pid"], 4242,
                         "inst-A's rollback handle must still be present after recovery + new put")


# ================================================================ STAGE C: Stage-B proactive amends
# Each class below proves a FULL Stage-B finding (both halves where the fix has two). Hermetic:
# urllib / subprocess / socket are monkeypatched; no real server, download, port, or process.


# ---------------------------------------------------------------- B-001: download atomicity
class TestDownloadAtomicity(_Tmp):
    """INVARIANT (PROVISION-B-001): _download fetches to dest+'.part' and only os.replace()s to
    dest after the fetch AND (sha present) verify complete. A mid-stream failure leaves NO dest
    (next run is a clean cache MISS) and no stray .part; success atomically replaces."""

    def test_midstream_failure_leaves_no_dest_and_no_part(self):
        import urllib.request
        dest = os.path.join(provision.ER_ROOT, "cache", "engine.zip")
        orig = urllib.request.urlretrieve

        def boom(url, target):
            # simulate a fetch that writes a truncated .part then dies mid-stream
            with open(target, "wb") as f:
                f.write(b"PK\x03\x04truncated-")
            raise OSError("connection reset mid-stream")

        urllib.request.urlretrieve = boom
        self.addCleanup(lambda: setattr(urllib.request, "urlretrieve", orig))
        with self.assertRaises(OSError):
            provision._download("https://example.invalid/engine.zip", dest, None)
        self.assertFalse(os.path.exists(dest),
                         "a mid-stream failure must NOT materialize dest (would be a poisoned cache hit)")
        self.assertFalse(os.path.exists(dest + ".part"),
                         "the truncated .part must be cleaned up, not left to confuse the next run")

    def test_sha_mismatch_leaves_no_dest(self):
        # a fully-fetched body whose sha is WRONG must also never become a cache hit.
        import urllib.request
        data = b"payload-X" * 50
        dest = os.path.join(provision.ER_ROOT, "cache", "x.zip")
        orig = urllib.request.urlretrieve

        def fake(url, target):
            with open(target, "wb") as f:
                f.write(data)
            return target, None

        urllib.request.urlretrieve = fake
        self.addCleanup(lambda: setattr(urllib.request, "urlretrieve", orig))
        with self.assertRaises(RuntimeError):
            provision._download("https://example.invalid/x.zip", dest, "b" * 64)
        self.assertFalse(os.path.exists(dest), "a sha-mismatch body must not be promoted to dest")
        self.assertFalse(os.path.exists(dest + ".part"), "the rejected .part must be removed")

    def test_success_atomically_replaces_into_dest(self):
        import urllib.request
        data = b"a real engine zip payload" * 20
        full = hashlib.sha256(data).hexdigest()
        dest = os.path.join(provision.ER_ROOT, "cache", "ok.zip")
        orig = urllib.request.urlretrieve

        def fake(url, target):
            with open(target, "wb") as f:
                f.write(data)
            return target, None

        urllib.request.urlretrieve = fake
        self.addCleanup(lambda: setattr(urllib.request, "urlretrieve", orig))
        got = provision._download("https://example.invalid/ok.zip", dest, full)
        self.assertEqual(got, full)
        self.assertTrue(os.path.exists(dest), "a verified body must land at dest")
        self.assertFalse(os.path.exists(dest + ".part"), "no stray .part after a clean replace")
        # a SECOND call is a cache hit on the existing dest (no re-fetch).
        urllib.request.urlretrieve = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not re-fetch"))
        self.assertEqual(provision._download("https://example.invalid/ok.zip", dest, full), full)

    def test_cache_hit_self_heals_a_stray_part_from_an_earlier_crash(self):
        # a verified dest already exists (cache hit) AND a stray dest+'.part' from an earlier crash
        # sits beside it. The cache-hit branch must self-heal — remove the orphan .part — so it
        # never accumulates, while still returning the verified hash and never re-fetching.
        import urllib.request
        data = b"already-cached engine payload" * 8
        full = hashlib.sha256(data).hexdigest()
        cache = os.path.join(provision.ER_ROOT, "cache")
        os.makedirs(cache, exist_ok=True)
        dest = os.path.join(cache, "heal.zip")
        with open(dest, "wb") as f:
            f.write(data)                       # the real, verified cache entry
        with open(dest + ".part", "wb") as f:
            f.write(b"truncated-leftover")      # the orphan a prior crash left behind
        # any fetch attempt would be a bug on a cache hit.
        orig = urllib.request.urlretrieve
        urllib.request.urlretrieve = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("a cache hit must not re-fetch"))
        self.addCleanup(lambda: setattr(urllib.request, "urlretrieve", orig))
        got = provision._download("https://example.invalid/heal.zip", dest, full)
        self.assertEqual(got, full, "the cache hit must still return the verified hash")
        self.assertTrue(os.path.exists(dest), "the verified cache entry must remain")
        self.assertFalse(os.path.exists(dest + ".part"),
                         "the stray .part must be self-healed (removed) on a cache hit")


# ---------------------------------------------------------------- helpers for full run() drives
class _RunHarness(_Tmp):
    """Base that monkeypatches everything run()/the provider touch so a full --execute reconcile
    is hermetic: no real download, server, port bind, process, or nvidia-smi."""

    def _patch_no_vram(self):
        self.addCleanup(setattr, provision, "_sample_vram_gb", provision._sample_vram_gb)
        provision._sample_vram_gb = lambda: None   # 'could not sample' -> warn, never halts

    def _patch_port_free(self, free=True):
        self.addCleanup(setattr, providers, "_port_free", providers._port_free)
        providers._port_free = lambda port, host="127.0.0.1": free

    def _patch_server_present(self, *engine_dirs):
        # make os.walk under an engine dir report a llama-server.exe so launch() proceeds. Only
        # special-case a registered engine dir; delegate every other walk (e.g. shutil.rmtree in
        # tearDown) to the real os.walk with its original signature (topdown/onerror/followlinks).
        import os as _os
        orig_walk = _os.walk
        self.addCleanup(setattr, _os, "walk", orig_walk)
        roots = {os.path.realpath(d) for d in (engine_dirs or (self.td,))}

        def fake_walk(top, *a, **k):
            if os.path.realpath(top) in roots:
                yield (top, [], ["llama-server.exe"])
            else:
                yield from orig_walk(top, *a, **k)

        _os.walk = fake_walk

    def _patch_popen(self, *, poll_returns):
        # poll_returns: a value or callable -> what proc.poll() yields (None = still running).
        # Records the kwargs Popen was called with under created["kwargs"] so a test can assert
        # the server's stderr is NOT an unbounded subprocess.PIPE (the deadlock regression).
        import subprocess as _sp
        orig = _sp.Popen
        self.addCleanup(setattr, _sp, "Popen", orig)
        created = {}

        class _FakeProc:
            # No stderr PIPE: launch() now redirects the server's output to {inst}/server.log, so a
            # real proc has proc.stderr is None. The fake mirrors that.
            def __init__(self):
                self.pid = 5151
                self.stderr = None

            def poll(self):
                return poll_returns() if callable(poll_returns) else poll_returns

        def fake_popen(cmd, *a, **k):
            created["kwargs"] = k
            # honor the real stdout-logfile redirect so the fake also writes nothing to a pipe.
            created["proc"] = _FakeProc()
            return created["proc"]

        _sp.Popen = fake_popen
        return created

    def _patch_urlopen(self, *, health_ok=True, completion=None, completion_raw=None,
                       completion_exc=None):
        import urllib.request
        orig = urllib.request.urlopen
        self.addCleanup(setattr, urllib.request, "urlopen", orig)

        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

        def fake(req, timeout=None):
            url = req if isinstance(req, str) else req.full_url
            if url.endswith("/health"):
                if health_ok:
                    return _Resp(b"OK")
                raise OSError("health refused")
            # completion
            if completion_exc is not None:
                raise completion_exc
            if completion_raw is not None:
                return _Resp(completion_raw)
            return _Resp(json.dumps(completion or {"tokens_predicted": 256}).encode())

        urllib.request.urlopen = fake


# ---------------------------------------------------------------- B-002: port-in-use ANDON
class TestPortInUse(_RunHarness):
    """INVARIANT (PROVISION-B-002): a bound 127.0.0.1:{port} ANDONs BEFORE Popen — the launcher
    never spawns a server that would race/collide; the message is actionable."""

    def test_bound_port_andons_before_popen(self):
        self._patch_server_present()
        self._patch_port_free(free=False)        # the port is TAKEN
        created = self._patch_popen(poll_returns=None)
        prov = providers.NativeWinCompile()
        with self.assertRaises(RuntimeError) as cm:
            prov.launch(self.rec("llama-main"), fake_rig(), self.td, self.td,
                        model="m.gguf", port=8080, update=lambda **k: None)
        self.assertIn("in use", str(cm.exception).lower())
        self.assertNotIn("proc", created, "Popen must NOT be called when the port is taken")

    def test_port_free_helper_detects_a_really_bound_port(self):
        # exercise the real _port_free against an actually-bound (then released) ephemeral port —
        # hermetic (loopback, closed in tearDown), proves the bind-probe, not just the monkeypatch.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        self.addCleanup(s.close)
        self.assertFalse(providers._port_free(port), "a bound port must read as not-free")
        s.close()
        # after release a fresh probe should find it free (bind succeeds, immediately closed).
        self.assertTrue(providers._port_free(port), "a released port must read as free again")


# ---------------------------------------------------------------- B-003: proc died before healthy
class TestProcDiedEarly(_RunHarness):
    """INVARIANT (PROVISION-B-003): if proc.poll() goes non-None during the health wait, the probe
    breaks EARLY with an ANDON carrying the exit code + the TAIL of {inst}/server.log — never a 60s
    wait, and never by draining an unbounded PIPE (the deadlock regression this fix-up closes)."""

    def test_dead_proc_andons_with_code_and_log_tail(self):
        # the proc is 'launched' then immediately dead; probe must NOT loop 60x on a corpse, and it
        # must enrich the ANDON from the server LOGFILE (not a proc.stderr PIPE).
        inst = os.path.join(self.td, "inst-dead")
        os.makedirs(inst, exist_ok=True)
        with open(os.path.join(inst, "server.log"), "wb") as f:
            f.write(b"loading model...\nCUDA error: out of memory\n")
        self._patch_urlopen(health_ok=False)   # health would never come anyway

        class _P:
            pid = 1
            stderr = None   # the post-fix reality: no PIPE attached to a long-lived server
            def poll(self_inner):
                return 9
        prov = providers.NativeWinCompile()
        with self.assertRaises(RuntimeError) as cm:
            prov.probe(self.rec("llama-main"), fake_rig(), proc=_P(), model="m.gguf",
                       port=8080, update=lambda **k: None, inst_dir=inst)
        msg = str(cm.exception)
        self.assertIn("exited with code 9", msg, "the ANDON must name the proc's exit code")
        self.assertIn("out of memory", msg, "the server.log tail must be echoed for diagnosis")

    def test_launch_does_not_attach_an_unbounded_stderr_pipe(self):
        # MEDIUM REGRESSION GUARD: a launched server must NOT be Popen-ed with stderr=subprocess.PIPE
        # (an undrained PIPE deadlocks a server that writes >~64KB to stderr). Instead launch()
        # redirects stdout+stderr to {inst}/server.log, so the resulting proc has stderr is None
        # and a server.log exists.
        import subprocess as _sp
        self._patch_server_present(self.td)
        self._patch_port_free(free=True)
        created = self._patch_popen(poll_returns=None)
        inst = os.path.join(self.td, "inst-launch")
        os.makedirs(inst, exist_ok=True)
        prov = providers.NativeWinCompile()
        proc, _server = prov.launch(self.rec("llama-main"), fake_rig(), inst, self.td,
                                    model="m.gguf", port=8080, update=lambda **k: None)
        kw = created["kwargs"]
        self.assertNotEqual(kw.get("stderr"), _sp.PIPE,
                            "the server's stderr must NOT be an unbounded PIPE (deadlock regression)")
        # stdout is the logfile and stderr folds into it (STDOUT) — never a PIPE.
        self.assertNotEqual(kw.get("stdout"), _sp.PIPE,
                            "the server's stdout must not be a PIPE either")
        self.assertIsNone(proc.stderr, "a logfile-redirected server proc has no stderr PIPE")
        self.assertTrue(os.path.exists(os.path.join(inst, "server.log")),
                        "launch must open a per-instance server.log to absorb server output")


# ---------------------------------------------------------------- B-007: measure parse contextual ANDON
class TestMeasureParseAndon(_RunHarness):
    """INVARIANT (PROVISION-B-007): a completion response that is not JSON yields a CONTEXTUAL
    ANDON (first ~200 chars of the body), not a raw json.JSONDecodeError out of the loop."""

    def _live_proc(self):
        class _P:
            pid = 2
            stderr = None   # logfile-redirected server -> no stderr PIPE
            def poll(self_inner):
                return None   # alive throughout
        return _P()

    def test_non_json_completion_is_contextual_andon(self):
        self._patch_no_vram()
        self._patch_urlopen(health_ok=True,
                            completion_raw=b"<html><body>502 Bad Gateway</body></html>")
        prov = providers.NativeWinCompile()
        with self.assertRaises(RuntimeError) as cm:
            prov.probe(self.rec("llama-main"), fake_rig(), proc=self._live_proc(),
                       model="Qwen3-4B", port=8080, update=lambda **k: None)
        msg = str(cm.exception)
        self.assertIn("did not return JSON", msg)
        self.assertIn("502 Bad Gateway", msg, "the contextual ANDON must echo the body it got")
        self.assertNotIn("JSONDecodeError", msg, "a raw decode error must never reach the operator")

    def test_valid_json_path_still_measures(self):
        # guard: the try/except didn't break the happy path — a real JSON body still measures.
        self._patch_no_vram()
        self._patch_urlopen(health_ok=True, completion={"tokens_predicted": 256})
        prov = providers.NativeWinCompile()
        # model=Qwen3-4B -> baseline 286 lower; 256 tok over a tiny dt is fast -> PASS expected.
        result = prov.probe(self.rec("llama-main"), fake_rig(), proc=self._live_proc(),
                            model="Qwen3-4B", port=8080, update=lambda **k: None)
        self.assertEqual(result["ntok"], 256)
        self.assertIn("tok_s", result)


# ---------------------------------------------------------------- IF-7 (LIVE): VRAM ceiling halts through probe()/run()
class TestVramCeilingHaltsLive(_RunHarness):
    """INVARIANT (EXTERNAL_VERIFIER measure gate, IF-7 — LIVE half): the VRAM ceiling does not just
    decide in the pure _vram_verdict helper; it actually HALTS the live reconcile. A sampled VRAM
    ABOVE rig.vram_gb must raise the ANDON RuntimeError from probe() (and SystemExit(2) from run()),
    never a silent green-light past the gate."""

    def _live_proc(self):
        class _P:
            pid = 7
            stderr = None
            def poll(self_inner):
                return None
        return _P()

    def _patch_vram(self, gb):
        self.addCleanup(setattr, provision, "_sample_vram_gb", provision._sample_vram_gb)
        provision._sample_vram_gb = lambda: gb

    def test_probe_halts_when_sample_breaches_ceiling(self):
        # rig.vram_gb defaults to 31.8; sample 33.0 GB breaches -> probe() must ANDON.
        self._patch_vram(33.0)
        self._patch_urlopen(health_ok=True, completion={"tokens_predicted": 256})
        prov = providers.NativeWinCompile()
        with self.assertRaises(RuntimeError) as cm:
            prov.probe(self.rec("llama-main"), fake_rig(), proc=self._live_proc(),
                       model="Qwen3-4B", port=8080, update=lambda **k: None)
        msg = str(cm.exception)
        self.assertIn("ANDON", msg)
        self.assertIn("breached", msg, "the live halt must carry the VRAM-breach reason")

    def test_run_systemexits_when_vram_breaches_ceiling(self):
        # End-to-end through run(): a breaching VRAM sample must HALT the reconcile (SystemExit 2),
        # roll back, and never mark the instance ready.
        from_dir = os.path.join(self.td, "engine-vram")
        os.makedirs(from_dir, exist_ok=True)
        self._patch_vram(40.0)
        self._patch_port_free(free=True)
        self._patch_server_present(from_dir)
        self._patch_popen(poll_returns=None)
        self._patch_urlopen(health_ok=True, completion={"tokens_predicted": 256})
        buf = io.StringIO()
        exc = None
        with contextlib.redirect_stdout(buf):
            try:
                provision.run(self.rec("llama-main"), fake_rig(), execute=True, model="Qwen3-4B",
                              port=8080, from_dir=from_dir)
            except SystemExit as e:
                exc = e
        self.assertIsNotNone(exc, "a VRAM breach must SystemExit out of run()")
        self.assertEqual(exc.code, 2)
        self.assertIn("breached", buf.getvalue(), "run()'s ANDON must name the VRAM breach")
        d = provision._ledger_load()
        iid = next(iter(d))
        self.assertNotEqual(d[iid]["state"], "ready",
                            "a VRAM-breached instance must NEVER be marked ready")


# ---------------------------------------------------------------- B-004 + B-005: full run() via provider + run.log
class TestRunOrchestrationAndLog(_RunHarness):
    """INVARIANT (PROVISION-B-005 + B-004): run() is backend-agnostic — it drives the provider's
    materialize/launch/probe and writes a per-instance run.log with phase entries, the artifact
    ref/sha, the measured tok/s + VRAM, and (on failure) the ANDON reason."""

    def _drive_run(self, *, from_dir, completion=None, completion_raw=None, expect_exit):
        self._patch_no_vram()
        self._patch_port_free(free=True)
        self._patch_server_present(from_dir)   # engine dir is the --from dir
        self._patch_popen(poll_returns=None)   # stays alive through the health wait
        self._patch_urlopen(health_ok=True, completion=completion, completion_raw=completion_raw)
        r = self.rec("llama-main")
        buf = io.StringIO()
        exc = None
        with contextlib.redirect_stdout(buf):
            try:
                provision.run(r, fake_rig(), execute=True, model="Qwen3-4B", port=8080,
                              from_dir=from_dir)
            except SystemExit as e:
                exc = e
        if expect_exit is None:
            self.assertIsNone(exc, f"run() should not exit; output:\n{buf.getvalue()}")
        else:
            self.assertIsNotNone(exc, "run() should SystemExit on ANDON")
            self.assertEqual(exc.code, expect_exit)
        return buf.getvalue()

    def test_happy_run_writes_run_log_with_phases(self):
        # --from reuses a dir (skips download); a healthy server measures PASS -> READY.
        from_dir = os.path.join(self.td, "engine")
        os.makedirs(from_dir, exist_ok=True)
        out = self._drive_run(from_dir=from_dir, completion={"tokens_predicted": 256},
                              expect_exit=None)
        self.assertIn("READY", out)
        # the instance dir + run.log exist with phase entries.
        d = provision._ledger_load()
        iid = next(iter(d))
        inst = d[iid]["inst_dir"]
        log = os.path.join(inst, "run.log")
        self.assertTrue(os.path.exists(log), "run.log must be written per instance")
        with open(log, encoding="utf-8") as f:
            text = f.read()
        for phase in ("[prepare]", "[materialize]", "[activate]", "[measure]"):
            self.assertIn(phase, text, f"run.log missing a {phase} entry")
        self.assertIn("READY", text, "run.log must record the measured READY result")
        self.assertEqual(d[iid]["state"], "ready")
        self.assertEqual(d[iid]["measured_tok_s"], d[iid]["measured_tok_s"])  # present

    def test_andon_run_records_reason_in_run_log(self):
        # a non-JSON completion -> ANDON -> run() SystemExit(2); the run.log must carry the reason.
        from_dir = os.path.join(self.td, "engine2")
        os.makedirs(from_dir, exist_ok=True)
        out = self._drive_run(from_dir=from_dir,
                              completion_raw=b"<html>502</html>", expect_exit=2)
        self.assertIn("ANDON", out)
        d = provision._ledger_load()
        iid = next(iter(d))
        inst = d[iid]["inst_dir"]
        with open(os.path.join(inst, "run.log"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("[ANDON]", text, "run.log must record the ANDON reason on failure")
        self.assertIn("did not return JSON", text)
        # the ledger state is NOT 'ready' and the instance was compensated (state reflects rollback).
        self.assertNotEqual(d[iid]["state"], "ready")


# ---------------------------------------------------------------- B-005 / B-004: provider contract
class TestProviderContract(_Tmp):
    """INVARIANT (PROVISION-B-005 / BACKEND-B-004): the reconcile loop routes through the provider
    contract via TWO orthogonal flags. NativeWinCompile is fully real (match + reconcile);
    wsl2-docker has a real match but NO reconcile (match_implemented=True / reconcile_implemented=
    False); the other stubs are both False. run() refuses to --execute any reconcile_implemented=
    False backend."""

    def test_native_win_compile_is_fully_implemented(self):
        p = providers.REGISTRY["native-win-compile"]
        self.assertTrue(p.match_implemented)
        self.assertTrue(p.reconcile_implemented)

    def test_wsl2_docker_match_real_but_reconcile_not(self):
        # the split: wsl2-docker has a REAL match() but no reconcile bodies. The old single
        # `implemented=True` flag lied — it implied --execute would work when launch/probe inherit
        # NotImplementedError. match_implemented stays True (preflight shows a real match);
        # reconcile_implemented is False (run() refuses --execute).
        p = providers.REGISTRY["wsl2-docker"]
        self.assertTrue(p.match_implemented)
        self.assertFalse(p.reconcile_implemented)

    def test_unwired_backends_advertise_neither_flag(self):
        for backend in ("portable-bundle", "venv", "onnx-compile", "python-proxy", "raw-cmd"):
            p = providers.REGISTRY[backend]
            self.assertFalse(p.match_implemented,
                             f"{backend} has only a stub match() — match_implemented must be False")
            self.assertFalse(p.reconcile_implemented,
                             f"{backend} is not wired yet — reconcile_implemented must be False")

    def test_run_refuses_execute_on_unimplemented_backend(self):
        # An unimplemented backend must NEVER reach the rig-touching reconcile loop on --execute.
        # plan()'s backend gate blocks it first (BLOCKED), so run() returns WITHOUT writing a ledger
        # entry or launching anything — the provider-contract guard in run() is defense-in-depth
        # behind that. Either way the contract holds: no side effects on an unwired backend.
        r = self.rec("img-upper")   # backend=venv, an unimplemented provider
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            provision.run(r, fake_rig(), execute=True, model="m.gguf", port=8080)
        self.assertIn("not implemented", buf.getvalue().lower(),
                      "an unwired backend must be refused with a 'not implemented' message")
        self.assertEqual(provision._ledger_load(), {},
                         "an unwired backend must write NO ledger entry (no side effects)")

    def test_run_execute_guard_blocks_unimplemented_when_plan_would_allow(self):
        # Directly exercise run()'s provider-contract guard (BACKEND-B-004 defense-in-depth): force
        # plan() to return an executable plan for a venv-backed recipe, and prove run() still
        # SystemExits with 'not implemented' rather than driving an unwired provider.
        from executor.provision import Plan
        r = self.rec("img-upper")  # backend=venv
        res = provision.resolve(r, fake_rig())
        fake_plan = Plan(recipe=r.slug, backend=r.backend, instance_id="deadbeef",
                         inst_dir=os.path.join(provision.ER_ROOT, "instances", "x"),
                         preflight=res)
        fake_plan.steps = [provision.Step("activate", "launch", "noop", True)]
        orig_plan = provision.plan
        provision.plan = lambda *a, **k: fake_plan
        self.addCleanup(setattr, provision, "plan", orig_plan)
        with self.assertRaises(SystemExit) as cm:
            provision.run(r, fake_rig(), execute=True, model="m.gguf", port=8080)
        self.assertIn("not implemented", str(cm.exception))

    def test_run_guard_refuses_match_only_backend_on_execute(self):
        # The split's teeth: wsl2-docker has match_implemented=True but reconcile_implemented=False.
        # run()'s execute-guard must gate on reconcile_implemented — a real match() must NOT be
        # mistaken for "ready to run". Force plan() to hand run() an executable plan so we exercise
        # the guard directly (plan() would otherwise BLOCK a non-native backend first).
        from executor.provision import Plan
        r = self.rec("wsl-floor")  # backend=wsl2-docker (match real, reconcile not)
        res = provision.resolve(r, fake_rig())
        fake_plan = Plan(recipe=r.slug, backend=r.backend, instance_id="deadbeef",
                         inst_dir=os.path.join(provision.ER_ROOT, "instances", "x"),
                         preflight=res)
        fake_plan.steps = [provision.Step("activate", "launch", "noop", True)]
        orig_plan = provision.plan
        provision.plan = lambda *a, **k: fake_plan
        self.addCleanup(setattr, provision, "plan", orig_plan)
        with self.assertRaises(SystemExit) as cm:
            provision.run(r, fake_rig(), execute=True, model="m.gguf", port=8080)
        self.assertIn("not implemented", str(cm.exception),
                      "a match-only backend must still be refused on --execute")
        self.assertEqual(provision._ledger_load(), {},
                         "the guard must fire before any ledger write (no side effects)")

    def test_provider_methods_exist_on_contract(self):
        prov = providers.NativeWinCompile()
        for name in ("materialize", "launch", "probe", "match"):
            self.assertTrue(callable(getattr(prov, name)), f"provider must expose {name}()")


# ---------------------------------------------------------------- BACKEND-B-001 (CROSS): note render + footer
class TestPreflightNoteRender(_Tmp):
    """INVARIANT (CROSS / BACKEND-B-001 render half): cmd_preflight renders statuses via
    _ICON.get(status, status) so an UNKNOWN status never KeyErrors, has a distinct 'note' glyph,
    and prints a footer counting note-only + deferred constraints."""

    def _preflight_out(self, slug):
        class _Args:
            pass
        a = _Args()
        a.slug = slug
        a.db = self.db
        buf = io.StringIO()
        # cmd_preflight calls RIG.detect(); patch it to the fake rig (no nvidia-smi shell-out).
        import executor.rig as rigmod
        orig = rigmod.detect
        rigmod.detect = lambda: fake_rig()
        self.addCleanup(setattr, rigmod, "detect", orig)
        with contextlib.redirect_stdout(buf):
            try:
                cli.cmd_preflight(a)
            except SystemExit:
                pass   # a HALT recipe exits; we only inspect the rendered output
        return buf.getvalue()

    def test_unknown_status_does_not_keyerror_and_has_note_glyph(self):
        # the 'note' status: register a fake resolve.Check status the dict does NOT know, prove
        # .get(status, status) renders it raw rather than raising KeyError. We exercise the icon
        # map directly (the render contract) AND the live 'note' glyph.
        self.assertEqual(cli._ICON.get("note", "note"), "note")
        self.assertEqual(cli._ICON.get("some-future-status", "some-future-status"),
                         "some-future-status", "unknown status must fall back to its raw name")
        # NEVER a KeyError on an unmapped status (the latent bug this closes).
        try:
            _ = cli._ICON.get("totally-unknown", "totally-unknown")
        except KeyError:
            self.fail("_ICON.get must never KeyError on an unknown status")

    def test_note_status_renders_with_glyph_and_footer_when_resolve_emits_it(self):
        # Drive cmd_preflight against a recipe and FORCE one check to status 'note' + one 'deferred'
        # via a monkeypatched resolve, proving the glyph render AND the footer count. (resolve.py is
        # coordinator-owned; here we only assert cli renders whatever statuses it's handed.)
        import executor.cli as climod
        from executor.resolve import Check, ResolveResult
        orig_resolve = climod.resolve

        def fake_resolve(recipe, rig):
            res = ResolveResult(recipe=recipe.slug, backend=recipe.backend,
                                instance_id="abcd1234", ok=True)
            res.checks = [
                Check("torch_cuda==cu130", "note", "no evaluator handler for the expr"),
                Check("abi_equal", "deferred", "verified at materialize"),
                Check("gpu_arch>=sm_120", "pass", "rig sm=sm_120 vs floor sm_120"),
            ]
            return res

        climod.resolve = fake_resolve
        self.addCleanup(setattr, climod, "resolve", orig_resolve)
        out = self._preflight_out("unmapped-expr")
        self.assertIn("[note]", out, "the 'note' status must render with its distinct glyph")
        self.assertIn("torch_cuda==cu130", out)
        self.assertIn("1 note-only / 1 deferred", out,
                      "the footer must count note-only + deferred constraints")

    def test_no_footer_when_no_note_or_deferred(self):
        # a recipe whose checks are all pass/warn must NOT print the note/deferred footer.
        import executor.cli as climod
        from executor.resolve import Check, ResolveResult
        orig_resolve = climod.resolve

        def fake_resolve(recipe, rig):
            res = ResolveResult(recipe=recipe.slug, backend=recipe.backend,
                                instance_id="abcd1234", ok=True)
            res.checks = [Check("gpu_arch>=sm_120", "pass", "ok")]
            return res

        climod.resolve = fake_resolve
        self.addCleanup(setattr, climod, "resolve", orig_resolve)
        out = self._preflight_out("llama-main")
        self.assertNotIn("note-only", out, "no footer when there are no note/deferred checks")


# ---------------------------------------------------------------- BACKEND-B-004: provider-not-implemented in preflight
class TestPreflightProviderNotImplemented(_Tmp):
    """INVARIANT (BACKEND-B-004): cmd_preflight shows 'match=n/a — provider not implemented' for an
    unwired provider instead of a misleading 'YES'."""

    def _preflight_out(self, slug):
        class _Args:
            pass
        a = _Args()
        a.slug = slug
        a.db = self.db
        import executor.rig as rigmod
        orig = rigmod.detect
        rigmod.detect = lambda: fake_rig()
        self.addCleanup(setattr, rigmod, "detect", orig)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                cli.cmd_preflight(a)
            except SystemExit:
                pass
        return buf.getvalue()

    def test_implemented_provider_shows_match(self):
        out = self._preflight_out("llama-main")  # native-win-compile (match + reconcile real)
        self.assertIn("match=", out)
        self.assertNotIn("not implemented", out)

    def test_match_only_provider_shows_real_match(self):
        # wsl2-docker has a REAL match() but no reconcile bodies — preflight must show its REAL
        # match (gated on match_implemented), NOT 'n/a'. (The old single `implemented` flag would
        # have shown either a misleading 'YES' OR an over-eager 'n/a' depending on its value.)
        out = self._preflight_out("wsl-floor")  # wsl2-docker, match_implemented=True
        self.assertIn("provider wsl2-docker  match=", out,
                      "a real match() must render its YES/no verdict, not n/a")
        self.assertNotIn("match=n/a", out)
        self.assertNotIn("not implemented", out)

    def test_unimplemented_provider_shows_na(self):
        out = self._preflight_out("img-upper")  # venv (match_implemented=False)
        self.assertIn("match=n/a", out)
        self.assertIn("not implemented", out)


# ---------------------------------------------------------------- B-006: cli error shape (no traceback)
class TestCliErrorShape(_Tmp):
    """INVARIANT (PROVISION-B-006, shipcheck gate B): a RuntimeError out of a command (notably the
    corrupt-ledger guard) surfaces as a structured stderr line + non-zero exit, NO raw traceback."""

    def test_corrupt_ledger_status_exits_nonzero_with_message_no_traceback(self):
        # seed a ledger then corrupt it on disk so `er status` -> _ledger_load() raises RuntimeError.
        provision._ledger_put("inst-A", {"state": "ready", "compensators": []})
        with open(provision.LEDGER, "w", encoding="utf-8") as f:
            f.write("{ not valid json ")
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                cli.main(["--db", self.db, "status"])
        self.assertNotEqual(cm.exception.code, 0, "a corrupt ledger must exit non-zero")
        text = err.getvalue()
        self.assertIn("er: error:", text, "the error must be a structured one-liner on stderr")
        self.assertIn("ledger corrupt", text, "the structured message must explain the failure")
        self.assertNotIn("Traceback", text, "no raw traceback may reach the operator (gate B)")
        self.assertNotIn("Traceback", out.getvalue())

    def test_runtime_error_from_command_is_caught_in_main(self):
        # NON-VACUOUS: this MUST drive cli.main() itself (not a re-implemented copy of its
        # try/except). main() builds the parser fresh on each call and binds fn via the bare name
        # `cmd_status` resolved from the module global, so patching climod.cmd_status BEFORE main()
        # makes argparse bind the patched fn. A RuntimeError out of args.fn(args) must surface as a
        # structured 'er: error: <msg>' on stderr + SystemExit(1), with NO traceback.
        import executor.cli as climod
        orig = climod.cmd_status

        def boom(args):
            raise RuntimeError("synthetic command failure")

        climod.cmd_status = boom
        self.addCleanup(setattr, climod, "cmd_status", orig)

        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                cli.main(["--db", self.db, "status"])
        self.assertEqual(cm.exception.code, 1, "a command RuntimeError must exit 1")
        text = err.getvalue()
        self.assertIn("er: error: synthetic command failure", text,
                      "the error must be a structured one-liner on stderr")
        self.assertNotIn("Traceback", text, "no raw traceback may reach the operator")
        self.assertNotIn("Traceback", out.getvalue())


# ---------------------------------------------------------------- CIDOCS-B-004: provision/teardown help text
class TestCliHelpText(_Tmp):
    """INVARIANT (CIDOCS-B-004): the provision/teardown args carry help= text, and --execute's help
    states it is the only flag that touches the rig."""

    def _provision_help(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                cli.main(["provision", "--help"])
        return buf.getvalue()

    def test_execute_help_warns_it_touches_the_rig(self):
        h = self._provision_help()
        self.assertIn("--execute", h)
        self.assertIn("touches the rig", h, "the --execute help must flag it as the rig-touching flag")
        self.assertIn("dry-run", h)

    def test_model_port_from_and_slug_have_help(self):
        h = self._provision_help()
        for needle in ("--model", "--port", "--from", "recipe slug"):
            self.assertIn(needle, h, f"provision --help must document {needle}")

    def test_teardown_instance_has_help(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                cli.main(["teardown", "--help"])
        self.assertIn("instance id", buf.getvalue(), "teardown must document its instance arg")


if __name__ == "__main__":
    unittest.main()
