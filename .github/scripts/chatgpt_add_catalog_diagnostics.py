from pathlib import Path

path = Path("v5/live_raw_pipeline.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        '''    gcc_representative_ambiguous: int = 0\n    gcc_no_representative: int = 0\n    gcc_records_with_grader: int = 0''',
        '''    gcc_representative_ambiguous: int = 0\n    gcc_no_representative: int = 0\n    gcc_catalog_searches: int = 0\n    gcc_catalog_candidate_pages_opened: int = 0\n    gcc_catalog_completed_sales_enabled: int = 0\n    gcc_catalog_search_failures: int = 0\n    gcc_records_with_grader: int = 0''',
    ),
    (
        '''                gcc_no_representative=getattr(\n                    gcc_source, "no_representative", 0\n                ),\n                gcc_records_with_grader=getattr(''',
        '''                gcc_no_representative=getattr(\n                    gcc_source, "no_representative", 0\n                ),\n                gcc_catalog_searches=getattr(\n                    gcc_source, "catalog_searches", 0\n                ),\n                gcc_catalog_candidate_pages_opened=getattr(\n                    gcc_source, "catalog_candidate_pages_opened", 0\n                ),\n                gcc_catalog_completed_sales_enabled=getattr(\n                    gcc_source, "catalog_completed_sales_enabled", 0\n                ),\n                gcc_catalog_search_failures=getattr(\n                    gcc_source, "catalog_search_failures", 0\n                ),\n                gcc_records_with_grader=getattr(''',
    ),
    (
        '''            f"no representative: {summary.providers.gcc_no_representative}",\n            f"cache hits: {summary.providers.gcc_history_cache_hits}",''',
        '''            f"no representative: {summary.providers.gcc_no_representative}",\n            f"catalog searches: {summary.providers.gcc_catalog_searches}",\n            (\n                "catalog candidate pages opened: "\n                f"{summary.providers.gcc_catalog_candidate_pages_opened}"\n            ),\n            (\n                "completed-sales filter enabled: "\n                f"{summary.providers.gcc_catalog_completed_sales_enabled}"\n            ),\n            f"catalog search failures: {summary.providers.gcc_catalog_search_failures}",\n            f"cache hits: {summary.providers.gcc_history_cache_hits}",''',
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
