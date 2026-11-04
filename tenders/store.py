"""Wegschrijven naar Supabase (PostgREST), schema altdata."""

from __future__ import annotations

import base64
import json
import logging
import os
from urllib.parse import urlparse

import requests

SCHEMA = "altdata"
log = logging.getLogger(__name__)


def key_role(key: str) -> str:
    """Welk soort sleutel is dit? Geeft 'service_role', 'secret', 'anon', 'publishable' of 'onbekend'.

    Leest enkel de publieke 'role'-claim van een JWT; de sleutel zelf wordt nooit gelogd.
    """
    if key.startswith("sb_secret_"):
        return "secret"
    if key.startswith("sb_publishable_"):
        return "publishable"
    if key.startswith("eyJ") and key.count(".") == 2:
        payload = key.split(".")[1]
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return str(claims.get("role", "onbekend"))
        except (ValueError, json.JSONDecodeError):
            return "onbekend"
    return "onbekend"


def normalize_base_url(raw: str) -> str:
    """Aanvaardt 'https://x.supabase.co', met of zonder '/' of '/rest/v1' erachter."""
    parsed = urlparse(raw.strip())
    path = parsed.path.rstrip("/")
    if path in ("", "/rest/v1"):
        return f"{parsed.scheme}://{parsed.netloc}"
    raise ValueError(
        f"SUPABASE_URL heeft een onverwacht pad '{parsed.path}'. "
        "Gebruik enkel de project-URL, bv. https://abcdefgh.supabase.co"
    )


class Supabase:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = normalize_base_url(url or os.environ["SUPABASE_URL"])
        key = (key or os.environ["SUPABASE_SERVICE_KEY"]).strip()
        role = key_role(key)
        log.info("Supabase %s, sleuteltype: %s", urlparse(self.url).netloc, role)
        if role in ("anon", "publishable", "authenticated"):
            raise ValueError(
                f"SUPABASE_SERVICE_KEY is een {role}-sleutel. Gebruik de service_role-sleutel "
                "(Project Settings → API Keys → Legacy API keys) of een secret key (sb_secret_…)."
            )
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        # Oude service_role-sleutels zijn JWT's (beginnen met "eyJ") en moeten ook als Bearer mee.
        if key.startswith("eyJ"):
            self.headers["Authorization"] = f"Bearer {key}"

    def select(self, table: str, params: dict) -> list[dict]:
        """Leest een tabel of view uit schema altdata (alle rijen, per 1000)."""
        out: list[dict] = []
        while True:
            r = requests.get(
                f"{self.url}/rest/v1/{table}",
                params=params,
                headers={**self.headers, "Accept-Profile": SCHEMA, "Range": f"{len(out)}-{len(out) + 999}"},
                timeout=60,
            )
            if r.status_code >= 300:
                hint = next((h for code, h in HINTS.items() if code in r.text), "")
                raise RuntimeError(f"Supabase select {table} {r.status_code}: {r.text[:500]}{hint}")
            page = r.json()
            out += page
            if len(page) < 1000:
                return out

    def upsert_awards(self, rows: list[dict], batch: int = 500) -> None:
        for i in range(0, len(rows), batch):
            r = requests.post(
                f"{self.url}/rest/v1/awards",
                params={"on_conflict": "bron,bron_id"},
                headers={
                    **self.headers,
                    "Content-Profile": SCHEMA,
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
                json=rows[i : i + batch],
                timeout=60,
            )
            if r.status_code >= 300:
                hint = next((h for code, h in HINTS.items() if code in r.text), "")
                raise RuntimeError(f"Supabase upsert {r.status_code}: {r.text[:500]}{hint}")


HINTS = {
    "PGRST106": "\nTip: voeg 'altdata' toe bij Project Settings → Data API → Exposed schemas.",
    "PGRST205": "\nTip: voer supabase/migrations/001_altdata_awards.sql uit in de SQL Editor.",
    "42501": "\nTip: voer supabase/migrations/001_altdata_awards.sql (opnieuw) volledig uit in de SQL Editor;"
             " de grant-regels geven service_role toegang tot het schema.",
    "PGRST204": "\nTip: voer de ontbrekende migratie uit (bv. supabase/migrations/003_awards_publicatiedatum.sql).",
    "PGRST125": "\nTip: SUPABASE_URL moet de project-URL zijn, bv. https://abcdefgh.supabase.co",
}
