from pathlib import Path


SQLITE_FILES = (
    Path("tests/test_robot_kb_final_remediation.py"),
    Path("tests/test_robot_kb_foundation.py"),
    Path("tests/test_robot_kb_integrity_hardening.py"),
    Path("tests/test_robot_kb_sidecar_remediation.py"),
)

for path in SQLITE_FILES:
    text = path.read_text(encoding="utf-8")
    count = text.count("[1, 2, 3, 4]")
    if count < 1:
        raise SystemExit(f"expected SQLite migration assertion not found in {path}")
    path.write_text(text.replace("[1, 2, 3, 4]", "[1, 2, 3, 4, 5]"), encoding="utf-8")
    print(f"{path}: updated {count} SQLite migration expectation(s)")

postgres = Path("tests/test_robot_kb_postgres.py")
text = postgres.read_text(encoding="utf-8")
replacements = (
    ("self.assertEqual(list(catalog), [1, 2])", "self.assertEqual(list(catalog), [1, 2, 3])", 1),
    (
        "self.assertEqual([version for version, _ in empty.scripts], [1, 2])",
        "self.assertEqual([version for version, _ in empty.scripts], [1, 2, 3])",
        2,
    ),
    ("self.assertEqual(sorted(empty.applied), [1, 2])", "self.assertEqual(sorted(empty.applied), [1, 2, 3])", 1),
    (
        "self.assertEqual([version for version, _ in existing.scripts], [2])",
        "self.assertEqual([version for version, _ in existing.scripts], [2, 3])",
        2,
    ),
    ("self.assertEqual(sorted(existing.applied), [1, 2])", "self.assertEqual(sorted(existing.applied), [1, 2, 3])", 1),
)
for old, new, expected_count in replacements:
    count = text.count(old)
    if count != expected_count:
        raise SystemExit(
            f"unexpected count for postgres migration assertion {old!r}: "
            f"expected {expected_count}, got {count}"
        )
    text = text.replace(old, new)
postgres.write_text(text, encoding="utf-8")
print("tests/test_robot_kb_postgres.py: migration expectations advanced to 0003")
