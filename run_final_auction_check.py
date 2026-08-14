from __future__ import annotations

from v4_auction_last_chance import run_targeted_final_checks
from v4_final_alert_notification import send_identity_rich_final_notification


if __name__ == "__main__":
    count = run_targeted_final_checks(notify_fn=send_identity_rich_final_notification)
    raise SystemExit(0)
