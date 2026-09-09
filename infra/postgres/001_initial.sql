create extension if not exists vector;

do $$
begin
  if not exists (select from pg_roles where rolname = 'triage_app') then
    create role triage_app login password 'triage_local_only';
  end if;
end
$$;

create table if not exists tenants (
  id text primary key,
  display_name text not null,
  region text not null,
  created_at timestamptz not null default now()
);

create table if not exists tenant_policies (
  tenant_id text primary key references tenants(id) on delete restrict,
  confidence_threshold numeric(4,3) not null check (confidence_threshold between 0 and 1),
  allowed_providers text[] not null default '{}',
  allowed_regions text[] not null default '{}',
  version bigint not null default 1,
  updated_at timestamptz not null default now()
);

create table if not exists idempotency_records (
  tenant_id text not null references tenants(id) on delete restrict,
  idempotency_key text not null,
  result jsonb not null,
  created_at timestamptz not null default now(),
  primary key (tenant_id, idempotency_key)
);

create table if not exists audit_events (
  sequence_id bigint generated always as identity primary key,
  tenant_id text not null references tenants(id) on delete restrict,
  ticket_id text not null,
  correlation_id text not null,
  event_type text not null,
  occurred_at timestamptz not null,
  attributes jsonb not null default '{}'
);

create table if not exists triage_jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id text not null references tenants(id) on delete restrict,
  idempotency_key text not null,
  payload jsonb not null,
  status text not null default 'pending' check (status in ('pending', 'processing', 'complete', 'failed')),
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  result jsonb,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, idempotency_key)
);

create index if not exists triage_jobs_claim
  on triage_jobs (available_at, created_at) where status = 'pending';

create or replace function claim_triage_job()
returns table (id text, payload jsonb)
language sql
security definer
set search_path = public, pg_temp
as $$
  update triage_jobs set status = 'processing', attempts = attempts + 1,
    updated_at = now()
  where triage_jobs.id = (
    select triage_jobs.id from triage_jobs
    where status = 'pending' and available_at <= now()
    order by created_at for update skip locked limit 1
  )
  returning triage_jobs.id::text, triage_jobs.payload
$$;

create index if not exists audit_events_tenant_time
  on audit_events (tenant_id, occurred_at desc);

alter table tenant_policies enable row level security;
alter table tenant_policies force row level security;
alter table idempotency_records enable row level security;
alter table idempotency_records force row level security;
alter table audit_events enable row level security;
alter table audit_events force row level security;
alter table triage_jobs enable row level security;
alter table triage_jobs force row level security;

drop policy if exists tenant_policy_isolation on tenant_policies;
create policy tenant_policy_isolation on tenant_policies
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));
drop policy if exists idempotency_isolation on idempotency_records;
create policy idempotency_isolation on idempotency_records
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));
drop policy if exists audit_isolation on audit_events;
create policy audit_isolation on audit_events
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));
drop policy if exists triage_jobs_isolation on triage_jobs;
create policy triage_jobs_isolation on triage_jobs
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));

grant connect on database triage to triage_app;
grant usage on schema public to triage_app;
grant select, insert, update on tenant_policies, idempotency_records to triage_app;
grant select, insert on audit_events to triage_app;
grant select, insert, update on triage_jobs to triage_app;
grant usage, select on sequence audit_events_sequence_id_seq to triage_app;
revoke all on function claim_triage_job() from public;
grant execute on function claim_triage_job() to triage_app;

insert into tenants (id, display_name, region)
values ('example', 'Example tenant', 'local')
on conflict (id) do nothing;
insert into tenant_policies
  (tenant_id, confidence_threshold, allowed_providers, allowed_regions)
values ('example', 0.8, array['lmstudio'], array['local'])
on conflict (tenant_id) do nothing;

revoke update, delete, truncate on audit_events from triage_app;
