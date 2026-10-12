# Extended compiler and OS compatibility

The decompiler reads **VM**, not Jack source. The compiler's opt-in extensions
use existing VM instructions, so there is no new bytecode format to select.

## What is recovered

| Compiler source feature | Decompiled representation |
|---|---|
| Hex/binary integers, character literals | Numeric values; original spelling is lost |
| `<=`, `>=`, `!=` | Equivalent standard Jack comparisons plus `~` |
| Escaped strings | Escaped literals in extension-marked classes; standard literals or `String.new`/`appendChar` calls otherwise |
| Local initialisers | Local declarations followed by assignments in execution order |
| Scalar compound assignment | Ordinary assignment with a binary expression |
| Array compound assignment | Compound syntax, preserving one evaluation of the target/index |
| `for` | `for` with initialisation as a preceding assignment; update and continue targets retained |
| `break`, `continue` | Innermost loop controls |
| Constants and enum members | Inlined values; names, declared types and enum membership are lost |

The generated file includes a `Requires jackc --extensions` comment whenever
loop controls, for loops, array compound updates, or escaped strings require
extended syntax. In marked files, backslashes are escaped to preserve their
character values under the compiler's extension-mode lexer.
Compile these files using the companion compiler CLI:

```bash
jackdecomp path/to/vm-folder --verify -o recovered
jackc --extensions recovered -o rebuilt
```

The compiler GUI currently defaults to standard mode. Ctrl+J opens that GUI; it
does not enable extensions automatically. Use the CLI above for marked files.
`--verify`/Ctrl+T still works through the decompiler's own checking compiler,
which understands the extension syntax it emits. That checker is not a general
replacement for the companion compiler and does not parse source-level const/
enum declarations or reconstruct syntax erased by compilation.

## Why array compound syntax matters

```jack
let values[Main.nextIndex()] += Main.delta();
```

Replacing this with an assignment that mentions `nextIndex()` twice changes
behaviour. The VM keeps the target address and old value on its stack while the
RHS runs. The decompiler detects that pattern and emits compound syntax, and
its checking compiler reproduces the same instructions. This also handles RHS
calls that modify the target or overwrite temporary/pointer segments.

## Loop reconstruction

Standard while/if reconstruction remains based on jump structure. Valid jumps
to the current loop exit/header become break/continue. For the companion
compiler's `FOR$`, `FORUPDATE$`, and `ENDFOR$` label convention, a separate
update block becomes a for header, including an empty update/condition.
Continue goes to that update; break and return skip it. Arbitrary gotos,
conditional back edges (do-while), or multi-statement update blocks are still
reported as unsupported, with original VM retained in comments.

A program is assumed to use a consistent compiler layout. Companion `$` labels
select its base-first array-read layout across routines, including routines
without labels. Without a dialect marker, a bare sum of two VM variables can
be ambiguous (array base versus index): VM has no types. Exact round-trip
verification is the guard against changed instruction order, not proof that
all inferred variable names/types express the original author's intent.

## Verification remains strict

Standard nand2tetris and companion compilers differ in conditional jump layout
and array-read operand order. The verifier tries both checking-compiler layouts
and accepts **only instruction-for-instruction equality**, after existing label
and function-name normalisation. It does not waive differences or substitute a
heuristic semantic comparison. Old standard fixtures remain supported.

## Extended OS APIs

All 66 companion public additions are known, including Memory/Screen utilities,
String methods, Math shifts/mod/clamp, Input, Random, IntQueue, IntStack, Console,
Timer, and Clock. Signatures guide receiver syntax, return/parameter types and
variable naming. In particular `stack.pop()` is recognised as a method rather
than a function taking an unrelated integer argument.

Recognition does not supply an implementation: use a compatible extended OS,
not the stock nand2tetris OS. Clock host support remains a runtime requirement.
When decompiling the OS itself, program definitions take precedence over the
external signature catalogue; private helpers can be reconstructed from VM.

## Tests and optional companions

```bash
python3 -m pytest -q
# With sibling compiler/VM checkouts available:
PYTHONPATH="../jack-compiler:../jackvm-py" python3 -m pytest tests/test_extensions.py -q
```

Core tests exercise all extended OS signatures, loops, and array compound
patterns using the built-in checker. Optional tests compile real extended Jack
(including the combined teaching lesson), compare the compiler/decompiler OS
contracts, and decompile/verify the full packaged extended OS VM. CI fetches the
companions and enables imports so these checks run there.
