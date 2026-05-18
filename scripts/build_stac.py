"""Thin wrapper script to call the package CLI entrypoint.

This file ensures the local `src/` package is preferred when executed from
the repository root. Without this, Python may import an installed version of
`esa_trait_publish` (from an egg), which can be out-of-date. We prepend the
local `src` directory to sys.path so imports resolve to the workspace code.
"""

import sys
import os
from pathlib import Path

# Prepend the repository-local `src/` directory so `import esa_trait_publish`
# will resolve to the workspace code rather than an installed package.
repo_root = Path(__file__).resolve().parents[1]
local_src = str((repo_root / "src").resolve())
if local_src not in sys.path:
	sys.path.insert(0, local_src)

from esa_trait_publish.cli import main


if __name__ == "__main__":
	main()

