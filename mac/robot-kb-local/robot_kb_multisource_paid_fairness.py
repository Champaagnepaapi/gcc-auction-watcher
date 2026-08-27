from __future__ import annotations

import os
import time
from typing import Any


def install(harvest: Any) -> None:
    """Prevent one paid provider from consuming the other provider's runtime.

    When both provider keys are configured, PokeTrace receives the first half of
    the bounded paid-run window and PokemonPriceTracker receives the remaining
    half. If PokeTrace finishes early, PPT inherits the unused time. With only
    one configured provider, that provider keeps the full bounded window.
    """

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
        started_at = time.monotonic()
        global_deadline = started_at + runtime_seconds
        ppt_key = os.getenv("POKEMON_PRICE_TRACKER_API_KEY", "").strip()
        pt_key = os.getenv("POKETRACE_API_KEY", "").strip()

        if pt_key and ppt_key:
            poketrace_seconds = runtime_seconds // 2
            poketrace_deadline = started_at + poketrace_seconds
            diag.notes.append(
                f"paid:provider-windows:poketrace={poketrace_seconds}s:"
                f"ppt={runtime_seconds - poketrace_seconds}s"
            )
            harvest.harvest_poketrace(
                kb,
                state,
                pt_key,
                diag,
                poketrace_deadline,
            )
            if time.monotonic() < global_deadline:
                harvest.harvest_ppt(
                    kb,
                    state,
                    ppt_key,
                    diag,
                    global_deadline,
                )
            else:
                diag.notes.append("ppt:provider-window-exhausted")
            return

        if pt_key:
            harvest.harvest_poketrace(
                kb,
                state,
                pt_key,
                diag,
                global_deadline,
            )
        else:
            diag.notes.append("poketrace:key-not-configured")

        if ppt_key:
            if time.monotonic() < global_deadline:
                harvest.harvest_ppt(
                    kb,
                    state,
                    ppt_key,
                    diag,
                    global_deadline,
                )
            else:
                diag.notes.append("ppt:provider-window-exhausted")
        else:
            diag.notes.append("ppt:key-not-configured")

    harvest.run_paid = run_paid_fair
    harvest._robot_kb_paid_fairness_installed = True
