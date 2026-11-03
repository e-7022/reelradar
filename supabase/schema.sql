-- mini-virlo: схема для Supabase (free tier)
-- Выполнить один раз: Supabase → SQL Editor → вставить и Run.

-- ============ Таблицы ============

create table if not exists creators (
  username        text primary key,
  status          text not null default 'candidate'
                  check (status in ('tracked', 'candidate', 'blocked', 'rejected')),
  source          text,                 -- 'seed' | 'hashtag'
  english_score   real,                 -- 0..1, эвристика «англоязычный автор»
  best_views      bigint,               -- лучший ролик, найденный при discovery
  added_at        timestamptz not null default now(),
  last_tracked_at timestamptz
);

create table if not exists reels (
  short_code    text primary key,
  username      text not null,
  url           text,
  caption       text,
  thumbnail_url text,
  hashtags      text[],
  duration_sec  real,
  posted_at     timestamptz,
  source        text,                   -- 'track' | 'hashtag'
  views         bigint,
  likes         bigint,
  comments      bigint,
  first_seen_at timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists reels_username_posted_idx on reels (username, posted_at desc);
create index if not exists reels_posted_idx on reels (posted_at desc);

-- История просмотров: нужна для скорости роста (views/час)
create table if not exists reel_snapshots (
  short_code  text not null references reels (short_code) on delete cascade,
  captured_at timestamptz not null default now(),
  views       bigint,
  likes       bigint,
  comments    bigint,
  primary key (short_code, captured_at)
);

-- ============ Расчёт виральности ============

create or replace view reel_scores as
with ranked as (
  select r.username, r.views,
         row_number() over (partition by r.username
                            order by r.posted_at desc nulls last) as rn
  from reels r
  where r.views is not null
),
baseline as (            -- «норма» автора: медиана просмотров последних 30 роликов
  select username,
         percentile_cont(0.5) within group (order by views) as median_views,
         count(*) as baseline_n
  from ranked
  where rn <= 30
  group by username
),
vel as (                 -- прирост просмотров в час между двумя последними замерами
  select short_code, views_per_hour
  from (
    select short_code,
           (views - lag(views) over w)::double precision
             / nullif(extract(epoch from (captured_at - lag(captured_at) over w)) / 3600.0, 0)
             as views_per_hour,
           row_number() over (partition by short_code order by captured_at desc) as rn
    from reel_snapshots
    window w as (partition by short_code order by captured_at)
  ) s
  where rn = 1 and views_per_hour is not null
)
select
  r.short_code,
  r.username,
  r.url,
  r.caption,
  r.thumbnail_url,
  r.hashtags,
  r.duration_sec,
  r.posted_at,
  r.source,
  r.views,
  r.likes,
  r.comments,
  c.status as creator_status,
  b.median_views,
  b.baseline_n,
  -- outlier: во сколько раз ролик выше нормы автора (нужно ≥ 5 роликов в базе)
  case when b.baseline_n >= 5 and b.median_views > 0
       then round((r.views / b.median_views)::numeric, 2) end as outlier,
  -- скорость: по снимкам, а если снимок один — средняя с момента публикации
  round(coalesce(
    v.views_per_hour,
    r.views / greatest(extract(epoch from (now() - r.posted_at)) / 3600.0, 1)
  )::numeric, 1) as views_per_hour,
  (v.views_per_hour is not null) as velocity_measured,
  round(((coalesce(r.likes, 0) + coalesce(r.comments, 0))::numeric
         / nullif(r.views, 0)) * 100, 2) as engagement_pct,
  case
    when b.baseline_n >= 5 and b.median_views > 0 and r.views / b.median_views >= 10 then 'viral'
    when b.baseline_n >= 5 and b.median_views > 0 and r.views / b.median_views >= 3  then 'hot'
    else 'normal'
  end as tier
from reels r
left join baseline b using (username)
left join vel v using (short_code)
left join creators c using (username)
where coalesce(c.status, 'candidate') not in ('blocked', 'rejected');

-- Сводка по авторам
create or replace view creator_scores as
select
  c.username,
  c.status,
  c.english_score,
  c.last_tracked_at,
  count(s.short_code)                                   as reels_count,
  max(s.median_views)                                   as median_views,
  max(s.views)                                          as best_views,
  max(s.outlier)                                        as best_outlier,
  count(*) filter (where s.tier = 'viral')              as viral_count,
  count(*) filter (where s.tier in ('viral', 'hot'))    as hot_count
from creators c
left join reel_scores s using (username)
where c.status not in ('blocked', 'rejected')
group by c.username, c.status, c.english_score, c.last_tracked_at;

-- Тренды хэштегов: сколько раз тег встречается в «залетевших» роликах
-- за последние 7 дней против предыдущих 7 дней
create or replace view hashtag_trends as
select
  lower(tag) as tag,
  count(*) filter (where posted_at >= now() - interval '7 days')                   as this_week,
  count(*) filter (where posted_at >= now() - interval '14 days'
                     and posted_at <  now() - interval '7 days')                   as prev_week,
  round(avg(outlier), 1)                                                          as avg_outlier,
  sum(views)                                                                      as total_views
from reel_scores, unnest(hashtags) as tag
where tier in ('viral', 'hot')
  and posted_at >= now() - interval '14 days'
group by lower(tag)
having count(*) >= 2;

-- Для баз, созданных до появления статуса 'rejected'
alter table creators drop constraint if exists creators_status_check;
alter table creators add constraint creators_status_check
  check (status in ('tracked', 'candidate', 'blocked', 'rejected'));

-- ============ Доступ ============
-- Публичный anon-ключ (дашборд) может только читать. Писать может лишь коллектор
-- service-ключом. View работают с правами того, кто читает (security_invoker).

alter view reel_scores    set (security_invoker = true);
alter view creator_scores set (security_invoker = true);
alter view hashtag_trends set (security_invoker = true);

alter table creators       enable row level security;
alter table reels          enable row level security;
alter table reel_snapshots enable row level security;

revoke all on creators, reels, reel_snapshots from anon, authenticated;
revoke all on reel_scores, creator_scores, hashtag_trends from anon, authenticated;
grant select on creators, reels, reel_snapshots to anon, authenticated;
grant select on reel_scores, creator_scores, hashtag_trends to anon, authenticated;

drop policy if exists "public read" on creators;
drop policy if exists "public read" on reels;
drop policy if exists "public read" on reel_snapshots;
create policy "public read" on creators       for select to anon, authenticated using (true);
create policy "public read" on reels          for select to anon, authenticated using (true);
create policy "public read" on reel_snapshots for select to anon, authenticated using (true);
