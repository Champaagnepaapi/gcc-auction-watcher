from __future__ import annotations

import os
from typing import Any, Mapping, Sequence


PROVIDER_METRIC_OBSERVATION = "PROVIDER_METRIC_OBSERVATION"


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(1, value)


def _existing_metric_ids(kb: Any, source: str, metrics: Sequence[Any]) -> set[str]:
    """Fetch already-stored metric native IDs in bounded SQL chunks.

    The pinned P3 persistence layer is intentionally immutable and performs
    multiple SQL operations per normalized observation. Provider payloads can
    contain thousands of metrics, so feeding every unseen metric from one HTTP
    response can make one provider hold the local multisource lock for hours.
    """

    native_ids = list(dict.fromkeys(str(metric.native_id) for metric in metrics if metric.native_id))
    if not native_ids:
        return set()

    existing: set[str] = set()
    chunk_size = 200
    for offset in range(0, len(native_ids), chunk_size):
        chunk = native_ids[offset : offset + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = kb.connection.execute(
            f"""
            SELECT o.source_native_record_id
            FROM market_observation o
            JOIN source_system s ON s.id = o.source_system_id
            WHERE s.code = ?
              AND o.observation_type = ?
              AND o.source_native_record_id IN ({placeholders})
            """,
            (source, PROVIDER_METRIC_OBSERVATION, *chunk),
        ).fetchall()
        existing.update(str(row["source_native_record_id"]) for row in rows)
    return existing


def install(harvest: Any) -> None:
    """Bound normalized provider work while retaining full immutable raw payloads.

    Each provider response still stores its complete raw payload. Only a bounded
    number of *new* normalized metrics are sealed per raw record on one pass;
    later revisits skip already-stored native IDs and continue with the next
    unseen metrics. This preserves eventual completeness while prioritizing broad
    card coverage and preventing one large card/set response from monopolizing
    the Mac collector for hours.

    The wrapper also preserves PPT set progress across scheduled runs. The base
    harvester refreshes the set catalog on every run; without this adapter it
    resets positions to zero and repeatedly revisits the first sets whenever a
    run ends before the complete catalog.
    """

    if getattr(harvest, "_robot_kb_provider_bounds_installed", False):
        return

    original_persist_metrics = harvest.persist_metrics
    original_refresh_ppt_sets = harvest.refresh_ppt_sets
    original_next_ppt_set = harvest.next_ppt_set

    def persist_metrics_bounded(
        kb: Any,
        metrics: Sequence[Any],
        raw: Mapping[str, Any],
        raw_id: str,
        source: str,
        observed_at: str,
    ) -> int:
        limit = _positive_int("ROBOT_KB_PROVIDER_METRICS_PER_RECORD", 12)
        existing = _existing_metric_ids(kb, source, metrics)
        selected = []
        selected_ids: set[str] = set()
        for metric in metrics:
            native_id = str(metric.native_id)
            if not native_id or native_id in existing or native_id in selected_ids:
                continue
            selected.append(metric)
            selected_ids.add(native_id)
            if len(selected) >= limit:
                break
        # The P3-compatible persistence function always stores the immutable raw
        # provider record, even when all normalized metrics were already present.
        return original_persist_metrics(kb, selected, raw, raw_id, source, observed_at)

    def refresh_ppt_sets_preserve_progress(
        state: dict[str, Any],
        session: Any,
        key: str,
        diag: Any,
    ) -> bool:
        ppt_state = state.get("ppt", {})
        previous_positions = dict(ppt_state.get("positions", {}))
        previous_language_index = int(ppt_state.get("language_index", 0))
        ok = original_refresh_ppt_sets(state, session, key, diag)
        if not ok:
            return False
        for language in ("english", "japanese"):
            rows = state["ppt"]["sets"].get(language, [])
            state["ppt"]["positions"][language] = min(
                max(0, int(previous_positions.get(language, 0))),
                len(rows),
            )
        state["ppt"]["language_index"] = previous_language_index % 2
        return True

    def next_ppt_set_with_cycle_reset(state: dict[str, Any]):
        item = original_next_ppt_set(state)
        if item is None:
            # The caller records cycle completion and exits. Reset only after it
            # has observed exhaustion so the next scheduled run starts a new pass.
            state["ppt"]["positions"]["english"] = 0
            state["ppt"]["positions"]["japanese"] = 0
            state["ppt"]["language_index"] = 0
        return item

    harvest.persist_metrics = persist_metrics_bounded
    harvest.refresh_ppt_sets = refresh_ppt_sets_preserve_progress
    harvest.next_ppt_set = next_ppt_set_with_cycle_reset
    harvest._robot_kb_provider_bounds_installed = True
