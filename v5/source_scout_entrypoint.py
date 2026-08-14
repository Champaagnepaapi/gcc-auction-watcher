from __future__ import annotations

from typing import Mapping, Sequence
from urllib.parse import quote

from . import source_scout_benchmark as scout
from .models import CardIdentity


SEED_SPECS: Sequence[tuple[str, str]] = (
    ("en", "base1"),
    ("fr", "base1"),
    ("de", "base1"),
    ("it", "base1"),
    ("es", "base1"),
    ("en", "swsh3"),
    ("fr", "swsh3"),
    ("de", "swsh3"),
    ("en", "sv06"),
    ("fr", "sv06"),
    ("de", "sv06"),
    ("it", "sv06"),
    ("es", "sv06"),
)


def _finish_from_variants(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    # A benchmark seed may deliberately select one catalogue-proven printing.
    # We never infer a finish from absence; only explicit True values count.
    if value.get("holo") is True:
        return "Holo"
    if value.get("reverse") is True:
        return "Reverse Holo"
    return None


def _candidate_indices(length: int) -> tuple[int, ...]:
    if length <= 0:
        return ()
    raw = (0, length // 4, length // 2, (3 * length) // 4, length - 1)
    return tuple(dict.fromkeys(index for index in raw if 0 <= index < length))


def _supplement_from_tcgdex(
    panel: list[scout.PanelCard],
    *,
    size: int,
    diagnostics: dict[str, object],
) -> list[scout.PanelCard]:
    if len(panel) >= size:
        return panel

    client = scout.SafeClient(
        "tcgdex_seed",
        call_cap=60,
        interval=0.05,
        response_cap=2_000_000,
        total_cap=40_000_000,
    )
    seen = {
        (
            scout._normalize_card_name(card.identity.card_name),
            scout._normalize(card.identity.set),
            scout._normalize_card_number(card.identity.card_number),
            scout.lang(card.identity.language),
        )
        for card in panel
    }
    seeded = 0

    for language, set_id in SEED_SPECS:
        if len(panel) >= size or client.runtime.blocked:
            break
        response, payload = client.request(
            "GET",
            f"https://api.tcgdex.net/v2/{quote(language, safe='')}/sets/{quote(set_id, safe='')}",
        )
        if not response or response.status_code != 200 or not isinstance(payload, Mapping):
            continue
        set_name = str(payload.get("name") or "").strip()
        cards = payload.get("cards")
        if not set_name or not isinstance(cards, list):
            continue

        for index in _candidate_indices(len(cards)):
            if len(panel) >= size or client.runtime.blocked:
                break
            resume = cards[index]
            if not isinstance(resume, Mapping):
                continue
            card_id = str(resume.get("id") or "").strip()
            if not card_id:
                continue
            detail_response, detail = client.request(
                "GET",
                f"https://api.tcgdex.net/v2/{quote(language, safe='')}/cards/{quote(card_id, safe='')}",
            )
            if (
                not detail_response
                or detail_response.status_code != 200
                or not isinstance(detail, Mapping)
            ):
                continue
            name = str(detail.get("name") or resume.get("name") or "").strip()
            local_id = str(detail.get("localId") or resume.get("localId") or "").strip()
            detail_set = detail.get("set")
            canonical_set = (
                str(detail_set.get("name") or "").strip()
                if isinstance(detail_set, Mapping)
                else set_name
            ) or set_name
            if not name or not local_id or not canonical_set:
                continue
            key = (
                scout._normalize_card_name(name),
                scout._normalize(canonical_set),
                scout._normalize_card_number(local_id),
                scout.lang(language),
            )
            if key in seen:
                continue
            seen.add(key)
            identity = CardIdentity(
                game="Pokémon TCG",
                card_name=name,
                set=canonical_set,
                card_number=local_id,
                language=language,
                finish=_finish_from_variants(detail.get("variants")),
            )
            panel.append(
                scout.PanelCard(
                    identity=identity,
                    tcgdex_id=card_id,
                    tcgdex_language=language,
                    marketplace="TCGDEX_SEED",
                )
            )
            seeded += 1

    diagnostics["tcgdex_seed_calls"] = client.runtime.calls
    diagnostics["tcgdex_seed_bytes"] = client.runtime.bytes_read
    diagnostics["tcgdex_seeded_cards"] = seeded
    diagnostics["tcgdex_seed_blocked"] = client.runtime.blocked
    diagnostics["panel_size_after_seed"] = len(panel)
    return panel


_ORIGINAL_BUILD_PANEL = scout.build_panel


def build_panel(client_id: str, client_secret: str, size: int):
    panel, diagnostics = _ORIGINAL_BUILD_PANEL(client_id, client_secret, size)
    diagnostics["ebay_canonical_panel_size"] = len(panel)
    panel = _supplement_from_tcgdex(panel, size=size, diagnostics=diagnostics)
    return panel, diagnostics


def main() -> int:
    scout.build_panel = build_panel
    return scout.main()


if __name__ == "__main__":
    raise SystemExit(main())
