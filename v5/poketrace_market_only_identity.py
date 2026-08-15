"""Market-only PokeTrace policy for the experimental V5 live diagnostic.

PokeTrace remains the market-data provider. This module deliberately prevents
PokeTrace search results and PokeTrace canonical scans from being used to create
or rescue card identity in the live V5 workflow.

The identity adapter is still kept alive because exact TCGdex provenance and
provider aliases are registered through it for later PokeTrace *market* lookup.
No identity acceptance, ambiguity clearing, visual rescue, or microvariant proof
is sourced from PokeTrace under this policy.
"""

from __future__ import annotations

from .detailed_identity_observability import (
    DetailedLocalVisualIdentityResolver,
    DetailedPokeTraceIdentityResolver,
    ProviderDiagnostic,
    _identity_key,
)
from .models import CardIdentity
from .poketrace_identity import (
    PokeTraceIdentityResolution,
    render_poketrace_identity_counters,
)


POKETRACE_IDENTITY_MARKET_ONLY = "POKETRACE_IDENTITY_DISABLED_MARKET_ONLY"
POKETRACE_MARKET_ONLY_STATUS = "DISABLED_MARKET_ONLY"


class MarketOnlyPokeTraceIdentityResolver(DetailedPokeTraceIdentityResolver):
    """Keep alias/provenance plumbing but never query PokeTrace for identity."""

    def __init__(self, provider) -> None:
        super().__init__(provider)
        self.identity_disabled_skips = 0

    def resolve_identity(self, identity: CardIdentity) -> PokeTraceIdentityResolution:
        self.identity_disabled_skips += 1
        diagnostic = ProviderDiagnostic(
            provider="POKETRACE",
            status=POKETRACE_MARKET_ONLY_STATUS,
            reason_codes=(POKETRACE_IDENTITY_MARKET_ONLY,),
            details={
                "identity_requests_sent": 0,
                "market_provider_enabled_unchanged": bool(
                    getattr(getattr(self.provider, "config", None), "enabled", False)
                ),
            },
        )
        self._detailed_diagnostics[_identity_key(identity)] = diagnostic
        return PokeTraceIdentityResolution(
            identity=identity,
            matched=False,
            ambiguous=False,
            provider_status=POKETRACE_MARKET_ONLY_STATUS,
        )


class MarketOnlyPokeTraceVisualIdentityResolver(DetailedLocalVisualIdentityResolver):
    """Disable the PokeTrace-backed visual candidate search in live V5."""

    def __init__(self, *args, **kwargs) -> None:
        # Explicit policy wins even if the workflow still carries the historical
        # V5_VISUAL_IDENTITY_ENABLED=true environment variable.
        kwargs["enabled"] = False
        super().__init__(*args, **kwargs)


def render_market_only_identity_counters(
    resolver: MarketOnlyPokeTraceIdentityResolver,
) -> str:
    """Keep legacy counters while making the new provider role unambiguous."""

    rendered = render_poketrace_identity_counters(resolver).splitlines()
    if len(rendered) >= 3:
        rendered[1] = "role: MARKET/PRICING ONLY — identity retrieval disabled"
        rendered[2] = (
            "identity retrieval: 0 PokeTrace HTTP searches by policy; "
            "TCGdex/catalogue evidence remains authoritative"
        )
        rendered.insert(
            3,
            "identity lookups skipped before PokeTrace network: "
            f"{resolver.identity_disabled_skips}",
        )
    return "\n".join(rendered)


def render_poketrace_market_only_policy(
    identity_resolver: MarketOnlyPokeTraceIdentityResolver,
    visual_resolver=None,
) -> str:
    visual_disabled = bool(
        visual_resolver is None or not getattr(visual_resolver, "enabled", False)
    )
    return "\n".join(
        (
            "=== V5 POKETRACE ROLE POLICY ===",
            "identity search: DISABLED (TCGdex/catalogue owns identity)",
            (
                "identity lookups skipped before PokeTrace network: "
                f"{identity_resolver.identity_disabled_skips}"
            ),
            (
                "PokeTrace-backed visual identity search: DISABLED"
                if visual_disabled
                else "PokeTrace-backed visual identity search: ENABLED"
            ),
            "PokeTrace market/pricing provider: UNCHANGED",
            "TCGdex deterministic aliases may still feed PokeTrace market lookup: YES",
        )
    )
