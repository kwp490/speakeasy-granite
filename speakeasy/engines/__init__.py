"""Engine implementations.

During the migration this package holds new engine code (currently the
:class:`~speakeasy.engines.fake.FakeEngine` test double).  Heavy ML imports are
only permitted *inside* function bodies, never at module scope, so importing
this package never pulls torch/transformers into the interpreter.
"""

from __future__ import annotations
