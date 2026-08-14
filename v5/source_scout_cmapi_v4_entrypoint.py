from __future__ import annotations

from typing import Mapping

from . import source_scout_benchmark as scout
from . import source_scout_cmapi_v2_entrypoint as v2
from . import source_scout_cmapi_v3_entrypoint as v3


def _strict_identity_matches(
    card: scout.PanelCard,
    match_identity: object,
    row: Mapping[str, object],
    language: str,
) -> bool:
    # A provider `tcgid` string that happens to equal a TCGdex id is useful
    # diagnostic metadata, but it is not by itself a proven cross-provider
    # alias. Preserve the project's deterministic identity contract: exact
    # name + set + collector number (or the already-explicit FR English anchor)
    # is required before market data can be attached automatically.
    del card, language
    return (
        scout.candidate_identity(
            match_identity,
            name=row.get("name"),
            set_name=v2._set_name(row),
            number=v2._number(row),
        )
        == "EXACT"
    )


def main() -> int:
    v3._identity_matches = _strict_identity_matches
    return v3.main()


if __name__ == "__main__":
    raise SystemExit(main())
