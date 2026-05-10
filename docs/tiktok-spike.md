# TikTok Creative Center spike — 2026-05-10

Probe of TikTok's Creative Center as a data source for trending US lifestyle hashtags. Spike was 30 minutes; the goal was to confirm what's reachable without auth and decide whether the W3 ingestion plan can rely on it as a primary or value-add source.

## TL;DR

- **Public landing page is reachable.** `https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en` returns 200 and renders the trending hashtag UI.
- **Internal JSON API requires authentication.** The endpoint the UI hits (`creative_radar_api/v1/popular_trend/hashtag/list`) returns `{"code":40101,"msg":"no permission"}` without an authenticated session token.
- **Anti-bot infrastructure is real.** Akamai edge caching, signed `msToken` cookies, `x-tt-trace-*` fingerprinting headers. Plain `requests` is not going to work; this is playwright-or-bust.
- **Path forward: playwright with full session bootstrap.** Run a headless Chromium, let it visit the public page (which mints the `msToken` cookie), then either intercept the XHR the page makes OR scrape the rendered DOM. Either way, this is W3 work, not a 5-line `httpx.get()`.

## Test results

### Test 1 — public landing page (no auth)
```
GET https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en
→ HTTP 200, text/html
→ Server: Akamai edge (TLB origin)
→ x-nextjs-cache: HIT (Next.js SSR app)
→ Sets msToken cookie (10-day expiry, SameSite=None)
```

The public page works without auth. Anyone can browse the trending hashtags by region.

### Test 2 — direct API call (no auth)
```
GET https://ads.tiktok.com/creative_radar_api/v1/popular_trend/hashtag/list?period=7&page=1&limit=5&country_code=US
→ HTTP 200, but body is JSON: {"code":40101,"msg":"no permission","request_id":"..."}
```

Application-level auth, not HTTP-level. The response is a 200 envelope but the API rejects on permission. The check is on whatever signed cookie/token the page injects when an authed session loads it.

### Test 3 — auth model

The `msToken` cookie minted on the public landing page is necessary but not sufficient. The Creative Center API also expects:
- A signed `_signature` query parameter computed client-side (visible if you tail the network panel).
- The `webid` cookie from the JS SDK that boots when the page loads.
- Other request-header fingerprints (`x-tt-logid`, etc.) that the JS adds.

This is a deliberately scraping-resistant pipeline. You can't reproduce it from `curl` alone.

## Recommended path

**Use playwright in a long-lived session, not headless `httpx`.**

1. Boot a headless Chromium with playwright.
2. Visit the public landing page once per day; let it mint cookies.
3. Use `page.route()` to intercept the XHR the UI makes when listing trending hashtags. Capture the response JSON.
4. Cache the response in `signals_cache` for graceful-degradation reuse.
5. On a fresh failure (anti-bot block, network timeout, schema change), the orchestrator already falls back to the cultural calendar per the design doc.

Estimated W3 implementation effort: 1 day (4 hours playwright setup + 2 hours intercepting the XHR + 1 hour caching + 1 hour error handling).

## Risks (carry into W3)

- **Anti-bot detection.** TikTok rotates fingerprinting checks. A scraper that works in W3 may stop working in W6. The graceful-degradation primitive absorbs this — if TikTok dies, the dashboard keeps shipping content from the cultural calendar.
- **No SLA, no contract.** Public TikTok data is fair game for personal/research use, but their ToS forbids automated scraping. We mitigate by:
  - Single daily fetch, identified user agent, rate-limited (1 req/min while session is active).
  - No re-publishing of TikTok content verbatim — we read trending hashtag *names* and *volumes*, not user video content.
  - Public dashboard never stores or links to specific TikTok user posts.
- **Region targeting.** `country_code=US` is the param we want. Verify that the JSON shape includes per-country breakdowns, not just global trending. Confirm in the W3 implementation.
- **JSON shape may change.** TikTok ships UI updates regularly; the internal API isn't versioned. Use `parse_or_default()` from `pipeline/llm.py` (or the equivalent for non-LLM JSON) to fail soft.

## Decision

**Keep TikTok as a value-add source on top of the always-on cultural calendar.** Updated 2026-05-10: Reddit ingestion was scoped out of the W1 build at the user's direction. Sources are now cultural calendar (always-on) + TikTok (graceful via playwright).

W3 implementation order:
1. Cultural calendar reader (already shipped — `data/calendar.yaml` parses cleanly with 18 entries).
2. TikTok via playwright XHR interception (the only realtime signal source).

If TikTok playwright proves unworkable after a 1-day spike during W3, fall back to: monitor public TikTok hashtag pages directly (`https://www.tiktok.com/tag/{hashtag}`) and infer trends from there. Worse signal but more reliable.
