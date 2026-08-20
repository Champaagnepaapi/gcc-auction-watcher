from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import v4_global_marketplace_scan as scan
from v4_global_market_core import ACTIVE_AUCTION, AUCTION_SNAPSHOT_LE5, FIXED_ASK


NOW = datetime(2026, 8, 20, 17, 0, tzinfo=timezone.utc)


def _gcc_row(*, row_id: str, price_cents: int, end_time: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {
        "id": row_id,
        "status": "ON_SALE",
        # Intentionally no sellingTypeGroup/sellingType: this mirrors the live
        # GCC payload shape that exposed the marketplace-first regression.
        "priceInCents": price_cents,
        "item": {
            "gradingCompany": "PSA",
            "grade": "10",
            "collectible": {
                "category": "Pokemon",
                "type": "Cards",
                "language": "Japanese",
                "character": {"englishName": "Mewtwo"},
                "set": "151",
                "reference": "183/165",
            },
        },
    }
    if end_time is not None:
        row["endTime"] = end_time
    return row


class _Response:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _Session:
    def __init__(self, fixed_rows: list[dict[str, object]], auction_rows: list[dict[str, object]]):
        self.fixed_rows = fixed_rows
        self.auction_rows = auction_rows
        self.calls: list[str] = []

    def get(self, _url: str, *, params: dict[str, object], headers: dict[str, str], timeout: int):
        del headers, timeout
        selling = str(params["sellingTypeGroup"])
        self.calls.append(selling)
        rows = self.fixed_rows if selling == "FIXED_PRICE" else self.auction_rows
        return _Response({"results": rows, "info": {"nextPage": None}})

    def close(self) -> None:
        return None


class GccRequestTypeRegressionTests(unittest.TestCase):
    def test_missing_row_type_keeps_request_fixed_vs_auction(self):
        session = _Session(
            fixed_rows=[_gcc_row(row_id="fixed", price_cents=9900)],
            auction_rows=[
                _gcc_row(
                    row_id="auction",
                    price_cents=100,
                    end_time=(NOW + timedelta(minutes=30)).isoformat(),
                )
            ],
        )
        listings, status = scan.scan_gcc_inventory(
            observed_at=NOW,
            max_pages_each=1,
            session=session,
        )
        by_id = {listing.source_id: listing for listing in listings}
        self.assertEqual(status.status, "OK")
        self.assertEqual(session.calls, ["FIXED_PRICE", "AUCTION"])
        self.assertEqual(by_id["fixed"].evidence_type, FIXED_ASK)
        self.assertEqual(by_id["auction"].evidence_type, ACTIVE_AUCTION)
        self.assertNotEqual(by_id["auction"].evidence_type, FIXED_ASK)

    def test_missing_row_type_preserves_le5_auction_gate(self):
        session = _Session(
            fixed_rows=[],
            auction_rows=[
                _gcc_row(
                    row_id="auction-le5",
                    price_cents=100,
                    end_time=(NOW + timedelta(minutes=3)).isoformat(),
                )
            ],
        )
        listings, _status = scan.scan_gcc_inventory(
            observed_at=NOW,
            max_pages_each=1,
            session=session,
        )
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].evidence_type, AUCTION_SNAPSHOT_LE5)
        self.assertNotIn("SOLD", listings[0].evidence_type)


if __name__ == "__main__":
    unittest.main()
