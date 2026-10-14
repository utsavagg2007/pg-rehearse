"""Planned feature 3–7; foundation-stage placeholder.

Execute experiments inside the run network with scoped database credentials and no Docker socket.
No database behavior is implemented in this module yet.
"""

import sys

from pg_rehearse.errors import ExitCode

if __name__ == "__main__":
    print("The isolated database worker is not implemented yet (feature 3).", file=sys.stderr)
    raise SystemExit(ExitCode.INCONCLUSIVE)
