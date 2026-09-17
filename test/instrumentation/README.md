# Instrumentation tests

These tests check what the LLVM pass (`profiler/DiscoPoP`) inserts into a program. A test compiles
a small program with the DiscoPoP compiler wrapper, stops clang right after the pass has run and
asserts on the resulting LLVM IR:

```
discopop_cxx -S -emit-llvm test.cpp -o instrumented.ll
```

That is the earliest point at which the work of the pass is observable. Everything below it — the
profiling run, the dependency files, the pattern detection — only ever sees the already
instrumented program, so a mistake made here surfaces much later and only indirectly, if at all.
The tests in `test/profiler` cover the other end: they run the instrumented program and compare the
dependencies it reports against a gold standard.

## Layout

- `test_instrumentation.py` — what the pass inserts and where: function entry and exit, memory
  accesses, allocations, loops, call sites.
- `test_omission.py` — the basic block machinery that stands in for the instrumentation the pass
  leaves out (`__dp_report_bb`, `__dp_report_bb_pair`, `__dp_add_bb_deps`).
- `test_loop_counters.py` — the iteration counters (`__dp_loop_incr`, `__dp_loop_output`) and their
  agreement with `loop_meta.txt`.
- `utilities.py` — compiling and parsing, plus the shared assertions.

## Running them

```bash
. venv/bin/activate
python3 -m unittest -v -k "*test.instrumentation.*"
```

The tests need the profiler installed (`pip install ./profiler`, **without** `-e`), because they
invoke `discopop_cxx` from the venv. Compiling one program takes about half a second, and each test
class compiles once, no matter how many assertions it makes.

Set `DP_TEST_KEEP_ARTIFACTS=y` to keep the temporary build directory of each class; its path is
printed at the end of the class. It holds the program, the instrumented `instrumented.ll` and the
`.discopop` directory the pass wrote.

## Writing a test

Derive from `InstrumentationTestCase` and put the program into `SOURCE`. Mark the lines an
assertion refers to with a `// @<name>` comment, so that editing the program does not silently
invalidate every expectation:

```python
class TestSomething(InstrumentationTestCase):
    SOURCE = """
        int main() {
          int b[4];
          b[0] = 1;      // @write
          return b[0];
        }
        """

    def test_the_write_is_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_write", "write")
```

`utilities.py` parses the IR into functions, basic blocks and calls, and resolves the source line a
callback reports. The pass uses two conventions for that, and `InstrumentedProgram.source_line`
hides the difference:

- `__dp_func_entry`, `__dp_loop_entry`, `__dp_alloca`, … report a **packed location**,
  `(fileID << 14) + line` (see `LIDSIZE` in `profiler/share/include/DPUtils.hpp`).
- `__dp_read`, `__dp_write`, `__dp_call` report an **instruction id**, which the pass resolves
  through `.discopop/profiler/instructionID_to_lineID_mapping.txt`.
