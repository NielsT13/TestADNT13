"""Tests voor analyse/toets_omzet.py op synthetische gegevens."""

import unittest
from datetime import date

from analyse import toets_omzet as t


def synthetic(growths, ted_signal=True):
    """Bouwt rapportering en gunningen waarin TED de groei van de volgende 12 maanden perfect aankondigt."""
    rows, awards = [], []
    level = 100e6
    halves = []
    for y in range(2017, 2017 + len(growths) // 2 + 2):
        for s in (1, 2):
            halves.append((y, s))
    values = {}
    for i, h in enumerate(halves):
        g = growths[i] if i < len(growths) else 0.0
        level *= 1 + g / 2
        values[h] = level
    for y in sorted({h[0] for h in halves}):
        h1, fy = values[(y, 1)], values[(y, 1)] + values[(y, 2)]
        rows.append(dict(kengetal="omzet", periode_start=f"{y}-01-01", datum=f"{y}-06-30", waarde_eur=h1,
                         gepubliceerd_op=f"{y}-09-20"))
        rows.append(dict(kengetal="omzet", periode_start=f"{y}-01-01", datum=f"{y}-12-31", waarde_eur=fy,
                         gepubliceerd_op=f"{y + 1}-03-20"))
        rows.append(dict(kengetal="orderboek", periode_start="", datum=f"{y}-06-30", waarde_eur=150e6,
                         gepubliceerd_op=f"{y}-09-20"))
        rows.append(dict(kengetal="orderboek", periode_start="", datum=f"{y}-12-31", waarde_eur=150e6,
                         gepubliceerd_op=f"{y + 1}-03-20"))
    return rows, awards, values


class ToetsTest(unittest.TestCase):
    def test_no_lookahead_for_awards(self):
        rows, _, _ = synthetic([0.1] * 8)
        rap = t.Rapportering(t.load_rapportering(rows))
        r = rap.release((2019, 1))
        before = t.Award(r, 10e6, False)
        after = t.Award(date(r.year, r.month, r.day + 1), 99e6, False)
        modif = t.Award(r, 50e6, True)
        pts = {p.half: p for p in t.build_points(rap, [before, after, modif])}
        omzet12 = rap.half((2018, 2), r) + rap.half((2019, 1), r)
        self.assertAlmostEqual(pts[(2019, 1)].x_ted, 10e6 / omzet12)

    def test_restated_values_only_after_publication(self):
        rows, _, _ = synthetic([0.0] * 8)
        rows.append(dict(kengetal="omzet", periode_start="2018-01-01", datum="2018-06-30", waarde_eur=1.0,
                         gepubliceerd_op="2019-09-20"))
        rap = t.Rapportering(t.load_rapportering(rows))
        self.assertNotEqual(rap.half((2018, 1), date(2019, 1, 1)), 1.0)
        self.assertEqual(rap.half((2018, 1)), 1.0)

    def test_informative_ted_beats_trend(self):
        growths = [0.05, 0.20, -0.05, 0.15, 0.0, 0.25, 0.10, -0.10, 0.30, 0.05, 0.12, 0.02, 0.18, -0.02,
                   0.22, 0.08, -0.06, 0.14, 0.03, 0.27]
        rows, _, values = synthetic(growths)
        rap = t.Rapportering(t.load_rapportering(rows))
        pts0 = t.build_points(rap, [])
        # TED aangekondigd vlak voor elke publicatie, evenredig met de latere groei
        awards = []
        for p in pts0:
            omzet12 = rap.half(t.shift(p.half, -1), p.datum) + rap.half(p.half, p.datum)
            awards.append(t.Award(p.datum, (1 + 4 * p.groei) * 0.5 * omzet12, False))
        res = t.evaluate(t.predict(t.build_points(rap, awards)))
        self.assertGreater(res["n"], 3)
        self.assertLess(res["modellen"]["ted"]["mae"], res["modellen"]["trend"]["mae"])
        self.assertLess(res["modellen"]["ted"]["mae"], res["modellen"]["geen_groei"]["mae"])

    def test_ols(self):
        a, b = t.ols([[1], [2], [3], [4]], [3, 5, 7, 9])
        self.assertAlmostEqual(a, 1)
        self.assertAlmostEqual(b, 2)

    def test_awards_without_publication_date(self):
        with self.assertRaises(RuntimeError):
            t.load_awards([{"publicatiedatum": None, "bedrag_excl_btw": 1, "notice_type": "can-standard"}])


if __name__ == "__main__":
    unittest.main()
