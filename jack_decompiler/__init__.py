"""
jack_decompiler - turn nand2tetris Jack VM code (.vm) back into Jack source (.jack).

    python -m jack_decompiler                  # open the GUI
    python -m jack_decompiler games/pong -o out  # decompile from the command line
"""

from .decompiler import ClassResult, DecompileResult, decompile_files, decompile_functions, decompile_text
from .engine import DecompileError
from .vm_reader import VMSyntaxError

__version__ = "0.2.0"
__all__ = ["ClassResult", "DecompileError", "DecompileResult", "VMSyntaxError", "decompile_files",
           "decompile_functions", "decompile_text", "__version__"]
