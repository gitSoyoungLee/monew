-- =====================================================================
-- N+1 개선 측정용 대량 데이터 생성 스크립트 (PostgreSQL)
--   실행 예) psql -U monew -d monew -v articles=10000 -v users=1000 \
--             -v comments_per_article=10 -v views_per_article=10 -f seed.sql
--   - 대상 스키마: bench (프로젝트 schema.sql 로 생성한 동일 구조, public 은 건드리지 않음)
--   - 기존 bench 데이터는 모두 지우고 다시 만든다 (같은 조건 재현용)
--   - setseed 로 난수를 고정해 같은 파라미터면 같은 분포가 나온다
-- =====================================================================
SET search_path TO bench;
SELECT setseed(0.42);

TRUNCATE comment_likes, comments, notifications, article_views, article_interests,
         subscriptions, interest_keywords, articles, users, interests, keywords CASCADE;

-- 1) 사용자: 측정에 쓰는 고정 사용자 1명 + 일반 사용자 (:users)명
INSERT INTO users (id, email, nickname, password, deleted, created_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'bench@monew.test', 'bench-user', 'bench', false, now());

INSERT INTO users (id, email, nickname, password, deleted, created_at)
SELECT gen_random_uuid(), 'user' || g || '@monew.test', 'user' || g, 'pw', false, now()
FROM generate_series(1, :users) g;

-- 2) 기사: (:articles)건, 발행일은 최근 1년에 고르게 분포
INSERT INTO articles (id, title, source, source_url, summary, view_count, published_date,
                      deleted, created_at)
SELECT gen_random_uuid(),
       '벤치마크 기사 제목 ' || g,
       (ARRAY['NAVER','HANKYUNG','CHOSUN','YONHAP'])[1 + (g % 4)],
       'https://bench.monew.test/articles/' || g,
       '벤치마크용 기사 요약입니다. 번호 ' || g,
       0,
       now() - (random() * interval '365 days'),
       false,
       now() - (random() * interval '365 days')
FROM generate_series(1, :articles) g;

-- 기사 id 를 번호로 참조하기 위한 임시 테이블
CREATE TEMP TABLE a_idx AS
SELECT row_number() OVER (ORDER BY id) AS rn, id FROM articles;
CREATE UNIQUE INDEX ON a_idx (rn);
CREATE TEMP TABLE u_idx AS
SELECT row_number() OVER (ORDER BY id) AS rn, id FROM users;
CREATE UNIQUE INDEX ON u_idx (rn);

-- 3) 댓글: 기사당 평균 (:comments_per_article)개, 작성자/기사는 무작위 배정
INSERT INTO comments (id, user_id, article_id, content, like_count, deleted, created_at)
SELECT gen_random_uuid(), u.id, a.id, '벤치마크 댓글 ' || r.g, 0, false, now()
FROM (SELECT g,
             1 + floor(random() * (:users + 1))::int AS urn,
             1 + floor(random() * :articles)::int    AS arn
      FROM generate_series(1, :articles * :comments_per_article) g) r
JOIN u_idx u ON u.rn = r.urn
JOIN a_idx a ON a.rn = r.arn;

-- 4) 조회 기록: 기사당 평균 (:views_per_article)건 시도, (user, article) 중복은 제거
INSERT INTO article_views (id, user_id, article_id, viewed_at, created_at)
SELECT gen_random_uuid(), u.id, a.id, now(), now()
FROM (SELECT DISTINCT
             1 + floor(random() * (:users + 1))::int AS urn,
             1 + floor(random() * :articles)::int    AS arn
      FROM generate_series(1, :articles * :views_per_article) g) r
JOIN u_idx u ON u.rn = r.urn
JOIN a_idx a ON a.rn = r.arn
ON CONFLICT (user_id, article_id) DO NOTHING;

-- 측정 사용자는 최신 기사 일부를 확실히 본 상태로 (viewedByMe true/false 가 섞이도록 최신 200건 중 절반)
INSERT INTO article_views (id, user_id, article_id, viewed_at, created_at)
SELECT gen_random_uuid(), '00000000-0000-0000-0000-000000000001', id, now(), now()
FROM (SELECT id, row_number() OVER (ORDER BY published_date DESC, created_at DESC) rn
      FROM articles) x
WHERE rn <= 200 AND rn % 2 = 0
ON CONFLICT (user_id, article_id) DO NOTHING;

-- article.view_count 를 실제 조회 기록 수와 맞춤
UPDATE articles a SET view_count = v.cnt
FROM (SELECT article_id, count(*) cnt FROM article_views GROUP BY article_id) v
WHERE a.id = v.article_id;

ANALYZE;

SELECT (SELECT count(*) FROM articles)      AS articles,
       (SELECT count(*) FROM comments)      AS comments,
       (SELECT count(*) FROM article_views) AS article_views,
       (SELECT count(*) FROM users)         AS users;
