import os
import unittest
from unittest.mock import patch

import run_watcher_multimarket as production


class MislistedProductionPolicyTests(unittest.TestCase):
    def test_lane_stays_disabled_even_if_workflow_env_requests_enable(self):
        with patch.dict(os.environ, {"V4_MISLISTED_SLAB_HUNTER_ENABLED": "true"}, clear=False):
            self.assertFalse(production._mislisted_slab_hunter_enabled())


if __name__ == "__main__":
    unittest.main()
