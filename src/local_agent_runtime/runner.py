"""Private detached supervisor entry point; use agent-runtime start to launch work."""

from .process import main

if __name__ == "__main__":
    raise SystemExit(main())
