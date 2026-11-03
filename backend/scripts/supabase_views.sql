-- Run in Supabase: SQL Editor -> New query -> paste -> Run
-- (after `alembic upgrade head` has created the tables)

create extension if not exists postgis;

-- Flat view used by the frontend dashboard (lat/lon as plain floats)
create or replace view public.transformers_flat as
select
  t.id,
  t.transformer_code,
  t.rated_kva,
  t.age_years,
  t.operational_status,
  t.district,
  t.address_text,
  t.substation_id,
  t.current_status,
  t.current_failure_risk,
  t.current_health_score,
  t.current_load_pct,
  t.current_load_kw,
  t.current_oil_temp_c,
  t.manufacturer,
  t.cooling_type,
  t.num_consumers,
  ST_Y(t.location::geometry) as latitude,
  ST_X(t.location::geometry) as longitude
from public.transformers t;

-- Allow the browser (publishable/anon key) to read these for the dashboard.
-- Read-only; writes still need the backend's DB credentials.
alter table public.transformers enable row level security;
alter table public.substations  enable row level security;

drop policy if exists "anon read transformers" on public.transformers;
create policy "anon read transformers" on public.transformers for select to anon using (true);

drop policy if exists "anon read substations" on public.substations;
create policy "anon read substations" on public.substations for select to anon using (true);

grant select on public.transformers_flat to anon;
alter view public.transformers_flat set (security_invoker = true);
