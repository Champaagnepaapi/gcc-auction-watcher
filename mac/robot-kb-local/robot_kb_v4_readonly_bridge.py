#!/usr/bin/env python3
"""Localhost-only, authenticated, read-only Robot KB evidence bridge for V4.

The bridge exposes only typed exact completed-sale facts. It never exposes raw
payloads, source URLs, credentials, asks, active auctions or provider metrics.
A separate user-managed HTTPS/private tunnel may proxy this localhost service;
PostgreSQL itself must never be exposed.
"""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DB_HOST = "127.0.0.1"
DB_PORT = 5432
DB_NAME = "robot_pokemon_kb"
DB_USER = "robotpokemon_kb"
MAX_ROWS = 50


def _scalar_json(value: object) -> str:
    if value is None:
        return ""
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if isinstance(parsed, bool) or parsed is None:
        return ""
    if isinstance(parsed, (str, int, float)):
        return str(parsed).strip()
    return ""


def _grade_normalized(value: object) -> str:
    text = str(value or "").strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return str(int(number)) if number.is_integer() else str(number)


def filter_exact_sold_rows(rows, *, grader: str, grade: str):
    expected_grader = grader.strip().upper()
    expected_grade = _grade_normalized(grade)
    output = []
    for row in rows:
        raw_grader = _scalar_json(row.get("grader_value_json"))
        raw_grade = _scalar_json(row.get("grade_value_json"))
        if str(row.get("grader_resolution_state") or "") != "PROVEN":
            continue
        if str(row.get("grade_resolution_state") or "") != "PROVEN":
            continue
        if raw_grader.strip().upper() != expected_grader:
            continue
        if _grade_normalized(raw_grade) != expected_grade:
            continue
        if str(row.get("transaction_status") or "") != "COMPLETED":
            continue
        if str(row.get("lifecycle_state") or "") != "SEALED":
            continue
        try:
            amount_minor = int(row.get("amount_minor"))
        except (TypeError, ValueError):
            continue
        currency = str(row.get("currency") or "").upper()
        component = str(row.get("component_type") or "")
        sold_at = str(row.get("sold_at") or "").strip()
        source_code = str(row.get("source_code") or "").strip().casefold()
        if amount_minor <= 0 or not currency or not sold_at or not source_code:
            continue
        if component not in {"ITEM_PRICE", "HAMMER_PRICE", "ACCEPTED_OFFER", "TOTAL"}:
            continue
        output.append(
            {
                "source_code": source_code,
                "transaction_status": "COMPLETED",
                "sold_at": sold_at,
                "amount_minor": amount_minor,
                "currency": currency,
                "component_type": component,
            }
        )
    return output


class Database:
    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg unavailable in Robot KB local runtime") from exc
        password = os.environ.get("ROBOT_KB_V4_BRIDGE_DB_PASSWORD", "")
        if not password:
            raise RuntimeError("Robot KB local PostgreSQL password unavailable")
        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=password,
            autocommit=True,
            application_name="RobotKBV4ReadOnlyBridge",
            options="-c default_transaction_read_only=on -c statement_timeout=4000",
        )
        with conn.cursor() as cur:
            cur.execute("SHOW transaction_read_only")
            if cur.fetchone() != ("on",):
                conn.close()
                raise RuntimeError("Robot KB bridge database session is not read-only")
        return conn

    @staticmethod
    def _dicts(cur):
        columns = [item.name for item in cur.description or []]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def exact_sold(self, tcgdex_card_id: str, grader: str, grade: str, limit: int):
        card_sql = """
            SELECT DISTINCT il.canonical_card_id
            FROM external_identifier ei
            JOIN identifier_link il ON il.external_identifier_id = ei.id
            WHERE ei.namespace = 'TCGDEX_CARD_ID'
              AND ei.identifier_value = %s
              AND il.resolution_state = 'PROVEN'
              AND il.canonical_card_id IS NOT NULL
            ORDER BY il.canonical_card_id
        """
        sold_sql = """
            SELECT
                mo.id AS observation_id,
                mo.lifecycle_state,
                ss.code AS source_code,
                st.transaction_status,
                COALESCE(st.sale_occurred_at, mo.event_at, mo.observed_at) AS sold_at,
                pc.amount_minor,
                pc.currency,
                pc.component_type,
                grader.resolution_state AS grader_resolution_state,
                grader.resolved_value_json AS grader_value_json,
                grade.resolution_state AS grade_resolution_state,
                grade.resolved_value_json AS grade_value_json
            FROM market_observation mo
            JOIN sale_transaction st ON st.observation_id = mo.id
            JOIN source_system ss ON ss.id = mo.source_system_id
            LEFT JOIN LATERAL (
                SELECT p.amount_minor, p.currency, p.component_type
                FROM price_component p
                WHERE p.observation_id = mo.id
                  AND p.knowledge_state = 'KNOWN'
                  AND p.amount_minor IS NOT NULL
                  AND p.amount_minor > 0
                  AND p.component_type IN ('ITEM_PRICE','HAMMER_PRICE','ACCEPTED_OFFER','TOTAL')
                ORDER BY CASE p.component_type
                    WHEN 'ITEM_PRICE' THEN 1
                    WHEN 'HAMMER_PRICE' THEN 2
                    WHEN 'ACCEPTED_OFFER' THEN 3
                    WHEN 'TOTAL' THEN 4
                    ELSE 9
                END
                LIMIT 1
            ) pc ON TRUE
            LEFT JOIN LATERAL (
                SELECT fr.resolution_state, fr.resolved_value_json
                FROM identity_subject ids
                JOIN field_resolution fr ON fr.identity_subject_id = ids.id
                WHERE ids.source_record_id = mo.source_record_id
                  AND fr.field_name = 'grader'
                ORDER BY fr.created_at DESC
                LIMIT 1
            ) grader ON TRUE
            LEFT JOIN LATERAL (
                SELECT fr.resolution_state, fr.resolved_value_json
                FROM identity_subject ids
                JOIN field_resolution fr ON fr.identity_subject_id = ids.id
                WHERE ids.source_record_id = mo.source_record_id
                  AND fr.field_name = 'grade'
                ORDER BY fr.created_at DESC
                LIMIT 1
            ) grade ON TRUE
            WHERE mo.canonical_card_id = %s
              AND mo.observation_type = 'SALE_TRANSACTION'
              AND st.transaction_status = 'COMPLETED'
              AND mo.lifecycle_state = 'SEALED'
              AND pc.amount_minor IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM observation_relationship rel
                  WHERE rel.to_observation_id = mo.id
                    AND rel.relationship_type IN ('REVISION_OF','CANCELS','VOIDS')
              )
            ORDER BY COALESCE(st.sale_occurred_at, mo.event_at, mo.observed_at) DESC
            LIMIT %s
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(card_sql, (tcgdex_card_id,))
            card_ids = [row[0] for row in cur.fetchall()]
            if len(card_ids) != 1:
                return {
                    "schema_version": 1,
                    "identity": {
                        "tcgdex_card_id": tcgdex_card_id,
                        "grader": grader.strip().upper(),
                        "grade": _grade_normalized(grade),
                        "proof": "UNRESOLVED" if not card_ids else "CONFLICT",
                    },
                    "sales": [],
                }
            cur.execute(sold_sql, (card_ids[0], max(1, min(limit, MAX_ROWS))))
            rows = self._dicts(cur)
        return {
            "schema_version": 1,
            "identity": {
                "tcgdex_card_id": tcgdex_card_id,
                "grader": grader.strip().upper(),
                "grade": _grade_normalized(grade),
                "proof": "PROVEN_TCGDEX_AND_GRADE",
            },
            "sales": filter_exact_sold_rows(rows, grader=grader, grade=grade),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "RobotKBV4ReadOnlyBridge/1"

    def log_message(self, format, *args):
        # Do not log URLs/query strings, card identities or authorization data.
        print(f"bridge_http status={args[1] if len(args) > 1 else 'unknown'}", flush=True)

    def _json(self, status: int, payload: object):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        expected = os.environ.get("ROBOT_KB_V4_BRIDGE_TOKEN", "")
        if not expected:
            return False
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[7:], expected)

    def do_GET(self):
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"schema_version": 1, "status": "ok", "read_only": True})
            return
        if parsed.path != "/v1/exact-sold":
            self._json(404, {"error": "not_found"})
            return
        query = parse_qs(parsed.query, keep_blank_values=False)
        tcgdex_card_id = str((query.get("tcgdex_card_id") or [""])[0]).strip()
        grader = str((query.get("grader") or [""])[0]).strip().upper()
        grade = _grade_normalized((query.get("grade") or [""])[0])
        try:
            limit = int((query.get("limit") or ["30"])[0])
        except ValueError:
            limit = 30
        if not tcgdex_card_id or not grader or not grade:
            self._json(400, {"error": "missing_exact_identity"})
            return
        try:
            payload = self.server.database.exact_sold(tcgdex_card_id, grader, grade, limit)
        except Exception as error:
            print(f"bridge_db_error type={type(error).__name__}", flush=True)
            self._json(503, {"error": "database_unavailable"})
            return
        self._json(200, payload)


def main() -> int:
    token = os.environ.get("ROBOT_KB_V4_BRIDGE_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("ROBOT_KB_V4_BRIDGE_TOKEN missing/too short")
    try:
        port = int(os.environ.get("ROBOT_KB_V4_BRIDGE_PORT", str(DEFAULT_PORT)))
    except ValueError:
        port = DEFAULT_PORT
    if not 1024 <= port <= 65535:
        raise SystemExit("invalid bridge port")
    server = ThreadingHTTPServer((HOST, port), Handler)
    server.database = Database()
    print(f"Robot KB V4 read-only bridge listening on {HOST}:{port}", flush=True)
    print("PostgreSQL remains localhost-only; use a separate authenticated HTTPS/private tunnel if remote V4 access is required.", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
