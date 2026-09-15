<!--
 /*
 * This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */
 -->

# Important Notes
The execution of the unit tests requires the `build` folder to be located within the original `discopop` directory!

# Executing Unit Tests
The end-to-end tests can be executed by simply using `python -m unittest -v`.

# Work-in-progress Tests
The tests below `test/wip_end_to_end` are known to fail and are excluded from collection
(see `test/wip_end_to_end/__init__.py`), so neither `python -m unittest -v` nor `pytest`
picks them up. To work on one of them, run it explicitly, e.g.
`python -m unittest -v test.wip_end_to_end.do_all.backwards_array_access.test`.
Once it passes, move it over to `test/end_to_end`.
