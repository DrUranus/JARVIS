"""Ausdruecklicher Start: `python -m jarvis.control_center [--open]` ist derselbe Start wie `jarvis-cc` (echtes Backend, nur Loopback, nur mit control_center.enabled)."""
from jarvis.control_center.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
