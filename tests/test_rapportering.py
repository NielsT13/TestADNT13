"""Controles op data/moury_rapportering.csv en de gegenereerde migratie."""

import csv
import sys
import unittest
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rapportering_sql  # noqa: E402

with (ROOT / "data" / "moury_rapportering.csv").open(encoding="utf-8") as f:
    ROWS = list(csv.DictReader(f))


def latest(rows):
    """Laatst gepubliceerde waarde per (entiteit, kengetal, periode_start, datum)."""
    out = {}
    for r in sorted(rows, key=lambda r: r["gepubliceerd_op"]):
        out[(r["entiteit"], r["kengetal"], r["periode_start"], r["datum"])] = int(r["waarde_eur"])
    return out


class RapporteringTest(unittest.TestCase):
    def test_migration_in_sync_with_csv(self):
        self.assertEqual(
            rapportering_sql.SQL.read_text(encoding="utf-8"), rapportering_sql.render(),
            "voer 'python scripts/rapportering_sql.py' uit na een wijziging in de CSV",
        )

    def test_fields(self):
        keys = set()
        for r in ROWS:
            self.assertIn(r["kengetal"], ("omzet", "orderboek"))
            self.assertEqual(r["kengetal"] == "omzet", r["periode_start"] != "")
            date.fromisoformat(r["datum"])
            self.assertGreaterEqual(int(r["waarde_eur"]), 0)
            self.assertTrue(r["bron_url"].startswith("https://www.moury-construct.be/"))
            self.assertGreaterEqual(r["gepubliceerd_op"], r["datum"] if r["kengetal"] == "omzet" else "2018")
            k = (r["entiteit"], r["kengetal"], r["periode_start"], r["datum"], r["gepubliceerd_op"])
            self.assertNotIn(k, keys, k)
            keys.add(k)

    def test_subsidiaries_sum_to_group(self):
        akt = latest(ROWS)
        sums = defaultdict(int)
        for (ent, kg, ps, d), v in akt.items():
            if ent != "groep":
                sums[(kg, ps, d)] += v
        for (kg, ps, d), total in sums.items():
            group = akt[("groep", kg, ps, d)]
            self.assertLessEqual(abs(group - total), 1000, (kg, ps, d, group, total))

    def test_half_years_complete(self):
        akt = latest(ROWS)
        for y in range(2018, 2026):
            self.assertIn(("groep", "omzet", f"{y}-01-01", f"{y}-06-30"), akt)
            self.assertIn(("groep", "omzet", f"{y}-01-01", f"{y}-12-31"), akt)


if __name__ == "__main__":
    unittest.main()
