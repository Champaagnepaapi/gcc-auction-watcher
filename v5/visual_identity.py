from __future__ import annotations

import io
import os
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .card_number_ocr import LocalCardNumberOCR
from .market_values.poketrace import _candidate_market_compatible
from .models import CardIdentity
from .microvariants import (
    EditionRegionEvidence,
    LocalMicrovariantValidator,
    MICROVARIANT_APPLICABLE,
    MicrovariantApplicability,
    MicrovariantResolution,
)
from .microvariant_detector import (
    CanonicalMicrovariantReference,
    DeterministicLocalMicrovariantEvidenceProvider,
    MicrovariantEvidenceRequest,
)
from .poketrace_identity import (
    REQUEST_OK,
    PokeTraceIdentityResolver,
    _normalize,
    _normalize_card_number,
    _resolved_identity,
    _set_similarity,
    _variant_family,
)
from .poketrace_matching import _candidate_evidence, _normalize_card_name


MAX_VISUAL_IMAGE_BYTES = 8 * 1024 * 1024


@dataclass
class VisualIdentityCounters:
    forensic_eligible: int = 0
    skipped_run_limit: int = 0
    attempted: int = 0
    api_searches: int = 0
    api_unavailable: int = 0
    visual_searches_skipped_after_breaker: int = 0
    no_ebay_image: int = 0
    no_candidates: int = 0
    candidates_considered: int = 0
    candidate_images_downloaded: int = 0
    candidate_image_failures: int = 0
    ebay_images_downloaded: int = 0
    ebay_image_failures: int = 0
    low_confidence: int = 0
    close_second: int = 0
    rescued: int = 0
    card_number_overrides: int = 0
    ambiguities_cleared: int = 0
    market_snapshots_primed: int = 0
    ocr_rescued: int = 0
    ocr_market_snapshots_primed: int = 0
    eu_enrichment_attempts: int = 0
    eu_enrichment_candidates: int = 0
    eu_enrichment_matches: int = 0
    eu_enrichment_ambiguous: int = 0
    eu_enrichment_rejected_no_image: int = 0
    eu_enrichment_rejected_variant: int = 0
    eu_enrichment_rejected_core: int = 0
    cardmarket_snapshots_recovered: int = 0
    premium_variant_candidate_not_inherited: int = 0
    microvariant_visual_attempts: int = 0
    microvariant_visual_confirmed: int = 0
    microvariant_visual_inconclusive: int = 0
    microvariant_gate_blocked_before_market: int = 0
    market_snapshot_not_primed_microvariant: int = 0
    eu_enrichment_not_attempted_microvariant: int = 0
    applicability_pre_macro_known: int = 0
    applicability_pre_macro_unknown: int = 0
    applicability_post_macro_attempts: int = 0
    applicability_post_macro_resolved: int = 0
    applicability_post_macro_unknown: int = 0
    microvariant_reference_pairs_available: int = 0
    microvariant_reference_pairs_missing: int = 0
    microvariant_card_normalization_success: int = 0
    microvariant_card_normalization_failure: int = 0
    microvariant_alignment_success: int = 0
    microvariant_alignment_failure: int = 0
    microvariant_region_usable: int = 0
    microvariant_region_unusable: int = 0
    microvariant_first_confirmed: int = 0
    microvariant_unlimited_confirmed: int = 0
    microvariant_other_confirmed: int = 0
    microvariant_unknown: int = 0
    microvariant_conflict: int = 0
    blocker_edition: int = 0
    blocker_finish: int = 0
    blocker_promo: int = 0
    blocker_special_finish: int = 0
    blocker_multiple: int = 0


@dataclass(frozen=True)
class VisualIdentityResolution:
    identity: CardIdentity
    matched: bool = False
    card_id: Optional[str] = None
    score: float = 0.0
    margin: float = 0.0
    microvariant: MicrovariantResolution = field(
        default_factory=MicrovariantResolution
    )


@dataclass(frozen=True)
class _ImageSignature:
    average_hash: Tuple[bool, ...]
    edge_hash: Tuple[bool, ...]
    center_hash: Tuple[bool, ...]
    color_histogram: Tuple[float, ...]


@dataclass(frozen=True)
class _VisualCandidate:
    payload: Mapping[str, object]
    metadata_score: float
    image_url: str


class LocalVisualIdentityResolver:
    """Resolve ambiguous/incomplete identities from the actual eBay card image.

    This is intentionally a second-line resolver. It never scans every listing
    and never replaces a clean structured identity. It asks PokeTrace for a
    small candidate set, downloads the canonical scan URLs returned by the API,
    and compares them locally with the eBay image using perceptual/edge/color
    signatures. If that image matcher cannot separate the candidates, an
    optional local OCR pass reads only lower-card strips and may select a
    collector number that already exists in the same PokeTrace candidate pool.

    No model API, image persistence, bid or purchase is involved.
    """

    def __init__(
        self,
        poketrace_identity: PokeTraceIdentityResolver,
        *,
        ebay_image_fetcher: Callable[[str], Optional[bytes]],
        candidate_image_fetcher: Optional[Callable[[str], Optional[bytes]]] = None,
        enabled: Optional[bool] = None,
        max_candidates: Optional[int] = None,
        max_ebay_images: Optional[int] = None,
        minimum_score: Optional[float] = None,
        minimum_margin: Optional[float] = None,
        override_number_minimum_score: Optional[float] = None,
        override_number_minimum_margin: Optional[float] = None,
        eu_enrichment_enabled: Optional[bool] = None,
        card_number_ocr: Optional[LocalCardNumberOCR] = None,
        microvariant_validator: Optional[LocalMicrovariantValidator] = None,
        microvariant_evidence_provider: Optional[
            Callable[[MicrovariantEvidenceRequest], Optional[EditionRegionEvidence]]
        ] = None,
        post_macro_applicability_resolver: Optional[
            Callable[[CardIdentity], MicrovariantApplicability]
        ] = None,
    ) -> None:
        self.poketrace_identity = poketrace_identity
        self.provider = poketrace_identity.provider
        self.ebay_image_fetcher = ebay_image_fetcher
        self.candidate_image_fetcher = (
            candidate_image_fetcher or self._fetch_poketrace_image
        )
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("V5_VISUAL_IDENTITY_ENABLED", "false").strip().casefold()
            == "true"
        )
        self.max_candidates = max(
            1,
            min(
                12,
                max_candidates
                if max_candidates is not None
                else int(os.getenv("V5_VISUAL_IDENTITY_MAX_CANDIDATES", "8")),
            ),
        )
        self.max_ebay_images = max(
            1,
            min(
                4,
                max_ebay_images
                if max_ebay_images is not None
                else int(os.getenv("V5_VISUAL_IDENTITY_MAX_EBAY_IMAGES", "3")),
            ),
        )
        self.minimum_score = (
            minimum_score
            if minimum_score is not None
            else float(os.getenv("V5_VISUAL_IDENTITY_MIN_SCORE", "0.74"))
        )
        self.minimum_margin = (
            minimum_margin
            if minimum_margin is not None
            else float(os.getenv("V5_VISUAL_IDENTITY_MIN_MARGIN", "0.08"))
        )
        self.override_number_minimum_score = (
            override_number_minimum_score
            if override_number_minimum_score is not None
            else float(os.getenv("V5_VISUAL_IDENTITY_OVERRIDE_NUMBER_MIN_SCORE", "0.82"))
        )
        self.override_number_minimum_margin = (
            override_number_minimum_margin
            if override_number_minimum_margin is not None
            else float(os.getenv("V5_VISUAL_IDENTITY_OVERRIDE_NUMBER_MIN_MARGIN", "0.12"))
        )
        self.eu_enrichment_enabled = (
            eu_enrichment_enabled
            if eu_enrichment_enabled is not None
            else os.getenv(
                "V5_VISUAL_IDENTITY_EU_ENRICHMENT_ENABLED", "false"
            ).strip().casefold()
            == "true"
        )
        self.card_number_ocr = card_number_ocr or LocalCardNumberOCR()
        self.microvariant_validator = (
            microvariant_validator or LocalMicrovariantValidator()
        )
        self.microvariant_evidence_provider = (
            microvariant_evidence_provider
            or DeterministicLocalMicrovariantEvidenceProvider()
        )
        self.post_macro_applicability_resolver = post_macro_applicability_resolver
        self.counters = VisualIdentityCounters()
        self._scan_signature_cache: dict[str, Tuple[_ImageSignature, ...]] = {}
        self._scan_bytes_cache: dict[str, Optional[bytes]] = {}

    def resolve_identity(
        self,
        identity: CardIdentity,
        image_urls: Sequence[str],
        *,
        marketplace_id: Optional[str] = None,
        microvariant_applicability: MicrovariantApplicability = (
            MicrovariantApplicability()
        ),
    ) -> VisualIdentityResolution:
        if (
            not self.enabled
            or not self.provider.config.enabled
            or not self.provider.config.api_key
        ):
            return VisualIdentityResolution(identity)

        usable_image_urls = tuple(
            dict.fromkeys(str(value).strip() for value in image_urls if str(value).strip())
        )[: self.max_ebay_images]
        if not usable_image_urls:
            self.counters.no_ebay_image += 1
            return VisualIdentityResolution(identity)

        search_text = self._visual_search_text(identity)
        if not search_text:
            return VisualIdentityResolution(identity)
        if self.provider.circuit_open:
            self.counters.visual_searches_skipped_after_breaker += 1
            self.provider._record_call_avoided_after_breaker()
            return VisualIdentityResolution(identity)

        self.counters.attempted += 1
        self.counters.api_searches += 1
        payload, status = self.poketrace_identity._request(
            identity, search_text, market="US"
        )
        if status != REQUEST_OK or payload is None:
            self.counters.api_unavailable += 1
            return VisualIdentityResolution(identity)

        data = payload.get("data")
        raw_candidates = (
            tuple(item for item in data if isinstance(item, Mapping))
            if isinstance(data, Sequence) and not isinstance(data, (str, bytes))
            else ()
        )
        candidates = self._candidate_pool(identity, raw_candidates)
        if not candidates:
            self.counters.no_candidates += 1
            return VisualIdentityResolution(identity)

        ebay_signatures = []
        ebay_image_bytes = []
        for image_url in usable_image_urls:
            image_bytes = self.ebay_image_fetcher(image_url)
            if image_bytes is None:
                self.counters.ebay_image_failures += 1
                continue
            try:
                signatures = _image_signatures(image_bytes)
            except (OSError, TypeError, ValueError):
                self.counters.ebay_image_failures += 1
                continue
            if signatures:
                self.counters.ebay_images_downloaded += 1
                ebay_signatures.extend(signatures)
                ebay_image_bytes.append(image_bytes)

        if not ebay_signatures:
            self.counters.no_ebay_image += 1
            return VisualIdentityResolution(identity)

        scored: list[tuple[float, float, _VisualCandidate]] = []
        for candidate in candidates:
            canonical_signatures = self._canonical_signatures(candidate.image_url)
            if not canonical_signatures:
                continue
            visual_score = max(
                _signature_similarity(left, right)
                for left in ebay_signatures
                for right in canonical_signatures
            )
            scored.append((visual_score, candidate.metadata_score, candidate))

        if not scored:
            self.counters.low_confidence += 1
            ocr = self._try_ocr_rescue(
                identity,
                candidates,
                ebay_image_bytes,
                ebay_signatures,
                marketplace_id,
                microvariant_applicability,
                raw_candidates,
            )
            return ocr or VisualIdentityResolution(identity)

        scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
        best_score, _metadata_score, best = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        margin = best_score - second_score

        expected_number = _normalize_card_number(identity.card_number)
        candidate_number = _normalize_card_number(best.payload.get("cardNumber"))
        overrides_number = bool(
            expected_number and candidate_number and expected_number != candidate_number
        )
        score_floor = (
            self.override_number_minimum_score
            if overrides_number
            else self.minimum_score
        )
        margin_floor = (
            self.override_number_minimum_margin
            if overrides_number
            else self.minimum_margin
        )

        if best_score < score_floor:
            self.counters.low_confidence += 1
            ocr = self._try_ocr_rescue(
                identity,
                candidates,
                ebay_image_bytes,
                ebay_signatures,
                marketplace_id,
                microvariant_applicability,
                raw_candidates,
            )
            if ocr is not None:
                return ocr
            return VisualIdentityResolution(identity, score=best_score, margin=margin)
        if len(scored) > 1 and margin < margin_floor:
            self.counters.close_second += 1
            ocr = self._try_ocr_rescue(
                identity,
                candidates,
                ebay_image_bytes,
                ebay_signatures,
                marketplace_id,
                microvariant_applicability,
                raw_candidates,
            )
            if ocr is not None:
                return ocr
            return VisualIdentityResolution(identity, score=best_score, margin=margin)

        resolved = replace(
            _resolved_identity(identity, best.payload),
            ambiguities=(),
        )
        if not (resolved.card_name and resolved.set and resolved.card_number):
            self.counters.low_confidence += 1
            ocr = self._try_ocr_rescue(
                identity,
                candidates,
                ebay_image_bytes,
                ebay_signatures,
                marketplace_id,
                microvariant_applicability,
                raw_candidates,
            )
            if ocr is not None:
                return ocr
            return VisualIdentityResolution(identity, score=best_score, margin=margin)

        if overrides_number:
            self.counters.card_number_overrides += 1
        if identity.ambiguities:
            self.counters.ambiguities_cleared += 1

        microvariant = self._validate_microvariant(
            resolved,
            best.payload,
            ebay_image_bytes,
            microvariant_applicability,
            raw_candidates,
        )
        if not microvariant.blocks_economics:
            self.poketrace_identity._prime_market_snapshot(
                identity, resolved, best.payload, market="US"
            )
            self.counters.market_snapshots_primed += 1
        else:
            self.counters.microvariant_gate_blocked_before_market += 1
            self.counters.market_snapshot_not_primed_microvariant += 1
        self.counters.rescued += 1
        if not microvariant.blocks_economics:
            self._enrich_eu_market(
                resolved,
                ebay_signatures,
                marketplace_id,
                microvariant,
            )
        elif self._eu_enrichment_eligible(marketplace_id):
            self.counters.eu_enrichment_not_attempted_microvariant += 1
        return VisualIdentityResolution(
            resolved,
            matched=True,
            card_id=str(best.payload.get("id") or "").strip() or None,
            score=best_score,
            margin=margin,
            microvariant=microvariant,
        )

    def _try_ocr_rescue(
        self,
        identity: CardIdentity,
        candidates: Sequence[_VisualCandidate],
        ebay_image_bytes: Sequence[bytes],
        ebay_signatures: Sequence[_ImageSignature],
        marketplace_id: Optional[str],
        microvariant_applicability: MicrovariantApplicability,
        raw_candidates: Sequence[Mapping[str, object]],
    ) -> Optional[VisualIdentityResolution]:
        result = self.card_number_ocr.resolve(
            ebay_image_bytes,
            tuple(candidate.payload for candidate in candidates),
            identity.card_number,
        )
        if not result.matched or result.candidate is None:
            return None

        retained_ambiguities = tuple(
            value
            for value in identity.ambiguities
            if not (
                value.startswith("card_number:")
                or value.startswith("card_name: resolution set+number ambigue")
                or value == "catalog_identity_ambiguous"
            )
        )
        resolved = replace(
            _resolved_identity(identity, result.candidate),
            ambiguities=retained_ambiguities,
        )
        if (
            not (resolved.card_name and resolved.set and resolved.card_number)
            or resolved.ambiguities
        ):
            return None

        microvariant = self._validate_microvariant(
            resolved,
            result.candidate,
            ebay_image_bytes,
            microvariant_applicability,
            raw_candidates,
        )
        if not microvariant.blocks_economics:
            self.poketrace_identity._prime_market_snapshot(
                identity, resolved, result.candidate, market="US"
            )
            self.counters.ocr_market_snapshots_primed += 1
            self._enrich_eu_market(
                resolved,
                ebay_signatures,
                marketplace_id,
                microvariant,
            )
        else:
            self.counters.microvariant_gate_blocked_before_market += 1
            self.counters.market_snapshot_not_primed_microvariant += 1
            if self._eu_enrichment_eligible(marketplace_id):
                self.counters.eu_enrichment_not_attempted_microvariant += 1
        self.counters.ocr_rescued += 1
        return VisualIdentityResolution(
            resolved,
            matched=True,
            card_id=str(result.candidate.get("id") or "").strip() or None,
            microvariant=microvariant,
        )

    def _validate_microvariant(
        self,
        identity: CardIdentity,
        candidate: Mapping[str, object],
        ebay_image_bytes: Sequence[bytes],
        applicability: MicrovariantApplicability,
        raw_candidates: Sequence[Mapping[str, object]],
    ) -> MicrovariantResolution:
        if applicability.status == "MICROVARIANT_APPLICABILITY_UNKNOWN":
            self.counters.applicability_pre_macro_unknown += 1
            if self.post_macro_applicability_resolver is not None:
                self.counters.applicability_post_macro_attempts += 1
                try:
                    post_macro = self.post_macro_applicability_resolver(identity)
                except (OSError, TypeError, ValueError):
                    post_macro = MicrovariantApplicability()
                applicability = post_macro
                if post_macro.status == "MICROVARIANT_APPLICABILITY_UNKNOWN":
                    self.counters.applicability_post_macro_unknown += 1
                else:
                    self.counters.applicability_post_macro_resolved += 1
        else:
            self.counters.applicability_pre_macro_known += 1
        preliminary = self.microvariant_validator.resolve(
            identity,
            applicability,
            candidate=candidate,
        )
        attempted = bool(
            applicability.status == MICROVARIANT_APPLICABLE
            or (
                applicability.status == "MICROVARIANT_APPLICABILITY_UNKNOWN"
                and preliminary.premium_candidate_not_inherited
            )
        )
        evidence = None
        if attempted:
            winning_reference, competing_references = self._microvariant_references(
                identity, candidate, raw_candidates
            )
            try:
                evidence = self.microvariant_evidence_provider(
                    MicrovariantEvidenceRequest(
                        identity,
                        candidate,
                        ebay_image_bytes,
                        winning_reference,
                        competing_references,
                        applicability,
                    )
                )
            except (OSError, TypeError, ValueError):
                evidence = None
        resolution = self.microvariant_validator.resolve(
            identity,
            applicability,
            candidate=candidate,
            evidence=evidence,
            visual_attempted=attempted,
        )
        self.counters.premium_variant_candidate_not_inherited += int(
            resolution.premium_candidate_not_inherited
        )
        self.counters.microvariant_visual_attempts += int(
            resolution.visual_attempted
        )
        self.counters.microvariant_visual_confirmed += int(
            resolution.visual_confirmed
        )
        self.counters.microvariant_visual_inconclusive += int(
            resolution.visual_attempted and not resolution.visual_confirmed
        )
        self._count_microvariant_resolution(resolution)
        return resolution

    def _microvariant_references(
        self,
        identity: CardIdentity,
        winning: Mapping[str, object],
        raw_candidates: Sequence[Mapping[str, object]],
    ) -> Tuple[
        Optional[CanonicalMicrovariantReference],
        Tuple[CanonicalMicrovariantReference, ...],
    ]:
        winning_url = str(winning.get("image") or "").strip()
        winning_bytes = self._canonical_image_bytes(winning_url) if winning_url else None
        winning_reference = (
            CanonicalMicrovariantReference(winning, winning_bytes)
            if winning_bytes is not None
            else None
        )
        competing = []
        for candidate in raw_candidates:
            if candidate is winning or not self._same_exact_macro(identity, winning, candidate):
                continue
            if not self._different_microvariant(winning, candidate):
                continue
            image_url = str(candidate.get("image") or "").strip()
            image_bytes = self._canonical_image_bytes(image_url) if image_url else None
            if image_bytes is None:
                continue
            competing.append(CanonicalMicrovariantReference(candidate, image_bytes))
            if len(competing) >= 4:
                break
        return winning_reference, tuple(competing)

    @staticmethod
    def _same_exact_macro(
        identity: CardIdentity,
        winning: Mapping[str, object],
        candidate: Mapping[str, object],
    ) -> bool:
        if _normalize(candidate.get("productType")) not in {"", "single"}:
            return False
        if _normalize_card_name(candidate.get("name")) != _normalize_card_name(
            winning.get("name")
        ):
            return False
        if _normalize_card_number(candidate.get("cardNumber")) != _normalize_card_number(
            winning.get("cardNumber")
        ):
            return False
        winning_set = winning.get("set")
        candidate_set = candidate.get("set")
        if not isinstance(winning_set, Mapping) or not isinstance(candidate_set, Mapping):
            return False
        if _set_similarity(
            winning_set.get("name"),
            candidate_set.get("name"),
            candidate_set.get("slug"),
        ) != 1.0:
            return False
        expected_language = _normalize(identity.language)
        winning_language = _normalize(winning.get("language"))
        candidate_language = _normalize(candidate.get("language"))
        if not expected_language or not winning_language or not candidate_language:
            return False
        safe_language_aliases = {
            "en": "english",
            "anglais": "english",
            "fr": "french",
            "francais": "french",
            "de": "german",
            "allemand": "german",
            "es": "spanish",
            "espagnol": "spanish",
            "it": "italian",
            "italien": "italian",
            "ja": "japanese",
            "jp": "japanese",
            "japonais": "japanese",
        }
        expected_language = safe_language_aliases.get(expected_language, expected_language)
        winning_language = safe_language_aliases.get(winning_language, winning_language)
        candidate_language = safe_language_aliases.get(candidate_language, candidate_language)
        if winning_language != candidate_language or expected_language != winning_language:
            return False
        return True

    @staticmethod
    def _different_microvariant(
        winning: Mapping[str, object], candidate: Mapping[str, object]
    ) -> bool:
        from .variant_semantics import semantics_from_poketrace_candidate

        left = semantics_from_poketrace_candidate(winning)
        right = semantics_from_poketrace_candidate(candidate)
        return any(
            left_value != right_value and (left_value is not None or right_value is not None)
            for left_value, right_value in (
                (left.edition, right.edition),
                (left.finish, right.finish),
                (left.promo, right.promo),
                (left.special_finish, right.special_finish),
            )
        )

    def _count_microvariant_resolution(self, resolution: MicrovariantResolution) -> None:
        if not resolution.visual_attempted:
            return
        self.counters.microvariant_reference_pairs_available += int(
            resolution.reference_pair_available
        )
        self.counters.microvariant_reference_pairs_missing += int(
            not resolution.reference_pair_available
        )
        self.counters.microvariant_card_normalization_success += int(
            resolution.card_normalized
        )
        self.counters.microvariant_card_normalization_failure += int(
            not resolution.card_normalized
        )
        self.counters.microvariant_alignment_success += int(
            resolution.alignment_succeeded
        )
        self.counters.microvariant_alignment_failure += int(
            not resolution.alignment_succeeded
        )
        self.counters.microvariant_region_usable += int(
            resolution.discriminative_region_usable
        )
        self.counters.microvariant_region_unusable += int(
            not resolution.discriminative_region_usable
        )
        status = resolution.edition_status
        self.counters.microvariant_first_confirmed += int(status == "FIRST_EDITION_CONFIRMED")
        self.counters.microvariant_unlimited_confirmed += int(status == "UNLIMITED_CONFIRMED")
        self.counters.microvariant_other_confirmed += int(status == "OTHER_VARIANT_CONFIRMED")
        self.counters.microvariant_unknown += int(status == "EDITION_UNKNOWN")
        self.counters.microvariant_conflict += int(status == "EDITION_CONFLICT")
        blocker_counter = {
            "edition": "blocker_edition",
            "finish": "blocker_finish",
            "promo": "blocker_promo",
            "special_finish": "blocker_special_finish",
            "multiple": "blocker_multiple",
        }.get(resolution.blocker_dimension)
        if blocker_counter:
            setattr(self.counters, blocker_counter, getattr(self.counters, blocker_counter) + 1)

    def _eu_enrichment_eligible(self, marketplace_id: Optional[str]) -> bool:
        return bool(
            self.eu_enrichment_enabled
            and marketplace_id
            and marketplace_id != "EBAY_US"
            and self.provider.supports_eu_market
        )

    def _enrich_eu_market(
        self,
        resolved: CardIdentity,
        ebay_signatures: Sequence[_ImageSignature],
        marketplace_id: Optional[str],
        microvariant: Optional[MicrovariantResolution] = None,
    ) -> None:
        """Prime one strict EU record after a non-US visual/OCR rescue.

        This is valuation provenance only. The returned listing identity is
        never replaced by the EU provider payload, and a failed enrichment
        never weakens the existing identity or variant gates.
        """

        if (
            not self.eu_enrichment_enabled
            or not marketplace_id
            or marketplace_id == "EBAY_US"
            or not self.provider.supports_eu_market
            or not (resolved.card_name and resolved.set and resolved.card_number)
            or self.provider.circuit_open
        ):
            return

        search_identity, _alias = self.provider.identity_for_search(resolved)
        search_text = self._visual_search_text(search_identity)
        if not search_text:
            return

        self.counters.eu_enrichment_attempts += 1
        payload, status = self.poketrace_identity._request(
            search_identity,
            search_text,
            market="EU",
            use_structured_filters=True,
        )
        if status != REQUEST_OK or payload is None:
            return

        data = payload.get("data")
        raw_candidates = (
            tuple(item for item in data if isinstance(item, Mapping))
            if isinstance(data, Sequence) and not isinstance(data, (str, bytes))
            else ()
        )
        candidates = tuple(
            item
            for item in raw_candidates
            if _candidate_market_compatible(item, "EU")
        )
        self.provider.counters.market_mismatch_rejections += (
            len(raw_candidates) - len(candidates)
        )
        self.counters.eu_enrichment_candidates += len(candidates)

        metadata_proven: list[Mapping[str, object]] = []
        for candidate in candidates:
            evidence = _candidate_evidence(search_identity, candidate)
            if _normalize(candidate.get("productType")) not in {"", "single"}:
                self.counters.eu_enrichment_rejected_core += 1
                continue
            exact_core = bool(
                evidence.name_matched
                and evidence.set_matched
                and evidence.number_exact
            )
            if not exact_core:
                self.counters.eu_enrichment_rejected_core += 1
                continue

            if not evidence.variant_compatible and not self._confirmed_microvariant_matches(
                resolved, candidate, microvariant
            ):
                self.counters.eu_enrichment_rejected_variant += 1
                continue
            metadata_proven.append(candidate)

        # A whole-card perceptual match proves artwork, not a tiny edition mark
        # or a price-sensitive finish.  Incomplete microvariant metadata is no
        # longer bridged here; only the dedicated local validator may do that.
        accepted = metadata_proven
        if len(accepted) != 1:
            if len(accepted) > 1:
                self.counters.eu_enrichment_ambiguous += 1
            return

        card = accepted[0]
        if not self.provider._prime_market_match(
            resolved,
            "EU",
            card,
            count_match=True,
        ):
            return
        self.counters.eu_enrichment_matches += 1
        prices = card.get("prices")
        if (
            str(card.get("currency") or "").strip().upper() == "EUR"
            and isinstance(prices, Mapping)
        ):
            self.counters.cardmarket_snapshots_recovered += 1

    @staticmethod
    def _confirmed_microvariant_matches(
        identity: CardIdentity,
        candidate: Mapping[str, object],
        resolution: Optional[MicrovariantResolution],
    ) -> bool:
        if resolution is None or not resolution.visual_confirmed:
            return False
        from .variant_semantics import variant_compatibility

        if resolution.edition_status == "FIRST_EDITION_CONFIRMED":
            proven = replace(identity, edition="1st Edition")
        elif resolution.edition_status == "UNLIMITED_CONFIRMED":
            proven = replace(identity, edition="Unlimited")
        elif resolution.edition_status != "OTHER_VARIANT_CONFIRMED":
            return False
        elif resolution.blocker_dimension == "promo":
            if resolution.confirmed_value != "promo":
                return False
            proven = replace(identity, rarity="Promo")
        elif resolution.blocker_dimension == "finish":
            proven = replace(identity, finish=resolution.confirmed_value)
        elif resolution.blocker_dimension == "special_finish":
            proven = replace(identity, variant=resolution.confirmed_value)
        else:
            return False
        return variant_compatibility(proven, candidate).compatible

    @staticmethod
    def _visual_search_text(identity: CardIdentity) -> str:
        # The card number is intentionally not used as the primary visual search
        # discriminator: live runs show that this is the field most often
        # conflicting with otherwise plausible PokeTrace candidates.
        parts = [
            str(value).strip()
            for value in (identity.card_name, identity.set)
            if value and str(value).strip()
        ]
        if not parts and identity.card_number:
            parts.append(str(identity.card_number).strip())
        return " ".join(parts)

    def _candidate_pool(
        self,
        identity: CardIdentity,
        candidates: Sequence[Mapping[str, object]],
    ) -> Tuple[_VisualCandidate, ...]:
        unique: dict[tuple[str, str, str, str], _VisualCandidate] = {}
        expected_name = _normalize_card_name(identity.card_name)
        expected_number = _normalize_card_number(identity.card_number)
        expected_variant = _variant_family(identity.variant)

        for candidate in candidates:
            product_type = _normalize(candidate.get("productType"))
            if product_type and product_type != "single":
                continue
            image_url = str(candidate.get("image") or "").strip()
            if not image_url:
                continue
            candidate_name = _normalize_card_name(candidate.get("name"))
            if expected_name and candidate_name != expected_name:
                continue
            set_payload = candidate.get("set")
            set_name = (
                set_payload.get("name") if isinstance(set_payload, Mapping) else None
            )
            set_slug = (
                set_payload.get("slug") if isinstance(set_payload, Mapping) else None
            )
            set_similarity = _set_similarity(identity.set, set_name, set_slug)
            if identity.set and set_similarity < 0.66:
                continue
            candidate_variant = _variant_family(candidate.get("variant"))
            if (
                expected_variant
                and candidate_variant
                and expected_variant != candidate_variant
            ):
                continue

            candidate_number = _normalize_card_number(candidate.get("cardNumber"))
            metadata_score = 0.0
            metadata_score += 4.0 if expected_name and candidate_name == expected_name else 0.0
            metadata_score += 3.0 * set_similarity if identity.set else 0.0
            metadata_score += (
                3.0
                if expected_number and candidate_number == expected_number
                else 0.0
            )
            metadata_score += (
                1.0
                if expected_variant and candidate_variant == expected_variant
                else 0.0
            )
            key = (
                str(candidate.get("id") or "").strip(),
                candidate_name,
                candidate_number,
                _normalize(set_name),
            )
            previous = unique.get(key)
            value = _VisualCandidate(candidate, metadata_score, image_url)
            if previous is None or value.metadata_score > previous.metadata_score:
                unique[key] = value

        ordered = sorted(
            unique.values(), key=lambda value: value.metadata_score, reverse=True
        )[: self.max_candidates]
        self.counters.candidates_considered += len(ordered)
        return tuple(ordered)

    def _canonical_signatures(self, image_url: str) -> Tuple[_ImageSignature, ...]:
        cached = self._scan_signature_cache.get(image_url)
        if cached is not None:
            return cached
        image_bytes = self._canonical_image_bytes(image_url)
        if image_bytes is None:
            self._scan_signature_cache[image_url] = ()
            return ()
        try:
            signatures = _image_signatures(image_bytes)
        except (OSError, TypeError, ValueError):
            self.counters.candidate_image_failures += 1
            signatures = ()
        if signatures:
            self.counters.candidate_images_downloaded += 1
        self._scan_signature_cache[image_url] = signatures
        return signatures

    def _canonical_image_bytes(self, image_url: str) -> Optional[bytes]:
        if image_url in self._scan_bytes_cache:
            return self._scan_bytes_cache[image_url]
        image_bytes = self.candidate_image_fetcher(image_url)
        if image_bytes is None:
            self.counters.candidate_image_failures += 1
        self._scan_bytes_cache[image_url] = image_bytes
        return image_bytes

    def _fetch_poketrace_image(self, image_url: str) -> Optional[bytes]:
        parsed = urlparse(image_url)
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not (
            hostname == "poketrace.com" or hostname.endswith(".poketrace.com")
        ):
            return None
        try:
            response = self.provider.session.get(
                image_url,
                headers={"Accept": "image/*"},
                timeout=self.provider.config.timeout_seconds,
                stream=True,
            )
        except Exception:
            return None
        try:
            if getattr(response, "status_code", None) != 200:
                return None
            raw_length = getattr(response, "headers", {}).get("Content-Length")
            if raw_length and int(raw_length) > MAX_VISUAL_IMAGE_BYTES:
                return None
            content = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > MAX_VISUAL_IMAGE_BYTES:
                    return None
            return bytes(content) if content else None
        except (AttributeError, TypeError, ValueError):
            return None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


def render_visual_identity_counters(resolver: LocalVisualIdentityResolver) -> str:
    counters = resolver.counters
    ocr = resolver.card_number_ocr.counters
    return "\n".join(
        (
            "=== V5 LOCAL VISUAL IDENTITY RESCUE ===",
            f"enabled: {str(resolver.enabled).lower()}",
            "scope: ambiguous/insufficient RAW listings only",
            "method: local perceptual + edge + color scan matching",
            "model API calls: 0",
            f"forensic eligible: {counters.forensic_eligible}",
            f"skipped by per-run limit: {counters.skipped_run_limit}",
            f"attempted: {counters.attempted}",
            f"PokeTrace candidate searches: {counters.api_searches}",
            f"candidate searches unavailable: {counters.api_unavailable}",
            (
                "visual searches skipped after breaker: "
                f"{counters.visual_searches_skipped_after_breaker}"
            ),
            f"no visual candidates after metadata filter: {counters.no_candidates}",
            f"no usable eBay image after fetch: {counters.no_ebay_image}",
            f"candidate scans considered: {counters.candidates_considered}",
            f"candidate scans downloaded: {counters.candidate_images_downloaded}",
            f"candidate image failures: {counters.candidate_image_failures}",
            f"eBay images downloaded: {counters.ebay_images_downloaded}",
            f"eBay image failures: {counters.ebay_image_failures}",
            f"low-confidence rejects: {counters.low_confidence}",
            f"close-second/ambiguous rejects: {counters.close_second}",
            f"visual identities rescued: {counters.rescued}",
            f"visual structured card-number overrides: {counters.card_number_overrides}",
            f"ambiguities cleared by visual evidence: {counters.ambiguities_cleared}",
            f"market snapshots primed from visual match: {counters.market_snapshots_primed}",
            (
                "premium variant candidate not inherited: "
                f"{counters.premium_variant_candidate_not_inherited}"
            ),
            f"microvariant visual attempts: {counters.microvariant_visual_attempts}",
            (
                "microvariant visual confirmed: "
                f"{counters.microvariant_visual_confirmed}"
            ),
            (
                "microvariant visual inconclusive: "
                f"{counters.microvariant_visual_inconclusive}"
            ),
            (
                "microvariant gate blocked before market: "
                f"{counters.microvariant_gate_blocked_before_market}"
            ),
            (
                "market snapshot not primed - microvariant: "
                f"{counters.market_snapshot_not_primed_microvariant}"
            ),
            (
                "EU enrichment not attempted - microvariant: "
                f"{counters.eu_enrichment_not_attempted_microvariant}"
            ),
            "--- microvariant applicability timing ---",
            f"pre-macro known: {counters.applicability_pre_macro_known}",
            f"pre-macro unknown: {counters.applicability_pre_macro_unknown}",
            f"post-macro attempts: {counters.applicability_post_macro_attempts}",
            f"post-macro resolved: {counters.applicability_post_macro_resolved}",
            f"post-macro still unknown: {counters.applicability_post_macro_unknown}",
            "--- exact reference-pair detector ---",
            (
                "reference pairs available: "
                f"{counters.microvariant_reference_pairs_available}"
            ),
            (
                "reference pairs missing: "
                f"{counters.microvariant_reference_pairs_missing}"
            ),
            (
                "card normalization success: "
                f"{counters.microvariant_card_normalization_success}"
            ),
            (
                "card normalization failure: "
                f"{counters.microvariant_card_normalization_failure}"
            ),
            f"alignment success: {counters.microvariant_alignment_success}",
            f"alignment failure: {counters.microvariant_alignment_failure}",
            f"discriminative region usable: {counters.microvariant_region_usable}",
            f"discriminative region unusable: {counters.microvariant_region_unusable}",
            f"First confirmed: {counters.microvariant_first_confirmed}",
            f"Unlimited confirmed: {counters.microvariant_unlimited_confirmed}",
            f"other microvariant confirmed: {counters.microvariant_other_confirmed}",
            f"microvariant UNKNOWN: {counters.microvariant_unknown}",
            f"microvariant CONFLICT: {counters.microvariant_conflict}",
            f"blocker dimension edition: {counters.blocker_edition}",
            f"blocker dimension finish: {counters.blocker_finish}",
            f"blocker dimension promo: {counters.blocker_promo}",
            (
                "blocker dimension special_finish: "
                f"{counters.blocker_special_finish}"
            ),
            f"blocker dimension multiple: {counters.blocker_multiple}",
            "--- targeted local card-number OCR fallback ---",
            f"OCR enabled: {str(resolver.card_number_ocr.config.enabled).lower()}",
            f"OCR attempted: {ocr.attempted}",
            f"OCR calls: {ocr.ocr_calls}",
            f"OCR failures: {ocr.ocr_failures}",
            f"OCR candidate-matching tokens seen: {ocr.candidate_tokens_seen}",
            f"OCR consensus found: {ocr.consensus_found}",
            f"OCR rejected no consensus: {ocr.rejected_no_consensus}",
            f"OCR rejected duplicate candidate number: {ocr.rejected_candidate_ambiguous}",
            f"OCR identities rescued: {counters.ocr_rescued}",
            f"OCR structured card-number overrides: {ocr.structured_number_overrides}",
            f"market snapshots primed from OCR match: {counters.ocr_market_snapshots_primed}",
            "--- strict EU/CardMarket enrichment after non-US rescue ---",
            f"EU enrichment enabled: {str(resolver.eu_enrichment_enabled).lower()}",
            f"EU enrichment attempts: {counters.eu_enrichment_attempts}",
            f"EU candidates: {counters.eu_enrichment_candidates}",
            f"EU matches: {counters.eu_enrichment_matches}",
            f"EU ambiguous: {counters.eu_enrichment_ambiguous}",
            (
                "EU rejected no usable canonical image: "
                f"{counters.eu_enrichment_rejected_no_image}"
            ),
            f"EU rejected variant: {counters.eu_enrichment_rejected_variant}",
            f"EU rejected core identity: {counters.eu_enrichment_rejected_core}",
            (
                "CardMarket snapshots recovered: "
                f"{counters.cardmarket_snapshots_recovered}"
            ),
            "persisted images/OCR text: 0",
            "persisted eBay identifiers: 0",
        )
    )


def _image_signatures(image_bytes: bytes) -> Tuple[_ImageSignature, ...]:
    with Image.open(io.BytesIO(image_bytes)) as opened:
        base = ImageOps.exif_transpose(opened).convert("RGB")
        if min(base.size) < 32:
            raise ValueError("image too small")
        base.thumbnail((900, 900))
        candidates = [base]
        cropped = _subject_crop(base)
        if cropped is not None:
            candidates.append(cropped)

        signatures = []
        for candidate in candidates:
            for angle in (0, 90, 180, 270):
                rotated = candidate.rotate(angle, expand=True) if angle else candidate
                normalized = ImageOps.fit(rotated, (256, 356), method=Image.Resampling.LANCZOS)
                signatures.append(_signature(normalized))
        return tuple(signatures)


def _subject_crop(image: Image.Image) -> Optional[Image.Image]:
    sample = image.copy()
    sample.thumbnail((420, 420))
    width, height = sample.size
    if width < 40 or height < 40:
        return None

    patch = max(3, min(width, height) // 20)
    corner_boxes = (
        (0, 0, patch, patch),
        (width - patch, 0, width, patch),
        (0, height - patch, patch, height),
        (width - patch, height - patch, width, height),
    )
    corner_means = [ImageStat.Stat(sample.crop(box)).mean[:3] for box in corner_boxes]
    background = tuple(
        sorted(values)[len(values) // 2]
        for values in zip(*corner_means)
    )

    pixels = sample.load()
    xs = []
    ys = []
    threshold_sq = 38.0 * 38.0
    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            distance_sq = (
                (red - background[0]) ** 2
                + (green - background[1]) ** 2
                + (blue - background[2]) ** 2
            )
            if distance_sq >= threshold_sq:
                xs.append(x)
                ys.append(y)
    if len(xs) < width * height * 0.18:
        return None

    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    box_width = right - left + 1
    box_height = bottom - top + 1
    if box_width * box_height < width * height * 0.24:
        return None
    padding_x = max(2, int(box_width * 0.025))
    padding_y = max(2, int(box_height * 0.025))
    left = max(0, left - padding_x)
    right = min(width, right + padding_x + 1)
    top = max(0, top - padding_y)
    bottom = min(height, bottom + padding_y + 1)

    scale_x = image.width / width
    scale_y = image.height / height
    original_box = (
        int(left * scale_x),
        int(top * scale_y),
        int(right * scale_x),
        int(bottom * scale_y),
    )
    cropped = image.crop(original_box)
    ratio = min(cropped.size) / max(cropped.size)
    if ratio < 0.45:
        return None
    return cropped


def _signature(image: Image.Image) -> _ImageSignature:
    gray = ImageOps.grayscale(image)
    center = gray.crop((20, 52, 236, 300))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return _ImageSignature(
        average_hash=_average_hash(gray, 16),
        edge_hash=_difference_hash(edges, 16),
        center_hash=_average_hash(center, 16),
        color_histogram=_color_histogram(image, bins=8),
    )


def _average_hash(image: Image.Image, size: int) -> Tuple[bool, ...]:
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    values = tuple(resized.getdata())
    mean = sum(values) / len(values)
    return tuple(value >= mean for value in values)


def _difference_hash(image: Image.Image, size: int) -> Tuple[bool, ...]:
    resized = image.resize((size + 1, size), Image.Resampling.LANCZOS)
    values = tuple(resized.getdata())
    bits = []
    for y in range(size):
        offset = y * (size + 1)
        for x in range(size):
            bits.append(values[offset + x] >= values[offset + x + 1])
    return tuple(bits)


def _color_histogram(image: Image.Image, bins: int) -> Tuple[float, ...]:
    resized = image.resize((96, 128), Image.Resampling.BILINEAR)
    histogram = resized.histogram()
    channel_size = 256
    bin_width = channel_size // bins
    pixels = resized.width * resized.height
    result = []
    for channel in range(3):
        values = histogram[channel * channel_size : (channel + 1) * channel_size]
        for index in range(bins):
            start = index * bin_width
            end = channel_size if index == bins - 1 else (index + 1) * bin_width
            result.append(sum(values[start:end]) / pixels)
    return tuple(result)


def _bit_similarity(left: Tuple[bool, ...], right: Tuple[bool, ...]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    equal = sum(a == b for a, b in zip(left, right))
    return equal / len(left)


def _histogram_similarity(left: Tuple[float, ...], right: Tuple[float, ...]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return sum(min(a, b) for a, b in zip(left, right)) / 3.0


def _signature_similarity(left: _ImageSignature, right: _ImageSignature) -> float:
    return (
        0.30 * _bit_similarity(left.average_hash, right.average_hash)
        + 0.35 * _bit_similarity(left.edge_hash, right.edge_hash)
        + 0.25 * _bit_similarity(left.center_hash, right.center_hash)
        + 0.10 * _histogram_similarity(left.color_histogram, right.color_histogram)
    )
