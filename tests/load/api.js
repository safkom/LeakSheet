// k6 load test for the API's hot paths: a cached /sheet, its 304 revalidation, /health.
// CI runs it against the production image with a cache from tests/load/seed_cache.py, so
// no request leaves the runner. Locally (seed .cache first, then start the API):
//   uv run python -m tests.load.seed_cache .cache && uv run uvicorn src.api:app --port 8080
//   k6 run tests/load/api.js
// Against production, stay under the rate limiter (60 /sheet requests a minute; each
// iteration makes two): BASE_URL=https://sheets.safko.eu/api SHEET_URL=<tracker> RATE=0.25 k6 run tests/load/api.js
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE_URL || "http://127.0.0.1:8080";
const SHEET = __ENV.SHEET_URL || "https://docs.google.com/spreadsheets/d/k6-synthetic-tracker/htmlview";
const BODY = JSON.stringify({ url: SHEET });
const JSON_HEADERS = { "Content-Type": "application/json", "Accept-Encoding": "gzip" };

export const options = {
  scenarios: {
    hot_paths: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.RATE || 15),
      timeUnit: "1s",
      duration: __ENV.DURATION || "30s",
      preAllocatedVUs: 20,
      maxVUs: 60,
    },
  },
  // Budgets for a shared CI runner; a regression shows as a multiple, not a few percent.
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    "http_req_duration{endpoint:sheet}": ["p(95)<1500"],
    "http_req_duration{endpoint:sheet_304}": ["p(95)<250"],
    "http_req_duration{endpoint:health}": ["p(95)<250"],
  },
};

export function setup() {
  const res = http.post(`${BASE}/sheet`, BODY, { headers: JSON_HEADERS });
  if (res.status !== 200) {
    throw new Error(`/sheet answered ${res.status}: is the cache seeded and the API up at ${BASE}?`);
  }
  return { etag: res.headers["Etag"] };
}

export default function (data) {
  const full = http.post(`${BASE}/sheet`, BODY, { headers: JSON_HEADERS, tags: { endpoint: "sheet" } });
  check(full, {
    "sheet is served from the cache": (r) => r.status === 200 && ["hit", "stale"].includes(r.headers["X-Cache-Status"]),
  });

  const revalidated = http.post(`${BASE}/sheet`, BODY, {
    headers: { ...JSON_HEADERS, "If-None-Match": data.etag },
    tags: { endpoint: "sheet_304" },
  });
  check(revalidated, { "an unchanged sheet is a 304": (r) => r.status === 304 });

  const health = http.get(`${BASE}/health`, { tags: { endpoint: "health" } });
  check(health, { "health is ok": (r) => r.status === 200 && r.json("status") === "ok" });
}
