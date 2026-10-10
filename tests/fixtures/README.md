# Sample programs used by the tests

Compiled `.vm` files, one folder per program, copied from
[jackvm-py](https://github.com/kpillai2017/jackvm-py)'s `games/` folder:

| Folder | What it is | Source |
|--------|------------|--------|
| `pong/` | Single-player Pong | nand2tetris software suite |
| `square-game/` | Move a square around | nand2tetris software suite |
| `average/` | Averages typed numbers; includes its own Jack OS classes | nand2tetris software suite |
| `hello-world/` | Prints "Hello world!" | nand2tetris software suite |

The nand2tetris programs come from the
[nand2tetris software suite](https://www.nand2tetris.org/software).

`tests/test_roundtrip.py` decompiles each one and checks that compiling
the result gives back exactly the same VM code. If a `jackvm-py` checkout
sits next to this repository (or `$JACKVM_GAMES` points at a games
folder), all of its games are checked as well, including Space Invaders.
