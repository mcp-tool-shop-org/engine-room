"""Backend-domain regression tests for the engine-room executor (stdlib unittest only).

Each test probes a FULL invariant from the Stage-A backend audit and is named for the
invariant it proves. Fixtures (build_min_db / fake_rig) are coordinator-owned — imported,
never edited. Run from the repo root:

    python -m unittest tests.test_backend -v
"""
from __future__ import annotations
import os
import tempfile
import unittest

from tests._fixtures import build_min_db, fake_rig
from executor import rig as rigmod
from executor import resolve as resolvemod
from executor.recipes import Constraint, load_recipe


def _check_for(result, needle):
    """Return the first Check whose .name contains needle (or None)."""
    for c in result.checks:
        if needle in c.name:
            return c
    return None


class TestCudaConflictAndon(unittest.TestCase):
    """BACKEND-A-001: conflicts_when cuda>=13 must read cuda_runtime too, and ANDON on unknown."""

    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(), "er_backend_a001.db")
        build_min_db(self.tmp)
        self.recipe = load_recipe("cuda13-trap", self.tmp)
        self.assertIsNotNone(self.recipe, "cuda13-trap fixture recipe missing")

    def test_live_cuda13_runtime_halts_even_without_nvcc(self):
        """INVARIANT: a live CUDA-13 runtime (UMD) trips the conflict even when nvcc (toolkit)
        is absent — the check must NOT silently pass by reading only rig.cuda_toolkit (None)."""
        rig = fake_rig(cuda_runtime="13.3", cuda_toolkit=None)
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "cuda_toolkit>=13")
        self.assertIsNotNone(chk, "conflicts_when cuda>=13 check did not run")
        self.assertNotEqual(chk.status, "pass",
                            f"CUDA-13 runtime must not pass the conflict (got {chk.status})")
        self.assertEqual(chk.status, "halt", f"expected halt, got {chk.status}: {chk.detail}")
        self.assertFalse(res.ok, "resolve must not be ok when the CUDA-13 conflict fires")

    def test_unknown_cuda_does_not_silently_pass(self):
        """INVARIANT (ANDON): when BOTH cuda fields are None the conflict cannot be cleared —
        absence of evidence is not evidence of safety; must warn/halt, never pass."""
        rig = fake_rig(cuda_runtime=None, cuda_toolkit=None)
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "cuda_toolkit>=13")
        self.assertIsNotNone(chk)
        self.assertNotEqual(chk.status, "pass",
                            "unknown CUDA must not silently pass a conflicts_when check")

    def test_clean_cuda12_runtime_passes(self):
        """INVARIANT: a known-good CUDA 12.x runtime clears the >=13 conflict (no false halt)."""
        rig = fake_rig(cuda_runtime="12.8", cuda_toolkit=None)
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "cuda_toolkit>=13")
        self.assertIsNotNone(chk)
        self.assertEqual(chk.status, "pass", f"clean CUDA 12.8 should pass; got {chk.status}: {chk.detail}")


class TestCudaRuntimeRegex(unittest.TestCase):
    """BACKEND-A-002 / M1: nvidia-smi header parse must catch 'CUDA UMD Version:' too."""

    def test_umd_header_token_parsed(self):
        """INVARIANT: the live header token 'CUDA UMD Version: 13.3' yields cuda_runtime=13.3."""
        header = (
            "+-----------------------------------------------------------------------------+\n"
            "| NVIDIA-SMI 610.47   Driver Version: 610.47   CUDA UMD Version: 13.3          |\n"
            "+-----------------------------------------------------------------------------+\n"
        )
        self.assertEqual(rigmod._parse_cuda_runtime(header), "13.3")

    def test_classic_header_token_still_parsed(self):
        """INVARIANT: the classic 'CUDA Version: 12.8' header still parses (no regression)."""
        header = "| NVIDIA-SMI 555.00   Driver Version: 555.00   CUDA Version: 12.8 |\n"
        self.assertEqual(rigmod._parse_cuda_runtime(header), "12.8")

    def test_no_cuda_token_returns_none(self):
        self.assertIsNone(rigmod._parse_cuda_runtime("no cuda here"))
        self.assertIsNone(rigmod._parse_cuda_runtime(None))


class TestWsl2Utf16(unittest.TestCase):
    """BACKEND-A-003: `wsl --version` emits UTF-16-LE — parse must decode it, not drop to None."""

    def test_utf16_le_version_decoded(self):
        """INVARIANT: a UTF-16-LE 'wsl --version' payload yields wsl2_version=2.7.3.0,
        not None (which would mis-fire the wsl2 defect_floor + wsl2-docker provider)."""
        raw = "WSL version: 2.7.3.0\nKernel version: 6.6.36.3-1\n".encode("utf-16-le")
        self.assertEqual(rigmod._parse_wsl2_version(raw), "2.7.3.0")

    def test_utf8_version_still_decoded(self):
        raw = "WSL version: 2.5.0.0\n".encode("utf-8")
        self.assertEqual(rigmod._parse_wsl2_version(raw), "2.5.0.0")

    def test_no_version_returns_none(self):
        self.assertIsNone(rigmod._parse_wsl2_version(b""))
        self.assertIsNone(rigmod._parse_wsl2_version("nothing".encode("utf-16-le")))


class TestGpuArchThreshold(unittest.TestCase):
    """BACKEND-A-004 / M3: gpu_arch capability must honor the sm_NNN threshold + comparator."""

    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(), "er_backend_a004.db")
        build_min_db(self.tmp)

    def test_higher_floor_does_not_pass_on_lower_rig(self):
        """INVARIANT: 'gpu_arch>=sm_130' must NOT pass on an sm_120 rig (was hardcoded to
        ok = rig.sm == 'sm_120', so any expr passed)."""
        recipe = load_recipe("arch-floor", self.tmp)  # expr: gpu_arch>=sm_130
        rig = fake_rig(sm="sm_120")
        res = resolvemod.resolve(recipe, rig)
        chk = _check_for(res, "gpu_arch")
        self.assertIsNotNone(chk, "gpu_arch capability check did not run")
        self.assertNotEqual(chk.status, "pass",
                            f"sm_130 floor must not pass on sm_120 rig; got {chk.status}")

    def test_met_floor_passes(self):
        """INVARIANT: 'gpu_arch>=sm_120' passes on an sm_120 rig (the floor is met)."""
        recipe = load_recipe("arch-floor", self.tmp)
        recipe.constraints[0].expr = "gpu_arch>=sm_120"
        rig = fake_rig(sm="sm_120")
        res = resolvemod.resolve(recipe, rig)
        chk = _check_for(res, "gpu_arch")
        self.assertIsNotNone(chk)
        self.assertEqual(chk.status, "pass", f"met floor should pass; got {chk.status}: {chk.detail}")

    def test_unknown_sm_does_not_silently_pass(self):
        """INVARIANT (ANDON): an unknown rig.sm cannot clear a gpu_arch floor — must not pass."""
        recipe = load_recipe("arch-floor", self.tmp)
        rig = fake_rig(sm=None)
        res = resolvemod.resolve(recipe, rig)
        chk = _check_for(res, "gpu_arch")
        self.assertIsNotNone(chk)
        self.assertNotEqual(chk.status, "pass", "unknown sm must not silently pass a gpu_arch floor")


class TestSmiNameWithComma(unittest.TestCase):
    """BACKEND-A-005 / M4: a GPU name containing a comma must not break name/mem/driver parse."""

    def test_comma_in_gpu_name_parses_fields(self):
        """INVARIANT: 'NVIDIA RTX 5000, Ada Generation, 32760, 580.00' still yields the right
        memory + driver (the trailing two fields), not a blind/empty fingerprint."""
        line = "NVIDIA RTX 5000, Ada Generation, 32760, 580.00"
        parsed = rigmod._parse_smi_query(line)
        self.assertIsNotNone(parsed, "comma-in-name line failed to parse (blind fingerprint)")
        self.assertEqual(parsed["gpu"], "NVIDIA RTX 5000, Ada Generation")
        self.assertEqual(parsed["vram_gb"], round(32760 / 1024, 1))
        self.assertEqual(parsed["driver"], "580.00")

    def test_plain_name_still_parses(self):
        line = "NVIDIA GeForce RTX 5090, 32607, 610.47"
        parsed = rigmod._parse_smi_query(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["gpu"], "NVIDIA GeForce RTX 5090")
        self.assertEqual(parsed["driver"], "610.47")


class TestWsl2DefectFloorEvaluation(unittest.TestCase):
    """IF-10 / BACKEND-A-006: the defect_floor 'wsl2>=2.7.0' CONSTRAINT-EVALUATION triad.

    The wsl2 parser is covered elsewhere (TestWsl2Utf16); here we pin how resolve() EVALUATES
    the parsed value against the floor: unknown -> warn (defect can't apply), below -> halt + not
    ok, met -> pass. Uses the 'wsl-floor' fixture (defect_floor 'wsl2>=2.7.0')."""

    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(), "er_backend_a006.db")
        build_min_db(self.tmp)
        self.recipe = load_recipe("wsl-floor", self.tmp)
        self.assertIsNotNone(self.recipe, "wsl-floor fixture recipe missing")

    def test_unknown_wsl2_warns_not_pass(self):
        """INVARIANT (ANDON, half 1): an unknown wsl2_version must NOT silently pass — it warns,
        because an absent WSL pathway means the wsl2 defect simply can't apply (non-blocking)."""
        rig = fake_rig(wsl2_version=None)
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "wsl2>=2.7")
        self.assertIsNotNone(chk, "defect_floor wsl2>=2.7 check did not run")
        self.assertNotEqual(chk.status, "pass",
                            f"unknown wsl2 must not silently pass the defect_floor; got {chk.status}")
        self.assertEqual(chk.status, "warn", f"expected warn, got {chk.status}: {chk.detail}")
        self.assertTrue(res.ok, "an unknown wsl2 warn is non-blocking — resolve should still be ok")

    def test_below_floor_halts_and_not_ok(self):
        """INVARIANT (half 2): a wsl2 below the 2.7.0 floor HALTS (WDDM graph-capture hang) AND
        flips res.ok to False — both halves, not just the per-check status."""
        rig = fake_rig(wsl2_version="2.5.0.0")
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "wsl2>=2.7")
        self.assertIsNotNone(chk)
        self.assertEqual(chk.status, "halt", f"wsl2 2.5.0.0 must halt; got {chk.status}: {chk.detail}")
        self.assertFalse(res.ok, "resolve must not be ok when the wsl2 defect_floor halts")

    def test_met_floor_passes(self):
        """INVARIANT (half 3): a wsl2 at/above 2.7.0 clears the floor -> pass (no false halt)."""
        rig = fake_rig(wsl2_version="2.7.3.0")
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "wsl2>=2.7")
        self.assertIsNotNone(chk)
        self.assertEqual(chk.status, "pass", f"wsl2 2.7.3.0 should pass; got {chk.status}: {chk.detail}")
        self.assertTrue(res.ok, "a met wsl2 floor should leave resolve ok")


class TestCudaToolkitPositiveRequirement(unittest.TestCase):
    """IF-11 / BACKEND-A-007: the positive 'cuda_toolkit==12.8' requirement branch.

    Pins the DELIBERATE ASYMMETRY between a positive requirement and a conflict:
      - a positive requirement you CANNOT confirm (toolkit unknown) -> warn (non-blocking): wheels
        may bundle their own toolkit, so absence of nvcc is not a hard failure.
      - a value that CONTRADICTS the requirement (toolkit 13.0 != 12.8) -> halt.
    Contrast TestCudaConflictAndon, where an unknown you cannot RULE OUT -> halt (live runtime
    is definitely present). Uses the 'toolkit-12-8' fixture (capability 'cuda_toolkit==12.8')."""

    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(), "er_backend_a007.db")
        build_min_db(self.tmp)
        self.recipe = load_recipe("toolkit-12-8", self.tmp)
        self.assertIsNotNone(self.recipe, "toolkit-12-8 fixture recipe missing")

    def test_unknown_toolkit_warns_non_blocking(self):
        """INVARIANT (half 1 — asymmetry, requirement-unknown): no nvcc on PATH cannot CONFIRM
        the positive 12.8 requirement, so it warns (non-blocking) rather than halts — a positive
        requirement you can't confirm is softer than a conflict you can't rule out."""
        rig = fake_rig(cuda_toolkit=None)
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "cuda_toolkit==12.8")
        self.assertIsNotNone(chk, "cuda_toolkit==12.8 capability check did not run")
        self.assertEqual(chk.status, "warn", f"unknown toolkit should warn; got {chk.status}: {chk.detail}")
        self.assertTrue(res.ok, "a requirement-unknown warn is non-blocking — resolve stays ok")

    def test_wrong_toolkit_halts(self):
        """INVARIANT (half 2 — asymmetry, requirement-contradicted): a toolkit that is present but
        is NOT 12.8 (here 13.0) contradicts the positive requirement -> halt + not ok."""
        rig = fake_rig(cuda_toolkit="13.0")
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "cuda_toolkit==12.8")
        self.assertIsNotNone(chk)
        self.assertEqual(chk.status, "halt", f"toolkit 13.0 contradicts 12.8 -> halt; got {chk.status}: {chk.detail}")
        self.assertFalse(res.ok, "resolve must not be ok when the toolkit requirement is contradicted")


class TestUnmappedExprNote(unittest.TestCase):
    """BACKEND-B-001 / B-002: a constraint whose expr the evaluator has NO handler for resolves
    to the NEW status 'note' — legibly distinct from 'deferred' (a deliberate re-check) and from
    'pass' (an affirmative verdict). Uses the 'unmapped-expr' fixture (requires_when
    'torch_cuda==cu130', a shape no handler matches). Hermetic: built from the in-memory min DB,
    NOT the live engines.db."""

    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(), "er_backend_b001.db")
        build_min_db(self.tmp)
        self.recipe = load_recipe("unmapped-expr", self.tmp)
        self.assertIsNotNone(self.recipe, "unmapped-expr fixture recipe missing")

    def test_unmapped_expr_resolves_to_note(self):
        """INVARIANT: requires_when 'torch_cuda==cu130' (no evaluator handler) -> status 'note',
        NOT 'deferred' and NOT 'pass'. 'note' is the legible 'this executor has no rule' signal."""
        rig = fake_rig()
        res = resolvemod.resolve(self.recipe, rig)
        chk = _check_for(res, "torch_cuda==cu130")
        self.assertIsNotNone(chk, "the unmapped requires_when constraint check did not run")
        self.assertEqual(chk.status, "note",
                         f"unmapped expr must be 'note'; got {chk.status}: {chk.detail}")
        self.assertNotEqual(chk.status, "deferred", "an unmapped expr must NOT masquerade as a deferred re-check")
        self.assertNotEqual(chk.status, "pass", "an unmapped expr must NOT silently pass")

    def test_note_is_non_blocking(self):
        """INVARIANT: 'note' is non-blocking — an unmapped constraint must NOT halt provision
        (it is not in res.halts and res.ok stays True). Avoids false-halting KB rows the
        executor simply has no rule for yet."""
        res = resolvemod.resolve(self.recipe, fake_rig())
        chk = _check_for(res, "torch_cuda==cu130")
        self.assertEqual(chk.status, "note")
        self.assertNotIn(chk, res.halts, "'note' must never appear in res.halts")
        self.assertTrue(res.ok, "a note-only preflight has no halts — resolve should stay ok")


class TestConstraintDispatchTable(unittest.TestCase):
    """BACKEND-B-002: the constraint evaluator is a dispatch registry (matcher -> handler), and
    the terminal fall-through splits 'deferred' (deliberate punt) from 'note' (no handler).

    These pin the BEHAVIOR of the refactor against synthetic Constraint objects (no DB) so the
    full status set (pass/halt/warn/deferred/note) is locked at the seam, not just one path."""

    def test_abi_equal_stays_deferred_not_note(self):
        """INVARIANT: abi_equal is a DELIBERATE re-check-at-materialize -> 'deferred', NOT 'note'.
        The split must keep this distinct from the no-handler case."""
        c = Constraint(ctype="abi_equal", expr="abi(a)==abi(b)", reason=None)
        chk = resolvemod._eval_constraint(c, fake_rig())
        self.assertEqual(chk.status, "deferred",
                         f"abi_equal is a deliberate punt -> deferred; got {chk.status}")

    def test_unknown_conflicts_when_fallthrough_is_note_not_halt(self):
        """INVARIANT: a conflicts_when expr with NO matching handler falls through to 'note',
        NOT escalated to warn/halt — escalating would false-halt the ~29 KB conflict rows the
        evaluator does not model. 'note' is the legible signal instead."""
        c = Constraint(ctype="conflicts_when", expr="rocm>=6.0", reason="AMD path not modeled")
        chk = resolvemod._eval_constraint(c, fake_rig())
        self.assertEqual(chk.status, "note",
                         f"unmodeled conflicts_when must be 'note', not a false halt; got {chk.status}")
        self.assertNotEqual(chk.status, "halt", "an unmodeled conflicts_when must NOT false-halt")

    def test_registered_handler_still_dispatches(self):
        """INVARIANT (no regression): a registered shape still routes to its handler. The
        gpu_arch capability on an sm_120 rig with an sm_120 floor -> 'pass' (handler ran),
        proving the table dispatches, not just the fall-through."""
        c = Constraint(ctype="capability", expr="gpu_arch>=sm_120", reason=None)
        chk = resolvemod._eval_constraint(c, fake_rig(sm="sm_120"))
        self.assertEqual(chk.status, "pass",
                         f"registered gpu_arch handler should dispatch -> pass; got {chk.status}: {chk.detail}")

    def test_new_handler_is_one_line_registration(self):
        """INVARIANT (extensibility): the registry is the single extension point. Registering a
        matcher->handler pair makes a previously-unmapped expr resolve via the new handler instead
        of falling through to 'note'. We append, exercise, then restore so the suite stays clean."""
        c = Constraint(ctype="requires_when", expr="torch_cuda==cu130", reason=None)
        # before registration: falls through to 'note'
        self.assertEqual(resolvemod._eval_constraint(c, fake_rig()).status, "note")
        sentinel = lambda cc, rig: resolvemod.Check(cc.expr, "pass", "handled by test handler")
        resolvemod._HANDLERS.append((lambda cc: "torch_cuda==cu130" in cc.expr, sentinel))
        try:
            chk = resolvemod._eval_constraint(c, fake_rig())
            self.assertEqual(chk.status, "pass", "the one-line registration should now handle the expr")
            self.assertEqual(chk.detail, "handled by test handler")
        finally:
            resolvemod._HANDLERS.pop()  # restore the registry for the rest of the suite


class TestSmiPerFieldDegrade(unittest.TestCase):
    """BACKEND-B-003: _parse_smi_query degrades PER FIELD — a non-numeric memory.total keeps
    name + driver and sets vram_gb=None, instead of dropping the whole row to None."""

    def test_na_memory_keeps_name_and_driver(self):
        """INVARIANT: 'NVIDIA X, [N/A], 580.00' -> name+driver retained, vram_gb=None (NOT a
        whole-row None that would blank the fingerprint)."""
        parsed = rigmod._parse_smi_query("NVIDIA X, [N/A], 580.00")
        self.assertIsNotNone(parsed, "[N/A] memory must NOT drop the whole row to None")
        self.assertEqual(parsed["gpu"], "NVIDIA X")
        self.assertEqual(parsed["driver"], "580.00")
        self.assertIsNone(parsed["vram_gb"], "non-numeric memory.total -> vram_gb None")

    def test_na_memory_with_comma_name_still_degrades_per_field(self):
        """INVARIANT: per-field degrade composes with the comma-in-name rsplit — the name is
        still the everything-before-the-last-two-fields, driver intact, vram None."""
        parsed = rigmod._parse_smi_query("NVIDIA RTX 5000, Ada Generation, [N/A], 580.00")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["gpu"], "NVIDIA RTX 5000, Ada Generation")
        self.assertEqual(parsed["driver"], "580.00")
        self.assertIsNone(parsed["vram_gb"])

    def test_numeric_memory_still_yields_vram(self):
        """INVARIANT (no regression): a numeric memory still produces a real vram_gb."""
        parsed = rigmod._parse_smi_query("NVIDIA X, 32760, 580.00")
        self.assertEqual(parsed["vram_gb"], round(32760 / 1024, 1))

    def test_wrong_field_count_still_none(self):
        """INVARIANT: an unparseable row SHAPE (too few fields) is still None — only the memory
        FIELD degrades, not the row structure."""
        self.assertIsNone(rigmod._parse_smi_query("just-a-name"))


class TestSmTableBlackwellSkus(unittest.TestCase):
    """BACKEND-B-005: the sm mapping is a data table and covers the full sm_120 Blackwell
    desktop family (5090/5080 plus the 5070, 5070 Ti, 5060 family the original ladder omitted)."""

    def test_5070_is_sm_120(self):
        """INVARIANT: 'NVIDIA GeForce RTX 5070' -> 'sm_120' (was unmapped -> None before)."""
        self.assertEqual(rigmod._sm_for("NVIDIA GeForce RTX 5070"), "sm_120")

    def test_5070_ti_and_5060_family_are_sm_120(self):
        for name in ("NVIDIA GeForce RTX 5070 Ti", "NVIDIA GeForce RTX 5060",
                     "NVIDIA GeForce RTX 5060 Ti"):
            self.assertEqual(rigmod._sm_for(name), "sm_120", f"{name} should map to sm_120")

    def test_existing_5090_5080_still_sm_120(self):
        """INVARIANT (no regression): the original SKUs still resolve via the table."""
        self.assertEqual(rigmod._sm_for("NVIDIA GeForce RTX 5090"), "sm_120")
        self.assertEqual(rigmod._sm_for("NVIDIA GeForce RTX 5080"), "sm_120")

    def test_unknown_gpu_still_none(self):
        """INVARIANT: a non-Blackwell name is still None (the table didn't over-match)."""
        self.assertIsNone(rigmod._sm_for("NVIDIA GeForce RTX 4090"))
        self.assertIsNone(rigmod._sm_for(None))


if __name__ == "__main__":
    unittest.main()
