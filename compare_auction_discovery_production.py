from __future__ import annotations

# Validation entrypoint only. Install the exact production auction-discovery
# chain before importing compare_auction_discovery, whose module-level imports
# otherwise capture the pre-hardening collector.
from v4_auction_pagination_stability import install_v4_auction_pagination_stability

install_v4_auction_pagination_stability()

from compare_auction_discovery import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
