"""Wegschrijven naar Supabase (PostgREST), schema altdata."""

from __future__ import annotations

import os

import requests

SCHEMA = "altdata"


class Supabase:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        key = key or os.environ["SUPABASE_SERVICE_KEY"]
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
                raise RuntimeError(f"Supabase upsert {r.status_code}: {r.text[:500]}")
