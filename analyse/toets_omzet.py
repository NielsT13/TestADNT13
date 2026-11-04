"""Toets: voorspelt TED de omzet van Moury Construct beter dan eenvoudige alternatieven?

Opzet (zonder vooruit te kijken):
- Voorspelmoment = de dag waarop Moury de omzet van halfjaar t publiceert (maart of september).
- Doel = omzetgroei over de volgende 12 maanden: (H[t+1] + H[t+2]) / (H[t-1] + H[t]) - 1.
- Op het voorspelmoment gebruiken we enkel wat toen gepubliceerd was:
    * omzet en orderboek zoals toen bekend (herwerkte cijfers pas vanaf hun publicatie);
    * TED-gunningen met publicatiedatum in de 12 maanden vóór het voorspelmoment.
- Modellen worden telkens opnieuw geschat op de voorspellingen waarvan de uitkomst op dat
  moment al bekend was (expanding window), en daarna geëvalueerd op de volgende voorspelling.

Modellen:
    geen_groei      groei = 0
    trend           groei = gemiddelde van de tot dan gekende groeicijfers
    orderboek       groei = a + b * (orderboek / omzet laatste 12 maanden)
    ted             groei = a + b * (TED-bedrag laatste 12 maanden / omzet laatste 12 maanden)
    orderboek_ted   beide verklarende variabelen samen

Gebruik:
    python -m analyse.toets_omzet                         # leest uit Supabase (SUPABASE_URL/_SERVICE_KEY)
    python -m analyse.toets_omzet --csv data/moury_rapportering.csv --awards awards.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta

MIN_TRAIN = {"orderboek": 4, "ted": 4, "orderboek_ted": 6}
MODELS = ["geen_groei", "trend", "orderboek", "ted", "orderboek_ted"]


# ---------- gegevens ----------
@dataclass
class Obs:
    kengetal: str
    periode_start: date | None
    datum: date
    waarde: float
    gepubliceerd_op: date


@dataclass
class Award:
    publicatiedatum: date
    bedrag: float
    wijziging: bool


def _d(s) -> date | None:
    return date.fromisoformat(str(s)[:10]) if s else None


def load_rapportering(rows: list[dict]) -> list[Obs]:
    return [
        Obs(r["kengetal"], _d(r["periode_start"]), _d(r["datum"]), float(r["waarde_eur"]), _d(r["gepubliceerd_op"]))
        for r in rows
        if r.get("entiteit", "groep") == "groep"
    ]


def load_awards(rows: list[dict]) -> list[Award]:
    out = []
    missing = 0
    for r in rows:
        if not r.get("publicatiedatum"):
            missing += 1
            continue
        out.append(Award(_d(r["publicatiedatum"]), float(r.get("bedrag_excl_btw") or 0),
                         "modif" in (r.get("notice_type") or "")))
    if rows and missing == len(rows):
        raise RuntimeError("Geen enkele gunning heeft een publicatiedatum: voer migratie 003 uit en draai de backfill opnieuw.")
    return out


# ---------- halfjaren ----------
Half = tuple[int, int]  # (jaar, 1 of 2)


def shift(h: Half, n: int) -> Half:
    i = h[0] * 2 + (h[1] - 1) + n
    return (i // 2, i % 2 + 1)


class Rapportering:
    def __init__(self, obs: list[Obs]):
        self.omzet = [o for o in obs if o.kengetal == "omzet"]
        self.orderboek = sorted((o for o in obs if o.kengetal == "orderboek"), key=lambda o: (o.gepubliceerd_op, o.datum))

    def _rows(self, start: date, end: date, asof: date | None):
        rows = [o for o in self.omzet if o.periode_start == start and o.datum == end
                and (asof is None or o.gepubliceerd_op <= asof)]
        return sorted(rows, key=lambda o: o.gepubliceerd_op)

    def _value(self, start: date, end: date, asof: date | None) -> float | None:
        rows = self._rows(start, end, asof)
        return rows[-1].waarde if rows else None

    def half(self, h: Half, asof: date | None = None) -> float | None:
        """Omzet van halfjaar h zoals bekend op `asof` (None = laatste publicatie)."""
        y, s = h
        h1 = self._value(date(y, 1, 1), date(y, 6, 30), asof)
        if s == 1:
            return h1
        fy = self._value(date(y, 1, 1), date(y, 12, 31), asof)
        return fy - h1 if fy is not None and h1 is not None else None

    def release(self, h: Half) -> date | None:
        """Eerste publicatie van de omzet van halfjaar h (H2 = jaarcijfer)."""
        y, s = h
        end = date(y, 6, 30) if s == 1 else date(y, 12, 31)
        rows = self._rows(date(y, 1, 1), end, None)
        return rows[0].gepubliceerd_op if rows else None

    def orderboek_asof(self, asof: date) -> float | None:
        known = [o for o in self.orderboek if o.gepubliceerd_op <= asof]
        if not known:
            return None
        latest_date = max(o.datum for o in known)
        return max((o for o in known if o.datum == latest_date), key=lambda o: o.gepubliceerd_op).waarde


@dataclass
class Point:
    half: Half
    datum: date            # voorspelmoment
    doel_bekend_op: date
    x_orderboek: float
    x_ted: float
    groei: float           # werkelijke groei (laatste cijfers)
    voorspelling: dict = field(default_factory=dict)


def build_points(rap: Rapportering, awards: list[Award]) -> list[Point]:
    halves = sorted({(o.periode_start.year, 1 if o.datum.month == 6 else 2) for o in rap.omzet})
    points = []
    for h in halves:
        r = rap.release(h)
        r2 = rap.release(shift(h, 2))
        if not r or not r2:
            continue
        now = [rap.half(shift(h, -1), r), rap.half(h, r)]
        truth_prev = [rap.half(shift(h, -1)), rap.half(h)]
        truth_next = [rap.half(shift(h, 1)), rap.half(shift(h, 2))]
        ob = rap.orderboek_asof(r)
        if None in now + truth_prev + truth_next or ob is None:
            continue
        omzet12 = sum(now)
        ted = sum(a.bedrag for a in awards if not a.wijziging and r - timedelta(days=365) < a.publicatiedatum <= r)
        points.append(Point(h, r, r2, ob / omzet12, ted / omzet12, sum(truth_next) / sum(truth_prev) - 1))
    return points


# ---------- modellen ----------
def ols(xs: list[list[float]], ys: list[float]) -> list[float]:
    """Kleinste kwadraten met intercept; xs = lijst van rijen. Geeft [a, b1, b2, ...]."""
    k = len(xs[0])
    n = len(ys)
    mx = [sum(r[j] for r in xs) / n for j in range(k)]
    my = sum(ys) / n
    xc = [[r[j] - mx[j] for j in range(k)] for r in xs]
    yc = [y - my for y in ys]
    A = [[sum(r[i] * r[j] for r in xc) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * y for r, y in zip(xc, yc)) for i in range(k)]
    beta = _solve(A, b)
    return [my - sum(bj * mj for bj, mj in zip(beta, mx))] + beta


def _solve(A, b):
    n = len(b)
    M = [row[:] + [bi] for row, bi in zip(A, b)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            raise ValueError("singuliere matrix")
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [a - f * bb for a, bb in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


def features(p: Point, model: str) -> list[float]:
    return {"orderboek": [p.x_orderboek], "ted": [p.x_ted], "orderboek_ted": [p.x_orderboek, p.x_ted]}[model]


def predict(points: list[Point]) -> list[Point]:
    for p in points:
        train = [q for q in points if q.doel_bekend_op <= p.datum]
        p.voorspelling["geen_groei"] = 0.0
        p.voorspelling["trend"] = sum(q.groei for q in train) / len(train) if train else None
        for m in ("orderboek", "ted", "orderboek_ted"):
            if len(train) < MIN_TRAIN[m]:
                p.voorspelling[m] = None
                continue
            try:
                coef = ols([features(q, m) for q in train], [q.groei for q in train])
            except ValueError:
                p.voorspelling[m] = None
                continue
            p.voorspelling[m] = coef[0] + sum(c * x for c, x in zip(coef[1:], features(p, m)))
    return points


def evaluate(points: list[Point]) -> dict:
    """Vergelijk de modellen op de voorspellingen waar ze allemaal een waarde hebben."""
    common = [p for p in points if all(p.voorspelling.get(m) is not None for m in MODELS)]
    res = {"n": len(common), "modellen": {}}
    for m in MODELS:
        err = [p.voorspelling[m] - p.groei for p in common]
        if not err:
            continue
        res["modellen"][m] = {
            "mae": sum(abs(e) for e in err) / len(err),
            "rmse": math.sqrt(sum(e * e for e in err) / len(err)),
            "beter_dan_trend": sum(abs(p.voorspelling[m] - p.groei) < abs(p.voorspelling["trend"] - p.groei)
                                   for p in common),
        }
    return res


# ---------- rapport ----------
def pct(v: float | None) -> str:
    return "–" if v is None else f"{v * 100:+.1f}%"


def report(points: list[Point], res: dict) -> str:
    lines = ["## Toets: voorspelt TED de omzetgroei van Moury Construct?", ""]
    lines.append(f"Voorspellingen die alle modellen konden maken: **{res['n']}**. "
                 "Doel: omzetgroei over de volgende 12 maanden, voorspeld op de dag van het halfjaar- of jaarbericht.")
    lines += ["", "| Model | Gem. absolute fout | RMSE | Beter dan trend |", "|---|---|---|---|"]
    for m, r in res["modellen"].items():
        btd = "–" if m == "trend" else f"{r['beter_dan_trend']} van {res['n']}"
        lines.append(f"| {m} | {r['mae'] * 100:.1f} %-punt | {r['rmse'] * 100:.1f} %-punt | {btd} |")
    lines += ["", "### Per voorspelling", "",
              "| Halfjaar | Voorspeld op | Orderboek/omzet | TED/omzet | Werkelijk | " + " | ".join(MODELS) + " |",
              "|---|---|---|---|---|" + "---|" * len(MODELS)]
    for p in points:
        lines.append(f"| {p.half[0]}-H{p.half[1]} | {p.datum} | {p.x_orderboek:.2f} | {p.x_ted:.2f} | {pct(p.groei)} | "
                     + " | ".join(pct(p.voorspelling.get(m)) for m in MODELS) + " |")
    lines += ["", "_Kleine steekproef met overlappende periodes: lees dit als een indicatie, niet als bewijs._", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="rapportering als CSV (standaard: uit Supabase)")
    ap.add_argument("--awards", help="gunningen als JSON-lines (standaard: uit Supabase)")
    a = ap.parse_args(argv)

    if a.csv and a.awards:
        with open(a.csv, encoding="utf-8") as f:
            rap_rows = list(csv.DictReader(f))
        with open(a.awards, encoding="utf-8") as f:
            award_rows = [json.loads(l) for l in f if l.strip()]
    else:
        from tenders.store import Supabase
        sb = Supabase()
        rap_rows = sb.select("moury_rapportering", {
            "select": "entiteit,kengetal,periode_start,datum,waarde_eur,gepubliceerd_op", "entiteit": "eq.groep"})
        award_rows = sb.select("awards", {"select": "publicatiedatum,bedrag_excl_btw,notice_type"})

    points = predict(build_points(Rapportering(load_rapportering(rap_rows)), load_awards(award_rows)))
    res = evaluate(points)
    text = report(points, res)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
