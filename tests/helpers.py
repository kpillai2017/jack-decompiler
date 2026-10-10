"""Small helpers shared by the tests."""

from jack_decompiler import decompile_text
from jack_decompiler.compiler import compile_jack
from jack_decompiler.verify import verify


def jack_of(vm: str, cls: str = "Main", **options) -> str:
    """Decompile one class's VM text and return its Jack source."""
    return decompile_text(vm, f"{cls}.vm", **options).classes[cls].jack


def body_lines(jack: str) -> list:
    """The non-comment, non-blank lines of a Jack file, stripped."""
    return [line.strip() for line in jack.splitlines()
            if line.strip() and not line.strip().startswith(("/**", "*", "*/", "//"))]


def round_trip(jack_source: str, cls: str = "Main"):
    """Compile Jack -> VM, decompile it, and check that recompiling gives the same VM."""
    vm = compile_jack(jack_source, f"{cls}.jack")
    result = decompile_text(vm, f"{cls}.vm")
    checks = verify(result)
    return result, checks
