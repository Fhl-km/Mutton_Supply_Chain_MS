"""python -m mscm 入口。"""

from __future__ import annotations

import sys


def main() -> int:
    from mscm.app import run
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
