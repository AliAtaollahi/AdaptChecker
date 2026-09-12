#!/usr/bin/env python3
"""Run the observable RDG slice comparison with a plain `python3`.

    python3 adaptcheck.py model1.rebeca model2.rebeca observables.txt -o out

No installation and no third-party package: the whole tool is standard
library, so this only needs to import the `rdgcompare` package next to it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rdgcompare.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
