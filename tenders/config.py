"""Wie hoort bij de groep Moury Construct, en hoe herkennen we die in TED-aankondigingen."""

import re

# Bron: jaarverslag 2025, bijlage 05 "Liste des entreprises consolidées" (volledig geconsolideerd).
GROUP_COMPANY_IDS = {
    "0413821301": "Moury Construct",
    "0403907307": "Les Entreprises G. Moury",
    "0402375301": "Bemat",
    "0425504257": "Mosabois",
    "0449118908": "D-FI",
    "0454338102": "Volt-Air",
}

# Zoektermen voor de volledige-tekstzoekopdracht in de TED Search API.
SEARCH_TERMS = ["Moury", "Bemat", "Mosabois", "D-FI", "Volt-air", *GROUP_COMPANY_IDS.keys()]

# Een winnaarnaam telt als groepslid als ze hierop matcht ...
GROUP_NAME_RX = re.compile(r"\b(moury|bemat|mosabois|d-fi|volt-air)\b", re.I)
# ... tenzij ze hierop matcht (andere bedrijven met een gelijkaardige naam).
EXCLUDE_NAME_RX = re.compile(r"moury\s*cpc|moury\s*promotion", re.I)

BUYER_COUNTRIES = ["BEL", "LUX"]


def normalize_company_id(raw: str | None) -> str | None:
    """'BE 0403.907.307', 'be0403907307', '403907307' -> '0403907307'."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        digits = "0" + digits
    return digits if len(digits) == 10 else None


def format_company_id(digits: str | None) -> str | None:
    if not digits:
        return None
    return f"{digits[:4]}.{digits[4:7]}.{digits[7:]}"


_GROUP_AND_FILLER_WORDS = re.compile(
    r"\b(moury|g|gilles|construct|bemat|b[ée]tons?|et|mat[ée]riaux|en|abr[ée]g[ée]|agr[ée]g[ée]|mosabois|d-fi|volt-air"
    r"|les|ets|[ée]tablissements|entreprises?|s\.?\s?a|n\.?\s?v|s\.?\s?r\.?\s?l|s\.?\s?s?\.?\s?m|a\.?\s?m|thv"
    r"|soci[ée]t[ée]|simple|momentan[ée]e?|association|groupement|d'op[ée]rateurs|[ée]conomiques|tva|btw|\d+)\b",
    re.I,
)


def has_external_partner(names: list[str]) -> bool:
    """True als de winnende partij een partner buiten de groep bevat.

    'SM BEMAT MOURY' of 'SA Bemat + SA Moury' -> False (100 % groep);
    'SSM MOURY - FRANKI' of 'Bemat + Duchêne' -> True.
    """
    for n in names:
        if not is_group_member(n):
            return True
        # Groepsnaam met nog een andere naam erin, bv. 'Association Duchêne Moury'.
        rest = _GROUP_AND_FILLER_WORDS.sub(" ", n)
        if re.search(r"[A-Za-zÀ-ÿ]{3,}", rest):
            return True
    return False


def is_group_member(name: str | None, company_id: str | None = None) -> bool:
    if normalize_company_id(company_id) in GROUP_COMPANY_IDS:
        return True
    return bool(name) and bool(GROUP_NAME_RX.search(name)) and not EXCLUDE_NAME_RX.search(name)
