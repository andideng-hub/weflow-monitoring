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
