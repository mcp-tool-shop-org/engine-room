"""Provider contract — the one non-leaky seam over heterogeneous backends.

Each backend implements a 4-function interface (match / materialize / launch / probe). The core
executor carries ZERO backend-specific code; it dispatches on recipe.backend. Only `match()` (a
read-only rig-suitability check) is implemented in this first slice — `materialize/launch/probe`
are the SIDE-EFFECTING next increment (built per-backend with the lock/ledger/compensators), so
they raise NotImplementedError until then rather than half-doing something irreversible.
"""
from __future__ import annotations
from .recipes import Recipe
from .rig import Rig

_NEXT = "provisioning (materialize/launch/probe) is the executor's next increment — built per-backend with lock + ledger + compensators"


class Provider:
    backend: str = ""
    summary: str = ""

    def match(self, recipe: Recipe, rig: Rig) -> tuple[bool, str]:
        """Read-only: can this backend run on this rig? (no side effects)"""
        return True, "ok"

    def materialize(self, recipe, rig, instance):  # side-effecting
        raise NotImplementedError(_NEXT)

    def launch(self, recipe, rig, instance):        # side-effecting
        raise NotImplementedError(_NEXT)

    def probe(self, recipe, rig, instance):         # reads the running endpoint
        raise NotImplementedError(_NEXT)


class NativeWinCompile(Provider):
    backend = "native-win-compile"
    summary = "from-source / prebuilt-wheel build on native Windows (llama.cpp, ExLlamaV3, mistral.rs)"
    def match(self, recipe, rig):
        if rig.os_surface != "windows":
            return False, "needs native Windows"
        if rig.sm != "sm_120":
            return False, f"expects sm_120, rig={rig.sm}"
        return True, "native-Windows Blackwell"


class Wsl2Docker(Provider):
    backend = "wsl2-docker"
    summary = "Linux-first engines under WSL2 + Docker (vLLM, SGLang, TEI)"
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
