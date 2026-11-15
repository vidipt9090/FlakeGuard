"""FlakeGuard module execution entry point (`python -m flakeguard`)."""

import sys

from flakeguard.cli import main

if __name__ == "__main__":
    sys.exit(main())

