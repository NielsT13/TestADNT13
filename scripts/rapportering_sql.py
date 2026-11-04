"""Genereert supabase/migrations/002_moury_rapportering.sql uit data/moury_rapportering.csv.

Gebruik: python scripts/rapportering_sql.py   (overschrijft het migratiebestand)
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "moury_rapportering.csv"
SQL = ROOT / "supabase" / "migrations" / "002_moury_rapportering.sql"

HEADER = """\
-- Door Moury Construct gerapporteerde omzet en orderboek – schema altdata
-- GEGENEREERD door scripts/rapportering_sql.py uit data/moury_rapportering.csv; niet met de hand aanpassen.
-- Uitvoeren in de Supabase SQL-editor ná 001_altdata_awards.sql. Het script kan veilig opnieuw uitgevoerd worden.

create table if not exists altdata.moury_rapportering (
    id                 bigint generated always as identity primary key,
    entiteit           text    not null default 'groep',  -- 'groep' of een dochter, bv. 'Bemat'
    ondernemingsnummer text,
    kengetal           text    not null check (kengetal in ('omzet', 'orderboek')),
    periode_start      date,                              -- omzet: begin van de periode; orderboek: leeg
    datum              date    not null,                  -- omzet: einde van de periode; orderboek: datum van de stand
    waarde_eur         numeric(14, 0) not null,
    gepubliceerd_op    date    not null,                  -- bij herwerkte cijfers wint de laatste publicatie
    bron               text    not null,
    bron_url           text,
    opmerking          text,
    check ((kengetal = 'omzet') = (periode_start is not null))
);

create unique index if not exists moury_rapportering_uniek on altdata.moury_rapportering
    (entiteit, kengetal, coalesce(periode_start, date '0001-01-01'), datum, gepubliceerd_op);

alter table altdata.moury_rapportering enable row level security;
grant select, insert, update, delete on altdata.moury_rapportering to service_role;

-- Laatst gepubliceerde waarde per entiteit, kengetal en periode/datum.
drop view if exists altdata.moury_halfjaar;
drop view if exists altdata.moury_rapportering_actueel;
create view altdata.moury_rapportering_actueel as
select distinct on (entiteit, kengetal, periode_start, datum) *
from altdata.moury_rapportering
order by entiteit, kengetal, periode_start, datum, gepubliceerd_op desc, id desc;

-- Per halfjaar: omzet, orderboek begin/einde, impliciete nieuwe orders en de TED-gunningen ernaast.
--   nieuwe_orders_impliciet = orderboek einde - orderboek begin + omzet van het halfjaar
-- Het orderboek wordt niet altijd op balansdatum gerapporteerd. We nemen de stand op de einddatum
-- van het halfjaar, of anders de eerste stand binnen 92 dagen erna (orderboek_*_datum toont welke).
create view altdata.moury_halfjaar as
with akt as (
    select * from altdata.moury_rapportering_actueel where entiteit = 'groep'
),
hj as (
    select d::date                                         as halfjaar_start,
           (d + interval '6 months' - interval '1 day')::date as halfjaar_einde
    from generate_series(date '2018-01-01', current_date, interval '6 months') d
),
omzet as (
    select hj.*,
           case when extract(month from hj.halfjaar_start) = 1 then h1.waarde_eur
                else fy.waarde_eur - h1b.waarde_eur end    as omzet_halfjaar
    from hj
    left join akt h1  on h1.kengetal = 'omzet' and h1.periode_start = hj.halfjaar_start
                     and h1.datum = hj.halfjaar_einde
    left join akt fy  on fy.kengetal = 'omzet' and extract(month from hj.halfjaar_start) = 7
                     and fy.periode_start = date_trunc('year', hj.halfjaar_start)::date
                     and fy.datum = hj.halfjaar_einde
    left join akt h1b on h1b.kengetal = 'omzet' and extract(month from hj.halfjaar_start) = 7
                     and h1b.periode_start = date_trunc('year', hj.halfjaar_start)::date
                     and h1b.datum = (date_trunc('year', hj.halfjaar_start) + interval '6 months' - interval '1 day')::date
),
met_ob as (
    select o.*, ob.waarde_eur as orderboek_einde, ob.datum as orderboek_einde_datum
    from omzet o
    left join lateral (
        select waarde_eur, datum from akt
        where kengetal = 'orderboek' and datum between o.halfjaar_einde and o.halfjaar_einde + 92
        order by datum limit 1
    ) ob on true
),
reeks as (
    select m.*,
           lag(orderboek_einde)       over (order by halfjaar_start) as orderboek_begin,
           lag(orderboek_einde_datum) over (order by halfjaar_start) as orderboek_begin_datum
    from met_ob m
)
select
    r.halfjaar_start,
    extract(year from r.halfjaar_start)::int || '-H'
        || case when extract(month from r.halfjaar_start) = 1 then '1' else '2' end      as halfjaar,
    r.omzet_halfjaar,
    r.orderboek_begin,
    r.orderboek_begin_datum,
    r.orderboek_einde,
    r.orderboek_einde_datum,
    (r.orderboek_begin_datum = r.halfjaar_start - 1
        and r.orderboek_einde_datum = r.halfjaar_einde)                                   as orderboek_exact,
    r.orderboek_einde - r.orderboek_begin + r.omzet_halfjaar                              as nieuwe_orders_impliciet,
    coalesce(t.aantal_gunningen, 0)                                                       as ted_aantal,
    coalesce(t.totaal_bedrag_excl_btw, 0)                                                 as ted_totaal,
    coalesce(t.bedrag_enkel_groep, 0)                                                     as ted_enkel_groep,
    coalesce(t.bedrag_met_partners, 0)                                                    as ted_met_partners,
    round(coalesce(t.totaal_bedrag_excl_btw, 0)
          / nullif(r.orderboek_einde - r.orderboek_begin + r.omzet_halfjaar, 0), 3)       as ted_dekking,
    round((r.orderboek_einde - r.orderboek_begin + r.omzet_halfjaar)
          / nullif(r.omzet_halfjaar, 0), 2)                                               as book_to_bill
from reeks r
left join altdata.awards_per_halfjaar t on t.halfjaar_start = r.halfjaar_start
order by r.halfjaar_start;

grant select on altdata.moury_rapportering_actueel, altdata.moury_halfjaar to service_role;

-- Startgegevens 2017-2026 (bron per rij in bron_url).
insert into altdata.moury_rapportering
    (entiteit, ondernemingsnummer, kengetal, periode_start, datum, waarde_eur, gepubliceerd_op, bron, bron_url, opmerking)
values
"""

FOOTER = "\non conflict do nothing;\n"


def q(v: str) -> str:
    return "null" if v == "" else "'" + v.replace("'", "''") + "'"


def render() -> str:
    with CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    values = []
    for r in rows:
        values.append(
            "    ({}, {}, {}, {}, {}, {}, {}, {}, {}, {})".format(
                q(r["entiteit"]), q(r["ondernemingsnummer"]), q(r["kengetal"]),
                q(r["periode_start"]) + ("::date" if r["periode_start"] else ""),
                q(r["datum"]) + "::date", r["waarde_eur"], q(r["gepubliceerd_op"]) + "::date",
                q(r["bron"]), q(r["bron_url"]), q(r["opmerking"]),
            )
        )
    return HEADER + ",\n".join(values) + FOOTER


if __name__ == "__main__":
    SQL.write_text(render(), encoding="utf-8")
    print(f"{SQL.relative_to(ROOT)} geschreven")
