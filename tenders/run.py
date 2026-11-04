"""Gegunde overheidsopdrachten van de groep Moury Construct ophalen uit TED en opslaan in Supabase.

Dagelijks:  python -m tenders.run                       (laatste 7 dagen, overlap is onschuldig)
Backfill:   python -m tenders.run --van 2018-01-01 --tot 2018-12-31
Proefdraai: python -m tenders.run --van 2025-01-01 --dry-run   (schrijft niets weg)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, timedelta

from .store import Supabase
from .ted import Ted

log = logging.getLogger("tenders")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--van", type=date.fromisoformat, help="publicatiedatum vanaf (YYYY-MM-DD)")
    p.add_argument("--tot", type=date.fromisoformat, help="publicatiedatum tot en met (YYYY-MM-DD)")
    p.add_argument("--lookback-dagen", type=int, default=7)
    p.add_argument("--max-minuten", type=float, default=8.0, help="stop netjes voor de job-timeout")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    t0 = time.monotonic()
    end = a.tot or date.today()
    start = a.van or (end - timedelta(days=a.lookback_dagen))
    log.info("venster publicatiedatum %s t/m %s", start, end)

    ted = Ted()
    candidates = ted.search_candidates(start, end)
    log.info("kandidaat-aankondigingen: %d", len(candidates))
    awards, resume_from = ted.collect(candidates, deadline=t0 + a.max_minuten * 60)
    rows = [aw.as_row() for aw in awards]
    log.info("gunningen aan de groep: %d (met bedrag: %d)", len(rows), sum(r["bedrag_excl_btw"] is not None for r in rows))

    if a.dry_run:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    elif rows:
        Supabase().upsert_awards(rows)
        log.info("weggeschreven naar Supabase: %d rijen", len(rows))

    duration = time.monotonic() - t0
    summary = (
        f"venster {start} t/m {end} | kandidaten {len(candidates)} | gunningen {len(rows)} | duur {duration:.1f}s"
    )
    log.info(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"### TED-gunningen Moury Construct\n\n{summary}\n")
            if resume_from:
                f.write(f"\n**Niet volledig:** herstart met van = `{resume_from}`.\n")
    if resume_from:
        log.error("tijdslimiet bereikt; nog niet verwerkt vanaf %s. Start opnieuw met --van %s", resume_from, resume_from)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
