"""GCC source-contract adapter for provable completed sales.

Live schema validation on 2026-08-14 established that GCC's explicit
`status=SOLD` response exposes the consummated amount as `priceInCents`/`price`
and the transaction timestamp as `soldAt`. This adapter keeps the immutable raw
payload unchanged and supplies that contract to the conservative generic GCC
normalizer only when BOTH explicit SOLD status and an aware soldAt timestamp are
present.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Optional

from .models import NormalizationBatch, RawSourceRecord
from . import normalizers


GCC_SOLD_PRICE_CONTRACT = "GCC_STATUS_SOLD_PLUS_SOLD_AT_PRICE"


def _status(payload: Mapping[str, Any]) -> str:
    return str(payload.get("status") or "").strip().upper()


def _sale_timestamp(payload: Mapping[str, Any]) -> Optional[str]:
    return normalizers._aware_timestamp(
        payload.get("soldAt") or payload.get("saleOccurredAt")
    )


def _has_explicit_final_price(payload: Mapping[str, Any]) -> bool:
    value, _ = normalizers._explicit_final_price(payload)
    return value is not None


def _gcc_contract_price_minor(payload: Mapping[str, Any]) -> Optional[int]:
    return normalizers._money(
        payload,
        cents_fields=("priceInCents",),
        major_fields=("price",),
    )


def normalize_gcc_source_contract(record: RawSourceRecord) -> NormalizationBatch:
    """Normalize GCC while recognizing its validated SOLD response contract.

    Safety invariant: `price` is NEVER upgraded to a sale merely because an
    auction ended. The adapter requires status exactly SOLD + explicit soldAt.
    """
    payload = record.payload
    if (
        _status(payload) != "SOLD"
        or _sale_timestamp(payload) is None
        or _has_explicit_final_price(payload)
    ):
        return normalizers.normalize_gcc(record)

    price_minor = _gcc_contract_price_minor(payload)
    if price_minor is None:
        return normalizers.normalize_gcc(record)

    adapted_payload = dict(payload)
    adapted_payload["soldPriceInCents"] = price_minor
    adapted_record = replace(record, payload=adapted_payload)
    batch = normalizers.normalize_gcc(adapted_record)

    observations = []
    for observation in batch.observations:
        if observation.genuine_sale_evidence:
            fact = dict(observation.fact)
            fact["final_price_evidence_method"] = GCC_SOLD_PRICE_CONTRACT
            observations.append(replace(observation, fact=fact))
        else:
            observations.append(observation)
    return replace(batch, observations=tuple(observations))
