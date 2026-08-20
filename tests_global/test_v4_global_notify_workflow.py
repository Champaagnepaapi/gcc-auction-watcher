from __future__ import annotations

import unittest
from pathlib import Path


class GlobalNotifyWorkflowTests(unittest.TestCase):
    def test_schedule_is_hourly_but_hard_default_off(self):
        text = Path('.github/workflows/v4-global-notify.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('cron: "41 * * * *"', text)
        self.assertIn("vars.GLOBAL_NOTIFY_ENABLED == 'true'", text)
        self.assertIn("github.event_name == 'workflow_dispatch'", text)
        self.assertIn("github.event_name == 'schedule'", text)
        self.assertIn("&& 'true' || 'false'", text)

    def test_manual_dispatch_can_only_be_dry_run(self):
        text = Path('.github/workflows/v4-global-notify.yml').read_text(encoding='utf-8')
        env_line = next(line.strip() for line in text.splitlines() if line.strip().startswith('GLOBAL_NOTIFY_ENABLED:'))
        self.assertIn("github.event_name == 'schedule'", env_line)
        self.assertNotIn('inputs.notify', text)
        self.assertNotIn('send_notifications', text)

    def test_state_is_persistent_and_isolated_by_event(self):
        text = Path('.github/workflows/v4-global-notify.yml').read_text(encoding='utf-8')
        self.assertIn('actions/cache/restore@v4', text)
        self.assertIn('actions/cache/save@v4', text)
        self.assertIn('global-notify-state-${{ github.event_name }}-', text)
        self.assertIn('--state .global-notify-state/state.json', text)

    def test_runner_and_provider_secrets_are_bounded_to_notification_lane(self):
        text = Path('.github/workflows/v4-global-notify.yml').read_text(encoding='utf-8')
        self.assertIn('python v4_global_notify_resilient.py', text)
        self.assertIn('GLOBAL_TCGDEX_MAX_ATTEMPTS: "2"', text)
        self.assertIn('GLOBAL_TCGDEX_REQUEST_TIMEOUT_SECONDS: "10"', text)
        self.assertIn('GLOBAL_TCGDEX_RETRY_BACKOFF_SECONDS: "0.25"', text)
        self.assertIn('GLOBAL_PPT_MAX_HTTP_CALLS: "12"', text)
        self.assertIn('GLOBAL_PPT_MAX_CREDITS: "60"', text)
        self.assertIn('GLOBAL_PPT_DAILY_REMAINING_FLOOR: "15000"', text)
        self.assertIn('NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('contents: read', text)


if __name__ == '__main__':
    unittest.main()
