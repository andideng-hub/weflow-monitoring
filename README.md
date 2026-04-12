# Weflow Transcript Monitoring

Daily automated check for CSM customer meetings missing Weflow transcripts. Alerts to `#weflow-daily-alert` in Slack every weekday at 7 AM PT.

## Setup

```bash
cp .env.example .env  # fill in N8N API key
python3 build_workflow.py
```

Pushes the full 27-node workflow to N8N Cloud. Re-run to update.

## How It Works

GCal (7 CSM calendars) → N8N workflow (daily cron) → SFDC Weflow transcript check → Slack alert

**Schedule:** `0 7 * * 1-5` (7 AM PT, Mon-Fri)

**Filtering:** Only flags meetings with corporate external attendees who accepted. Excludes internal domains, freemail (Gmail/Yahoo/etc.), cancelled meetings, and meetings the CSM declined.

## Structure

```
weflow-monitoring/
├── README.md              # This file
├── BRIEF.md               # Project story — problem, design, findings
├── BUILD-LOG.md           # Engineering journal — 10 bugs, root causes, fixes
├── EDGE-CASES.md          # Operational edge cases and coverage data
├── build_workflow.py      # N8N workflow deployment script (27 nodes)
├── .env.example           # Required credentials template
└── .gitignore
```

## Systems

| System | Role | Auth |
|--------|------|------|
| N8N Cloud | Workflow orchestration + cron | API key |
| Google Calendar | CSM meeting data (7 calendars) | OAuth refresh token |
| Salesforce | `Weflow__WeflowVideoRecording__c` transcript lookup | N8N SFDC credential |
| Slack | `#weflow-daily-alert` channel | Andi Bot |

## Docs

- [BRIEF.md](BRIEF.md) — Project context, design decisions, findings
- [BUILD-LOG.md](BUILD-LOG.md) — Engineering journal (10 bugs hit and resolved)
- [EDGE-CASES.md](EDGE-CASES.md) — Known edge cases and coverage snapshots
- [N8N Workflow](https://hginsightsoperations.app.n8n.cloud/workflow/eKF3VvLs2yrvhKq6) — Live workflow in N8N UI
