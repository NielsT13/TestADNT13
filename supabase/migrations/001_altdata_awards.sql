-- Gegunde overheidsopdrachten (Moury Construct en dochters) – schema altdata
-- Uitvoeren in de Supabase SQL-editor. Het script kan veilig opnieuw uitgevoerd worden.

create schema if not exists altdata;

create table if not exists altdata.awards (
    id                 bigint generated always as identity primary key,
    bron               text        not null,               -- 'TED'
    bron_id            text        not null,               -- TED: '<publicatienr>/<tender- of gunnings-id>'
    datum_gunning      date,                               -- datum sluiting contract, anders publicatiedatum
    opdrachtgever      text,
    winnaar            text        not null,               -- alle leden van de winnende combinatie, met ' + '
    ondernemingsnummer text,                               -- groepslid, formaat 0403.907.307 (vaak leeg vóór 2023)
    bedrag_excl_btw    numeric(14, 2),                     -- waarde van het contract/perceel in EUR, excl. btw
    looptijd_maanden   numeric(6, 1),
    url                text,
    is_combinatie      boolean     not null default false, -- combinatie met een partner BUITEN de groep
    notice_type        text,                               -- 'can-standard', 'can-modif', ...
    opgehaald_op       timestamptz not null default now(),
    constraint awards_bron_uniek unique (bron, bron_id)
);

create index if not exists awards_datum_idx on altdata.awards (datum_gunning);

-- Enkel de service-sleutel (GitHub Actions) mag schrijven en lezen; RLS zonder policies blokkeert anon/authenticated.
alter table altdata.awards enable row level security;

-- Per halfjaar het gegunde bedrag. Wijzigingen (can-modif) herhalen meestal het oorspronkelijke bedrag
-- en worden daarom apart geteld en niet opgeteld in de bedragen.
create or replace view altdata.awards_per_halfjaar
with (security_invoker = on) as
select
    make_date(extract(year from datum_gunning)::int,
              case when extract(month from datum_gunning) <= 6 then 1 else 7 end, 1)        as halfjaar_start,
    extract(year from datum_gunning)::int || '-H'
        || case when extract(month from datum_gunning) <= 6 then '1' else '2' end          as halfjaar,
    count(*) filter (where notice_type not like '%modif%')                                 as aantal_gunningen,
    count(*) filter (where notice_type not like '%modif%' and bedrag_excl_btw is null)     as aantal_zonder_bedrag,
    coalesce(sum(bedrag_excl_btw) filter (where notice_type not like '%modif%'), 0)        as totaal_bedrag_excl_btw,
    coalesce(sum(bedrag_excl_btw) filter (where notice_type not like '%modif%'
                                          and not is_combinatie), 0)                       as bedrag_enkel_groep,
    coalesce(sum(bedrag_excl_btw) filter (where notice_type not like '%modif%'
                                          and is_combinatie), 0)                           as bedrag_met_partners,
    count(*) filter (where notice_type like '%modif%')                                     as aantal_wijzigingen
from altdata.awards
where datum_gunning is not null
group by 1, 2
order by 1;

grant usage on schema altdata to service_role;
grant select, insert, update, delete on altdata.awards to service_role;
grant select on altdata.awards_per_halfjaar to service_role;
