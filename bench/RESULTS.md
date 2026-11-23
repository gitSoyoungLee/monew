# 기사 목록 API N+1 개선 재측정 결과 (2026-11-23)

## 1. 무엇을 비교했나
| 구분 | 브랜치 / 커밋 | 기사 목록 조회 방식 |
|---|---|---|
| 개선 전 | `bench/n1-before` (develop `046996c` + `ArticleServiceImpl.findAll`만 개선 커밋 `4a53b00` 이전 루프로 되돌림) | 기사 50건마다 `commentRepository.countByArticle(article)`, `articleViewRepository.existsByUserIdAndArticleId(...)` 를 개별 실행 |
| 개선 후 | `bench/n1-after` (develop `046996c` 그대로) | `countByArticleIds(IN …) GROUP BY` 1회 + `findViewedArticleIds(IN …)` 1회 |

- 두 브랜치 모두 develop 에서 분기했고, 차이는 `findAll` 의 연관 데이터 조회 방식뿐이다 (스키마, 리포지토리, 커서 쿼리, AOP 측정 도구 동일).
- 측정 도구 변경(양쪽 동일): 기존 AOP 값(`System.currentTimeMillis`)은 그대로 두고, 정밀도 확인용으로 `System.nanoTime` 합계를 로그에 함께 남기도록 추가. 10회 평균 기준 두 값의 차이는 1% 이내(호출 1회 단위로는 최대 약 20ms 차이)여서 기존 도구의 ms 해상도가 결과를 왜곡하지 않음을 확인 → 표에는 기존 AOP 값(ms)을 사용.

## 2. 측정 조건
- 요청: `GET /api/articles?orderBy=publishDate&direction=DESC&limit=50` (첫 페이지, 필터 없음), 헤더 `Monew-Request-User-Id: 00000000-0000-0000-0000-000000000001`
- 반복: 앱 기동 → 기동 확인 호출 1회(버림) → **워밍업 5회(버림) → 측정 10회의 평균**. 호출은 순차 1개씩, 매 호출 새 HTTP 연결.
- 측정 항목 (서로 다른 값, 섞지 말 것)
  - **쿼리 수**: AOP(PreparedStatement `execute*` 호출 횟수)
  - **쿼리 실행 시간 합**: AOP가 각 `execute*` 호출 전후 시간 차를 합한 값. 컨트롤러 AOP가 요청 단위로 로그에 남김 (`QueryStatistics`, `@RequestScope`)
  - **API 응답 시간**: 클라이언트(Python `http.client`, `perf_counter`)에서 요청 전송 ~ 응답 본문 수신 완료까지. 커넥션 획득, 매핑, JSON 직렬화, localhost 네트워크 포함
- 환경: Windows 11 노트북 1대에서 앱과 DB 동시 실행, PostgreSQL 17.4 (`shared_buffers=128MB`, 기본 설정), JDK 17.0.10, `-Xms1g -Xmx1g`, Spring Boot 3.4.4, dev 프로필
- 앱 실행 옵션(양쪽 동일): `currentSchema=bench,public`, `spring.sql.init.mode=never`(schema.sql 의 DROP TABLE 방지), Hibernate SQL/바인딩 로그 끔(로그 출력 비용이 쿼리 수에 비례해 응답 시간이 왜곡되지 않도록. 개선 전에 더 불리한 비용을 없앤 것이라 개선 폭을 줄이는 방향)
- 스키마: 프로젝트 `schema.sql` 그대로 (`comments.article_id` 에 **인덱스 없음**, `article_views` 는 `UNIQUE(user_id, article_id)` 인덱스 있음)
- 데이터: `bench/seed.sql` (setseed 고정). 기사 발행일 최근 1년 랜덤, 댓글은 기사당 평균 10개 랜덤 배정, 조회 기록은 기사당 평균 10건 랜덤(중복 제거), 측정 사용자는 최신 기사 200건 중 100건을 본 상태
- 정합성 확인: 모든 호출에서 개선 전/후 응답이 같음 (50건, 10k: viewedByMe=true 25건·댓글 수 합 471 / 100k: 25건·501), 측정 중 기사 수 변동 없음(totalElements 일정)

## 3. 결과 (10회 평균, 괄호는 중앙값)
| 데이터 규모 (기사 / 댓글 / 조회 기록 / 사용자) | 구분 | 쿼리 수 | 쿼리 실행 시간 합 (ms) | API 응답 시간 (ms) |
|---|---|---|---|---|
| 1만 / 10만 / 99,570 / 1,001 | 개선 전 | 103 | 719.7 (698.5) | 855.9 (816.6) |
| | 개선 후 | 5 | 76.1 (70.5) | 124.2 (119.0) |
| | **개선율** | **95.1%** | **89.4%** | **85.5%** |
| 10만 / 100만 / 999,614 / 10,001 (2차, 권장) | 개선 전 | 103 | 14,915.0 (14,908.5) | 15,083.4 (15,120.3) |
| | 개선 후 | 5 | 689.6 (730.5) | 733.0 (778.9) |
| | **개선율** | **95.1%** | **95.4%** | **95.1%** |
| 10만 / 100만 / 999,614 / 10,001 (1차) | 개선 전 | 103 | 20,516.8 (16,099.0) | 20,711.4 (16,249.4) |
| | 개선 후 | 5 | 720.3 (686.5) | 759.9 (724.5) |
| | 개선율 | 95.1% | 96.5% | 96.3% |

- 10만 건 1차의 개선 전 값은 측정 1~4회차가 35.8s → 27.7s → 24.7s → 22.1s 로 계속 줄다가 이후 ~15.7s 에서 안정됨. 댓글 테이블(167MB)이 `shared_buffers`(128MB)보다 커서 워밍업 5회로는 캐시가 다 데워지지 않은 것. 같은 조건으로 다시 잰 2차(편차 ±0.4s로 안정)를 대표값으로 쓰는 것을 권장 (2차가 개선 전 값이 더 작아 보수적).

### 보조 측정: `comments(article_id)` 인덱스를 추가한 경우 (본 측정과 별개, 측정 후 인덱스 삭제)
| 데이터 규모 | 구분 | 쿼리 수 | 쿼리 실행 시간 합 (ms) | API 응답 시간 (ms) |
|---|---|---|---|---|
| 10만 / 100만 / 999,614 / 10,001 | 개선 전 | 103 | 423.2 (395.0) | 579.4 (567.9) |
| | 개선 후 | 5 | 305.2 (322.5) | 353.8 (361.7) |
| | 개선율 | 95.1% | 27.9% | 38.9% |

## 4. 해석 / 주의할 점 (면접 대비)
1. **쿼리 수가 102→4 가 아니라 103→5** 로 나온다. SQL 로그로 확인한 추가 1회는 `select count(*) from users where id=?` (`userRepository.existsById`, 사용자 존재 검증). 이 코드는 N+1 개선(`4a53b00`, 2025-04-29) 이후 `a4cc2c0`(2025-05-02)에서 추가돼 개선 전/후 양쪽에 똑같이 1회씩 붙는다. 데이터 규모와 무관하게 103/5 로 고정 → "쿼리 수는 페이지 크기로 정해진다"는 전제는 맞음.
   - 개선 전 103 = 사용자 확인 1 + 기사 목록 1 + (댓글 수 1 + 조회 여부 1) × 50 + 전체 건수 1
   - 개선 후 5 = 사용자 확인 1 + 기사 목록 1 + 댓글 수 IN 1 + 조회 여부 IN 1 + 전체 건수 1
2. **시간 차이가 크게 벌어진 주원인은 `comments.article_id` 인덱스 부재**다. 개선 전에는 기사마다 `count(...) where article_id=?` 가 댓글 테이블 전체를 순차 스캔 → 50번 풀스캔. 개선 후에는 IN + GROUP BY 로 1번만 스캔. 데이터가 늘수록 이 차이가 선형으로 커진다(1만 건 0.7s → 10만 건 14.9s).
3. 인덱스가 있으면 개선 전/후 차이는 쿼리 시간 합 기준 약 118ms(28%)로 줄어든다. 이 경우 남는 차이가 "DB 왕복 98회" 자체의 비용이다. 개선 후에도 300ms 대가 남는 것은 두 버전 공통인 기사 목록 정렬(`published_date` 인덱스 없음, 10만 건 정렬 ~200ms)과 전체 건수 count 때문.
4. 응답 시간과 쿼리 실행 시간 합의 차이(개선 후 약 40~50ms)는 커넥션 획득, 엔티티/DTO 매핑, JSON 직렬화, HTTP 비용이다.
5. 100만 건 이상은 진행하지 않음: 개선 전 1회 호출이 댓글 1,000만 건을 50번 풀스캔해야 해 요청당 수 분 이상이 예상되어 마감 내 15회 반복 불가.

## 5. 재현 방법
```bash
# 1) bench 스키마 생성 (public 은 건드리지 않음)
psql -U monew -d monew -c "CREATE SCHEMA IF NOT EXISTS bench;"
(echo "SET search_path TO bench;"; cat monew/src/main/resources/schema.sql) | psql -U monew -d monew
# 2) 데이터 생성 (1만 건: articles=10000 users=1000 / 10만 건: articles=100000 users=10000)
psql -U monew -d monew -v articles=100000 -v users=10000 -v comments_per_article=10 -v views_per_article=10 -f bench/seed.sql
# 3) 각 브랜치에서 ./gradlew bootJar -x test 후 측정
python bench/measure.py before-100k <before jar> bench/results/before-100k.json
python bench/measure.py after-100k  <after jar>  bench/results/after-100k.json
python bench/summarize.py
```
- 주의: 앱의 기사 수집 배치가 매시 00분/10분에 돌기 때문에 그 시각을 피해서 측정함 (측정 중 기사 수 변동 없음 확인).
