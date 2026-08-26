from __future__ import annotations

# Activation is version-controlled so CI can prove the exact production gate.
import unittest
from pathlib import Path


class GlobalNotifyWorkflowTests(unittest.TestCase):
    def _text(self) -> str:
        return Path('.github/workflows/v4-global-notify.yml').read_text(encoding='utf-8')

    def _validation_text(self) -> str:
        return Path('.github/workflows/v4-global-market-offline-validation.yml').read_text(encoding='utf-8')

    def test_schedule_is_every_twenty_minutes_and_activation_is_explicit(self):
        text = self._text()
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('cron: "1,21,41 * * * *"', text)
        self.assertNotIn('cron: "1,11,21,31,41,51 * * * *"', text)
        self.assertEqual(text.count('cron:'), 1)
        self.assertIn('Resolve notification activation', text)
        self.assertIn('REPO_NOTIFY_FLAG: ${{ vars.GLOBAL_NOTIFY_ENABLED }}', text)
        self.assertIn('.github/global-notify-activation', text)
        self.assertIn("steps.activation.outputs.enabled == 'true'", text)
        self.assertIn("needs.gate.outputs.production", text)

    def test_watchdog_is_only_main_scanner_completion_and_is_staleness_gated(self):
        text = self._text()
        self.assertIn('workflow_run:', text)
        self.assertIn('workflows: ["GCC Auction Watcher"]', text)
        self.assertIn('types: [completed]', text)
        self.assertIn('branches: [main]', text)
        self.assertIn("source.name === 'GCC Auction Watcher'", text)
        self.assertIn("source.event === 'workflow_dispatch'", text)
        self.assertIn("source.head_branch === 'main'", text)
        self.assertIn("source.conclusion === 'success'", text)
        self.assertIn('heartbeat.ageMinutes < 30', text)
        self.assertIn('watchdog_stale_heartbeat_recovery', text)
        self.assertIn('watchdog_registry_unavailable', text)
        self.assertIn('watchdog_active_run_lookup_unavailable', text)
        self.assertIn("workflow_id: 'v4-global-notify.yml'", text)
        self.assertIn("run.event === 'schedule' || run.event === 'workflow_run'", text)

    def test_schedule_debounces_only_recent_healthy_production_heartbeat(self):
        text = self._text()
        self.assertIn('comments(last: 50)', text)
        self.assertIn('issue(number: $number)', text)
        self.assertIn('number: 150', text)
        self.assertIn("body.includes('trigger=schedule') || body.includes('trigger=workflow_run')", text)
        self.assertIn("body.includes('scan_job_result=success')", text)
        self.assertIn("body.includes('marketplace_status=success')", text)
        self.assertIn("body.includes('notification_activation=false')", text)
        self.assertIn('heartbeat.ageMinutes < 15', text)
        self.assertIn('schedule_debounced_recent_heartbeat', text)
        self.assertIn('schedule_registry_unavailable_fail_open', text)

    def test_twenty_minute_schedule_keeps_bounded_batch_and_non_overlapping_concurrency(self):
        text = self._text()
        self.assertIn('default: "50"', text)
        self.assertIn("GLOBAL_MARKETPLACE_MAX_EVALUATIONS: ${{ inputs.max_evaluations || '50' }}", text)
        self.assertNotIn("GLOBAL_MARKETPLACE_MAX_EVALUATIONS: ${{ inputs.max_evaluations || '20' }}", text)
        self.assertNotIn("GLOBAL_MARKETPLACE_MAX_EVALUATIONS: ${{ inputs.max_evaluations || '15' }}", text)
        self.assertNotIn("GLOBAL_MARKETPLACE_MAX_EVALUATIONS: ${{ inputs.max_evaluations || '10' }}", text)
        self.assertIn('group: v4-global-confirmed-notifications', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('timeout-minutes: 25', text)
        self.assertIn('GLOBAL_MARKETPLACE_WALL_TIMEOUT_SECONDS: "1020"', text)

    def test_scale_up_is_exercised_read_only_in_pr_validation(self):
        text = self._validation_text()
        self.assertIn('--max-evaluations 50', text)
        self.assertIn('GLOBAL_NOTIFY_ENABLED: "false"', text)
        self.assertIn('NTFY_TOPIC: ""', text)
        self.assertIn('GLOBAL_POKETRACE_CANDIDATE_DIAGNOSTICS: "true"', text)

    def test_manual_dispatch_can_only_be_dry_run(self):
        text = self._text()
        env_line = next(line.strip() for line in text.splitlines() if line.strip().startswith('GLOBAL_NOTIFY_ENABLED:'))
        self.assertIn("needs.gate.outputs.production == 'true'", env_line)
        self.assertIn("steps.activation.outputs.enabled == 'true'", env_line)
        self.assertIn("setGate(true, false, 'workflow_dispatch', 'manual_dry_run')", text)
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
        self.assertIn('if [ "${{ needs.gate.outputs.production }}" = "true" ]; then', text)

    def test_marketplace_state_is_shared_by_schedule_and_watchdog_only_after_success(self):
        text = self._text()
        self.assertIn('actions/cache/restore@v4', text)
        self.assertIn('actions/cache/save@v4', text)
        self.assertIn('global-marketplace-state-${{ needs.gate.outputs.state_lane }}-', text)
        self.assertNotIn('global-marketplace-state-${{ github.event_name }}-', text)
        self.assertIn("setGate(true, true, 'schedule', 'watchdog_stale_heartbeat_recovery')", text)
        self.assertIn("setGate(true, true, 'schedule', 'scheduled_production')", text)
        self.assertIn("setGate(true, false, 'workflow_dispatch', 'manual_dry_run')", text)
        self.assertIn('--state-dir .global-marketplace-state', text)
        self.assertIn("steps.marketplace.outcome == 'success'", text)
        self.assertNotIn('--state .global-notify-state/state.json', text)

    def test_marketplace_step_has_inner_timeout_before_job_timeout(self):
        text = self._text()
        self.assertIn('timeout --signal=TERM --kill-after=30s "${GLOBAL_MARKETPLACE_WALL_TIMEOUT_SECONDS}s"', text)
        self.assertIn('echo "timed_out=$timed_out" >> "$GITHUB_OUTPUT"', text)
        self.assertIn('if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then', text)
        self.assertIn('marketplace_timed_out: ${{ steps.marketplace.outputs.timed_out }}', text)

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
        self.assertIn('GLOBAL_PPT_MAX_HTTP_CALLS: "35"', text)
        self.assertIn('GLOBAL_PPT_MAX_CREDITS: "180"', text)
        self.assertIn('GLOBAL_PPT_DAILY_REMAINING_FLOOR: "15000"', text)
        self.assertIn('V4_POKETRACE_MAX_REQUESTS_PER_RUN: "60"', text)
        self.assertIn('NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('actions: read', text)
        self.assertIn('contents: read', text)
        self.assertIn('issues: write', text)

        validation = self._validation_text()
        self.assertIn('GLOBAL_PPT_MAX_HTTP_CALLS: "35"', validation)
        self.assertIn('GLOBAL_PPT_MAX_CREDITS: "180"', validation)
        self.assertIn('GLOBAL_PPT_DAILY_REMAINING_FLOOR: "15000"', validation)
        self.assertIn('V4_POKETRACE_MAX_REQUESTS_PER_RUN: "60"', validation)

    def test_production_runs_register_even_when_scan_job_fails_or_times_out(self):
        text = self._text()
        self.assertIn('Register Global production run in issue #150', text)
        self.assertIn('needs: [gate, scan]', text)
        self.assertIn("needs.gate.outputs.run_scan == 'true'", text)
        self.assertIn("needs.gate.outputs.production == 'true'", text)
        self.assertIn('actions/download-artifact@v4', text)
        self.assertIn('continue-on-error: true', text)
        self.assertIn('TRIGGER_REASON: ${{ needs.gate.outputs.reason }}', text)
        self.assertIn('SCAN_JOB_RESULT: ${{ needs.scan.result }}', text)
        self.assertIn('MARKETPLACE_TIMED_OUT: ${{ needs.scan.outputs.marketplace_timed_out }}', text)
        self.assertIn('issue_number: 150', text)
        self.assertIn("global_marketplace_out/global_marketplace_report.json", text)
        self.assertIn('run_id=${context.runId}', text)
        self.assertIn('trigger_reason=', text)
        self.assertIn('commit_sha=${context.sha}', text)
        self.assertIn('scan_job_result=', text)
        self.assertIn('marketplace_timed_out=', text)
        self.assertIn('notification_activation=', text)
        self.assertIn('marketplace_status=', text)
        self.assertIn('inventory_seen=', text)
        self.assertIn('selected_for_evaluation=', text)
        self.assertIn('pending_after=', text)
        self.assertIn('tcgdex_external_exact=', text)
        self.assertIn('ppt_matched=', text)
        self.assertIn('ppt_blocked_reason=', text)
        self.assertIn('poketrace_matched=', text)
        self.assertIn('confirmed_would_notify=', text)
        self.assertIn('notifications_sent=', text)
        self.assertIn('automatic_purchase=', text)
        self.assertIn('automatic_bid=', text)
        self.assertIn('automatic_checkout=', text)
        self.assertIn('automatic_payment=', text)


if __name__ == '__main__':
    unittest.main()
