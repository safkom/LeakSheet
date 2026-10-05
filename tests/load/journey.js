// What an app user gets through the public domain (Cloudflare → tunnel → nginx → API):
// browse trackers, open one, revisit it (304), load its era covers, read file metadata.
// Run: k6 run -e PROFILE=smoke tests/load/journey.js   (smoke | load | soak | spike | stress)
// One IP fits about 3 users under Cloudflare's 5 /api/sheet per 10 s (a journey makes two):
// smoke, load and soak stay inside it, and the load-prod workflow's `runners` adds IPs.
// spike and stress exceed it and the API's 60/min, so both need relaxing for the window.
// /stream (third-party hosts) gets one ranged request in smoke only; nothing forces a re-parse.
import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter, Rate } from "k6/metrics";
import { textSummary } from "https://jslib.k6.io/k6-summary/0.1.0/index.js";

const BASE = __ENV.BASE_URL || "https://sheets.safko.eu/api";
const PROFILE = __ENV.PROFILE || "smoke";
const UA = "LeakSheet/1 CFNetwork/3896.100.1.2.1 Darwin/27.0.0";
const COVERS_PER_OPEN = 8; // ArtistViewModel.coldStartArtCount
const COVER_WIDTH = 320; // EraCardView

// Real public trackers (tests/live_trackers.txt); Ye is the largest payload by far.
const TRACKERS = [
  { url: "https://yetracker.net/", weight: 4 },
  { url: "https://docs.google.com/spreadsheets/d/1i4OQglDHiiqMDthqfUFPutGmpZzK7n63LaoWApqhQXI/htmlview", weight: 2 },
  { url: "https://docs.google.com/spreadsheets/d/1v55XAPLzw1iuWxH1OQKajCIYPhW2BXcLoV4mXDZ55DI/htmlview", weight: 2 },
  { url: "https://docs.google.com/spreadsheets/d/1_SNZQS-AAXVleukgKlraegaozkLOu8WMHbUwmPm61hc/htmlview", weight: 1 },
  { url: "https://docs.google.com/spreadsheets/d/1zqqdIds1iwnx4lh29iF1IlraeuqfGhxH9qLNlWOnryo/htmlview", weight: 1 },
];

const PROFILES = {
  smoke: { executor: "constant-vus", vus: 1, duration: "1m" },
  load: {
    executor: "ramping-vus",
    stages: [{ duration: "2m", target: 3 }, { duration: "6m", target: 3 }, { duration: "2m", target: 0 }],
  },
  soak: { executor: "constant-vus", vus: 3, duration: "1h" },
  // A new leak drops: 50 users open the same tracker within seconds.
  spike: {
    executor: "ramping-vus",
    stages: [{ duration: "10s", target: 50 }, { duration: "1m", target: 50 }, { duration: "20s", target: 0 }],
    env: { ONLY_TRACKER: TRACKERS[0].url },
  },
  // Opens per second, raised until a threshold aborts the run.
  stress: {
    executor: "ramping-arrival-rate",
    startRate: 1,
    timeUnit: "1s",
    preAllocatedVUs: 50,
    maxVUs: 200,
    stages: [
      { duration: "2m", target: 2 }, { duration: "2m", target: 5 }, { duration: "2m", target: 10 },
      { duration: "2m", target: 20 }, { duration: "2m", target: 40 }, { duration: "1m", target: 0 },
    ],
  },
};

const abort = (threshold) => ({ threshold, abortOnFail: true, delayAbortEval: "30s" });
export const options = {
  scenarios: { [PROFILE]: { ...PROFILES[PROFILE], exec: "journey" } },
  setupTimeout: "5m",
  thresholds: {
    // Not counted as failures: 304 revalidations and rate-limit answers (tracked apart).
    http_req_failed: [abort("rate<0.05")],
    rate_limited: ["rate<0.01"],
    "http_req_duration{endpoint:sheet}": [abort("p(95)<10000")],
    "http_req_waiting{endpoint:sheet}": ["p(95)<2000"],
    "http_req_duration{endpoint:sheet_304}": ["p(95)<1000"],
    "http_req_duration{endpoint:cover}": ["p(95)<2000"],
    "http_req_duration{endpoint:trackers}": ["p(95)<2000"],
    checks: ["rate>0.95"],
  },
};
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 399 }, 429));

// A third-party host being down (pillows, imgur) is not a failure of ours.
const thirdParty = http.expectedStatuses({ min: 200, max: 399 }, 404, 429, 502);
const rateLimited = new Rate("rate_limited");
const cacheStatus = new Counter("cache_status");

function headers(extra) {
  return Object.assign({ "User-Agent": UA, "Accept-Encoding": "gzip" }, extra);
}

function note(res, endpoint) {
  rateLimited.add(res.status === 429 || res.status === 403);
  if (res.headers["X-Cache-Status"]) cacheStatus.add(1, { endpoint, status: res.headers["X-Cache-Status"] });
  // Ray IDs join a slow request to nginx's rt/urt fields: edge + tunnel time versus app time.
  if (res.timings.duration > 5000) {
    console.warn(`slow ${endpoint} ${Math.round(res.timings.duration)} ms ray=${res.headers["Cf-Ray"]}`);
  }
}

// Each tracker is fetched once here; the users then reuse its ETag and covers.
export function setup() {
  const trackers = TRACKERS.map((t) => {
    const res = http.post(`${BASE}/sheet`, JSON.stringify({ url: t.url }), {
      headers: headers({ "Content-Type": "application/json", Accept: "application/json" }),
      timeout: "180s",
      // A cold parse here is real-user latency too, but not the steady state the thresholds judge.
      tags: { endpoint: "setup" },
    });
    if (res.status !== 200) throw new Error(`setup: /sheet ${res.status} for ${t.url}`);
    const artist = res.json();
    const covers = artist.eras.map((e) => e.art_url).filter(Boolean).slice(0, COVERS_PER_OPEN);
    const links = [];
    for (const era of artist.eras) {
      for (const sec of era.sections) {
        for (const song of sec.songs) {
          for (const v of song.versions) for (const l of v.links || []) if (l.includes("pillows")) links.push(l);
        }
      }
      if (links.length >= 2) break;
    }
    return { url: t.url, weight: t.weight, etag: res.headers["Etag"], covers, links: links.slice(0, 2) };
  });
  sleep(10); // these five /sheet calls fill Cloudflare's per-IP window; let it pass
  return trackers;
}

function pick(trackers) {
  const only = __ENV.ONLY_TRACKER;
  if (only) return trackers.find((t) => t.url === only);
  let r = Math.random() * trackers.reduce((s, t) => s + t.weight, 0);
  return trackers.find((t) => (r -= t.weight) < 0) || trackers[0];
}

const think = (lo, hi) => (PROFILE === "stress" ? 0 : sleep(lo + Math.random() * (hi - lo)));

export function journey(trackers) {
  const tracker = pick(trackers);
  const sheetBody = JSON.stringify({ url: tracker.url });
  const sheetHeaders = { "Content-Type": "application/json", Accept: "application/x-ndjson, application/json" };

  group("browse", () => {
    const res = http.get(`${BASE}/trackers`, { headers: headers(), tags: { endpoint: "trackers" } });
    note(res, "trackers");
    check(res, { "trackers listed": (r) => r.status === 200 });
  });
  think(2, 6);

  group("open tracker", () => {
    const res = http.post(`${BASE}/sheet`, sheetBody, {
      headers: headers(sheetHeaders), tags: { endpoint: "sheet" }, responseType: "none", timeout: "120s",
    });
    note(res, "sheet");
    check(res, { "tracker opens": (r) => r.status === 200 });

    const covers = http.batch(tracker.covers.map((art) => ({
      method: "GET",
      url: `${BASE}/image-proxy?url=${encodeURIComponent(art.startsWith("//") ? `https:${art}` : art)}&w=${COVER_WIDTH}`,
      params: { headers: headers(), tags: { endpoint: "cover" }, responseType: "none" },
    })));
    covers.forEach((r) => note(r, "cover"));
    check(covers, { "covers load": (rs) => rs.every((r) => r.status === 200 || r.status === 404) });
  });
  think(5, 15);

  group("file details", () => {
    if (PROFILE === "stress" || PROFILE === "spike") return;
    for (const link of tracker.links) {
      const res = http.get(`${BASE}/metadata?url=${encodeURIComponent(link)}`, {
        headers: headers(), tags: { endpoint: "metadata" }, responseCallback: thirdParty,
      });
      note(res, "metadata");
    }
    if (PROFILE === "smoke" && tracker.links.length) {
      const res = http.get(`${BASE}/stream?url=${encodeURIComponent(tracker.links[0])}`, {
        headers: headers({ Range: "bytes=0-1" }), tags: { endpoint: "stream" }, responseType: "none",
        responseCallback: thirdParty,
      });
      note(res, "stream");
    }
  });
  think(10, 25);

  group("reopen tracker", () => {
    const res = http.post(`${BASE}/sheet`, sheetBody, {
      headers: headers(Object.assign({ "If-None-Match": tracker.etag }, sheetHeaders)),
      tags: { endpoint: "sheet_304" }, responseType: "none",
    });
    note(res, "sheet_304");
    // 200 when the tracker changed since setup.
    check(res, { "reopen revalidates": (r) => r.status === 304 || r.status === 200 });
  });
  think(5, 15);
}

export function handleSummary(data) {
  return {
    stdout: textSummary(data, { indent: " ", enableColors: false }),
    [`k6-${PROFILE}-summary.json`]: JSON.stringify(data, null, 1),
  };
}
