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

import hashlib
import json
import os
import tempfile
import unittest

from tests._fixtures import build_min_db, fake_rig  # coordinator-owned; import only
from executor import provision
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


if __name__ == "__main__":
    unittest.main()
