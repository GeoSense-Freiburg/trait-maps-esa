"""Thin wrapper script to call the package CLI entrypoint.

This file intentionally contains no logic; it simply forwards execution to
the CLI main() function so the script can be invoked directly.
"""

from esa_trait_publish.cli import main


if __name__ == "__main__":
	main()

