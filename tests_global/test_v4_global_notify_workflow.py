from __future__ import annotations

# Activation is version-controlled so CI can prove the exact scheduled gate.
import unittest
from pathlib import Path


class GlobalNotifyWorkflowTests(unittest.TestCase):
    def _text(self) -> str:
        return Path('.github/workflows/v4-global-notify.yml').read_text(encoding='utf-8')

    def test_schedule_is_every_ten_minutes_and_activation_is_explicit(self):
        text = self._text()
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('cron: "1,11,21,31,41,51 * * * *"', text)
        self.assertNotIn('cron: "41 * * * *"', text)
        self.assertIn('Resolve notification activation', text)
        self.assertIn('REPO_NOTIFY_FLAG: ${{ vars.GLOBAL_NOTIFY_ENABLED }}', text)
        self.assertIn('.github/global-notify-activation', text)
        self.assertIn("steps.activation.outputs.enabled == 'true'", text)
        self.assertIn("github.event_name == 'workflow_dispatch'", text)
        self.assertIn("github.event_name == 'schedule'", text)

    def test_ten_minute_schedule_keeps_bounded_batch_and_non_overlapping_concurrency(self):
        text = self._text()
        self.assertIn('default: "10"', text)
        self.assertIn("GLOBAL_MARKETPLACE_MAX_EVALUATIONS: ${{ inputs.max_evaluations || '10' }}", text)
        self.assertIn('group: v4-global-confirmed-notifications', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('timeout-minutes: 40', text)

    def test_manual_dispatch_can_only_be_dry_run(self):
        text = self._text()
        env_line = next(line.strip() for line in text.splitlines() if line.strip().startswith('GLOBAL_NOTIFY_ENABLED:'))
        self.assertIn("github.event_name == 'schedule'", env_line)
        self.assertIn("steps.activation.outputs.enabled == 'true'", env_line)
        self.assertNotIn('inputs.notify', text)
        self.assertNotIn('send_notifications', text)

    def test_versioned_activation_marker_is_explicit_true(self):
        marker = Path('.github/global-notify-activation').read_text(encoding='utf-8').strip()
        self.assertEqual(marker, 'true')

    def test_repository_false_is_emergency_override(self):
        text = self._text()
        self.assertIn('if [ "$REPO_NOTIFY_FLAG" = "false" ]; then', text)
        self.assertIn('elif [ "$REPO_NOTIFY_FLAG" = "true" ]; then', text)
        self.assertIn('elif [ "$marker" = "true" ]; then', text)

    def test_marketplace_state_is_persistent_and_isolated_by_event(self):
        text = self._text()
        self.assertIn('actions/cache/restore@v4', text)
        self.assertIn('actions/cache/save@v4', text)
        self.assertIn('global-marketplace-state-${{ github.event_name }}-', text)
        self.assertIn('--state-dir .global-marketplace-state', text)
        self.assertNotIn('--state .global-notify-state/state.json', text)

    def test_production_runner_is_marketplace_first_not_seed_rotation(self):
        text = self._text()
        self.assertIn('python v4_global_marketplace_notify_resilient.py', text)
        self.assertNotIn('python v4_global_notify_resilient.py', text)
        self.assertIn('id: marketplace', text)
        self.assertIn('--max-evaluations "$GLOBAL_MARKETPLACE_MAX_EVALUATIONS"', text)
        self.assertIn('--gcc-live-pages 100', text)
        self.assertIn('--browser-detail-cap 100', text)
        self.assertIn('--comc-pages 10', text)
        self.assertNotIn('GLOBAL_MAX_IDENTITIES', text)
        self.assertNotIn('--max-identities', text)
        self.assertNotIn('--market-candidates', text)

    def test_runner_and_provider_secrets_are_bounded_to_notification_lane(self):
        text = self._text()
        self.assertIn('GLOBAL_TCGDEX_MAX_ATTEMPTS: "2"', text)
        self.assertIn('GLOBAL_TCGDEX_REQUEST_TIMEOUT_SECONDS: "10"', text)
        self.assertIn('GLOBAL_TCGDEX_RETRY_BACKOFF_SECONDS: "0.25"', text)
        self.assertIn('GLOBAL_PPT_MAX_HTTP_CALLS: "12"', text)
        self.assertIn('GLOBAL_PPT_MAX_CREDITS: "60"', text)
        self.assertIn('GLOBAL_PPT_DAILY_REMAINING_FLOOR: "15000"', text)
        self.assertIn('NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('contents: read', text)
        self.assertIn('issues: write', text)

    def test_scheduled_runs_register_minimal_safe_metadata_in_issue_150(self):
        text = self._text()
        self.assertIn('Register Global schedule run in issue #150', text)
        self.assertIn("always() && github.event_name == 'schedule'", text)
        self.assertIn('issue_number: 150', text)
        self.assertIn("global_marketplace_out/global_marketplace_report.json", text)
        self.assertIn('run_id=${context.runId}', text)
        self.assertIn('commit_sha=${context.sha}', text)
        self.assertIn('notification_activation=', text)
        self.assertIn('marketplace_status=', text)
        self.assertIn('inventory_seen=', text)
        self.assertIn('selected_for_evaluation=', text)
        self.assertIn('pending_after=', text)
        self.assertIn('tcgdex_external_exact=', text)
        self.assertIn('ppt_matched=', text)
        self.assertIn('poketrace_matched=', text)
        self.assertIn('confirmed_would_notify=', text)
        self.assertIn('notifications_sent=', text)
        self.assertIn('automatic_purchase=', text)
        self.assertIn('automatic_bid=', text)
        self.assertIn('automatic_checkout=', text)
        self.assertIn('automatic_payment=', text)


if __name__ == '__main__':
    unittest.main()
