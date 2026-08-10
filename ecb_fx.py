"""Official ECB reference-rate parsing and an in-memory converter."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Optional

import requests


ECB_DAILY_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_PROVIDER = "European Central Bank euro foreign exchange reference rates"


@dataclass(frozen=True)
class ECBRateSnapshot:
    rate_date: date
    units_per_eur: Mapping[str, Decimal]
    provider: str = ECB_PROVIDER
    source_url: str = ECB_DAILY_RATES_URL

    def rate(self, source_currency: str, target_currency: str) -> Optional[Decimal]:
        source = source_currency.strip().upper()
        target = target_currency.strip().upper()
        if source == target:
            return Decimal("1")
        source_per_eur = (
            Decimal("1") if source == "EUR" else self.units_per_eur.get(source)
        )
        target_per_eur = (
            Decimal("1") if target == "EUR" else self.units_per_eur.get(target)
        )
        if source_per_eur is None or target_per_eur is None or source_per_eur <= 0:
            return None
        return target_per_eur / source_per_eur


def parse_ecb_snapshot(xml_text: str) -> Optional[ECBRateSnapshot]:
    try:
        root = ET.fromstring(xml_text or "")
    except ET.ParseError:
        return None
    dated_cube = next(
        (
            element
            for element in root.iter()
            if element.attrib.get("time")
        ),
        None,
    )
    if dated_cube is None:
        return None
    try:
        rate_date = date.fromisoformat(dated_cube.attrib["time"])
    except (KeyError, ValueError):
        return None
    rates: dict[str, Decimal] = {}
    for element in dated_cube.iter():
        currency = element.attrib.get("currency", "").strip().upper()
        if not currency:
            continue
        try:
            value = Decimal(element.attrib.get("rate", ""))
        except (InvalidOperation, TypeError):
            continue
        if value > 0:
            rates[currency] = value
    return ECBRateSnapshot(rate_date, rates) if rates else None


class ECBCurrencyConverter:
    """Fetch the official daily snapshot once, then convert only in memory."""

    method = "ECB_EURO_FOREIGN_EXCHANGE_REFERENCE_RATES"

    def __init__(
        self,
        http_get: Optional[Callable[..., object]] = None,
        timeout_seconds: float = 6.0,
    ) -> None:
        self._http_get = http_get or requests.get
        self._timeout_seconds = timeout_seconds
        self._lookup_done = False
        self.snapshot: Optional[ECBRateSnapshot] = None
        self.fetches = 0
        self.cache_hits = 0
        self.failures = 0

    def get_snapshot(self) -> Optional[ECBRateSnapshot]:
        if self._lookup_done:
            self.cache_hits += 1
            return self.snapshot
        self._lookup_done = True
        self.fetches += 1
        try:
            response = self._http_get(
                ECB_DAILY_RATES_URL,
                timeout=max(1.0, min(15.0, self._timeout_seconds)),
            )
            response.raise_for_status()
            self.snapshot = parse_ecb_snapshot(response.text)
        except Exception:
            self.snapshot = None
        if self.snapshot is None:
            self.failures += 1
        return self.snapshot

    def convert(
        self,
        amount: Decimal,
        source_currency: str,
        target_currency: str,
        on_date: Optional[date],
    ) -> Optional[Decimal]:
        del on_date  # The official daily feed contains the latest reference date.
        source = source_currency.strip().upper()
        target = target_currency.strip().upper()
        if source == target:
            return amount
        snapshot = self.get_snapshot()
        if snapshot is None:
            return None
        rate = snapshot.rate(source, target)
        return amount * rate if rate is not None else None

    def rate(self, source_currency: str, target_currency: str) -> Optional[Decimal]:
        snapshot = self.get_snapshot()
        return snapshot.rate(source_currency, target_currency) if snapshot else None
