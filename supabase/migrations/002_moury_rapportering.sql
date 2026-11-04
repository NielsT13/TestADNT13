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
    ('groep', '0413.821.301', 'omzet', '2017-01-01'::date, '2017-06-30'::date, 49813000, '2018-09-18'::date, 'Persbericht 30/06/2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2018.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2017-01-01'::date, '2017-12-31'::date, 97041000, '2019-03-28'::date, 'Persbericht 31/12/2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2018.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2018-01-01'::date, '2018-06-30'::date, 55445000, '2018-09-18'::date, 'Persbericht 30/06/2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2018.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2018-01-01'::date, '2018-06-30'::date, 55445000, '2019-09-27'::date, 'Persbericht 30/06/2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2019.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2018-01-01'::date, '2018-12-31'::date, 111367000, '2019-03-28'::date, 'Persbericht 31/12/2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2018.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2018-01-01'::date, '2018-12-31'::date, 111367000, '2020-03-26'::date, 'Persbericht 31/12/2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2019.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2019-01-01'::date, '2019-06-30'::date, 64622000, '2019-09-27'::date, 'Persbericht 30/06/2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2019.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2019-01-01'::date, '2019-06-30'::date, 63653000, '2020-09-25'::date, 'Persbericht 30/06/2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2020-1.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2019-01-01'::date, '2019-12-31'::date, 127850000, '2020-03-26'::date, 'Persbericht 31/12/2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2019.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2019-01-01'::date, '2019-12-31'::date, 126814000, '2021-03-23'::date, 'Persbericht 31/12/2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2020.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2020-01-01'::date, '2020-06-30'::date, 64890000, '2020-09-25'::date, 'Persbericht 30/06/2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2020-1.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2020-01-01'::date, '2020-06-30'::date, 64890000, '2021-09-30'::date, 'Halfjaarverslag 30/06/2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/rapport-intermediaire-au-30-juin-2021.pdf', 'vergelijkend cijfer; publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'omzet', '2020-01-01'::date, '2020-12-31'::date, 128602000, '2021-03-23'::date, 'Persbericht 31/12/2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2020.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2020-01-01'::date, '2020-12-31'::date, 128602000, '2022-03-22'::date, 'Persbericht 31/12/2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2021-sous-embargo.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2021-01-01'::date, '2021-06-30'::date, 75783000, '2021-09-30'::date, 'Halfjaarverslag 30/06/2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/rapport-intermediaire-au-30-juin-2021.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'omzet', '2021-01-01'::date, '2021-06-30'::date, 75783000, '2022-09-15'::date, 'Persbericht 30/06/2022', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2022-sous-embargo.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2021-01-01'::date, '2021-12-31'::date, 134822000, '2022-03-22'::date, 'Persbericht 31/12/2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2021-sous-embargo.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2021-01-01'::date, '2021-12-31'::date, 134822000, '2023-03-20'::date, 'Persbericht 31/12/2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/mc-communique-de-presse-31-decembre-2022.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2022-01-01'::date, '2022-06-30'::date, 79164000, '2022-09-15'::date, 'Persbericht 30/06/2022', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2022-sous-embargo.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2022-01-01'::date, '2022-06-30'::date, 79164000, '2023-09-25'::date, 'Persbericht 30/06/2023', 'https://www.moury-construct.be/wp-content/uploads/2023/09/MC-Communique-de-presse-30-juin-2023-vfinale-2.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2022-01-01'::date, '2022-12-31'::date, 155351000, '2023-03-20'::date, 'Persbericht 31/12/2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/mc-communique-de-presse-31-decembre-2022.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2022-01-01'::date, '2022-12-31'::date, 155351000, '2024-03-19'::date, 'Persbericht 31/12/2023', 'https://www.moury-construct.be/wp-content/uploads/2024/03/MC-Communique-de-presse-31-decembre-2023-final-.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2023-01-01'::date, '2023-06-30'::date, 93746000, '2023-09-25'::date, 'Persbericht 30/06/2023', 'https://www.moury-construct.be/wp-content/uploads/2023/09/MC-Communique-de-presse-30-juin-2023-vfinale-2.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2023-01-01'::date, '2023-06-30'::date, 93746000, '2024-09-23'::date, 'Persbericht 30/06/2024', 'https://www.moury-construct.be/wp-content/uploads/2024/09/MC-Communique-de-presse-30-juin-2024-final.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2023-01-01'::date, '2023-12-31'::date, 194027000, '2024-03-19'::date, 'Persbericht 31/12/2023', 'https://www.moury-construct.be/wp-content/uploads/2024/03/MC-Communique-de-presse-31-decembre-2023-final-.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2023-01-01'::date, '2023-12-31'::date, 194027000, '2025-03-24'::date, 'Persbericht 31/12/2024', 'https://www.moury-construct.be/wp-content/uploads/2025/03/MC-Communique-de-presse-2024_vf.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2024-01-01'::date, '2024-06-30'::date, 97971000, '2024-09-23'::date, 'Persbericht 30/06/2024', 'https://www.moury-construct.be/wp-content/uploads/2024/09/MC-Communique-de-presse-30-juin-2024-final.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2024-01-01'::date, '2024-06-30'::date, 97971000, '2025-09-22'::date, 'Persbericht 30/06/2025', 'https://www.moury-construct.be/wp-content/uploads/2025/09/MC-Communique-de-presse-30-juin-2025_final.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2024-01-01'::date, '2024-12-31'::date, 186340000, '2025-03-24'::date, 'Persbericht 31/12/2024', 'https://www.moury-construct.be/wp-content/uploads/2025/03/MC-Communique-de-presse-2024_vf.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2024-01-01'::date, '2024-12-31'::date, 186340000, '2026-03-20'::date, 'Persbericht 31/12/2025', 'https://www.moury-construct.be/wp-content/uploads/2026/03/MC-Communique-de-presse-31-decembre-2025.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2025-01-01'::date, '2025-06-30'::date, 124909000, '2025-09-22'::date, 'Persbericht 30/06/2025', 'https://www.moury-construct.be/wp-content/uploads/2025/09/MC-Communique-de-presse-30-juin-2025_final.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2025-01-01'::date, '2025-06-30'::date, 124909000, '2026-09-29'::date, 'Persbericht 30/06/2026', 'https://www.moury-construct.be/wp-content/uploads/2026/09/MC-Communique-de-presse-30-juin-2026.pdf', 'vergelijkend cijfer'),
    ('groep', '0413.821.301', 'omzet', '2025-01-01'::date, '2025-12-31'::date, 249552000, '2026-03-20'::date, 'Persbericht 31/12/2025', 'https://www.moury-construct.be/wp-content/uploads/2026/03/MC-Communique-de-presse-31-decembre-2025.pdf', null),
    ('groep', '0413.821.301', 'omzet', '2026-01-01'::date, '2026-06-30'::date, 147574000, '2026-09-29'::date, 'Persbericht 30/06/2026', 'https://www.moury-construct.be/wp-content/uploads/2026/09/MC-Communique-de-presse-30-juin-2026.pdf', null),
    ('Bemat', '0402.375.301', 'omzet', '2018-01-01'::date, '2018-12-31'::date, 34739000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Bemat', '0402.375.301', 'omzet', '2019-01-01'::date, '2019-12-31'::date, 42265000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Bemat', '0402.375.301', 'omzet', '2020-01-01'::date, '2020-12-31'::date, 40782000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Bemat', '0402.375.301', 'omzet', '2021-01-01'::date, '2021-12-31'::date, 45087000, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Bemat', '0402.375.301', 'omzet', '2022-01-01'::date, '2022-12-31'::date, 59091000, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Bemat', '0402.375.301', 'omzet', '2023-01-01'::date, '2023-12-31'::date, 78832000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'vergelijkend cijfer; publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Bemat', '0402.375.301', 'omzet', '2024-01-01'::date, '2024-12-31'::date, 64310000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Bemat', '0402.375.301', 'omzet', '2025-01-01'::date, '2025-12-31'::date, 98640000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('D-FI', '0449.118.908', 'omzet', '2023-01-01'::date, '2023-12-31'::date, 8625000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'vergelijkend cijfer; publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep; D-FI 2023 incl. Sandri en Ourth''Invest'),
    ('D-FI', '0449.118.908', 'omzet', '2024-01-01'::date, '2024-12-31'::date, 15466000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('D-FI', '0449.118.908', 'omzet', '2025-01-01'::date, '2025-12-31'::date, 17499000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Les Entreprises G. Moury', '0403.907.307', 'omzet', '2018-01-01'::date, '2018-12-31'::date, 70066000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Les Entreprises G. Moury', '0403.907.307', 'omzet', '2019-01-01'::date, '2019-12-31'::date, 81944000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Les Entreprises G. Moury', '0403.907.307', 'omzet', '2020-01-01'::date, '2020-12-31'::date, 86776000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Les Entreprises G. Moury', '0403.907.307', 'omzet', '2021-01-01'::date, '2021-12-31'::date, 87572000, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Les Entreprises G. Moury', '0403.907.307', 'omzet', '2022-01-01'::date, '2022-12-31'::date, 93745000, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Les Entreprises G. Moury', '0403.907.307', 'omzet', '2023-01-01'::date, '2023-12-31'::date, 102706000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'vergelijkend cijfer; publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Les Entreprises G. Moury', '0403.907.307', 'omzet', '2024-01-01'::date, '2024-12-31'::date, 103034000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Les Entreprises G. Moury', '0403.907.307', 'omzet', '2025-01-01'::date, '2025-12-31'::date, 129228000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mosabois', '0425.504.257', 'omzet', '2018-01-01'::date, '2018-12-31'::date, 1069000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mosabois', '0425.504.257', 'omzet', '2019-01-01'::date, '2019-12-31'::date, 1289000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mosabois', '0425.504.257', 'omzet', '2020-01-01'::date, '2020-12-31'::date, 1007000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mosabois', '0425.504.257', 'omzet', '2021-01-01'::date, '2021-12-31'::date, 2129000, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mosabois', '0425.504.257', 'omzet', '2022-01-01'::date, '2022-12-31'::date, 2483000, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mosabois', '0425.504.257', 'omzet', '2023-01-01'::date, '2023-12-31'::date, 3833000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'vergelijkend cijfer; publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mosabois', '0425.504.257', 'omzet', '2024-01-01'::date, '2024-12-31'::date, 3514000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mosabois', '0425.504.257', 'omzet', '2025-01-01'::date, '2025-12-31'::date, 4167000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Moury Construct (holding)', '0413.821.301', 'omzet', '2019-01-01'::date, '2019-12-31'::date, 29000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Moury Construct (holding)', '0413.821.301', 'omzet', '2020-01-01'::date, '2020-12-31'::date, 33000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Moury Construct (holding)', '0413.821.301', 'omzet', '2023-01-01'::date, '2023-12-31'::date, 8000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'vergelijkend cijfer; publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Moury Construct (holding)', '0413.821.301', 'omzet', '2024-01-01'::date, '2024-12-31'::date, 16000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Moury Construct (holding)', '0413.821.301', 'omzet', '2025-01-01'::date, '2025-12-31'::date, 17000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mourylux', null, 'omzet', '2018-01-01'::date, '2018-12-31'::date, 5493000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mourylux', null, 'omzet', '2019-01-01'::date, '2019-12-31'::date, 1287000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mourylux', null, 'omzet', '2020-01-01'::date, '2020-12-31'::date, 4000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mourylux', null, 'omzet', '2021-01-01'::date, '2021-12-31'::date, 33000, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mourylux', null, 'omzet', '2022-01-01'::date, '2022-12-31'::date, 32000, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mourylux', null, 'omzet', '2023-01-01'::date, '2023-12-31'::date, 23000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'vergelijkend cijfer; publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mourylux', null, 'omzet', '2024-01-01'::date, '2024-12-31'::date, 0, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('Mourylux', null, 'omzet', '2025-01-01'::date, '2025-12-31'::date, 0, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd; D-FI en Mosabois incl. intragroepsomzet, G. Moury excl. schrijnwerk/HVAC van de groep'),
    ('groep', '0413.821.301', 'orderboek', null, '2018-06-30'::date, 144900000, '2018-09-18'::date, 'Persbericht 30/06/2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2018.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2018-12-31'::date, 155000000, '2019-03-28'::date, 'Persbericht 31/12/2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2018.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2018-12-31'::date, 155462000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'orderboek', null, '2019-07-31'::date, 177700000, '2019-09-27'::date, 'Persbericht 30/06/2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2019.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2020-01-31'::date, 151200000, '2020-03-26'::date, 'Persbericht 31/12/2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2019.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2020-01-31'::date, 151166000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'orderboek', null, '2020-08-31'::date, 164000000, '2020-09-25'::date, 'Persbericht 30/06/2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2020-1.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2021-02-28'::date, 179500000, '2021-03-23'::date, 'Persbericht 31/12/2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2020.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2021-02-28'::date, 179455000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'orderboek', null, '2021-08-31'::date, 186000000, '2021-09-30'::date, 'Halfjaarverslag 30/06/2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/rapport-intermediaire-au-30-juin-2021.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2022-02-28'::date, 239000000, '2022-03-22'::date, 'Persbericht 31/12/2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-31-decembre-2021-sous-embargo.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2022-02-28'::date, 238472000, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'orderboek', null, '2022-06-30'::date, 238000000, '2022-09-15'::date, 'Persbericht 30/06/2022', 'https://www.moury-construct.be/wp-content/uploads/2022/11/mc-communique-de-presse-30-juin-2022-sous-embargo.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2023-02-28'::date, 234000000, '2023-03-20'::date, 'Persbericht 31/12/2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/mc-communique-de-presse-31-decembre-2022.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2023-02-28'::date, 234112000, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'orderboek', null, '2023-06-30'::date, 248000000, '2023-09-25'::date, 'Persbericht 30/06/2023', 'https://www.moury-construct.be/wp-content/uploads/2023/09/MC-Communique-de-presse-30-juin-2023-vfinale-2.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2023-12-31'::date, 240515000, '2024-04-30'::date, 'Jaarverslag 2023', 'https://www.moury-construct.be/wp-content/uploads/2024/04/Rapport-annuel-2023-Moury-Construct-VF.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'orderboek', null, '2024-02-29'::date, 245000000, '2024-03-19'::date, 'Persbericht 31/12/2023', 'https://www.moury-construct.be/wp-content/uploads/2024/03/MC-Communique-de-presse-31-decembre-2023-final-.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2024-06-30'::date, 335000000, '2024-09-23'::date, 'Persbericht 30/06/2024', 'https://www.moury-construct.be/wp-content/uploads/2024/09/MC-Communique-de-presse-30-juin-2024-final.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2024-12-31'::date, 357491000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'orderboek', null, '2025-02-28'::date, 361000000, '2025-03-24'::date, 'Persbericht 31/12/2024', 'https://www.moury-construct.be/wp-content/uploads/2025/03/MC-Communique-de-presse-2024_vf.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2025-08-31'::date, 354000000, '2025-09-22'::date, 'Persbericht 30/06/2025', 'https://www.moury-construct.be/wp-content/uploads/2025/09/MC-Communique-de-presse-30-juin-2025_final.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2025-12-31'::date, 316178000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd'),
    ('groep', '0413.821.301', 'orderboek', null, '2026-02-28'::date, 371500000, '2026-03-20'::date, 'Persbericht 31/12/2025', 'https://www.moury-construct.be/wp-content/uploads/2026/03/MC-Communique-de-presse-31-decembre-2025.pdf', 'afgerond in persbericht'),
    ('groep', '0413.821.301', 'orderboek', null, '2026-08-31'::date, 370000000, '2026-09-29'::date, 'Persbericht 30/06/2026', 'https://www.moury-construct.be/wp-content/uploads/2026/09/MC-Communique-de-presse-30-juin-2026.pdf', 'afgerond in persbericht'),
    ('Bemat', '0402.375.301', 'orderboek', null, '2018-12-31'::date, 54092000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd'),
    ('Bemat', '0402.375.301', 'orderboek', null, '2020-01-31'::date, 46230000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd'),
    ('Bemat', '0402.375.301', 'orderboek', null, '2021-02-28'::date, 59753000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd'),
    ('Bemat', '0402.375.301', 'orderboek', null, '2022-02-28'::date, 90002000, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd'),
    ('Bemat', '0402.375.301', 'orderboek', null, '2023-02-28'::date, 118568000, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd'),
    ('Bemat', '0402.375.301', 'orderboek', null, '2023-12-31'::date, 94898000, '2024-04-30'::date, 'Jaarverslag 2023', 'https://www.moury-construct.be/wp-content/uploads/2024/04/Rapport-annuel-2023-Moury-Construct-VF.pdf', 'publicatiedatum benaderd'),
    ('Bemat', '0402.375.301', 'orderboek', null, '2024-12-31'::date, 114659000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd'),
    ('Bemat', '0402.375.301', 'orderboek', null, '2025-12-31'::date, 97256000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd'),
    ('D-FI', '0449.118.908', 'orderboek', null, '2023-12-31'::date, 11005000, '2024-04-30'::date, 'Jaarverslag 2023', 'https://www.moury-construct.be/wp-content/uploads/2024/04/Rapport-annuel-2023-Moury-Construct-VF.pdf', 'publicatiedatum benaderd'),
    ('D-FI', '0449.118.908', 'orderboek', null, '2024-12-31'::date, 10357000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd'),
    ('D-FI', '0449.118.908', 'orderboek', null, '2025-12-31'::date, 15076000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd'),
    ('Les Entreprises G. Moury', '0403.907.307', 'orderboek', null, '2018-12-31'::date, 99818000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd'),
    ('Les Entreprises G. Moury', '0403.907.307', 'orderboek', null, '2020-01-31'::date, 104462000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd'),
    ('Les Entreprises G. Moury', '0403.907.307', 'orderboek', null, '2021-02-28'::date, 118630000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd'),
    ('Les Entreprises G. Moury', '0403.907.307', 'orderboek', null, '2022-02-28'::date, 147521000, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd'),
    ('Les Entreprises G. Moury', '0403.907.307', 'orderboek', null, '2023-02-28'::date, 114935000, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd'),
    ('Les Entreprises G. Moury', '0403.907.307', 'orderboek', null, '2023-12-31'::date, 134099000, '2024-04-30'::date, 'Jaarverslag 2023', 'https://www.moury-construct.be/wp-content/uploads/2024/04/Rapport-annuel-2023-Moury-Construct-VF.pdf', 'publicatiedatum benaderd'),
    ('Les Entreprises G. Moury', '0403.907.307', 'orderboek', null, '2024-12-31'::date, 231595000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd'),
    ('Les Entreprises G. Moury', '0403.907.307', 'orderboek', null, '2025-12-31'::date, 198887000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd'),
    ('Mosabois', '0425.504.257', 'orderboek', null, '2018-12-31'::date, 334000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd'),
    ('Mosabois', '0425.504.257', 'orderboek', null, '2020-01-31'::date, 474000, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd'),
    ('Mosabois', '0425.504.257', 'orderboek', null, '2021-02-28'::date, 1072000, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd'),
    ('Mosabois', '0425.504.257', 'orderboek', null, '2022-02-28'::date, 949000, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd'),
    ('Mosabois', '0425.504.257', 'orderboek', null, '2023-02-28'::date, 609000, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd'),
    ('Mosabois', '0425.504.257', 'orderboek', null, '2023-12-31'::date, 513000, '2024-04-30'::date, 'Jaarverslag 2023', 'https://www.moury-construct.be/wp-content/uploads/2024/04/Rapport-annuel-2023-Moury-Construct-VF.pdf', 'publicatiedatum benaderd'),
    ('Mosabois', '0425.504.257', 'orderboek', null, '2024-12-31'::date, 880000, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd'),
    ('Mosabois', '0425.504.257', 'orderboek', null, '2025-12-31'::date, 4959000, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd'),
    ('Mourylux', null, 'orderboek', null, '2018-12-31'::date, 1218000, '2019-04-30'::date, 'Jaarverslag 2018', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2018bis.pdf', 'publicatiedatum benaderd'),
    ('Mourylux', null, 'orderboek', null, '2020-01-31'::date, 0, '2020-04-30'::date, 'Jaarverslag 2019', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-rapport-annuel-2019.pdf', 'publicatiedatum benaderd'),
    ('Mourylux', null, 'orderboek', null, '2021-02-28'::date, 0, '2021-04-30'::date, 'Jaarverslag 2020', 'https://www.moury-construct.be/wp-content/uploads/2022/11/moury-ra-2020-complet.pdf', 'publicatiedatum benaderd'),
    ('Mourylux', null, 'orderboek', null, '2022-02-28'::date, 0, '2022-04-30'::date, 'Jaarverslag 2021', 'https://www.moury-construct.be/wp-content/uploads/2022/11/vf-photos-ok-mco-rapport-annuel-2021-complet-10-compresse.pdf', 'publicatiedatum benaderd'),
    ('Mourylux', null, 'orderboek', null, '2023-02-28'::date, 0, '2023-04-30'::date, 'Jaarverslag 2022', 'https://www.moury-construct.be/wp-content/uploads/2023/05/rapport-annuel-moury-construct-2022.pdf', 'publicatiedatum benaderd'),
    ('Mourylux', null, 'orderboek', null, '2023-12-31'::date, 0, '2024-04-30'::date, 'Jaarverslag 2023', 'https://www.moury-construct.be/wp-content/uploads/2024/04/Rapport-annuel-2023-Moury-Construct-VF.pdf', 'publicatiedatum benaderd'),
    ('Mourylux', null, 'orderboek', null, '2024-12-31'::date, 0, '2025-04-30'::date, 'Jaarverslag 2024', 'https://www.moury-construct.be/wp-content/uploads/2025/04/moury-rapport-annuel-2025.pdf', 'publicatiedatum benaderd'),
    ('Mourylux', null, 'orderboek', null, '2025-12-31'::date, 0, '2026-04-30'::date, 'Jaarverslag 2025', 'https://www.moury-construct.be/wp-content/uploads/2026/04/MOUR4360_RA_2025_planche.pdf', 'publicatiedatum benaderd')
on conflict do nothing;
