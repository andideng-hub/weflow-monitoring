# Build Log

Engineering journal from building and iterating on the Weflow monitoring workflow. Documents issues hit, root causes, fixes, and what we learned.

## Session 1 — Design + Build (Apr 9, 2026)

Designed the spec, validated against real GCal + SFDC data, and built the full 27-node N8N workflow in a single session. Hit 8 bugs during deployment, all resolved.

### Bug 1: N8N API — `GET /credentials` returns 405
**Symptom:** Script tried to list credentials to check if Google OAuth already existed. N8N Cloud returned 405 Method Not Allowed.
**Root cause:** N8N Cloud REST API does not expose `GET /credentials` endpoint.
**Fix:** Removed credential existence check. Create on first run, skip on subsequent runs.
**Learning:** N8N Cloud API has fewer endpoints than self-hosted. Don't assume all v1 endpoints exist.

### Bug 2: N8N credential schema — `oAuth2Api` requires `serverUrl`
**Symptom:** 400 error when creating Google OAuth credential — "missing property serverUrl".
**Root cause:** N8N's `oAuth2Api` credential type schema requires `serverUrl`, `accessTokenUrl`, `clientId`, `clientSecret`, `scope`, `authentication` per its allOf validation.
**Fix:** Added `"serverUrl": "https://www.googleapis.com"`.
**Learning:** Always fetch credential schema first: `GET /credentials/schema/{type}`.

### Bug 3: N8N credential schema — `oauthTokenData` must be JSON string
**Symptom:** 400 error — "data is of prohibited type [object Object]".
**Root cause:** The `oauthTokenData` field has type `"json"` in N8N schema, meaning it expects a serialized JSON string, not a nested object.
**Fix:** Wrapped with `json.dumps()`.
**Learning:** N8N schema type `"json"` = string, not object. Stringify before sending.

### Bug 4: N8N credential schema — PKCE prohibits `authUrl`
**Symptom:** 400 error after fixing serverUrl and oauthTokenData.
**Root cause:** N8N's allOf conditional schema: when `grantType != "authorizationCode"`, fields like `authUrl`, `authQueryParameters`, etc. are prohibited (via `"not": {"required": [...]}` patterns).
**Fix:** Removed `authUrl` from credential payload for PKCE grant type.
**Learning:** N8N credential schemas have conditional required/prohibited fields based on grantType. Read the full allOf block.

### Bug 5: N8N node positions — must be arrays, not objects
**Symptom:** 400 error — "request/body/nodes/0/position must be array".
**Root cause:** Used `{"x": 100, "y": 200}` for positions. N8N expects `[100, 200]`.
**Fix:** Changed `pos()` helper to return `[x, y]`.
**Learning:** N8N positions are `[x, y]` arrays.

### Bug 6: Slack node — wrong typeVersion and parameter structure
**Symptom:** N8N UI showed error on Slack node before execution.
**Root cause:** Used Slack node v2.2 with `resource/operation/channel` params. Production N8N uses v2.4 with `select/channelId` pattern. `channelId` requires resource locator format: `{"__rl": true, "value": "...", "mode": "id"}`.
**Fix:** Copied exact node structure from working test workflow.
**Learning:** Always check existing working nodes for exact parameter structure before building new ones.

### Bug 7: Google OAuth — "Unable to sign without access token"
**Symptom:** GCal HTTP Request nodes failed with auth error when using N8N's `oAuth2Api` credential.
**Root cause:** N8N's `oAuth2Api` credential stored an expired access token and didn't auto-refresh using the refresh_token. PKCE grant type may not support automatic refresh in N8N Cloud.
**Fix:** Removed N8N OAuth credential entirely. Added a "Refresh Google Token" HTTP Request node that POSTs to Google's token endpoint with `client_id`/`client_secret`/`refresh_token`/`grant_type=refresh_token`. GCal nodes use the resulting `access_token` via expression in Authorization header.
**Learning:** For Google APIs in N8N, manual token refresh via HTTP Request is more reliable than N8N's built-in OAuth credential system.

### Bug 8: Set node raw mode — "Cannot convert undefined or null to object"
**Symptom:** Tag nodes failed when trying to spread `$json` with calendarId.
**Root cause:** Set node v3.4 `mode: "raw"` with `{{ { ...($json), calendarId: '...' } }}` can't spread if `$json` is the full GCal API response (an object with `items` array).
**Fix:** Changed from `mode: "raw"` to `mode: "manual"` with `includeOtherFields: true` and explicit `assignments` for `calendarId`.
**Learning:** N8N Set node manual mode with `includeOtherFields: true` is safer than raw JSON mode for complex objects.

## Session 2 — Cron Fix + Filter Improvements (Apr 10, 2026)

Workflow wasn't sending the 7 AM alert. Investigated and found the cron was running at 2 PM PT because N8N interprets cron expressions in the instance's local timezone (PT), not UTC.

### Bug 9: Cron timezone mismatch
**Symptom:** Alert not received at 7 AM PT. Last execution was at 2 PM PT.
**Root cause:** Cron `0 14 * * *` was intended as 14:00 UTC = 7 AM PT. But N8N Cloud instance timezone defaults to PT, so it ran at 14:00 PT.
**Fix:** Changed to `0 7 * * 1-5` (7 AM in instance timezone, weekdays only).
**Learning:** N8N Cloud cron expressions use the instance timezone, not UTC. Check workflow settings for timezone override.

### Filter: Cancelled meetings showing as gaps
**Symptom:** Meetings with "0 accepted" external attendees were flagged as transcript gaps.
**Root cause:** The code computed `externalAccepted` but only used it for hint text, never filtered on it.
**Fix:** Added `if (extAccepted === 0) continue;` before recording the meeting.

### Filter: Personal Gmail counting as "customer"
**Symptom:** "LIVE DEMO" (fully internal meeting) flagged as having 1 customer attendee.
**Root cause:** A team member's personal Gmail (`tamannaguglani@gmail.com`) was on the invite alongside their HG email. The filter only excluded internal domains, so Gmail counted as "external."
**Fix:** Added freemail domain exclusion list (gmail.com, yahoo.com, hotmail.com, outlook.com, etc.).

## Session 3 — Empty-Day Bug Fix (Apr 12, 2026)

### Bug 10: Silent pipeline death on days with no customer meetings
**Symptom:** Workflow ran successfully but no Slack message sent on quiet days (e.g., Friday).
**Root cause:** When Filter + Dedup found no customer meetings, it returned an empty array `[]`. N8N stops pipeline execution when a node produces 0 output items. The downstream "no meetings" path in Format Slack Message never executed.
**Fix:** Return a sentinel item `[{ json: { noMeetings: true } }]` when no meetings found. Build SOQL filters it out with `.filter(m => !m.noMeetings)`.
**Learning:** N8N Code nodes with `runOnceForAllItems` must return at least 1 item to keep the pipeline flowing. Return a sentinel for the "empty" case.

## Session 3 — Data Verification (Apr 12, 2026)

Cross-referenced the Apr 9 gaps against Vitally (FourFour) and re-queried SFDC 3 days later to check for delayed syncs.

### Finding: Weflow sync is 1-2 hours, not 24h
Analyzed 92 recordings created Apr 9-10. The bulk sync during business hours, within 1-2 hours of meeting end. Small overnight cluster is timezone differences, not delays. Recordings that don't appear within a day are genuine failures.

### Finding: Name-matching is unreliable for recurring meetings
Initially matched Weflow recordings by meeting title. For recurring meetings like "HG | AS - Weekly catch up", a record created on Apr 10 could be the Apr 10 occurrence (synced promptly), not a delayed Apr 9 sync. Verified by matching actual iCalUIDs — the Apr 9 events had Weflow records from March with null transcripts. Genuine gap, not a delay.

### Finding: Some Weflow recordings are permanent placeholders
Weflow creates recording objects at calendar sync time (days before the meeting). Only ~38% get transcripts. Records with null transcript and null summary are placeholders that never captured audio.

## Session 4 — Hardening + Feature Pass (Apr 22-23, 2026)

Four PRs: retry hardening (#12), recurring-iCalUID collision fix (#13), meeting_link column (#14), SFDC pagination (#15).

### Bug 11: Dedup Rows silent failure on Google Sheets 503
**Symptom:** Daily 7 AM PT cron on 4/22 errored (execution 6070) and no Slack alert fired. Workflow was healthy, cron registered, SFDC + GCal fine — just no Slack post.
**Root cause:** Dedup Rows node does a single `GET` on `Sheet1!J:J` to build the seen-set. Google Sheets returned 503 that morning; no retry wrapper, node errored, downstream Slack step never ran.
**Fix (#12):** Wrapped the httpRequest in a 3-attempt exponential backoff (500ms/1500ms/4500ms). Only retries on 5xx or network errors — doesn't mask real failures.
**Learning:** Any single HTTP call that gates a downstream alert should have retry-with-backoff. One flaky Google response shouldn't silence the daily alert.

### Bug 12: Recurring-meeting iCalUID collision caused false ✅ coverage
**Symptom:** Monitor claimed 100% Weflow coverage for Growth meetings on Tue 4/21 (9/9). Ground-truth SFDC query showed actual coverage was 7/9 (78%). Two false positives:
- Celonis Bi-weekly Sync (Himani, 4/21) — monitor matched a recording dated **4/7**
- Lob | HG Insights (Sunabh+Meghan, 4/21) — monitor matched a recording dated **3/31**

**Root cause:** `Build SOQL` and `Retry: Collect Stale` filtered only on `Weflow__EventId__c IN (...)`. Recurring meetings reuse the series iCalUID across every instance. Two forms of iCalUID seen in GCal:
- Bare series ID (e.g. `5h9k9...@google.com` for Celonis)
- Inherited first-instance recurrence ID (e.g. `..._R20260331T151500@google.com` for Lob — pinned to the original instance, never rotates)

Neither is unique per instance — so iCalUID-only matching is fundamentally unsafe for recurring series.

**Fix (#13):** Added `Weflow__StartDateTime__c` to SELECT + WHERE range on both SOQL queries (yesterday's PT window for main, retry lookback for retry). In code, switched from `sfMap[eid] = record` to `sfByUid[eid] = [records]` + per-meeting match by iCalUID AND start-time proximity (±2h for main, full-day window for retry).
**Learning:** For recurring events, iCalUID is a series key, not an instance key. Always pair it with a time window or instance ID to avoid cross-instance collisions. The review sheet's transcript-poll was actually more accurate than the monitor because it filtered by date window — worth studying as a reference pattern.

### Feature: meeting_link column (#14)
Added col L (`meeting_link`) to Sheet1 and col F to Issue Log, populated with the Zoom/Meet/Teams join URL extracted from each GCal event. Extraction priority: `conferenceData.entryPoints` (video) → `hangoutLink` → URL regex on `location` → URL regex on `description` covering `zoom.us | meet.google.com | teams.microsoft.com | gotomeet.me | webex.com`.

**Regex bug caught in code review:** initial description regex had `[^\s"'<>]+` before the host anchor (requires ≥1 char), so bare `https://zoom.us/j/...` and `https://meet.google.com/abc-defg-hij` would silently miss. Changed `+` to `*` so the prefix segment is optional. Also added `<>` to `location` regex character class to avoid capturing trailing HTML.

Backfilled 65 rows for 4/20-4/22 via direct `events.get` lookups (see next discovery). Final fill rate: 65/65 (100%) once two GCal-lookup quirks were worked around.

### Bug 13: SFDC silent-drop pattern for long-text SOQL (#15)
**Flagged by the csm-weekly-review agent as a cross-repo find.** Both `SFDC Weflow Query` and `Retry: SFDC Query` nodes had `"options": {}` — no pagination. SFDC batches SOQL responses when the query selects long-text-area fields; without `nextRecordsUrl` pagination, records beyond page 1 are silently dropped.
**Threshold (verified via direct REST):** ~250 records for our SOQL shape (scalar selects, no child subqueries). The original "~24 rows" warning applies to SOQL with child subqueries (like csm-weekly-review's); scalar-only queries like ours don't hit the low threshold. Current workload is 18-30 iCalUIDs/query, comfortably under 250.
**Fix (#15):** Mirrored the csm-weekly-review pattern — added `responseContainsNextURL` pagination block on both SFDC HTTP nodes + new `Flatten SFDC Pages` and `Retry: Flatten SFDC Pages` code nodes that concatenate `records[]` across pages into a single item. Downstream consumers (`Transcript Check` reading `$input.all()`, `Retry: Apply Updates` reading `$input.first()`) kept unchanged.
**Learning:** The CSM-agent's urgency was overstated for our specific SOQL, but the fix pattern is still correct insurance. Pagination threshold depends on SOQL shape: subqueries hit ~24, scalar long-text hits ~250. Always worth assuming SFDC will paginate.

### Discovery: UpKeep cancellation-after-cron pattern
**Scenario:** A ❌ Gap row on 4/22 for UpKeep Weekly Sync on Himani's calendar showed "no transcript" but the event itself had been deleted from GCal when later looked up.
**Timeline:** Cron fired at 7 AM PT, event was confirmed → row written. At 10:07 AM PT, organizer deleted the past event as cleanup. Row is now a "ghost" — sheet says Gap but event doesn't exist.
**Workflow handles it:** `Retry: Cleanup No-shows` (shipped in PR #11) re-checks aged ❌ Gap rows with `showDeleted=true` and deletes them from both sheets if cancelled. 25h guard prevents premature deletion.
**Caveat:** The 25h guard is aggressive — for 11:30 AM PT meetings, the row sits in the sheet until the next cron >25h later (next day's 7 AM PT). Expected behavior but worth knowing.

### Discovery: `events.list?iCalUID=` misses confirmed events
During the 65-row meeting_link backfill, 2 rows couldn't be located via `events.list?iCalUID=<uid>&timeMin=...&timeMax=...` even though the events clearly existed:
- UpKeep (cancelled): `events.list` defaults to `showDeleted=false`, so cancelled events are hidden.
- Prophix (confirmed, in-window): no obvious explanation — likely a GCal quirk with `iCalUID` + `timeMin/timeMax` combo.

Direct `events.get` by event ID (col J = `gcal_event_id`) found both immediately.
**Learning:** For point lookups, prefer `events.get` with the specific event ID over `events.list` with filters. Use list only for discovery (scanning a calendar window).
