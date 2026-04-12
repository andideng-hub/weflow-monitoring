#!/usr/bin/env python3
"""
Build and push the Weflow Transcript Monitoring workflow to N8N.

Single-shot: run once to create the full workflow. Re-run to update.
All N8N nodes are defined here as Python dicts → pushed via REST API.
"""

import json, os, sys, urllib.request, urllib.parse
from pathlib import Path

# ── Load credentials ──────────────────────────────────────────────────────────

env = {}
for line in Path("/Users/andi.deng/Desktop/andi-ai/.env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

N8N_BASE = env["N8N_BASE_URL"].rstrip("/")
N8N_KEY = env["N8N_API_KEY"]
HEADERS = {"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}


def n8n(method, path, body=None, exit_on_error=True):
    url = f"{N8N_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        print(f"N8N API error: {e.code} {e.reason} — {err_body}")
        if exit_on_error:
            sys.exit(1)
        raise


# ── Google OAuth credential ──────────────────────────────────────────────────

google_creds_path = os.path.expanduser(
    "~/.google_workspace_mcp/credentials/andi.deng@hginsights.com.json"
)
with open(google_creds_path) as f:
    gcreds = json.load(f)

# Note: Google OAuth is handled by the "Refresh Google Token" HTTP node in the workflow.
# No N8N credential needed — the refresh_token/client creds are embedded in the node.

# ── Constants ─────────────────────────────────────────────────────────────────

SFDC_CRED_ID = "CbWF1JnPA0assjsx"
SLACK_CRED_ID = "iBeipcH2cF7I1QiU"
ANDI_SLACK_UID = "U09JRT0DHD2"
SFDC_URL = "https://hgdata.my.salesforce.com"

CSM_CALENDARS = [
    "debottama.mukherjee@hginsights.com",
    "nandini.yamdagni@hginsights.com",
    "himani.joshi@hginsights.com",
    "sunabh.punjabi@hginsights.com",
    "meghan.whiteman@hginsights.com",
    "ishant.mulani@hginsights.com",
    "brett.castonguay@hginsights.com",
]


def pos(x, y):
    return [x, y]


# ── Node Definitions ─────────────────────────────────────────────────────────

# 1. Schedule Trigger: 7 AM PT = 14:00 UTC daily
schedule_trigger = {
    "id": "schedule_trigger",
    "name": "Daily 7 AM PT",
    "type": "n8n-nodes-base.scheduleTrigger",
    "typeVersion": 1.3,
    "position": pos(0, 0),
    "parameters": {
        "rule": {
            "interval": [{"field": "cronExpression", "expression": "0 7 * * 1-5"}]
        }
    },
}

# 2. Manual Trigger: for testing in UI
manual_trigger = {
    "id": "manual_trigger",
    "name": "Manual Test Trigger",
    "type": "n8n-nodes-base.manualTrigger",
    "typeVersion": 1,
    "position": pos(0, 200),
    "parameters": {},
}

# 2b. Webhook Trigger: for testing from CLI
webhook_trigger = {
    "id": "webhook_trigger",
    "name": "Webhook Test Trigger",
    "type": "n8n-nodes-base.webhook",
    "typeVersion": 2,
    "position": pos(0, 400),
    "parameters": {
        "path": "weflow-monitoring-test",
        "httpMethod": "GET",
        "responseMode": "lastNode",
        "options": {},
    },
    "webhookId": "weflow-test-hook",
}

# 3. Date Range Code Node
date_range_code = {
    "id": "date_range",
    "name": "Compute Date Range",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(300, 100),
    "parameters": {
        "jsCode": """
// Compute yesterday's date range in Pacific Time (PDT = UTC-7, PST = UTC-8)
const nowUtc = new Date();

// "Today" midnight PT in UTC = today 07:00 UTC (PDT season: Apr-Oct)
const todayMidnightPT = new Date(nowUtc);
todayMidnightPT.setUTCHours(7, 0, 0, 0);

// If we're before 07:00 UTC, "today midnight PT" is actually yesterday in UTC terms
if (nowUtc.getUTCHours() < 7) {
  todayMidnightPT.setUTCDate(todayMidnightPT.getUTCDate() - 1);
}

const timeMax = todayMidnightPT.toISOString();
const timeMin = new Date(todayMidnightPT.getTime() - 24 * 60 * 60 * 1000).toISOString();

// Human-readable date for Slack
const yesterdayNoon = new Date(todayMidnightPT.getTime() - 12 * 60 * 60 * 1000);
const dateLabel = yesterdayNoon.toLocaleDateString('en-US', {
  weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  timeZone: 'America/Los_Angeles'
});

return [{ json: { timeMin, timeMax, dateLabel } }];
"""
    },
}

# 4. Refresh Google Token — POST to Google OAuth token endpoint
refresh_google_token = {
    "id": "refresh_google",
    "name": "Refresh Google Token",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": pos(480, 100),
    "parameters": {
        "method": "POST",
        "url": "https://oauth2.googleapis.com/token",
        "authentication": "none",
        "sendBody": True,
        "contentType": "form-urlencoded",
        "bodyParameters": {
            "parameters": [
                {"name": "client_id", "value": gcreds["client_id"]},
                {"name": "client_secret", "value": gcreds["client_secret"]},
                {"name": "refresh_token", "value": gcreds["refresh_token"]},
                {"name": "grant_type", "value": "refresh_token"},
            ]
        },
        "options": {},
    },
}

# 5-11. GCal HTTP Request nodes (one per CSM) — use Bearer token from refresh node
gcal_nodes = []
for i, email in enumerate(CSM_CALENDARS):
    encoded_email = urllib.parse.quote(email, safe="")
    gcal_nodes.append({
        "id": f"gcal_{i}",
        "name": f"GCal: {email.split('.')[0].title()}",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": pos(700, i * 110 - 330),
        "parameters": {
            "method": "GET",
            "url": f"https://www.googleapis.com/calendar/v3/calendars/{encoded_email}/events",
            "authentication": "genericCredentialType",
            "genericAuthType": "none",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "=Bearer {{ $('Refresh Google Token').first().json.access_token }}"},
                ]
            },
            "sendQuery": True,
            "queryParameters": {
                "parameters": [
                    {"name": "timeMin", "value": "={{ $('Compute Date Range').first().json.timeMin }}"},
                    {"name": "timeMax", "value": "={{ $('Compute Date Range').first().json.timeMax }}"},
                    {"name": "singleEvents", "value": "true"},
                    {"name": "orderBy", "value": "startTime"},
                    {"name": "maxResults", "value": "50"},
                ]
            },
            "options": {},
        },
    })

# 12-18. Tag nodes: inject calendarId into each GCal response
tag_nodes = []
for i, email in enumerate(CSM_CALENDARS):
    tag_nodes.append({
        "id": f"tag_{i}",
        "name": f"Tag: {email.split('.')[0].title()}",
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": pos(930, i * 110 - 330),
        "parameters": {
            "mode": "manual",
            "duplicateItem": False,
            "assignments": {
                "assignments": [
                    {"id": f"cal_{i}", "name": "calendarId", "value": email, "type": "string"},
                ]
            },
            "includeOtherFields": True,
            "options": {},
        },
    })

# 18. Merge all GCal results
merge_gcal = {
    "id": "merge_gcal",
    "name": "Merge GCal Results",
    "type": "n8n-nodes-base.merge",
    "typeVersion": 3.2,
    "position": pos(1000, 0),
    "parameters": {"mode": "append", "numberInputs": len(CSM_CALENDARS)},
}

# 19. Filter + Dedup Code Node
filter_dedup_code = {
    "id": "filter_dedup",
    "name": "Filter + Dedup",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(1200, 0),
    "parameters": {
        "mode": "runOnceForAllItems",
        "jsCode": """
const INTERNAL_DOMAINS = ["hginsights.com", "hgdata.com", "trustradius.com", "madkudu.com", "smoothoperator.cc"];
const FREEMAIL_DOMAINS = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
  "aol.com", "icloud.com", "protonmail.com", "live.com", "me.com", "googlemail.com"];

function getDomain(email) {
  return (email || "").split("@")[1] || "";
}
function isExternal(email) {
  const d = getDomain(email);
  return !INTERNAL_DOMAINS.includes(d) && !FREEMAIL_DOMAINS.includes(d);
}

const seen = {};

for (const item of $input.all()) {
  const calendarId = item.json.calendarId;
  const events = item.json.items || [];

  for (const ev of events) {
    const attendees = ev.attendees || [];
    const external = attendees.filter(a => isExternal(a.email || ""));
    if (external.length === 0) continue;

    const allDeclined = attendees.length > 0 &&
      attendees.every(a => a.responseStatus === "declined");
    if (allDeclined) continue;

    const iCalUID = ev.iCalUID || ev.id;

    // Skip only if ALL external attendees declined (matches CSM reviews logic)
    const extNotDeclined = external.filter(a => a.responseStatus !== "declined");
    if (extNotDeclined.length === 0) continue;

    if (seen[iCalUID]) {
      if (!seen[iCalUID].csms.includes(calendarId)) {
        seen[iCalUID].csms.push(calendarId);
      }
    } else {
      seen[iCalUID] = {
        iCalUID,
        summary: ev.summary || "(no title)",
        externalCount: external.length,
        csms: [calendarId],
      };
    }
  }
}

const meetings = Object.values(seen);
if (meetings.length === 0) {
  return [{ json: { noMeetings: true } }];
}
return meetings.map(m => ({ json: m }));
""",
    },
}

# 20. Build SOQL Code Node
build_soql_code = {
    "id": "build_soql",
    "name": "Build SOQL",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(1400, 0),
    "parameters": {
        "mode": "runOnceForAllItems",
        "jsCode": r"""
const meetings = $input.all().map(i => i.json).filter(m => !m.noMeetings);
if (meetings.length === 0) {
  return [{ json: { soql: "", meetingCount: 0, noMeetings: true } }];
}
const ids = meetings.map(m => `'${m.iCalUID.replace(/'/g, "\\'")}'`).join(",");
const soql = `SELECT Id, Name, Weflow__EventId__c, Weflow__Transcript__c FROM Weflow__WeflowVideoRecording__c WHERE Weflow__EventId__c IN (${ids})`;
return [{ json: { soql, meetingCount: meetings.length, noMeetings: false } }];
""",
    },
}

# 21. IF node: skip SFDC query if no meetings
if_has_meetings = {
    "id": "if_meetings",
    "name": "Has Meetings?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 2.3,
    "position": pos(1600, 0),
    "parameters": {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": ""},
            "combinator": "and",
            "conditions": [
                {
                    "leftValue": "={{ $json.noMeetings }}",
                    "rightValue": False,
                    "operator": {"type": "boolean", "operation": "equals"},
                }
            ],
        }
    },
}

# 22. SFDC HTTP Request: Weflow transcript query
sfdc_query = {
    "id": "sfdc_query",
    "name": "SFDC Weflow Query",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": pos(1800, -50),
    "credentials": {
        "salesforceOAuth2Api": {
            "id": SFDC_CRED_ID,
            "name": "Salesforce account 2",
        }
    },
    "parameters": {
        "method": "GET",
        "url": f"{SFDC_URL}/services/data/v58.0/query",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "salesforceOAuth2Api",
        "sendQuery": True,
        "queryParameters": {
            "parameters": [
                {"name": "q", "value": "={{ $('Build SOQL').first().json.soql }}"}
            ]
        },
        "options": {},
    },
}

# 23. Transcript Check Code Node
transcript_check_code = {
    "id": "transcript_check",
    "name": "Transcript Check",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(2000, -50),
    "parameters": {
        "mode": "runOnceForAllItems",
        "jsCode": """
// Build lookup: iCalUID -> has transcript
const sfdc = $input.all().map(i => i.json);
const transcriptMap = {};
for (const rec of sfdc) {
  const records = rec.records || [];
  for (const r of records) {
    const eid = r.Weflow__EventId__c;
    const hasTranscript = r.Weflow__Transcript__c !== null &&
                          r.Weflow__Transcript__c !== undefined &&
                          r.Weflow__Transcript__c !== "";
    transcriptMap[eid] = hasTranscript;
  }
}

// Get meetings from Filter + Dedup node
const meetings = $('Filter + Dedup').all().map(i => i.json);

const gaps = [];
const covered = [];

for (const m of meetings) {
  // Format CSM names from email
  const csmNames = m.csms.map(e => {
    const parts = e.split('@')[0].split('.');
    return parts.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
  }).join(', ');

  if (transcriptMap[m.iCalUID] === true) {
    const firstNames = m.csms.map(e => e.split('.')[0])
      .map(n => n.charAt(0).toUpperCase() + n.slice(1));
    covered.push(m.summary + ' (' + firstNames.join('+') + ')');
  } else {
    const countStr = m.externalCount === 1
      ? '1 customer attendee'
      : m.externalCount + ' customer attendees';
    gaps.push('\\u2022 ' + m.summary + ' (' + csmNames + ') — ' + countStr);
  }
}

return [{ json: { gaps, covered, gapCount: gaps.length } }];
""",
    },
}

# 24. Format Slack Message Code Node
slack_format_code = {
    "id": "slack_format",
    "name": "Format Slack Message",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(2200, 0),
    "parameters": {
        "jsCode": """
const dateLabel = $('Compute Date Range').first().json.dateLabel;

// Check if we came from the "no meetings" path
const buildSoql = $('Build SOQL').first().json;
if (buildSoql.noMeetings) {
  return [{ json: {
    message: '\\u2705 *Weflow Transcript Report — ' + dateLabel + '*\\nNo CSM customer meetings found for yesterday.'
  }}];
}

const { gaps, covered, gapCount } = $('Transcript Check').first().json;

let message;
if (gapCount === 0) {
  message = '\\u2705 *Weflow Transcript Report — ' + dateLabel + '*\\nAll CSM customer meetings from yesterday have transcripts.';
} else {
  const gapList = gaps.join('\\n');
  const coveredSummary = covered.length > 0
    ? '\\n\\n\\u2705 *Have transcripts (' + covered.length + '):* ' + covered.join(', ')
    : '';
  message = '\\ud83d\\udccb *Weflow Transcript Report — ' + dateLabel + '*\\n\\nMissing Weflow transcripts from yesterday\\'s CSM meetings:\\n\\n' + gapList + coveredSummary;
}

return [{ json: { message } }];
""",
    },
}

# 25. Slack DM Node
slack_dm = {
    "id": "slack_dm",
    "name": "Slack: #weflow-daily-alert",
    "type": "n8n-nodes-base.slack",
    "typeVersion": 2.4,
    "position": pos(2400, 0),
    "credentials": {
        "slackApi": {"id": SLACK_CRED_ID, "name": "Andi Slack Bot"}
    },
    "parameters": {
        "select": "channel",
        "channelId": {"__rl": True, "value": "C0ART2QD1U5", "mode": "id"},
        "text": "={{ $json.message }}",
        "otherOptions": {},
    },
}

# ── Assemble workflow ─────────────────────────────────────────────────────────

NODES = [
    schedule_trigger,
    manual_trigger,
    webhook_trigger,
    date_range_code,
    refresh_google_token,
    *gcal_nodes,
    *tag_nodes,
    merge_gcal,
    filter_dedup_code,
    build_soql_code,
    if_has_meetings,
    sfdc_query,
    transcript_check_code,
    slack_format_code,
    slack_dm,
]

# ── Build connections ─────────────────────────────────────────────────────────

CONNECTIONS = {
    # Both triggers → Date Range
    "Daily 7 AM PT": {"main": [[{"node": "Compute Date Range", "type": "main", "index": 0}]]},
    "Manual Test Trigger": {"main": [[{"node": "Compute Date Range", "type": "main", "index": 0}]]},
    "Webhook Test Trigger": {"main": [[{"node": "Compute Date Range", "type": "main", "index": 0}]]},
    # Date Range → Refresh Token → all 7 GCal nodes (fan-out)
    "Compute Date Range": {"main": [[{"node": "Refresh Google Token", "type": "main", "index": 0}]]},
    "Refresh Google Token": {"main": [[]]},
}

for i, email in enumerate(CSM_CALENDARS):
    first_name = email.split(".")[0].title()
    gcal_name = f"GCal: {first_name}"
    tag_name = f"Tag: {first_name}"

    CONNECTIONS["Refresh Google Token"]["main"][0].append(
        {"node": gcal_name, "type": "main", "index": 0}
    )
    CONNECTIONS[gcal_name] = {
        "main": [[{"node": tag_name, "type": "main", "index": 0}]]
    }
    CONNECTIONS[tag_name] = {
        "main": [[{"node": "Merge GCal Results", "type": "main", "index": i}]]
    }

CONNECTIONS["Merge GCal Results"] = {
    "main": [[{"node": "Filter + Dedup", "type": "main", "index": 0}]]
}
CONNECTIONS["Filter + Dedup"] = {
    "main": [[{"node": "Build SOQL", "type": "main", "index": 0}]]
}
CONNECTIONS["Build SOQL"] = {
    "main": [[{"node": "Has Meetings?", "type": "main", "index": 0}]]
}
# IF node: true (has meetings) → SFDC query; false (no meetings) → format Slack
CONNECTIONS["Has Meetings?"] = {
    "main": [
        [{"node": "SFDC Weflow Query", "type": "main", "index": 0}],
        [{"node": "Format Slack Message", "type": "main", "index": 0}],
    ]
}
CONNECTIONS["SFDC Weflow Query"] = {
    "main": [[{"node": "Transcript Check", "type": "main", "index": 0}]]
}
CONNECTIONS["Transcript Check"] = {
    "main": [[{"node": "Format Slack Message", "type": "main", "index": 0}]]
}
CONNECTIONS["Format Slack Message"] = {
    "main": [[{"node": "Slack: #weflow-daily-alert", "type": "main", "index": 0}]]
}

# ── Push to N8N ───────────────────────────────────────────────────────────────

WORKFLOW = {
    "name": "Weflow Transcript Monitoring",
    "nodes": NODES,
    "connections": CONNECTIONS,
    "settings": {"executionOrder": "v1"},
}

workflows = n8n("GET", "/workflows")
existing_wf = [
    w for w in workflows.get("data", [])
    if w["name"] == "Weflow Transcript Monitoring"
]

if existing_wf:
    wf_id = existing_wf[0]["id"]
    n8n("PUT", f"/workflows/{wf_id}", WORKFLOW)
    print(f"Updated workflow: {wf_id}")
else:
    result = n8n("POST", "/workflows", WORKFLOW)
    wf_id = result["id"]
    print(f"Created workflow: {wf_id}")

print(f"\nWorkflow ID: {wf_id}")
print(f"Nodes: {len(NODES)}")
print(f"Open: https://hginsightsoperations.app.n8n.cloud/workflow/{wf_id}")
print("\nNext: open in N8N UI → click 'Manual Test Trigger' → run full workflow")
