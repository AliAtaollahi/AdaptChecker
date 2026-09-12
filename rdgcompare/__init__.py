"""Observable RDG slice comparison for Timed Rebeca models.

Implements the Rebeca Dependence Graph, the observable RDG slice, and the RDG
equivalence of Section 3 of "Proving Timed Weak Equivalence of Actors based on
Slice Equivalence".  Standard library only.
"""

from .compare import compare
from .rdg import build_rdg
from .rebeca import parse_file, parse_source
from .slicing import observable_slice, parse_observables

__all__ = ["build_rdg", "compare", "observable_slice", "parse_file",
           "parse_observables", "parse_source"]
__version__ = "1.0"
