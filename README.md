# Weflow Transcript Monitoring

Daily automated check for CSM customer meetings missing Weflow transcripts. Alerts to `#weflow-daily-alert` in Slack every weekday at 7 AM PT.

## Problem

No visibility into whether Weflow is actually recording and syncing transcripts for CSM meetings. Gaps were going undetected for weeks -- the team only found out when reviewing call notes and realizing meetings had no recordings.

## How It Works

```
GCal (7 CSM calendars)
  |
  v
N8N Workflow (daily cron)
  |-- Fetch yesterday's events from each CSM calendar
  |-- Filter: only meetings with corporate external attendees
  |-- Exclude: internal-only, freemail (Gmail/Yahoo), cancelled (0 accepted)
  |-- Deduplicate by iCalUID (shared meetings across CSMs)
  |
  v
SFDC Query
  |-- Match meeting iCalUIDs against Weflow__WeflowVideoRecording__c
  |-- Check which have transcripts (Weflow__Transcript__c != null)
  |
  v
Slack Alert (#weflow-daily-alert)
  |-- List meetings missing transcripts
  |-- Show meetings that have transcripts
  |-- "No meetings" message on quiet days
```

## Architecture

- **N8N Workflow** (`eKF3VvLs2yrvhKq6`) — 27-node workflow on HG Insights Operations N8N Cloud instance
- **Schedule** — `0 7 * * 1-5` (7 AM PT, Mon-Fri, N8N instance timezone = PT)
- **Google Calendar API** — direct HTTP with manual token refresh (more reliable than N8N's built-in OAuth)
- **Salesforce** — queries `Weflow__WeflowVideoRecording__c` via N8N's SFDC credential
- **Slack** — posts to `#weflow-daily-alert` via Andi Bot

## Filtering Logic

A meeting counts as "customer-facing" only if:

1. At least one attendee has a **corporate** email domain (not internal, not freemail)
2. At least one corporate external attendee **accepted** (filters out cancelled meetings)
3. The CSM didn't decline

**Internal domains excluded:** hginsights.com, hgdata.com, trustradius.com, madkudu.com

**Freemail domains excluded:** gmail.com, yahoo.com, hotmail.com, outlook.com, aol.com, icloud.com, protonmail.com, live.com, me.com, googlemail.com

## CSMs Monitored

| CSM | Calendar |
|-----|----------|
| Debottama Mukherjee | debottama.mukherjee@hginsights.com |
| Nandini Yamdagni | nandini.yamdagni@hginsights.com |
| Himani Joshi | himani.joshi@hginsights.com |
| Sunabh Punjabi | sunabh.punjabi@hginsights.com |
| Meghan Whiteman | meghan.whiteman@hginsights.com |
| Ishant Mulani | ishant.mulani@hginsights.com |
| Brett Castonguay | brett.castonguay@hginsights.com |

## Build Script

`build_workflow.py` defines all 27 N8N nodes as Python dicts and pushes them via the N8N REST API. Run once to create, re-run to update.

```bash
# Requires .env with N8N_API_KEY, N8N_BASE_URL
# Requires Google OAuth credentials file
python3 build_workflow.py
```

This is a **single-shot deployment script**, not a service. The workflow runs entirely in N8N Cloud. The script exists so the workflow definition lives in version control rather than only in the N8N UI.

## Key Findings

### Weflow Sync Timing
- Most recordings sync to SFDC within **1-2 hours** of meeting end
- The 7 AM check for yesterday's meetings catches the vast majority
- Recordings that don't appear within 24 hours are genuine gaps (not delayed syncs)

### Coverage (Week of Apr 7-8, 2026)
- **76% Weflow hit rate** on customer-facing meetings
- 46% captured by both Weflow and FourFour
- 31% Weflow-only
- 23% true gaps (neither system captured)

### FourFour vs Weflow
- FourFour syncs to Vitally Notes (faster initial sync, ~minutes)
- Weflow syncs to SFDC (1-2 hours)
- Both capture the same meetings -- Weflow catches everything FourFour catches plus more
- This monitor checks Weflow/SFDC only; FourFour is a separate system

## Related

- [N8N Workflow](https://hginsightsoperations.app.n8n.cloud/workflow/eKF3VvLs2yrvhKq6)
- Slack: `#weflow-daily-alert`
