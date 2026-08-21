#!/usr/bin/env python3
"""Read-only local browser for Robot KB PostgreSQL."""

from __future__ import annotations

import html
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

HOST = "127.0.0.1"
DB_HOST = "127.0.0.1"
DB_PORT = 5432
DB_NAME = "robot_pokemon_kb"
DB_USER = "robotpokemon_kb"
PAGE_SIZE = 100
MAX_QUERY_LENGTH = 120
OBSERVATION_TYPES = {
    "SALE_TRANSACTION",
    "LISTING_SNAPSHOT",
    "PROVIDER_METRIC_OBSERVATION",
    "POPULATION_OBSERVATION",
    "FX_RATE_OBSERVATION",
}


def esc(value: object) -> str:
    if value is None:
        return "—"
    return html.escape(str(value))


def short(value: object, limit: int = 420) -> str:
    if value is None:
        return "—"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"[binaire masqué : {len(value)} octets]"
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + "…"
    return html.escape(text)


def money(amount_minor: object, currency: object) -> str:
    if amount_minor is None or currency is None:
        return "—"
    try:
        return f"{int(amount_minor) / 100:.2f} {esc(currency)}"
    except (TypeError, ValueError):
        return f"{esc(amount_minor)} {esc(currency)}"


class Database:
    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "psycopg n'est pas installé dans le runtime local. Relance Installer Robot KB Local.command."
            ) from exc

        password = os.environ.get("ROBOT_KB_VIEWER_PASSWORD", "")
        if not password:
            raise RuntimeError(
                "Mot de passe PostgreSQL local indisponible dans le Trousseau macOS."
            )

        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=password,
            autocommit=True,
            application_name="RobotKBViewer",
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        )
        with conn.cursor() as cur:
            cur.execute("SHOW transaction_read_only")
            row = cur.fetchone()
            if not row or row[0] != "on":
                conn.close()
                raise RuntimeError("La session PostgreSQL du viewer n'est pas en lecture seule.")
        return conn

    @staticmethod
    def _dicts(cur):
        if cur.description is None:
            return []
        columns = [item.name for item in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def health(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            if cur.fetchone() != (1,):
                raise RuntimeError("Health-check PostgreSQL local invalide.")

    def dashboard(self) -> dict[str, int]:
        sql_text = """
            SELECT
                (SELECT COUNT(*) FROM market_observation) AS observations,
                (SELECT COUNT(*) FROM sale_transaction WHERE transaction_status = 'COMPLETED') AS sold,
                (SELECT COUNT(*) FROM listing_snapshot) AS snapshots,
                (SELECT COUNT(*) FROM source_record) AS source_records,
                (SELECT COUNT(*) FROM canonical_card) AS canonical_cards,
                (
                    SELECT COUNT(*)
                    FROM identity_resolution
                    WHERE canonical_card_id IS NULL
                      AND resolution_state IN ('UNKNOWN', 'CONFLICT')
                ) AS unresolved
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql_text)
            row = cur.fetchone()
            keys = (
                "observations",
                "sold",
                "snapshots",
                "source_records",
                "canonical_cards",
                "unresolved",
            )
            return dict(zip(keys, row))

    def recent_sold(self, limit: int = 40) -> list[dict[str, object]]:
        sql_text = """
            SELECT
                mo.id AS observation_id,
                COALESCE(lc.localized_name, subj.subject_label, mo.source_native_record_id) AS card_name,
                cf.collector_number,
                COALESCE(lc.localized_set_name, cs.name) AS set_name,
                lc.language_code,
                cc.id AS canonical_card_id,
                ss.code AS source_code,
                ss.name AS source_name,
                st.sale_occurred_at,
                mo.event_at,
                mo.observed_at,
                pc.amount_minor,
                pc.currency,
                pc.component_type
            FROM sale_transaction st
            JOIN market_observation mo ON mo.id = st.observation_id
            JOIN source_system ss ON ss.id = mo.source_system_id
            LEFT JOIN canonical_card cc ON cc.id = mo.canonical_card_id
            LEFT JOIN localized_card lc ON lc.id = cc.localized_card_id
            LEFT JOIN card_family cf ON cf.id = lc.card_family_id
            LEFT JOIN canonical_set cs ON cs.id = cf.canonical_set_id
            LEFT JOIN LATERAL (
                SELECT s.subject_label
                FROM identity_subject s
                WHERE s.source_record_id = mo.source_record_id
                ORDER BY s.created_at DESC
                LIMIT 1
            ) subj ON TRUE
            LEFT JOIN LATERAL (
                SELECT p.amount_minor, p.currency, p.component_type
                FROM price_component p
                WHERE p.observation_id = mo.id
                  AND p.knowledge_state = 'KNOWN'
                  AND p.amount_minor IS NOT NULL
                ORDER BY CASE p.component_type
                    WHEN 'TOTAL' THEN 1
                    WHEN 'ITEM_PRICE' THEN 2
                    WHEN 'HAMMER_PRICE' THEN 3
                    WHEN 'ACCEPTED_OFFER' THEN 4
                    ELSE 9
                END
                LIMIT 1
            ) pc ON TRUE
            WHERE st.transaction_status = 'COMPLETED'
            ORDER BY COALESCE(st.sale_occurred_at, mo.event_at, mo.observed_at) DESC
            LIMIT %s
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql_text, (max(1, min(limit, 100)),))
            return self._dicts(cur)

    def search_cards(self, query: str) -> list[dict[str, object]]:
        pattern = f"%{query}%"
        sql_text = """
            SELECT
                cc.id AS canonical_card_id,
                lc.localized_name,
                cf.collector_number,
                COALESCE(lc.localized_set_name, cs.name) AS set_name,
                lc.language_code,
                vp.label AS variant_label,
                vp.semantic_key AS variant_key,
                cc.exact_comparison_key,
                COALESCE(stats.observations, 0) AS observations,
                COALESCE(stats.sold_count, 0) AS sold_count,
                stats.latest_observed_at
            FROM canonical_card cc
            JOIN localized_card lc ON lc.id = cc.localized_card_id
            JOIN card_family cf ON cf.id = lc.card_family_id
            JOIN canonical_set cs ON cs.id = cf.canonical_set_id
            JOIN variant_profile vp ON vp.id = cc.variant_profile_id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) AS observations,
                    COUNT(*) FILTER (WHERE mo.observation_type = 'SALE_TRANSACTION') AS sold_count,
                    MAX(mo.observed_at) AS latest_observed_at
                FROM market_observation mo
                WHERE mo.canonical_card_id = cc.id
            ) stats ON TRUE
            WHERE
                lc.localized_name ILIKE %s
                OR cf.family_name ILIKE %s
                OR cf.collector_number ILIKE %s
                OR COALESCE(lc.localized_set_name, '') ILIKE %s
                OR cs.name ILIKE %s
                OR cc.exact_comparison_key ILIKE %s
                OR EXISTS (
                    SELECT 1
                    FROM card_alias a
                    WHERE a.canonical_card_id = cc.id
                      AND a.alias_text ILIKE %s
                )
            ORDER BY sold_count DESC, observations DESC, lc.localized_name ASC
            LIMIT 100
        """
        params = (pattern,) * 7
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql_text, params)
            return self._dicts(cur)

    def search_unresolved(self, query: str) -> list[dict[str, object]]:
        pattern = f"%{query}%"
        sql_text = """
            SELECT
                s.id AS subject_id,
                s.subject_label,
                s.subject_type,
                s.created_at,
                latest.resolution_state,
                latest.unresolved_dimensions_json,
                latest.conflicts_json,
                sr.source_native_record_id,
                ss.code AS source_code
            FROM identity_subject s
            LEFT JOIN LATERAL (
                SELECT
                    ir.resolution_state,
                    ir.canonical_card_id,
                    ir.unresolved_dimensions_json,
                    ir.conflicts_json
                FROM identity_resolution ir
                WHERE ir.identity_subject_id = s.id
                ORDER BY ir.created_at DESC
                LIMIT 1
            ) latest ON TRUE
            LEFT JOIN source_record sr ON sr.id = s.source_record_id
            LEFT JOIN source_system ss ON ss.id = sr.source_system_id
            WHERE latest.canonical_card_id IS NULL
              AND (
                    COALESCE(s.subject_label, '') ILIKE %s
                    OR COALESCE(sr.source_native_record_id, '') ILIKE %s
              )
            ORDER BY s.created_at DESC
            LIMIT 100
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql_text, (pattern, pattern))
            return self._dicts(cur)

    def card_detail(self, card_id: str) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
        identity_sql = """
            SELECT
                cc.id AS canonical_card_id,
                lc.localized_name,
                lc.language_code,
                cf.collector_number,
                cf.family_name,
                cs.name AS canonical_set_name,
                lc.localized_set_name,
                cs.release_date,
                vp.label AS variant_label,
                vp.semantic_key AS variant_key,
                cc.exact_comparison_key,
                cc.created_at
            FROM canonical_card cc
            JOIN localized_card lc ON lc.id = cc.localized_card_id
            JOIN card_family cf ON cf.id = lc.card_family_id
            JOIN canonical_set cs ON cs.id = cf.canonical_set_id
            JOIN variant_profile vp ON vp.id = cc.variant_profile_id
            WHERE cc.id = %s
        """
        obs_sql = """
            SELECT
                mo.id AS observation_id,
                mo.observation_type,
                ss.code AS source_code,
                ss.name AS source_name,
                mo.source_native_record_id,
                mo.event_at,
                mo.observed_at,
                mo.lifecycle_state,
                st.transaction_status,
                st.sale_occurred_at,
                ls.snapshot_status,
                pc.amount_minor,
                pc.currency,
                pc.component_type
            FROM market_observation mo
            JOIN source_system ss ON ss.id = mo.source_system_id
            LEFT JOIN sale_transaction st ON st.observation_id = mo.id
            LEFT JOIN listing_snapshot ls ON ls.observation_id = mo.id
            LEFT JOIN LATERAL (
                SELECT p.amount_minor, p.currency, p.component_type
                FROM price_component p
                WHERE p.observation_id = mo.id
                  AND p.knowledge_state = 'KNOWN'
                  AND p.amount_minor IS NOT NULL
                ORDER BY CASE p.component_type
                    WHEN 'TOTAL' THEN 1
                    WHEN 'ITEM_PRICE' THEN 2
                    WHEN 'HAMMER_PRICE' THEN 3
                    WHEN 'ACCEPTED_OFFER' THEN 4
                    ELSE 9
                END
                LIMIT 1
            ) pc ON TRUE
            WHERE mo.canonical_card_id = %s
            ORDER BY mo.observed_at DESC
            LIMIT 200
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(identity_sql, (card_id,))
            rows = self._dicts(cur)
            identity = rows[0] if rows else None
            if identity is None:
                return None, []
            cur.execute(obs_sql, (card_id,))
            observations = self._dicts(cur)
            return identity, observations

    def observations(
        self, observation_type: str | None, offset: int
    ) -> list[dict[str, object]]:
        params: list[object] = []
        where = ""
        if observation_type:
            where = "WHERE mo.observation_type = %s"
            params.append(observation_type)
        params.extend((PAGE_SIZE, offset))
        sql_text = f"""
            SELECT
                mo.id AS observation_id,
                mo.observation_type,
                COALESCE(lc.localized_name, subj.subject_label, mo.source_native_record_id) AS card_name,
                cf.collector_number,
                COALESCE(lc.localized_set_name, cs.name) AS set_name,
                cc.id AS canonical_card_id,
                ss.code AS source_code,
                mo.event_at,
                mo.observed_at,
                pc.amount_minor,
                pc.currency,
                pc.component_type
            FROM market_observation mo
            JOIN source_system ss ON ss.id = mo.source_system_id
            LEFT JOIN canonical_card cc ON cc.id = mo.canonical_card_id
            LEFT JOIN localized_card lc ON lc.id = cc.localized_card_id
            LEFT JOIN card_family cf ON cf.id = lc.card_family_id
            LEFT JOIN canonical_set cs ON cs.id = cf.canonical_set_id
            LEFT JOIN LATERAL (
                SELECT s.subject_label
                FROM identity_subject s
                WHERE s.source_record_id = mo.source_record_id
                ORDER BY s.created_at DESC
                LIMIT 1
            ) subj ON TRUE
            LEFT JOIN LATERAL (
                SELECT p.amount_minor, p.currency, p.component_type
                FROM price_component p
                WHERE p.observation_id = mo.id
                  AND p.knowledge_state = 'KNOWN'
                  AND p.amount_minor IS NOT NULL
                ORDER BY CASE p.component_type
                    WHEN 'TOTAL' THEN 1
                    WHEN 'ITEM_PRICE' THEN 2
                    WHEN 'HAMMER_PRICE' THEN 3
                    WHEN 'ACCEPTED_OFFER' THEN 4
                    ELSE 9
                END
                LIMIT 1
            ) pc ON TRUE
            {where}
            ORDER BY mo.observed_at DESC
            LIMIT %s OFFSET %s
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql_text, tuple(params))
            return self._dicts(cur)

    def table_list(self) -> list[dict[str, object]]:
        sql_text = """
            SELECT
                c.relname AS table_name,
                COALESCE(s.n_live_tup, 0)::bigint AS estimated_rows
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
            ORDER BY c.relname
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql_text)
            return self._dicts(cur)

    def browse_table(
        self, table_name: str, offset: int
    ) -> tuple[list[str], list[dict[str, object]]]:
        try:
            from psycopg import sql
        except ImportError as exc:
            raise RuntimeError("psycopg indisponible.") from exc

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            columns = [row[0] for row in cur.fetchall()]
            if not columns:
                raise ValueError("Table inconnue.")

            visible_columns = [name for name in columns if name != "payload_bytes"]
            order_column = (
                "observed_at"
                if "observed_at" in columns
                else "created_at"
                if "created_at" in columns
                else columns[0]
            )
            query = sql.SQL("SELECT {} FROM {} ORDER BY {} DESC LIMIT %s OFFSET %s").format(
                sql.SQL(", ").join(sql.Identifier(name) for name in visible_columns),
                sql.Identifier(table_name),
                sql.Identifier(order_column),
            )
            cur.execute(query, (PAGE_SIZE, offset))
            return visible_columns, self._dicts(cur)


def layout(title: str, body: str, query: str = "") -> str:
    q = html.escape(query)
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store">
<title>{html.escape(title)} · Robot KB</title>
<style>
:root {{
  color-scheme: light dark;
  --bg:#f4f6f8; --panel:#fff; --text:#18212f; --muted:#657184;
  --line:#dfe4ea; --accent:#315efb; --good:#127a4d; --warn:#9a5b00;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#101318; --panel:#171b22; --text:#edf2f7; --muted:#9aa6b5;
  --line:#2a313c; --accent:#7da2ff; --good:#5ed39b; --warn:#f5b94c; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       background:var(--bg); color:var(--text); }}
header {{ position:sticky; top:0; z-index:5; background:color-mix(in srgb,var(--panel) 94%,transparent);
          backdrop-filter:blur(14px); border-bottom:1px solid var(--line); }}
.wrap {{ max-width:1380px; margin:auto; padding:18px 22px; }}
.headrow {{ display:flex; gap:18px; align-items:center; flex-wrap:wrap; }}
.brand {{ font-weight:800; font-size:18px; }}
nav a {{ color:var(--muted); text-decoration:none; margin-right:14px; font-weight:600; }}
nav a:hover {{ color:var(--accent); }}
.search {{ margin-left:auto; display:flex; gap:8px; min-width:min(480px,100%); flex:1; max-width:620px; }}
input {{ width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:10px;
         background:var(--panel); color:var(--text); }}
button,.button {{ border:0; border-radius:10px; padding:10px 14px; background:var(--accent);
                  color:white; font-weight:700; text-decoration:none; cursor:pointer; }}
main.wrap {{ padding-top:24px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(175px,1fr)); gap:12px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:16px; }}
.metric {{ font-size:26px; font-weight:800; margin-top:4px; }}
.muted {{ color:var(--muted); }}
.good {{ color:var(--good); font-weight:700; }}
.warn {{ color:var(--warn); font-weight:700; }}
h1 {{ font-size:24px; margin:0 0 18px; }}
h2 {{ font-size:18px; margin:28px 0 12px; }}
table {{ width:100%; border-collapse:separate; border-spacing:0; background:var(--panel);
         border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
th,td {{ padding:9px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }}
tr:last-child td {{ border-bottom:0; }}
td a {{ color:var(--accent); text-decoration:none; font-weight:650; }}
code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
.pills {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; }}
.pill {{ padding:6px 9px; border:1px solid var(--line); border-radius:999px; color:var(--muted); text-decoration:none; }}
.pill:hover {{ border-color:var(--accent); color:var(--accent); }}
.pager {{ display:flex; gap:10px; margin:16px 0; }}
.notice {{ border-left:4px solid var(--good); padding:10px 14px; background:var(--panel); border-radius:8px; }}
.error {{ border-left-color:#c43b3b; }}
@media (max-width:760px) {{
  .wrap {{ padding-left:12px; padding-right:12px; }}
  .search {{ order:3; max-width:none; min-width:100%; }}
  table {{ display:block; overflow:auto; white-space:nowrap; }}
}}
</style>
</head>
<body>
<header>
  <div class="wrap headrow">
    <div class="brand">Robot KB</div>
    <nav>
      <a href="/">Accueil</a>
      <a href="/observations">Observations</a>
      <a href="/tables">Tables</a>
    </nav>
    <form class="search" action="/search" method="get">
      <input name="q" value="{q}" maxlength="{MAX_QUERY_LENGTH}" placeholder="Pikachu, 25/102, Base Set…">
      <button type="submit">Rechercher</button>
    </form>
  </div>
</header>
<main class="wrap">{body}</main>
</body></html>"""


def render_sold(rows: list[dict[str, object]]) -> str:
    if not rows:
        return '<div class="card muted">Aucune vente SOLD finale trouvée.</div>'
    parts = [
        "<table><thead><tr><th>Carte</th><th>Set / N°</th><th>Prix</th><th>Source</th><th>Date</th></tr></thead><tbody>"
    ]
    for row in rows:
        name = esc(row["card_name"])
        if row.get("canonical_card_id"):
            name = f'<a href="/card?id={quote(str(row["canonical_card_id"]))}">{name}</a>'
        parts.append(
            "<tr>"
            f"<td>{name}</td>"
            f"<td>{esc(row.get('set_name'))}<br><span class='muted'>{esc(row.get('collector_number'))} · {esc(row.get('language_code'))}</span></td>"
            f"<td><strong>{money(row.get('amount_minor'), row.get('currency'))}</strong><br><span class='muted'>{esc(row.get('component_type'))}</span></td>"
            f"<td>{esc(row.get('source_code'))}</td>"
            f"<td>{esc(row.get('sale_occurred_at') or row.get('event_at') or row.get('observed_at'))}</td>"
            "</tr>"
        )
    parts.append("</tbody></table>")
    return "".join(parts)


def render_home(db: Database) -> str:
    stats = db.dashboard()
    sold = db.recent_sold()
    labels = [
        ("Observations", stats["observations"]),
        ("SOLD finaux", stats["sold"]),
        ("Snapshots", stats["snapshots"]),
        ("Records source", stats["source_records"]),
        ("Cartes canoniques", stats["canonical_cards"]),
        ("Résolutions non liées", stats["unresolved"]),
    ]
    metrics = "".join(
        f'<div class="card"><div class="muted">{esc(label)}</div><div class="metric">{value:,}</div></div>'
        for label, value in labels
    )
    body = (
        "<h1>Robot KB local</h1>"
        '<div class="notice">Lecture seule · PostgreSQL local 127.0.0.1 · aucune donnée n’est modifiée.</div>'
        f'<div class="grid" style="margin-top:14px">{metrics}</div>'
        "<h2>Dernières ventes SOLD prouvées</h2>"
        + render_sold(sold)
    )
    return layout("Accueil", body)


def render_search(db: Database, query: str) -> str:
    query = query.strip()[:MAX_QUERY_LENGTH]
    if not query:
        return layout(
            "Recherche",
            '<h1>Recherche</h1><div class="card muted">Entre un nom de carte, un numéro ou un set.</div>',
        )
    cards = db.search_cards(query)
    unresolved = db.search_unresolved(query)
    parts = [f"<h1>Résultats pour « {esc(query)} »</h1>"]
    parts.append(f"<h2>Cartes canoniques ({len(cards)})</h2>")
    if cards:
        parts.append(
            "<table><thead><tr><th>Carte</th><th>Set / N°</th><th>Langue</th><th>Variante</th><th>Obs.</th><th>SOLD</th><th>Dernière obs.</th></tr></thead><tbody>"
        )
        for row in cards:
            parts.append(
                "<tr>"
                f'<td><a href="/card?id={quote(str(row["canonical_card_id"]))}">{esc(row["localized_name"])}</a></td>'
                f"<td>{esc(row['set_name'])}<br><span class='muted'>{esc(row['collector_number'])}</span></td>"
                f"<td>{esc(row['language_code'])}</td>"
                f"<td>{esc(row['variant_label'] or row['variant_key'])}</td>"
                f"<td>{esc(row['observations'])}</td>"
                f"<td>{esc(row['sold_count'])}</td>"
                f"<td>{esc(row['latest_observed_at'])}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append('<div class="card muted">Aucune carte canonique correspondante.</div>')

    parts.append(f"<h2>Identités brutes / non résolues ({len(unresolved)})</h2>")
    if unresolved:
        parts.append(
            "<table><thead><tr><th>Libellé</th><th>Statut</th><th>Source</th><th>Record</th><th>Dimensions non résolues</th><th>Créé</th></tr></thead><tbody>"
        )
        for row in unresolved:
            state = row.get("resolution_state") or "UNKNOWN"
            cls = "warn" if state in {"UNKNOWN", "CONFLICT"} else ""
            parts.append(
                "<tr>"
                f"<td>{esc(row.get('subject_label'))}</td>"
                f"<td class='{cls}'>{esc(state)}</td>"
                f"<td>{esc(row.get('source_code'))}</td>"
                f"<td><code>{short(row.get('source_native_record_id'), 100)}</code></td>"
                f"<td><code>{short(row.get('unresolved_dimensions_json'), 180)}</code></td>"
                f"<td>{esc(row.get('created_at'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append('<div class="card muted">Aucune identité non résolue correspondante.</div>')
    return layout("Recherche", "".join(parts), query)


def render_card(db: Database, card_id: str) -> str:
    identity, observations = db.card_detail(card_id)
    if identity is None:
        return layout("Carte introuvable", '<h1>Carte introuvable</h1><div class="card">ID inconnu.</div>')
    info = (
        '<div class="grid">'
        f'<div class="card"><div class="muted">Carte</div><div class="metric" style="font-size:20px">{esc(identity["localized_name"])}</div></div>'
        f'<div class="card"><div class="muted">Set</div><strong>{esc(identity["localized_set_name"] or identity["canonical_set_name"])}</strong><br>{esc(identity["collector_number"])}</div>'
        f'<div class="card"><div class="muted">Langue</div><strong>{esc(identity["language_code"])}</strong></div>'
        f'<div class="card"><div class="muted">Variante</div><strong>{esc(identity["variant_label"] or identity["variant_key"])}</strong></div>'
        "</div>"
        f'<div class="card" style="margin-top:12px"><div class="muted">Exact comparison key</div><code>{short(identity["exact_comparison_key"], 800)}</code></div>'
    )
    parts = [f"<h1>{esc(identity['localized_name'])}</h1>", info, f"<h2>Observations récentes ({len(observations)})</h2>"]
    if observations:
        parts.append(
            "<table><thead><tr><th>Type</th><th>Prix</th><th>Source</th><th>Statut</th><th>Événement</th><th>Observé</th></tr></thead><tbody>"
        )
        for row in observations:
            status = row.get("transaction_status") or row.get("snapshot_status") or row.get("lifecycle_state")
            parts.append(
                "<tr>"
                f"<td>{esc(row['observation_type'])}</td>"
                f"<td>{money(row.get('amount_minor'), row.get('currency'))}<br><span class='muted'>{esc(row.get('component_type'))}</span></td>"
                f"<td>{esc(row.get('source_code'))}</td>"
                f"<td>{esc(status)}</td>"
                f"<td>{esc(row.get('sale_occurred_at') or row.get('event_at'))}</td>"
                f"<td>{esc(row.get('observed_at'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append('<div class="card muted">Aucune observation liée à cette carte.</div>')
    return layout(str(identity["localized_name"]), "".join(parts))


def render_observations(db: Database, observation_type: str | None, offset: int) -> str:
    rows = db.observations(observation_type, offset)
    pills = ['<a class="pill" href="/observations">Toutes</a>']
    for value in sorted(OBSERVATION_TYPES):
        pills.append(f'<a class="pill" href="/observations?type={quote(value)}">{esc(value)}</a>')
    parts = ["<h1>Observations</h1>", '<div class="pills">', "".join(pills), "</div>"]
    if rows:
        parts.append(
            "<table><thead><tr><th>Type</th><th>Carte</th><th>Set / N°</th><th>Prix</th><th>Source</th><th>Observé</th></tr></thead><tbody>"
        )
        for row in rows:
            name = esc(row.get("card_name"))
            if row.get("canonical_card_id"):
                name = f'<a href="/card?id={quote(str(row["canonical_card_id"]))}">{name}</a>'
            parts.append(
                "<tr>"
                f"<td>{esc(row['observation_type'])}</td>"
                f"<td>{name}</td>"
                f"<td>{esc(row.get('set_name'))}<br><span class='muted'>{esc(row.get('collector_number'))}</span></td>"
                f"<td>{money(row.get('amount_minor'), row.get('currency'))}</td>"
                f"<td>{esc(row.get('source_code'))}</td>"
                f"<td>{esc(row.get('observed_at'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append('<div class="card muted">Aucune observation sur cette page.</div>')
    prev_offset = max(0, offset - PAGE_SIZE)
    next_offset = offset + PAGE_SIZE
    type_param = f"&type={quote(observation_type)}" if observation_type else ""
    pager = ['<div class="pager">']
    if offset:
        pager.append(f'<a class="button" href="/observations?offset={prev_offset}{type_param}">← Précédent</a>')
    if len(rows) == PAGE_SIZE:
        pager.append(f'<a class="button" href="/observations?offset={next_offset}{type_param}">Suivant →</a>')
    pager.append("</div>")
    parts.append("".join(pager))
    return layout("Observations", "".join(parts))


def render_tables(db: Database) -> str:
    rows = db.table_list()
    parts = [
        "<h1>Tables PostgreSQL</h1>",
        '<div class="notice">Les compteurs de cette page sont des estimations PostgreSQL. Le viewer masque <code>payload_bytes</code> et reste en lecture seule.</div>',
        "<table style='margin-top:14px'><thead><tr><th>Table</th><th>Lignes estimées</th><th></th></tr></thead><tbody>",
    ]
    for row in rows:
        name = str(row["table_name"])
        parts.append(
            "<tr>"
            f"<td><code>{esc(name)}</code></td>"
            f"<td>{int(row['estimated_rows']):,}</td>"
            f'<td><a href="/table?name={quote(name)}">Parcourir</a></td>'
            "</tr>"
        )
    parts.append("</tbody></table>")
    return layout("Tables", "".join(parts))


def render_table(db: Database, table_name: str, offset: int) -> str:
    columns, rows = db.browse_table(table_name, offset)
    parts = [
        f"<h1>Table <code>{esc(table_name)}</code></h1>",
        '<div class="notice">100 lignes maximum par page · lecture seule · les octets bruts ne sont jamais affichés.</div>',
    ]
    if rows:
        parts.append("<table style='margin-top:14px'><thead><tr>")
        for column in columns:
            parts.append(f"<th>{esc(column)}</th>")
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>")
            for column in columns:
                parts.append(f"<td>{short(row.get(column))}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
    else:
        parts.append('<div class="card muted" style="margin-top:14px">Aucune ligne sur cette page.</div>')

    pager = ['<div class="pager">']
    if offset:
        pager.append(
            f'<a class="button" href="/table?name={quote(table_name)}&offset={max(0, offset-PAGE_SIZE)}">← Précédent</a>'
        )
    if len(rows) == PAGE_SIZE:
        pager.append(
            f'<a class="button" href="/table?name={quote(table_name)}&offset={offset+PAGE_SIZE}">Suivant →</a>'
        )
    pager.append("</div>")
    parts.append("".join(pager))
    return layout(f"Table {table_name}", "".join(parts))


class ViewerHandler(BaseHTTPRequestHandler):
    db: Database

    def _send(self, payload: str, status: int = 200) -> None:
        data = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _offset(params: dict[str, list[str]]) -> int:
        try:
            return max(0, min(int(params.get("offset", ["0"])[0]), 1_000_000))
        except (TypeError, ValueError):
            return 0

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path == "/":
                page = render_home(self.db)
            elif parsed.path == "/search":
                page = render_search(self.db, params.get("q", [""])[0])
            elif parsed.path == "/card":
                page = render_card(self.db, params.get("id", [""])[0])
            elif parsed.path == "/observations":
                requested = params.get("type", [""])[0]
                observation_type = requested if requested in OBSERVATION_TYPES else None
                page = render_observations(self.db, observation_type, self._offset(params))
            elif parsed.path == "/tables":
                page = render_tables(self.db)
            elif parsed.path == "/table":
                table_name = params.get("name", [""])[0][:100]
                page = render_table(self.db, table_name, self._offset(params))
            else:
                self._send(layout("Introuvable", "<h1>Page introuvable</h1>"), status=404)
                return
            self._send(page)
        except Exception as exc:
            password = os.environ.get("ROBOT_KB_VIEWER_PASSWORD", "")
            message = str(exc)
            if password:
                message = message.replace(password, "[SECRET]")
            print(f"Viewer Robot KB: {type(exc).__name__}: {message}", flush=True)
            self._send(
                layout(
                    "Erreur",
                    '<h1>Lecture impossible</h1><div class="notice error">'
                    "Le viewer n’a rien modifié. Regarde la fenêtre Terminal pour le diagnostic."
                    "</div>",
                ),
                status=500,
            )

    def log_message(self, _format: str, *args: object) -> None:
        return


def main() -> int:
    db = Database()
    db.health()

    ViewerHandler.db = db
    server = ThreadingHTTPServer((HOST, 0), ViewerHandler)
    url = f"http://{HOST}:{server.server_port}/"
    print("Robot KB Viewer — LECTURE SEULE", flush=True)
    print(f"Ouverture de {url}", flush=True)
    print("Ferme cette fenêtre Terminal ou fais Ctrl+C pour arrêter le viewer.", flush=True)

    threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
