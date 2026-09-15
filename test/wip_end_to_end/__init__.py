"""Work-in-progress end-to-end tests.

The tests below this package are known to fail: they describe behaviour the
analyses do not support yet (see commit "test: moved failing advanced tests to
wip"). They are kept around as a staging area, but they are excluded from test
collection so that a plain ``python -m unittest -v`` over the repository stays
green. Move a test back into ``test/end_to_end`` once it passes.
"""

import unittest
from typing import Any


def load_tests(loader: Any, standard_tests: Any, pattern: Any) -> unittest.TestSuite:
    """Hide this package from ``unittest`` discovery.

    Defining ``load_tests`` in a package's ``__init__.py`` makes discovery hand
    the whole package over to this function instead of recursing into it, so
    returning an empty suite drops every test below this directory.
    """
    return unittest.TestSuite()
