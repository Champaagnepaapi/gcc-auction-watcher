from __future__ import annotations

import unittest

from v5 import neon_cmapi_ingest_v2 as ingest


class CmapiNeonV2Tests(unittest.TestCase):
    def test_unproven_tcgplayer_history_currency_is_not_ingested(self) -> None:
        result = ingest._safe_insert_metric(
            None,  # type: ignore[arg-type]
            metric_name="CMAPI_TCGPLAYER_HISTORY_MARKET:GLOBAL:TCGDEX:swsh7-215",
        )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
