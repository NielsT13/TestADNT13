"""TED (Tenders Electronic Daily): kandidaten zoeken via de Search API, volledige XML uit de dagpakketten.

Officiële, open bronnen zonder authenticatie:
- Search API: https://docs.ted.europa.eu/api/latest/search.html
- Dagpakketten: https://ted.europa.eu/packages/daily/{jaar}{OJ S-nummer, 5 cijfers}
"""

from __future__ import annotations

import io
import logging
import re
import tarfile
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date

import requests

from . import config

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
PACKAGE_URL = "https://ted.europa.eu/packages/daily/{}"
NOTICE_URL = "https://ted.europa.eu/nl/notice/-/detail/{}"
USER_AGENT = "altdata-research/0.1 (python-requests)"
API_DELAY_S = 1.0
PACKAGE_DELAY_S = 2.0


@dataclass
class Candidate:
    publication_number: str  # bv. "741513-2023"
    publication_date: str
    notice_type: str
    ojs_number: str  # bv. "236/2023"

    @property
    def package_id(self) -> str:
        num, year = self.ojs_number.split("/")
        return f"{year}{int(num):05d}"


@dataclass
class Award:
    bron: str
    bron_id: str
    datum_gunning: str | None
    opdrachtgever: str | None
    winnaar: str
    ondernemingsnummer: str | None
    bedrag_excl_btw: float | None
    looptijd_maanden: float | None
    url: str
    is_combinatie: bool
    notice_type: str
    publicatiedatum: str | None = None  # publicatie in TED; nodig om niet vooruit te kijken

    def as_row(self) -> dict:
        return asdict(self)


class Ted:
    def __init__(self, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self._last = 0.0

    def _wait(self, delay: float) -> None:
        wait = delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    # ---------- zoeken ----------
    def search_candidates(self, start: date, end: date) -> list[Candidate]:
        ft = " OR ".join(f'FT ~ "{t}"' for t in config.SEARCH_TERMS)
        query = (
            f"({ft}) AND buyer-country IN ({' '.join(config.BUYER_COUNTRIES)})"
            f" AND form-type IN (result cont-modif)"
            f" AND publication-date>={start:%Y%m%d} AND publication-date<={end:%Y%m%d}"
        )
        out: dict[str, Candidate] = {}
        page = 1
        while True:
            self._wait(API_DELAY_S)
            r = self.s.post(
                SEARCH_URL,
                json={
                    "query": query,
                    "fields": ["publication-number", "publication-date", "notice-type", "ojs-number"],
                    "limit": 100,
                    "page": page,
                    "paginationMode": "PAGE_NUMBER",
                },
                timeout=60,
            )
            if r.status_code != 200:
                raise RuntimeError(f"TED Search API {r.status_code}: {r.text[:500]}")
            data = r.json()
            for n in data.get("notices", []):
                pn = n["publication-number"]
                out[pn] = Candidate(pn, n.get("publication-date", "")[:10], n.get("notice-type", ""), n["ojs-number"])
            total = data.get("totalNoticeCount", 0)
            if page * 100 >= total or not data.get("notices"):
                break
            page += 1
        return sorted(out.values(), key=lambda c: (c.publication_date, c.publication_number))

    # ---------- pakketten ----------
    def fetch_package(self, package_id: str) -> dict[str, bytes]:
        """Geeft {publicatienummer: xml-bytes} voor alle aankondigingen in een dagpakket."""
        self._wait(PACKAGE_DELAY_S)
        r = self.s.get(PACKAGE_URL.format(package_id), timeout=300)
        if r.status_code != 200 or not r.content.startswith(b"\x1f\x8b"):
            raise RuntimeError(f"pakket {package_id}: HTTP {r.status_code}")
        files = {}
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tf:
            for m in tf.getmembers():
                name = m.name.rsplit("/", 1)[-1]
                mm = re.fullmatch(r"(\d+)_(\d{4})\.xml", name)
                if m.isfile() and mm:
                    files[f"{int(mm.group(1))}-{mm.group(2)}"] = tf.extractfile(m).read()
        return files

    def collect(self, candidates: list[Candidate], deadline: float | None = None) -> tuple[list[Award], str | None]:
        """Haalt de XML op en parseert. Geeft (awards, eerste niet-verwerkte datum of None)."""
        by_package: dict[str, list[Candidate]] = defaultdict(list)
        for c in candidates:
            by_package[c.package_id].append(c)
        awards: list[Award] = []
        failures = 0
        for pid in sorted(by_package, key=lambda p: min(c.publication_date for c in by_package[p])):
            cands = by_package[pid]
            if deadline and time.monotonic() > deadline:
                return awards, min(c.publication_date for c in cands)
            try:
                files = self.fetch_package(pid)
            except (requests.RequestException, RuntimeError, tarfile.TarError) as e:
                failures += 1
                log.warning("pakket %s niet beschikbaar: %s", pid, e)
                continue
            for c in cands:
                xml = files.get(c.publication_number)
                if xml is None:
                    log.warning("%s niet gevonden in pakket %s", c.publication_number, pid)
                    continue
                awards += parse_notice(xml, c.publication_number, c.notice_type, c.publication_date)
        if by_package and failures == len(by_package):
            raise RuntimeError("geen enkel TED-pakket kon opgehaald worden")
        return [_plausible(a) for a in awards], None


# Meer dan de jaaromzet van de groep voor één perceel: vrijwel zeker een invoerfout van de opdrachtgever
# (bv. 563.402.620 i.p.v. 5.634.026,20). We bewaren de gunning, maar zonder bedrag.
MAX_PLAUSIBLE_EUR = 250_000_000


def _plausible(a: "Award") -> "Award":
    if a.bedrag_excl_btw is not None and a.bedrag_excl_btw > MAX_PLAUSIBLE_EUR:
        log.warning("onwaarschijnlijk bedrag %.0f EUR voor %s genegeerd (%s)", a.bedrag_excl_btw, a.bron_id, a.url)
        a.bedrag_excl_btw = None
    return a


# ---------- parsing ----------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _path(el, *names):
    for n in names:
        if el is None:
            return None
        el = _child(el, n)
    return el


def _text(el) -> str | None:
    if el is None:
        return None
    t = " ".join("".join(el.itertext()).split())
    return t or None


def _descendants(el, name):
    return [e for e in el.iter() if _local(e.tag) == name]


def _to_months(value: str | None, unit: str | None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    factor = {
        "DAY": 1 / 30.4375, "CALENDAR_DAY": 1 / 30.4375, "WORKING_DAY": 1 / 21.75,
        "WEEK": 7 / 30.4375, "MONTH": 1.0, "YEAR": 12.0,
    }.get((unit or "").upper())
    return round(v * factor, 1) if factor else None


def _months_between(start: str | None, end: str | None) -> float | None:
    try:
        d0, d1 = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    except (TypeError, ValueError):
        return None
    return round((d1 - d0).days / 30.4375, 1)


def _iso_date(s: str | None) -> str | None:
    return s[:10] if s and re.match(r"\d{4}-\d{2}-\d{2}", s) else None


def _amount(el) -> float | None:
    if el is None or (el.get("currencyID") or el.get("CURRENCY") or "EUR") != "EUR":
        return None
    try:
        return float(el.text)
    except (TypeError, ValueError):
        return None


def _is_combination(names: list[str]) -> bool:
    """Combinatie met minstens één partner buiten de groep (zie config.has_external_partner)."""
    return config.has_external_partner(names)


def _group_id(members: list[tuple[str, str | None]]) -> str | None:
    ids = [config.normalize_company_id(i) for _, i in members]
    known = [i for i in ids if i in config.GROUP_COMPANY_IDS]
    if known:
        return config.format_company_id(known[0])
    for (name, _), i in zip(members, ids):
        if i and config.is_group_member(name):
            return config.format_company_id(i)
    return None


def parse_notice(xml: bytes, publication_number: str, notice_type: str, publication_date: str) -> list[Award]:
    root = ET.fromstring(xml)
    if _local(root.tag) == "TED_EXPORT":
        return _parse_legacy(root, publication_number, notice_type, publication_date)
    return _parse_eforms(root, publication_number, notice_type, publication_date)


def _parse_eforms(root, pn, notice_type, pub_date) -> list[Award]:
    orgs = {}
    for org in _descendants(root, "Organization"):
        comp = _child(org, "Company")
        if comp is None:
            continue
        oid = _text(_path(comp, "PartyIdentification", "ID"))
        orgs[oid] = (_text(_path(comp, "PartyName", "Name")), _text(_path(comp, "PartyLegalEntity", "CompanyID")))

    buyer_id = _text(_path(root, "ContractingParty", "Party", "PartyIdentification", "ID"))
    buyer = orgs.get(buyer_id, (None, None))[0]

    durations = {}
    for lot in _children(root, "ProcurementProjectLot"):
        lot_id = _text(_child(lot, "ID"))
        period = _path(lot, "ProcurementProject", "PlannedPeriod")
        if period is None:
            continue
        dm = _child(period, "DurationMeasure")
        months = _to_months(dm.text, dm.get("unitCode")) if dm is not None else None
        if months is None:
            months = _months_between(_text(_child(period, "StartDate")), _text(_child(period, "EndDate")))
        durations[lot_id] = months

    result = next(iter(_descendants(root, "NoticeResult")), None)
    if result is None:
        return []
    parties = {}
    for tp in _children(result, "TenderingParty"):
        members = []
        for t in _children(tp, "Tenderer"):
            members.append(orgs.get(_text(_child(t, "ID")), (None, None)))
        parties[_text(_child(tp, "ID"))] = members
    tenders = {}
    for lt in _children(result, "LotTender"):
        tenders[_text(_child(lt, "ID"))] = {
            "amount": _amount(_path(lt, "LegalMonetaryTotal", "PayableAmount")),
            "party": _text(_path(lt, "TenderingParty", "ID")),
            "lot": _text(_path(lt, "TenderLot", "ID")),
        }
    contract_dates = {}
    for sc in _children(result, "SettledContract"):
        d = _iso_date(_text(_child(sc, "IssueDate"))) or _iso_date(_text(_child(sc, "AwardDate")))
        for ref in _children(sc, "LotTender"):
            contract_dates[_text(_child(ref, "ID"))] = d

    awards = []
    for lr in _children(result, "LotResult"):
        if _text(_child(lr, "TenderResultCode")) not in (None, "selec-w"):
            continue
        lot_id = _text(_path(lr, "TenderLot", "ID"))
        for ref in _children(lr, "LotTender"):
            tid = _text(_child(ref, "ID"))
            tender = tenders.get(tid)
            if not tender:
                continue
            members = parties.get(tender["party"], [])
            if not any(config.is_group_member(n, i) for n, i in members):
                continue
            names = [n for n, _ in members if n]
            awards.append(Award(
                bron="TED",
                bron_id=f"{pn}/{tid}",
                datum_gunning=contract_dates.get(tid) or pub_date[:10],
                opdrachtgever=buyer,
                winnaar=" + ".join(names),
                ondernemingsnummer=_group_id(members),
                bedrag_excl_btw=tender["amount"],
                looptijd_maanden=durations.get(tender["lot"] or lot_id),
                url=NOTICE_URL.format(pn),
                is_combinatie=_is_combination(names),
                notice_type=notice_type,
                publicatiedatum=pub_date[:10] or None,
            ))
    return awards


def _parse_legacy(root, pn, notice_type, pub_date) -> list[Award]:
    section = _child(root, "FORM_SECTION")
    forms = list(section) if section is not None else []
    form = next((f for f in forms if f.get("CATEGORY") == "ORIGINAL"), forms[0] if forms else None)
    if form is None:
        return []
    buyer = _text(_path(form, "CONTRACTING_BODY", "ADDRESS_CONTRACTING_BODY", "OFFICIALNAME"))

    durations, default_duration = {}, None
    for od in _descendants(form, "OBJECT_DESCR"):
        dur = _child(od, "DURATION")
        months = _to_months(dur.text, dur.get("TYPE")) if dur is not None else None
        if months is None:
            months = _months_between(_text(_child(od, "DATE_START")), _text(_child(od, "DATE_END")))
        lot_no = _text(_child(od, "LOT_NO"))
        if lot_no:
            durations[lot_no] = months
        if default_duration is None:
            default_duration = months

    awards = []
    for i, ac in enumerate(_descendants(form, "AWARD_CONTRACT"), start=1):
        awarded = _child(ac, "AWARDED_CONTRACT")
        if awarded is None:
            continue
        members = []
        for addr in _descendants(awarded, "ADDRESS_CONTRACTOR"):
            members.append((_text(_child(addr, "OFFICIALNAME")), _text(_child(addr, "NATIONALID"))))
        if not any(config.is_group_member(n, nid) for n, nid in members):
            continue
        names = [n for n, _ in members if n]
        lot_no = _text(_child(ac, "LOT_NO"))
        item = ac.get("ITEM") or str(i)
        awards.append(Award(
            bron="TED",
            bron_id=f"{pn}/{item}",
            datum_gunning=_iso_date(_text(_descendants(awarded, "DATE_CONCLUSION_CONTRACT")[0]))
            if _descendants(awarded, "DATE_CONCLUSION_CONTRACT") else pub_date[:10],
            opdrachtgever=buyer,
            winnaar=" + ".join(names),
            ondernemingsnummer=_group_id(members),
            bedrag_excl_btw=_amount(next(iter(_descendants(awarded, "VAL_TOTAL")), None)),
            looptijd_maanden=durations.get(lot_no, default_duration),
            url=NOTICE_URL.format(pn),
            is_combinatie=_is_combination(names),
            notice_type=notice_type,
            publicatiedatum=pub_date[:10] or None,
        ))
    return awards
