# Altdata: gegunde overheidsopdrachten Moury Construct

Dagelijkse verzameling van overheidsopdrachten die gegund zijn aan Moury Construct (Euronext Brussel: MOUR) en zijn dochters, als voorspeller voor het orderboek en de omzet.

## Wat het doet

- **Bron:** TED (Tenders Electronic Daily, EU). Dit is de enige officiële, open bron.
  - [Search API](https://docs.ted.europa.eu/api/latest/search.html), zonder sleutel, om kandidaat-aankondigingen te vinden.
  - Officiële dagpakketten `https://ted.europa.eu/packages/daily/…` met de volledige XML, om per perceel te bepalen wie wint en voor welk bedrag.
- **Groep:** de volledig geconsolideerde dochters uit het jaarverslag 2025: Les Entreprises G. Moury, Bemat, Mosabois, D-FI, Volt-Air en de holding. Zie `tenders/config.py`.
- **Opslag:** Supabase, tabel `altdata.awards` (één rij per gewonnen perceel), plus de view `altdata.awards_per_halfjaar`.
- **Workflow:** `.github/workflows/tenders.yml`
  - dagelijks om 05:17 UTC (06:17 in de winter, 07:17 in de zomer)
  - haalt telkens de laatste 7 dagen op; dubbele rijen worden overschreven dankzij de unieke sleutel `bron + bron_id`
  - de log en de samenvatting van elke run tonen het aantal kandidaten, het aantal gunningen en de duur

Het Belgische platform publicprocurement.be is niet opgenomen: het heeft geen officiële open API of open-datadownload.

## Eenmalige installatie (in de browser)

### 1. Tabel en view aanmaken in Supabase
1. Open je project op supabase.com → **SQL Editor** → **New query**.
2. Plak de volledige inhoud van `supabase/migrations/001_altdata_awards.sql` en klik **Run**. Het script mag later opnieuw uitgevoerd worden.

### 2. Het schema `altdata` openzetten voor de API
De workflow schrijft via de Supabase REST-API, en die ziet standaard enkel `public`.
1. Ga naar **Project Settings → Data API** (bij oudere projecten: **API**).
2. Voeg bij **Exposed schemas** `altdata` toe en klik **Save**.

De tabel staat op Row Level Security zonder policies: enkel de service-sleutel kan erin lezen of schrijven.

### 3. Secrets toevoegen in GitHub
1. Ga naar je repository → **Settings → Secrets and variables → Actions → New repository secret**.
2. Voeg toe:
   - `SUPABASE_URL`: de project-URL, bv. `https://abcdefgh.supabase.co`. Je vindt die onder Project Settings → Data API.
   - `SUPABASE_SERVICE_KEY`: de **service_role**-sleutel of de nieuwe **secret key** (`sb_secret_…`), onder Project Settings → API Keys. Gebruik niet de anon/publishable sleutel.

### 4. Backfill sinds 2018
1. Ga naar **Actions → "TED-gunningen Moury Construct" → Run workflow**.
2. Vul bij `van` in: `2018-01-01`. Laat `tot` leeg en klik **Run workflow**.
3. De run duurt ongeveer 4 minuten: ongeveer 115 aankondigingen en 125 rijen.
4. Als de tijdslimiet toch bereikt wordt, faalt de run. De samenvatting toont dan vanaf welke datum je opnieuw moet starten.

### Manueel starten
Gebruik dezelfde knop **Run workflow** met lege velden: dat verwerkt de laatste 7 dagen.

## De gegevens lezen

| Kolom | Betekenis |
|---|---|
| `bron_id` | TED-publicatienummer plus tender- of gunnings-id. De link staat in `url`. |
| `datum_gunning` | datum waarop het contract gesloten is; anders de publicatiedatum |
| `winnaar` | alle leden van de winnende partij, gescheiden door ` + ` |
| `ondernemingsnummer` | het groepslid (of de combinatie) als TED het vermeldt. Vóór eind 2023 ontbreekt het meestal. |
| `bedrag_excl_btw` | waarde van het **hele** contract of perceel in EUR |
| `is_combinatie` | `true` = gewonnen samen met een partner **buiten** de groep. Bemat + G. Moury samen telt als 100 % groep. |
| `notice_type` | `can-standard` = gunning, `can-modif` = wijziging van een bestaand contract |

De view `altdata.awards_per_halfjaar` geeft per halfjaar (op `datum_gunning`):
- `aantal_gunningen`
- `totaal_bedrag_excl_btw`, opgesplitst in `bedrag_enkel_groep` en `bedrag_met_partners`
- `aantal_zonder_bedrag`
- `aantal_wijzigingen`

Wijzigingen tellen niet mee in de bedragen: ze herhalen meestal het oorspronkelijke bedrag.

### Beperkingen
- **Dekking:** TED bevat vooral opdrachten boven de Europese drempel (werken vanaf ongeveer € 5,5 mln) en vrijwillige publicaties. Kleinere en private opdrachten ontbreken. Gebruik de reeks dus als trend, niet als volledig orderboek.
- **Combinaties:** het aandeel van Moury in een combinatie staat niet in TED. `bedrag_met_partners` is daarom een bovengrens.
- **Invoerfouten:** bedragen boven € 250 mln per perceel worden als invoerfout beschouwd en leeg gelaten, met een waarschuwing in de log. Voorbeeld: Foyer Fontainois 2024, € 563 mln voor een woningbouwproject.
- **Groepsleden herkennen:** dat gebeurt op naam (Moury, Bemat, Mosabois, D-FI, Volt-Air) en waar mogelijk op ondernemingsnummer. "Moury CPC" (Frankrijk) en "Moury Promotion" worden uitgesloten.
- **Gunningsdatum vs. publicatie:** de gunningsdatum kan maanden vóór de publicatie liggen, en een halfjaar kan nog aangevuld worden nadat het afgelopen is.

## Lokaal of in Codespaces

```bash
pip install -r requirements.txt
python -m unittest discover -s tests
python -m tenders.run --van 2025-01-01 --dry-run   # niets wegschrijven, rijen als JSON tonen
```
