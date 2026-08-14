from __future__ import annotations

import json
import os
import sys
from typing import Sequence

from . import source_scout_benchmark as scout
from . import source_scout_language_entrypoint as base
from . import source_scout_paid_v3_entrypoint as paid_v3


# Keep a handle to the real adapter before replacing scout.cmapi below.
_PROVIDER_CMAPI = scout.cmapi


def cmapi_three_language_probe(
    panel: Sequence[scout.PanelCard], key: str
) -> tuple[list[scout.Observation], scout.Runtime]:
    """Exactly one CMAPI card per purchase-scope language, three calls maximum."""
    selected: list[tuple[int, scout.PanelCard]] = []
    for wanted in base.LANGUAGES:
        for index, card in enumerate(panel):
            if scout.lang(card.identity.language) == wanted:
                selected.append((index, card))
                break

    out = [
        scout.Observation(
            "cmapi", card.label, error="SKIPPED_BOUNDED_THREE_CARD_PROBE"
        )
        for card in panel
    ]
    if not selected:
        return out, scout.Runtime(blocked=True, errors=["NO_LANGUAGE_SAMPLES"])

    # _PROVIDER_CMAPI sees only the three selected cards. In addition, the
    # global call cap is set to 3 in main(), so this remains fail-closed even
    # if this selection logic changes later.
    sample_rows, runtime = _PROVIDER_CMAPI([card for _, card in selected], key)
    for (index, _card), observation in zip(selected, sample_rows):
        out[index] = observation
    return out, runtime


def main() -> int:
    paid_v3.PPT_EVIDENCE.clear()
    paid_v3.PPT_PROBES.clear()

    scout.build_panel = base.build_language_panel
    scout.PANEL_SIZE = base.PANEL_SIZE
    os.environ["SOURCE_SCOUT_PANEL_SIZE"] = str(base.PANEL_SIZE)

    scout.PLAN["pokemonpricetracker"] = (
        "API $9.99/mo; 20k credits/day; 180d history; Japanese; "
        "eBay graded; Cardmarket EUR beta"
    )
    scout.pokemonpricetracker = paid_v3.pokemonpricetracker_api
    scout.poketrace = base.poketrace_corrected

    # Explicit user-authorized CMAPI test. Basic plan has paid overage after the
    # free daily allowance, so this benchmark is deliberately restricted to
    # three requests total and keeps the existing quota-remaining stop guard.
    scout.CMAPI_CALL_CAP = 3
    scout.CMAPI_TOTAL_CAP = 3_000_000
    scout.cmapi = cmapi_three_language_probe
    os.environ["SOURCE_SCOUT_ENABLE_CMAPI"] = "true"

    try:
        report = scout.run()
    except Exception as exc:
        print(
            f"SOURCE_SCOUT_CMAPI_FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    report["language_summary"] = base._language_summary(report)
    with open(
        os.getenv("SOURCE_SCOUT_JSON", "source_scout_report.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    rendered = base._language_markdown(report)
    with open(
        os.getenv("SOURCE_SCOUT_MARKDOWN", "source_scout_report.md"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(rendered)
    print(rendered)

    paid_v3._write_evidence()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
