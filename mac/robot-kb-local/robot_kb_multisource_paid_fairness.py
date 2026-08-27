from __future__ import annotations

import os
import time
from typing import Any


def install(harvest: Any) -> None:
    if getattr(harvest, "_robot_kb_paid_fairness_installed", False):
        return

    def run_paid_fair(kb: Any, state: dict[str, Any], diag: Any) -> None:
        if not harvest.paid_open():
            diag.notes.append("paid:configured-access-window-ended")
            return

        runtime_seconds = max(
            60,
            int(os.getenv("ROBOT_KB_PAID_MAX_RUNTIME_SECONDS", "5100")),
        )
        ppt_key = os.getenv("POKEMON_PRICE_TRACKER_API_KEY", "").strip()
        pt_key = os.getenv("POKETRACE_API_KEY", "").strip()

        if pt_key and ppt_key:
            poketrace_seconds = runtime_seconds // 2
            ppt_seconds = runtime_seconds - poketrace_seconds
            diag.notes.append(
                f"paid:provider-windows:poketrace={poketrace_seconds}s:"
                f"ppt={ppt_seconds}s:independent=true"
            )
            harvest.harvest_poketrace(
                kb,
                state,
                pt_key,
                diag,
                time.monotonic() + poketrace_seconds,
            )
            harvest.harvest_ppt(
                kb,
                state,
                ppt_key,
                diag,
                time.monotonic() + ppt_seconds,
            )
            return

        if pt_key:
            harvest.harvest_poketrace(
                kb,
                state,
                pt_key,
                diag,
                time.monotonic() + runtime_seconds,
            )
        else:
            diag.notes.append("poketrace:key-not-configured")

        if ppt_key:
            harvest.harvest_ppt(
                kb,
                state,
                ppt_key,
                diag,
                time.monotonic() + runtime_seconds,
            )
        else:
            diag.notes.append("ppt:key-not-configured")

    harvest.run_paid = run_paid_fair
    harvest._robot_kb_paid_fairness_installed = True
