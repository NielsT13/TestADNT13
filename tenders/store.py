"""Wegschrijven naar Supabase (PostgREST), schema altdata."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import requests

SCHEMA = "altdata"


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
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        # Oude service_role-sleutels zijn JWT's (beginnen met "eyJ") en moeten ook als Bearer mee.
        if key.startswith("eyJ"):
            self.headers["Authorization"] = f"Bearer {key}"

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
    "42501": "\nTip: gebruik de service_role- of secret-sleutel, niet de anon/publishable sleutel.",
    "PGRST125": "\nTip: SUPABASE_URL moet de project-URL zijn, bv. https://abcdefgh.supabase.co",
}
