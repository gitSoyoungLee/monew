"""results/<before|after>-<scale>.json 을 읽어 표(마크다운)로 출력한다.
데이터 건수는 results/counts-<scale>.txt (psql 출력: articles|comments|article_views|users) 에서 읽는다."""
import glob
import json
import os
import sys

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load(name):
    p = os.path.join(R, name + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def counts(scale):
    p = os.path.join(R, f"counts-{scale}.txt")
    if not os.path.exists(p):
        return None
    a, c, v, u = open(p, encoding="utf-8").read().strip().split("|")
    return int(a), int(c), int(v), int(u)


def pct(b, a):
    return f"{(b - a) / b * 100:.1f}%"


scales = sys.argv[1:] or sorted({os.path.basename(f).split("-", 1)[1][:-5]
                                 for f in glob.glob(os.path.join(R, "before-*.json"))})
print("| 데이터 규모 (기사 / 댓글 / 조회 기록 / 사용자) | 구분 | 쿼리 수 | 쿼리 실행 시간 합 (AOP, ms) | API 응답 시간 (ms) |")
print("|---|---|---|---|---|")
for s in scales:
    b, a = load(f"before-{s}"), load(f"after-{s}")
    if not (b and a):
        continue
    cn = counts(s)
    label = f"{cn[0]:,} / {cn[1]:,} / {cn[2]:,} / {cn[3]:,}" if cn else s
    for name, r in (("개선 전", b), ("개선 후", a)):
        print(f"| {label} | {name} | {r['query_count']['mean']:.0f} | "
              f"{r['query_time_ms']['mean']:.1f} (중앙값 {r['query_time_ms']['median']}) | "
              f"{r['response_ms']['mean']:.1f} (중앙값 {r['response_ms']['median']}) |")
    print(f"| {label} | **개선율** | {pct(b['query_count']['mean'], a['query_count']['mean'])} | "
          f"{pct(b['query_time_ms']['mean'], a['query_time_ms']['mean'])} | "
          f"{pct(b['response_ms']['mean'], a['response_ms']['mean'])} |")
