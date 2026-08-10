from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, Tuple

import requests

from .models import (
    CardIdentity,
    GradeAssessment,
    GradeImagePair,
    GradeProbabilities,
    ImageQuality,
)


CARDGRADER_OFFICIAL_BASE = "https://cardgrader.ai/v1"


class GradeProviderError(RuntimeError):
    pass


class GradeProviderUnavailable(GradeProviderError):
    pass


class PaidCallNotAuthorized(GradeProviderError):
    pass


class GradeAssessmentProvider(Protocol):
    def assess(
        self, image_pair: GradeImagePair, identity: CardIdentity
    ) -> GradeAssessment:
        ...


@dataclass(frozen=True)
class CardGraderAIConfig:
    api_key: str
    allow_paid_calls: bool = False
    timeout_seconds: float = 20.0
    poll_interval_seconds: float = 2.0
    max_wait_seconds: float = 150.0

    @classmethod
    def from_env(cls) -> "CardGraderAIConfig":
        api_key = os.getenv("CARDGRADER_API_KEY", "").strip()
        if not api_key:
            raise ValueError("CARDGRADER_API_KEY est absente")
        return cls(
            api_key=api_key,
            allow_paid_calls=(
                os.getenv("CARDGRADER_V5_ALLOW_PAID_CALLS", "false").strip().lower()
                == "true"
            ),
            timeout_seconds=float(os.getenv("CARDGRADER_V5_TIMEOUT_SECONDS", "20")),
            poll_interval_seconds=float(
                os.getenv("CARDGRADER_V5_POLL_INTERVAL_SECONDS", "2")
            ),
            max_wait_seconds=float(os.getenv("CARDGRADER_V5_MAX_WAIT_SECONDS", "150")),
        )


class CardGraderAIProvider:
    """Adaptateur officiel CardGrader.AI, bloque par defaut.

    ``POST /v1/scans`` consomme des credits. L'appel est impossible tant que
    ``allow_paid_calls`` (ou CARDGRADER_V5_ALLOW_PAID_CALLS) n'est pas vrai.
    Les lectures de resultat sont effectuees via ``GET /v1/scans/{id}``.
    """

    def __init__(
        self,
        config: CardGraderAIConfig,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()

    def assess(
        self, image_pair: GradeImagePair, identity: CardIdentity
    ) -> GradeAssessment:
        if not self.config.allow_paid_calls:
            raise PaidCallNotAuthorized(
                "Appel CardGrader.AI bloque: autorisation payante V5 absente"
            )
        if not image_pair.is_complete():
            raise GradeProviderError("Recto et verso explicites requis avant pre-grading")

        idempotency_material = "|".join(
            (
                image_pair.front_url or "",
                image_pair.back_url or "",
                identity.display_name(),
            )
        )
        idempotency_key = "gccv5_" + hashlib.sha256(
            idempotency_material.encode("utf-8")
        ).hexdigest()[:48]
        response = self.session.post(
            f"{CARDGRADER_OFFICIAL_BASE}/scans",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
            json={
                "frontImageUrl": image_pair.front_url,
                "backImageUrl": image_pair.back_url,
                "modules": ["grade"],
            },
            timeout=self.config.timeout_seconds,
        )
        self._raise_for_status(response, "soumission du scan")
        scan_id = response.json().get("id")
        if scan_id is None:
            raise GradeProviderUnavailable("CardGrader.AI n'a retourne aucun identifiant")

        deadline = time.monotonic() + self.config.max_wait_seconds
        while time.monotonic() < deadline:
            result = self.session.get(
                f"{CARDGRADER_OFFICIAL_BASE}/scans/{scan_id}",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=self.config.timeout_seconds,
            )
            self._raise_for_status(result, "lecture du scan")
            payload = result.json()
            status = str(payload.get("status", "")).lower()
            if status == "completed":
                return parse_cardgrader_assessment(payload)
            if status in {"failed", "cancelled", "error"}:
                raise GradeProviderUnavailable(
                    f"CardGrader.AI a termine le scan avec le statut {status}"
                )
            time.sleep(min(self.config.poll_interval_seconds, 5.0))
        raise GradeProviderUnavailable("Delai CardGrader.AI depasse")

    @staticmethod
    def _raise_for_status(response: requests.Response, operation: str) -> None:
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(response, "status_code", "inconnu")
            raise GradeProviderUnavailable(
                f"Echec CardGrader.AI pendant {operation} (HTTP {status})"
            ) from exc


def _float_or_none(value: object) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _confidence(value: object) -> Optional[float]:
    if isinstance(value, str) and value.strip().endswith("%"):
        number = _float_or_none(value.strip()[:-1])
        return number / 100 if number is not None else None
    number = _float_or_none(value)
    if number is None:
        return None
    if 1 < number <= 100:
        return number / 100
    if 0 <= number <= 1:
        return number
    return None


def _image_quality(value: object) -> ImageQuality:
    normalized = str(value or "").strip().casefold()
    if normalized in {"high", "excellent", "good", "bonne", "elevee", "élevée"}:
        return ImageQuality.HIGH
    if normalized in {"medium", "average", "moyenne", "acceptable"}:
        return ImageQuality.MEDIUM
    if normalized in {"low", "poor", "bad", "faible", "mauvaise"}:
        return ImageQuality.LOW
    return ImageQuality.UNKNOWN


def parse_cardgrader_assessment(payload: Mapping[str, object]) -> GradeAssessment:
    grading = payload.get("grading") or {}
    if not isinstance(grading, Mapping):
        raise GradeProviderUnavailable("Reponse CardGrader.AI sans bloc grading")
    predicted_grade = _float_or_none(
        grading.get("predictedGrade", grading.get("grade"))
    )
    if predicted_grade is None or not 0 <= predicted_grade <= 10:
        raise GradeProviderUnavailable("Grade predit CardGrader.AI absent ou invalide")
    sub_grades = grading.get("subGrades") or {}
    if not isinstance(sub_grades, Mapping):
        sub_grades = {}

    issues = []
    raw_issues = grading.get("issues") or grading.get("detectedIssues") or []
    if isinstance(raw_issues, list):
        issues.extend(str(issue) for issue in raw_issues if str(issue).strip())
    for key in ("summary", "justification"):
        if grading.get(key):
            issues.append(str(grading[key]))

    quality_value = grading.get("imageQuality", payload.get("imageQuality"))
    return GradeAssessment(
        predicted_grade=predicted_grade,
        centering=_float_or_none(sub_grades.get("centering")),
        corners=_float_or_none(sub_grades.get("corners")),
        edges=_float_or_none(sub_grades.get("edges")),
        surface=_float_or_none(sub_grades.get("surface")),
        confidence=_confidence(grading.get("confidence")),
        issues=tuple(dict.fromkeys(issues)),
        image_quality=_image_quality(quality_value),
        provider="CardGrader.AI API officielle",
    )


DEFAULT_DISTRIBUTIONS = {
    "10": (0.30, 0.45, 0.18, 0.07),
    "9": (0.06, 0.49, 0.30, 0.15),
    "8": (0.01, 0.14, 0.50, 0.35),
    "lower": (0.00, 0.04, 0.21, 0.75),
}


class ConservativeProbabilityPolicy:
    def __init__(
        self,
        distributions: Optional[Mapping[str, Tuple[float, float, float, float]]] = None,
    ) -> None:
        self.distributions = dict(distributions or DEFAULT_DISTRIBUTIONS)
        required = {"10", "9", "8", "lower"}
        if set(self.distributions) != required:
            raise ValueError("Les distributions doivent definir 10, 9, 8 et lower")
        for values in self.distributions.values():
            GradeProbabilities(*values)

    @classmethod
    def from_env(cls) -> "ConservativeProbabilityPolicy":
        raw = os.getenv("V5_GRADE_DISTRIBUTIONS_JSON", "").strip()
        if not raw:
            return cls()
        try:
            payload = json.loads(raw)
            distributions = {
                str(key): tuple(float(value) for value in values)
                for key, values in payload.items()
            }
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("V5_GRADE_DISTRIBUTIONS_JSON invalide") from exc
        return cls(distributions=distributions)  # type: ignore[arg-type]

    def probabilities_for(self, assessment: GradeAssessment) -> GradeProbabilities:
        if assessment.predicted_grade >= 9.75:
            key = "10"
        elif assessment.predicted_grade >= 8.75:
            key = "9"
        elif assessment.predicted_grade >= 7.75:
            key = "8"
        else:
            key = "lower"
        return GradeProbabilities(*self.distributions[key])
