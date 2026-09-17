"""Tests for the instrumentation the LLVM pass inserts.

Each test class compiles one small program and asserts on the callbacks the pass put into the
resulting LLVM IR: which ones were inserted, where they sit, and which source line and variable
they report. Source lines are referred to by the ``// @<marker>`` comments in the programs rather
than by number, so the programs stay editable.
"""

from .utilities import InstrumentationTestCase


class TestLoopOverArray(InstrumentationTestCase):
    """The canonical case: a loop writing an array, with scalars around it."""

    SOURCE = """
        int main() {                      // @main
          int a = 0;                      // @scalar_init
          int b[10];
          for (int i = 0; i < 10; ++i) {  // @loop
            b[i] = a + i;                 // @array_write
          }
          return b[3];                    // @array_read
        }
        """

    def test_main_is_entered_and_finalized(self) -> None:
        self.assertCallbackCount("__dp_func_entry", 1)
        self.assertInstrumentsLine("__dp_func_entry", "main")
        # the second argument marks the entry point of the program
        self.assertEqual(1, self.program.calls("__dp_func_entry")[0].arg_int(1))

        # main terminates the profiling run instead of reporting a plain function exit
        self.assertCallbackCount("__dp_finalize", 1)
        self.assertCallbackCount("__dp_func_exit", 0)
        self.assertInstrumentsLine("__dp_finalize", "array_read")

    def test_function_entry_precedes_everything_else(self) -> None:
        first = self.program.functions["main"][0]
        self.assertEqual(
            "__dp_func_entry",
            getattr(first, "callee", None),
            f"the first instruction of main is '{first.text}', so accesses before it go unreported",
        )

    def test_array_accesses_are_instrumented_at_their_source_lines(self) -> None:
        self.assertInstrumentsLine("__dp_write", "array_write")
        self.assertInstrumentsLine("__dp_read", "array_read")

    def test_instrumented_accesses_carry_the_variable_name(self) -> None:
        # The last argument is the name the later phases report the dependency under. An access
        # through a getelementptr keeps the name of the underlying variable behind a GEPRESULT_
        # prefix, which the gold standard tests in test/profiler expect to see as well.
        for callee in ("__dp_write", "__dp_read"):
            call = self.program.calls(callee)[0]
            name = self.program.string_value(call.arg_pointer(len(call.args) - 1))
            self.assertEqual("GEPRESULT_b", name, f"{callee} reports variable '{name}'")

    def test_scalar_locals_are_left_to_the_static_analysis(self) -> None:
        # Scalars that the pass can resolve statically are not instrumented individually; their
        # dependencies are reconstructed from the reported basic blocks. Only the array accesses
        # remain, so a regression that starts instrumenting scalars again shows up as extra calls.
        self.assertCallbackCount("__dp_write", 1)
        self.assertCallbackCount("__dp_read", 1)
        self.assertDoesNotInstrumentLine("__dp_write", "scalar_init")

    def test_every_reported_basic_block_is_reported_once(self) -> None:
        reports = self.program.calls("__dp_report_bb", function="main")
        blocks = [call.block for call in reports]
        identifiers = [call.arg_int(0) for call in reports]
        self.assertEqual(len(blocks), len(set(blocks)), f"a basic block is reported twice: {blocks}")
        self.assertEqual(
            len(identifiers),
            len(set(identifiers)),
            f"two basic blocks share a reported id: {list(zip(blocks, identifiers))}",
        )

    def test_the_loop_is_bracketed_by_entry_and_exit(self) -> None:
        self.assertCallbackCount("__dp_loop_entry", 1)
        self.assertCallbackCount("__dp_loop_exit", 1)
        self.assertInstrumentsLine("__dp_loop_entry", "loop")

        entry = self.program.calls("__dp_loop_entry")[0]
        exit_ = self.program.calls("__dp_loop_exit")[0]
        self.assertEqual(entry.arg_int(1), exit_.arg_int(1), "loop entry and exit report different loop ids")

    def test_the_stack_array_is_registered(self) -> None:
        # __dp_alloca tells the runtime which address range belongs to a stack variable
        self.assertCallbackCount("__dp_alloca", 1)
        alloca = self.program.calls("__dp_alloca")[0]
        self.assertEqual("b", self.program.string_value(alloca.arg_pointer(1)))
        # ten elements of four bytes each
        self.assertEqual(40, alloca.arg_int(4))
        self.assertEqual(10, alloca.arg_int(5))


class TestFunctionCall(InstrumentationTestCase):
    """A second function, so that entry, exit and call instrumentation become visible."""

    SOURCE = """
        int helper(int x) {               // @helper
          return x * 2;                   // @helper_return
        }

        int main() {                      // @main
          int values[4];
          for (int i = 0; i < 4; ++i) {
            values[i] = helper(i);        // @call
          }
          return values[0];               // @main_return
        }
        """

    def helper_name(self) -> str:
        """The mangled name clang gave to ``helper``."""
        names = [name for name in self.program.user_functions() if name != "main"]
        self.assertEqual(1, len(names), f"expected exactly one function besides main, found {names}")
        return names[0]

    def test_both_functions_are_entered(self) -> None:
        self.assertCallbackCount("__dp_func_entry", 2)
        self.assertInstrumentsLine("__dp_func_entry", "main", function="main")
        self.assertInstrumentsLine("__dp_func_entry", "helper", function=self.helper_name())

    def test_only_main_is_marked_as_the_entry_point(self) -> None:
        starts = {call.function: call.arg_int(1) for call in self.program.calls("__dp_func_entry")}
        self.assertEqual(1, starts["main"])
        self.assertEqual(0, starts[self.helper_name()])

    def test_the_helper_reports_its_exit_and_main_finalizes(self) -> None:
        self.assertCallbackCount("__dp_func_exit", 1, function=self.helper_name())
        self.assertCallbackCount("__dp_func_exit", 0, function="main")
        self.assertCallbackCount("__dp_finalize", 1, function="main")

    def test_the_call_site_is_instrumented_as_project_code(self) -> None:
        self.assertInstrumentsLine("__dp_call", "call")
        call = [c for c in self.program.calls("__dp_call") if self.program.source_line(c) is not None][0]
        # the second argument flags calls into code the pass did not instrument
        self.assertEqual(0, call.arg_int(1), "the call to helper is reported as a library call")


class TestNestedLoops(InstrumentationTestCase):
    """Loop ids have to stay distinct and paired, or loop nesting is mis-reported."""

    SOURCE = """
        int main() {
          int matrix[4][4];
          for (int i = 0; i < 4; ++i) {       // @outer
            for (int j = 0; j < 4; ++j) {     // @inner
              matrix[i][j] = i + j;           // @write
            }
          }
          return matrix[0][0];
        }
        """

    def test_both_loops_are_instrumented(self) -> None:
        self.assertCallbackCount("__dp_loop_entry", 2)
        self.assertCallbackCount("__dp_loop_exit", 2)
        self.assertInstrumentsLine("__dp_loop_entry", "outer")
        self.assertInstrumentsLine("__dp_loop_entry", "inner")

    def test_the_loops_get_distinct_ids(self) -> None:
        identifiers = [call.arg_int(1) for call in self.program.calls("__dp_loop_entry")]
        self.assertEqual(len(identifiers), len(set(identifiers)), f"the nested loops share a loop id: {identifiers}")

    def test_every_loop_entry_has_a_matching_exit(self) -> None:
        entered = sorted(call.required_arg_int(1) for call in self.program.calls("__dp_loop_entry"))
        exited = sorted(call.required_arg_int(1) for call in self.program.calls("__dp_loop_exit"))
        self.assertEqual(entered, exited)

    def test_the_innermost_write_is_instrumented_once(self) -> None:
        # the pass instruments the store, not the iterations, so one call covers all 16 writes
        self.assertCallbackCount("__dp_write", 1)
        self.assertInstrumentsLine("__dp_write", "write")


class TestHeapAllocation(InstrumentationTestCase):
    """Allocations have to be registered and unregistered, or addresses are reused silently.

    The three deallocations below reach clang as three different mangled names -- ``free``,
    ``_ZdaPv`` for ``delete[]`` and, since C++14, the sized ``_ZdlPvm`` for a plain ``delete`` --
    and the pass has to recognise all of them.
    """

    SOURCE = """
        #include <stdlib.h>

        int main() {
          int *m = (int *)malloc(4 * sizeof(int));  // @malloc
          m[0] = 1;                                 // @malloc_write
          int first = m[0];
          free(m);                                  // @free

          int *a = new int[4];                      // @new_array
          a[0] = 2;
          int second = a[0];
          delete[] a;                               // @delete_array

          int *s = new int;                         // @new_scalar
          *s = 3;
          int third = *s;
          delete s;                                 // @delete_scalar

          return first + second + third;
        }
        """

    def test_malloc_and_free_are_both_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_new", "malloc")
        self.assertInstrumentsLine("__dp_delete", "free")

    def test_new_and_delete_are_both_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_new", "new_array")
        self.assertInstrumentsLine("__dp_delete", "delete_array")
        self.assertInstrumentsLine("__dp_new", "new_scalar")
        self.assertInstrumentsLine("__dp_delete", "delete_scalar")

    def test_every_allocation_is_released_again(self) -> None:
        # a deallocation the pass does not recognise leaves the address range registered, so a
        # later allocation reusing the address inherits the accesses of the old object
        self.assertCallbackCount("__dp_new", 3)
        self.assertCallbackCount("__dp_delete", 3)

    def test_the_allocated_size_is_reported(self) -> None:
        allocation = [call for call in self.program.calls("__dp_new") if self.program.source_line(call) is not None]
        sizes = [call.arg_int(3) for call in allocation]
        self.assertIn(16, sizes, f"no allocation of 4 * sizeof(int) bytes was reported; sizes: {sizes}")

    def test_heap_accesses_are_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_write", "malloc_write")
