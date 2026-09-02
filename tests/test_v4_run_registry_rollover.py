from pathlib import Path


def test_main_scanner_active_registry_is_issue_235():
    workflow = (
        Path(__file__).parents[1] / ".github" / "workflows" / "watcher.yml"
    ).read_text(encoding="utf-8")

    assert 'Register V4 run in issue #235' in workflow
    assert 'issue_number: 235' in workflow
    assert 'Historical archive target was issue_number: 1' in workflow
