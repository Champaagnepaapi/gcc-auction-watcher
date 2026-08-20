"""Entrypoint for Global notifications with Global-only TCGdex resilience."""
from __future__ import annotations

from v4_global_tcgdex_resilience import install_global_tcgdex_resilience
import v4_global_notify


def main() -> int:
    install_global_tcgdex_resilience()
    return v4_global_notify.main()


if __name__ == "__main__":
    raise SystemExit(main())
