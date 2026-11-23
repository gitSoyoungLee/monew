"""
기사 목록 API N+1 개선 전/후 측정 하네스.

사용법:
  python measure.py <label> <jar 경로> <결과 json 경로> [--warmup 5] [--runs 10]

- 앱을 bench 스키마(currentSchema=bench)에 붙여 띄운다. schema.sql 자동 실행은 끈다(데이터 보존).
- SQL/바인딩 로그는 두 버전 모두 끈다 (로그 출력 비용이 쿼리 수에 비례해 응답 시간을 왜곡하지 않도록).
- GET /api/articles?orderBy=publishDate&direction=DESC&limit=50 (첫 페이지) 를 순차 호출한다.
- 워밍업 호출은 버리고, 이후 runs 회의 값을 기록한다.
  * 응답 시간: 클라이언트(Python)에서 요청 전송~응답 본문 수신 완료까지 (perf_counter)
  * 쿼리 수 / 쿼리 실행 시간 합: 컨트롤러 AOP 가 남긴 로그 한 줄 (QueryStatistics, @RequestScope)
"""
import argparse
import http.client
import json
import os
import re
import statistics
import subprocess
import sys
import time

USER_ID = "00000000-0000-0000-0000-000000000001"
PATH = "/api/articles?orderBy=publishDate&direction=DESC&limit=50"
PORT = 8089
LOG_RE = re.compile(
    r"Query Statistics: URL = GET /api/articles,\s+Query Count = (\d+), "
    r"Query Time = (\d+)\(ms\), Query Time\(nano\) = (\d+)\(us\)")


def call():
    conn = http.client.HTTPConnection("localhost", PORT, timeout=120)
    t0 = time.perf_counter()
    conn.request("GET", PATH, headers={"Monew-Request-User-Id": USER_ID})
    resp = conn.getresponse()
    body = resp.read()
    t1 = time.perf_counter()
    conn.close()
    return resp.status, body, (t1 - t0) * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("jar")
    ap.add_argument("out")
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--runs", type=int, default=10)
    a = ap.parse_args()

    log_path = a.out.replace(".json", ".log")
    logf = open(log_path, "w", encoding="utf-8")
    cmd = [
        "java", "-Xms1g", "-Xmx1g", "-jar", a.jar,
        f"--server.port={PORT}",
        "--spring.profiles.active=dev",
        "--spring.datasource.url=jdbc:postgresql://localhost:5432/monew?currentSchema=bench,public",
        "--spring.sql.init.mode=never",
        "--spring.batch.jdbc.initialize-schema=never",
        "--spring.jpa.show-sql=false",
        "--logging.level.org.hibernate.SQL=warn",
        "--logging.level.org.hibernate.orm.jdbc.bind=warn",
        "--logging.level.org.mongodb.driver.protocol.command=warn",
        "--spring.output.ansi.enabled=never",
        "--spring.boot.admin.client.enabled=false",
    ]
    jar_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(a.jar))))
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=jar_dir)
    try:
        # 기동 대기
        deadline = time.time() + 180
        while True:
            if proc.poll() is not None:
                raise SystemExit(f"app exited early, see {log_path}")
            try:
                status, _, _ = call()
                if status == 200:
                    break
            except OSError:
                pass
            if time.time() > deadline:
                raise SystemExit("startup timeout")
            time.sleep(1)
        # 기동 확인 호출 1회는 워밍업과 별개로 버림
        time.sleep(1)

        samples = []
        total = a.warmup + a.runs
        for i in range(total):
            before = open(log_path, encoding="utf-8", errors="replace").read()
            n_before = len(LOG_RE.findall(before))
            status, body, ms = call()
            # AOP 로그 한 줄이 기록될 때까지 대기
            for _ in range(50):
                found = LOG_RE.findall(open(log_path, encoding="utf-8", errors="replace").read())
                if len(found) > n_before:
                    break
                time.sleep(0.05)
            qc, qt, qus = found[-1]
            data = json.loads(body)
            rec = {
                "i": i, "warmup": i < a.warmup, "status": status,
                "response_ms": round(ms, 2),
                "query_count": int(qc), "query_time_ms": int(qt),
                "query_time_nano_ms": round(int(qus) / 1000, 2),
                "page_size": len(data.get("content", [])),
                "total_elements": data.get("totalElements"),
                "viewed_true": sum(1 for c in data.get("content", []) if c.get("viewedByMe")),
                "comment_sum": sum(c.get("commentCount") or 0 for c in data.get("content", [])),
            }
            samples.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
            time.sleep(0.2)

        m = [s for s in samples if not s["warmup"]]

        def summ(key):
            v = [s[key] for s in m]
            return {"mean": round(statistics.mean(v), 2), "median": round(statistics.median(v), 2),
                    "min": min(v), "max": max(v), "stdev": round(statistics.pstdev(v), 2)}

        result = {
            "label": a.label, "jar": a.jar, "warmup": a.warmup, "runs": a.runs,
            "request": f"GET {PATH} (Monew-Request-User-Id: {USER_ID})",
            "query_count": summ("query_count"),
            "query_time_ms": summ("query_time_ms"),
            "query_time_nano_ms": summ("query_time_nano_ms"),
            "response_ms": summ("response_ms"),
            "samples": samples,
        }
        json.dump(result, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("SUMMARY", json.dumps({k: result[k] for k in
                                     ("label", "query_count", "query_time_ms",
                                      "query_time_nano_ms", "response_ms")},
                                    ensure_ascii=False))
    finally:
        proc.terminate()
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
