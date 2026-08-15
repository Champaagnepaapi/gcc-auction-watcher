from pathlib import Path

path = Path('v5/live_raw_pipeline_catalog.py')
text = path.read_text(encoding='utf-8')

old_import = 'from .microvariants import LocalMicrovariantValidator, MicrovariantApplicability\n'
new_import = '''from .microvariants import (\n    LocalMicrovariantValidator,\n    MicrovariantApplicability,\n    MICROVARIANT_APPLICABILITY_UNKNOWN,\n)\n'''
if text.count(old_import) != 1:
    raise SystemExit(f'unexpected microvariant import count: {text.count(old_import)}')
text = text.replace(old_import, new_import, 1)

anchor = '''def _progress(message: str) -> None:\n    if os.getenv("V5_PROGRESS_LOGS", "false").strip().casefold() == "true":\n        print(f"[V5] {message}", flush=True)\n\n\nclass CatalogAwareLiveRawPipelineDiagnostic'''
helper = '''def _progress(message: str) -> None:\n    if os.getenv("V5_PROGRESS_LOGS", "false").strip().casefold() == "true":\n        print(f"[V5] {message}", flush=True)\n\n\ndef _refresh_post_macro_applicability(resolver, identity, applicability):\n    """Retry exact TCGdex microvariant proof after macro identity is complete.\n\n    This is deliberately narrower than identity resolution: only an exact\n    TCGdex catalogue result may replace an UNKNOWN/UNAVAILABLE applicability.\n    Provider-market metadata and other fallback sources cannot unblock the\n    microvariant gate through this path.\n    """\n\n    if applicability.status != MICROVARIANT_APPLICABILITY_UNKNOWN:\n        return applicability\n    resolve = getattr(resolver, "resolve_microvariant_applicability", None)\n    if not callable(resolve):\n        return applicability\n    refreshed = resolve(identity)\n    if not isinstance(refreshed, MicrovariantApplicability):\n        return applicability\n    if refreshed.source != "TCGDEX_EXACT":\n        return applicability\n    return refreshed\n\n\nclass CatalogAwareLiveRawPipelineDiagnostic'''
if text.count(anchor) != 1:
    raise SystemExit(f'unexpected progress/class anchor count: {text.count(anchor)}')
text = text.replace(anchor, helper, 1)

old_gate = '''        if microvariant is None:\n            microvariant = self.microvariant_validator.resolve(\n                identity,\n                microvariant_applicability,\n            )\n'''
new_gate = '''        if microvariant is None:\n            # A structured identity may already be macro-complete even when the\n            # first exact set lookup did not prove microvariant applicability.\n            # Reuse the deterministic post-macro TCGdex retry before blocking.\n            microvariant_applicability = _refresh_post_macro_applicability(\n                self.card_catalog_resolver,\n                identity,\n                microvariant_applicability,\n            )\n            microvariant = self.microvariant_validator.resolve(\n                identity,\n                microvariant_applicability,\n            )\n'''
if text.count(old_gate) != 1:
    raise SystemExit(f'unexpected validator gate count: {text.count(old_gate)}')
text = text.replace(old_gate, new_gate, 1)

path.write_text(text, encoding='utf-8')
print('wired exact TCGdex post-macro applicability retry')
