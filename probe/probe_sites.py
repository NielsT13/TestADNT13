"""Toegangstest voor de Belgische (nl-be) webshops van Marie Jo en PrimaDonna.

Doet een klein aantal requests (max ~12 per site, 2 s ertussen) met een
generieke User-Agent, respecteert robots.txt en probeert GEEN botbeveiliging
te omzeilen. Schrijft een rapport naar stdout en naar de GitHub
step summary (als GITHUB_STEP_SUMMARY gezet is).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "Mozilla/5.0 (compatible; altdata-research/0.1)"
DELAY_S = 2.0
LOCALE = "nl-be"
SITES = {
    "mariejo": "https://www.mariejo.com",
    "primadonna": "https://www.primadonna.com",
}
MAX_CHILD_SITEMAPS = 3
SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-BE,nl;q=0.9"})
_last_request = 0.0
report: list[str] = []


def out(line: str = "") -> None:
    print(line)
    report.append(line)


def polite_get(url: str, rp: robotparser.RobotFileParser | None) -> requests.Response | None:
    global _last_request
    path = urlparse(url).path
    if rp is not None and (path.startswith("/api/") or not rp.can_fetch(USER_AGENT, url)):
        out(f"- SKIP (robots.txt): `{url}`")
        return None
    wait = DELAY_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    try:
        r = session.get(url, timeout=30)
    except requests.RequestException as e:
        out(f"- FOUT `{url}`: {e}")
        return None
    finally:
        _last_request = time.monotonic()
    challenged = r.headers.get("cf-mitigated", "")
    title = re.search(r"<title>(.*?)</title>", r.text[:5000], re.S | re.I)
    out(
        f"- `{url}` → **{r.status_code}**, {len(r.content)} bytes, "
        f"type `{r.headers.get('content-type', '')}`, server `{r.headers.get('server', '')}`"
        + (f", **cf-mitigated: {challenged}**" if challenged else "")
        + (f", title: _{title.group(1).strip()[:80]}_" if title else "")
    )
    return r


def parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Geeft (child sitemaps, page urls) terug."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return [], []
    children = [e.text.strip() for e in root.findall("sm:sitemap/sm:loc", SM_NS) if e.text]
    urls = [e.text.strip() for e in root.findall("sm:url/sm:loc", SM_NS) if e.text]
    return children, urls


def analyse_product_page(html: str) -> None:
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I
    )
    out(f"  - JSON-LD blokken: {len(blocks)}")
    for i, b in enumerate(blocks):
        try:
            data = json.loads(b)
        except json.JSONDecodeError:
            out(f"    - blok {i}: geen geldige JSON")
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        types = [it.get("@type") for it in items if isinstance(it, dict)]
        out(f"    - blok {i}: types {types}")
        if any(t in ("Product", "ProductGroup") or (isinstance(t, list) and "Product" in t) for t in types):
            out("      ```json")
            for line in json.dumps(data, ensure_ascii=False, indent=1)[:4000].splitlines():
                out("      " + line)
            out("      ```")
    markers = {
        "__NEXT_DATA__": "__NEXT_DATA__" in html,
        "__NUXT__": "__NUXT__" in html,
        "window.__INITIAL_STATE__": "__INITIAL_STATE__" in html,
        "algolia (vermeld)": "algolia" in html.lower(),
        "og:price / product:price meta": "product:price" in html,
        "itemprop=price": 'itemprop="price"' in html,
    }
    for k, v in markers.items():
        out(f"  - {k}: {'ja' if v else 'nee'}")
    if "__NEXT_DATA__" in html:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            try:
                nd = json.loads(m.group(1))
                out(f"  - __NEXT_DATA__ top-level keys props.pageProps: {list(nd.get('props', {}).get('pageProps', {}).keys())[:30]}")
            except json.JSONDecodeError:
                pass


def probe(brand: str, base: str) -> None:
    out(f"## {brand} ({base})")
    rp = robotparser.RobotFileParser()
    r = polite_get(f"{base}/robots.txt", None)
    if r is None or r.status_code != 200:
        out("robots.txt niet leesbaar → stop voor deze site.")
        return
    rp.parse(r.text.splitlines())
    sitemaps = rp.site_maps() or [f"{base}/sitemaps/sitemap.xml"]
    out(f"- Sitemaps in robots.txt: {sitemaps}")

    r = polite_get(sitemaps[0], rp)
    if r is None or r.status_code != 200 or "<html" in r.text[:500].lower():
        out("- Sitemap niet bereikbaar (waarschijnlijk challenge). Ik probeer nog de nl-be homepage.")
        polite_get(f"{base}/{LOCALE}", rp)
        return

    children, urls = parse_sitemap(r.text)
    out(f"- Sitemap index: {len(children)} child sitemaps, {len(urls)} directe urls")
    for c in children[:50]:
        out(f"  - {c}")

    locale_children = [c for c in children if LOCALE in c.lower()] or children
    product_children = [c for c in locale_children if "product" in c.lower()] or locale_children
    page_urls = list(urls)
    for c in product_children[:MAX_CHILD_SITEMAPS]:
        rc = polite_get(c, rp)
        if rc is not None and rc.status_code == 200:
            _, u = parse_sitemap(rc.text)
            out(f"  - {c}: {len(u)} urls")
            page_urls += u

    be = [u for u in page_urls if f"/{LOCALE}/" in u or u.rstrip("/").endswith(f"/{LOCALE}")]
    out(f"- urls met /{LOCALE}/: {len(be)} (van {len(page_urls)} bekeken)")
    for u in be[:15]:
        out(f"  - {u}")

    # Kandidaat-productpagina: diepste pad met een cijfer erin (productcodes bevatten meestal cijfers)
    candidates = sorted(
        (u for u in be if re.search(r"\d{4,}", urlparse(u).path)),
        key=lambda u: -urlparse(u).path.count("/"),
    ) or sorted(be, key=lambda u: -urlparse(u).path.count("/"))
    for u in candidates[:2]:
        out(f"- Productpagina-kandidaat: {u}")
        rp_ = polite_get(u, rp)
        if rp_ is not None and rp_.status_code == 200:
            analyse_product_page(rp_.text)


def main() -> int:
    t0 = time.monotonic()
    out(f"# Toegangstest webshops ({LOCALE})")
    out(f"User-Agent: `{USER_AGENT}`, vertraging {DELAY_S}s per request")
    out()
    for brand, base in SITES.items():
        probe(brand, base)
        out()
    out(f"Duur: {time.monotonic() - t0:.1f}s")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(report) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
