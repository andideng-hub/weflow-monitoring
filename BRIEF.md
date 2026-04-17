# Weflow Transcript Monitoring — Project Brief

**Owner:** Andi Deng
**Stakeholders:** Sam Levan, Max Paulus, Jayesh (ops), Spencer (ops)
**Started:** April 9, 2026
**Status:** Live in production

---

## The Problem

We had no visibility into whether Weflow was actually recording CSM meetings. Transcript gaps were going undetected for weeks — the team only found out when reviewing call notes and realizing meetings had no recordings. By then it was too late to recover the conversation.

We needed a daily check that answers one simple question: **did yesterday's CSM meetings get recorded?**

## Why GCal Is the Source of Truth

If Weflow is broken, SFDC records may not exist at all. Starting from GCal ensures we catch failures that Weflow would otherwise silently swallow. GCal is the one system that always knows a meeting happened.

## Design

The approach: compare what *should* have been recorded (GCal meetings with external attendees) against what *was* recorded (Weflow transcripts in Salesforce).

### Data Flow

```
GCal (16 CSM calendars)
  → Filter to customer-facing meetings (corporate external attendees)
  → Deduplicate shared meetings by iCalUID
  → Match against SFDC Weflow__WeflowVideoRecording__c
  → Append one row per (meeting × CSM) to Google Sheet cache
  → Slack alert at 7 AM PT (terse: counts + sheet link)
```

### Output Model: Sheet as Detail, Slack as Summary

Slack carries only the daily totals (`X missing | Y recorded`) plus a hyperlink to the sheet. All per-meeting detail — CSM, title, customer domain, shared attendees, Weflow recording ID — lives in the "Weflow Transcript Log" Google Sheet (shared Customers drive). Ops filters the sheet by date, CSM, team, or status to drill in.

**Why:** With 16 CSMs, per-line Slack output runs dozens of bullets and becomes unreadable. The sheet makes every column filterable without flooding the channel.

**Sheet columns (12):** `alert_date`, `meeting_start_pt`, `csm_name`, `csm_email`, `team` (Growth/ENT), `status` (✅ Covered / ❌ Gap), `meeting_title`, `customer_domain`, `external_attendees`, `shared_with`, `weflow_recording_id`, `gcal_event_id`.

**Row granularity:** one row per (meeting × CSM). Shared meetings produce one row per attending CSM with `shared_with` listing the others — so filtering by CSM always works, and `gcal_event_id` lets ops dedup to unique meetings.

### What Counts as "Customer-Facing"

This took a few iterations to get right. The initial filter was too simple (any non-HG email = customer), which caused false positives:

**v1:** Any attendee with a non-internal email domain counts as external.
- Problem: Personal Gmail addresses (e.g., a team member's `tamannaguglani@gmail.com` alongside their HG email) triggered false positives. A fully internal "LIVE DEMO" meeting was flagged as having a customer attendee.

**v2 (current):** A meeting is customer-facing only if:
1. At least one attendee has a **corporate** email domain (not internal, not freemail)
2. At least one of those corporate attendees **accepted** (filters cancelled meetings)
3. The CSM didn't decline

**Internal domains:** hginsights.com, hgdata.com, trustradius.com, madkudu.com
**Freemail domains:** gmail.com, yahoo.com, hotmail.com, outlook.com, aol.com, icloud.com, protonmail.com, live.com, me.com, googlemail.com

### Build Approach

We defined the entire 27-node N8N workflow as Python dicts in a single build script (`build_workflow.py`) and pushed it via the N8N REST API. This means:

- The workflow definition lives in version control, not just the N8N UI
- Changes are auditable and repeatable
- We can update the live workflow with a single `python3 build_workflow.py` command

The alternative was building manually in the N8N UI, but that doesn't give us version history or the ability to reproduce the workflow from scratch.

---

## What We Learned

### Weflow Sync Timing

We initially worried about sync delays causing false positives. After analyzing 92 recordings over 2 days:

- **Most recordings sync within 1-2 hours** of meeting end
- The 7 AM check for yesterday's meetings catches the vast majority
- Recordings that don't appear within 24 hours are genuine gaps, not delayed syncs
- ~62% of Weflow recording objects in SFDC are **placeholders** — created at calendar sync time, never populated with transcripts

### Coverage Reality (Apr 7-8, 2026)

Spot-checked against FourFour (the other recording system) to understand the full picture:

| Status | Count | % |
|--------|-------|---|
| Both Weflow + FourFour captured | 6 | 46% |
| Weflow only | 4 | 31% |
| FourFour only | 0 | 0% |
| Neither system captured | 3 | 23% |
| **Weflow hit rate** | **10/13** | **76%** |

Weflow catches everything FourFour catches, plus more. FourFour syncs faster (minutes vs hours) but doesn't capture meetings Weflow misses.

### N8N Cloud Gotchas

Hit 10 bugs during development (full details in [BUILD-LOG.md](BUILD-LOG.md)). The key lessons:

1. **N8N Cloud cron uses instance timezone (PT), not UTC.** Our cron `0 14 * * *` was intended as 14:00 UTC = 7 AM PT, but actually ran at 2 PM PT.
2. **N8N's built-in Google OAuth doesn't auto-refresh.** Manual token refresh via HTTP Request node is more reliable.
3. **N8N Code nodes with 0 output items kill the pipeline.** Must return at least 1 sentinel item for the "empty" case — otherwise downstream nodes silently don't execute.
4. **N8N Cloud API has fewer endpoints than self-hosted.** `GET /credentials` returns 405. Don't assume all v1 endpoints exist.

### Data Verification Matters

When we first ran the report, 10 meetings showed as gaps. After investigation:
- 2 were cancelled meetings (no external attendees accepted) — fixed with acceptance filter
- 1 was an internal meeting with a personal Gmail — fixed with freemail exclusion
- 7 were genuine Weflow gaps

Always spot-check automated results against real data before trusting them.

---

## CSMs Monitored

### Growth
| Name | Calendar |
|------|----------|
| Debottama Mukherjee | debottama.mukherjee@hginsights.com |
| Nandini Yamdagni | nandini.yamdagni@hginsights.com |
| Himani Joshi | himani.joshi@hginsights.com |
| Sunabh Punjabi | sunabh.punjabi@hginsights.com |
| Meghan Whiteman | meghan.whiteman@hginsights.com |
| Ishant Mulani | ishant.mulani@hginsights.com |
| Brett Castonguay | brett.castonguay@hginsights.com |

### Enterprise (added Apr 17, 2026)
| Name | Title | Calendar |
|------|-------|----------|
| Divyam Dewan | CSM II | divyam.dewan@hginsights.com |
| Rani Guy | Strategic CSM | rani.guy@hginsights.com |
| Pam Huck | Enterprise CSM | pam.huck@hginsights.com |
| Nick Johnson | CSM II | nick.johnson@hginsights.com |
| Rishi Khushalani | Sr Customer Solutions Engineer | rishi.khushalani@hginsights.com |
| Andy Lim | CSM II | andy.lim@hginsights.com |
| Riley Rogers | Enterprise CSM | riley.rogers@hginsights.com |
| Varun Tiwari | CSM II | varun.tiwari@hginsights.com |
| Atisha Waghela | CSM II | atisha.waghela@hginsights.com |

## Known Limitations

- **Weflow-only** — doesn't check FourFour (Vitally) or Kaia (Outreach) transcripts
- **Zoom-only** — Weflow only records Zoom meetings; non-Zoom customer calls always appear as missing
- **PDT hardcoded** — date range assumes UTC-7 (Apr-Oct); needs UTC-8 update for Nov-Mar
- **CSMs only** — other GTM roles (AEs, BDAs, SEs beyond Rishi) not in scope

## Timeline

| Date | What |
|------|------|
| Apr 9 | Design spec written. Validated against live GCal + SFDC data. Built and deployed 27-node N8N workflow. Hit 8 bugs, all resolved same session. First Slack alert sent. |
| Apr 10 | Fixed cron timezone (was running at 2 PM instead of 7 AM). Added cancelled-meeting filter. Reduced false positives from 10 to 8. |
| Apr 12 | Added freemail exclusion (Gmail false positive). Fixed silent pipeline death on quiet days. Cross-referenced gaps against FourFour/Vitally. Verified Weflow sync timing (1-2 hours, not 24h). |
