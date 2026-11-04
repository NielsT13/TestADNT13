-- Publicatiedatum van de TED-aankondiging bij elke gunning.
-- Nodig voor de toets: op een bepaalde datum kende je enkel de gunningen die al gepubliceerd waren.
-- Uitvoeren in de Supabase SQL-editor ná 001 en 002, vóór de volgende run van de workflow.
-- Daarna één keer de backfill opnieuw draaien (van = 2017-01-01) om de kolom te vullen.

alter table altdata.awards add column if not exists publicatiedatum date;
create index if not exists awards_publicatiedatum_idx on altdata.awards (publicatiedatum);
