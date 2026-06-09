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
from executor.recipes import load_recipe


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


if __name__ == "__main__":
    unittest.main()
