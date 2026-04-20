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

# Shared filter constants (C1/S1) — single source of truth across weflow-monitoring
# and csm-weekly-review. Any domain add/remove goes in this one JSON file.
FILTER_CONSTANTS = json.load(open(
    "/Users/andi.deng/Desktop/andi-ai/data/config/meeting-filter-constants.json"
))

# ── Constants ─────────────────────────────────────────────────────────────────

SFDC_CRED_ID = "CbWF1JnPA0assjsx"
SLACK_CRED_ID = "iBeipcH2cF7I1QiU"
ANDI_SLACK_UID = "U09JRT0DHD2"
SFDC_URL = "https://hgdata.my.salesforce.com"

SHEET_ID = "1vhSMV2TcmLidUQhaCpXKQNjP_AmKirtFOYq-JhFM3W8"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

# Weflow Issue Log — RevOps-facing triage queue. Gap rows appended here daily.
ISSUE_LOG_SHEET_ID = "1rmPepjRWBPDFXYzSdFLasxdPcnp8yPa7N2guS6im-B0"

GROWTH_CSMS = [
    "debottama.mukherjee@hginsights.com",
    "nandini.yamdagni@hginsights.com",
    "himani.joshi@hginsights.com",
    "sunabh.punjabi@hginsights.com",
    "meghan.whiteman@hginsights.com",
    "ishant.mulani@hginsights.com",
    "brett.castonguay@hginsights.com",
]
ENT_CSMS = [
    "divyam.dewan@hginsights.com",
    "rani.guy@hginsights.com",
    "pam.huck@hginsights.com",
    "nick.johnson@hginsights.com",
    "andy.lim@hginsights.com",
    "riley.rogers@hginsights.com",
    "varun.tiwari@hginsights.com",
    "atisha.waghela@hginsights.com",
]
CSM_CALENDARS = GROWTH_CSMS + ENT_CSMS


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
            "interval": [{"field": "cronExpression", "expression": "0 7 * * 1-6"}]
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
        # "onReceived" returns 200 immediately — avoids "No item to return" when
        # parallel branches (retry chain) hit dead-end terminals.
        "responseMode": "onReceived",
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
// Compute date range in Pacific Time (PDT = UTC-7, PST = UTC-8).
//   Mon (dayOfWeek=1): mode="weekly"  — summary of prior week (no GCal/SFDC query)
//   Tue-Sat (2-6):     mode="daily"   — check yesterday's meetings
const nowUtc = new Date();

// "Today" midnight PT in UTC = today 07:00 UTC (PDT season: Apr-Oct)
const todayMidnightPT = new Date(nowUtc);
todayMidnightPT.setUTCHours(7, 0, 0, 0);
if (nowUtc.getUTCHours() < 7) {
  todayMidnightPT.setUTCDate(todayMidnightPT.getUTCDate() - 1);
}

const todayPT = new Date(todayMidnightPT.getTime() - 1);
const dayOfWeek = todayPT.getUTCDay();
const mode = (dayOfWeek === 1) ? "weekly" : "daily";

const fmtDay = (d, opts) => d.toLocaleDateString('en-US', { timeZone: 'America/Los_Angeles', ...opts });
// en-CA gives YYYY-MM-DD, matching the sheet's alert_date column format
const isoDate = (d) => d.toLocaleDateString('en-CA', { timeZone: 'America/Los_Angeles' });

let timeMin, timeMax, dateLabel, weeklyMin, weeklyMax;

if (mode === "weekly") {
  // Last week's meeting dates = previous Mon through previous Fri
  const lastMon = new Date(todayMidnightPT.getTime() - 7 * 86400000);
  const lastFri = new Date(todayMidnightPT.getTime() - 3 * 86400000);
  // Alert-date range in the sheet = Tue..Sat of previous week
  // (Tue alerted Mon meetings ... Sat alerted Fri meetings)
  const lastTue = new Date(todayMidnightPT.getTime() - 6 * 86400000);
  const lastSat = new Date(todayMidnightPT.getTime() - 2 * 86400000);
  weeklyMin = isoDate(lastTue);
  weeklyMax = isoDate(lastSat);

  const startLabel = fmtDay(lastMon, { month: 'short', day: 'numeric' });
  const endLabel = fmtDay(lastFri, { month: 'short', day: 'numeric' });
  dateLabel = startLabel + ' to ' + endLabel;

  // GCal window unused in weekly mode but kept for shape consistency
  timeMin = todayMidnightPT.toISOString();
  timeMax = todayMidnightPT.toISOString();
} else {
  // Daily: yesterday only
  timeMax = todayMidnightPT.toISOString();
  timeMin = new Date(todayMidnightPT.getTime() - 86400000).toISOString();
  const yesterdayNoon = new Date(todayMidnightPT.getTime() - 12 * 60 * 60 * 1000);
  dateLabel = yesterdayNoon.toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
    timeZone: 'America/Los_Angeles'
  });
  weeklyMin = "";
  weeklyMax = "";
}

return [{ json: { mode, timeMin, timeMax, dateLabel, weeklyMin, weeklyMax } }];
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

# ── Retry Stale Gaps (runs alongside daily flow; does not affect Slack alert) ──
# Re-query SFDC for recent ❌ Gap rows — if Weflow synced late, update sheet
# status to ✅ Covered and remove the row from the Weflow Issue Log.

# 4a. Retry: Collect Stale — read main sheet, filter ❌ Gap rows in last 3 days
retry_collect_stale = {
    "id": "retry_collect_stale",
    "name": "Retry: Collect Stale",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(480, 400),
    "parameters": {
        "jsCode": f"""
const token = $('Refresh Google Token').first().json.access_token;
const resp = await this.helpers.httpRequest({{
  method: 'GET',
  url: 'https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sheet1!A:K',
  headers: {{ Authorization: 'Bearer ' + token }},
  json: true,
}});
const rows = resp.values || [];
// today in PT, YYYY-MM-DD
const todayPT = new Date().toLocaleDateString('en-CA', {{ timeZone: 'America/Los_Angeles' }});
const cutoff = new Date(todayPT + 'T00:00:00Z');
cutoff.setUTCDate(cutoff.getUTCDate() - 3);
const cutoffStr = cutoff.toISOString().slice(0, 10);

// Row indexes are 1-based in Sheets API; +1 for header offset
const stale = [];
for (let i = 1; i < rows.length; i++) {{
  const r = rows[i];
  if (!r || r.length < 5) continue;
  const alertDate = r[0];
  const status = r[4] || '';
  if (!status.includes('Gap')) continue;
  if (!alertDate || alertDate < cutoffStr) continue;
  const instanceId = r[9] || '';
  let iCalUID = r[10] || '';
  // Fallback for rows written before col K existed: try instanceId + @google.com.
  // Works for non-recurring meetings; recurring instances won't match, we skip.
  if (!iCalUID && instanceId && !instanceId.includes('_')) {{
    iCalUID = instanceId + '@google.com';
  }}
  if (!iCalUID) continue;
  stale.push({{ rowIdx: i + 1, iCalUID, instanceId, alertDate }});
}}

if (stale.length === 0) return [{{ json: {{ noStale: true, stale: [] }} }}];

const icalIds = stale.map(s => "'" + s.iCalUID.replace(/'/g, "\\\\'") + "'").join(',');
const soql = `SELECT Id, Weflow__EventId__c, Weflow__Transcript__c, Weflow__RecordingId__c FROM Weflow__WeflowVideoRecording__c WHERE Weflow__EventId__c IN (${{icalIds}})`;
return [{{ json: {{ noStale: false, stale, soql }} }}];
""",
    },
}

# 4b. Retry: Has Stale? — gate
retry_if_stale = {
    "id": "retry_if_stale",
    "name": "Retry: Has Stale?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 2.3,
    "position": pos(680, 400),
    "parameters": {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": ""},
            "combinator": "and",
            "conditions": [{
                "leftValue": "={{ $json.noStale }}",
                "rightValue": False,
                "operator": {"type": "boolean", "operation": "equals"},
            }],
        }
    },
}

# 4c. Retry: SFDC Query — uses SFDC OAuth credential
retry_sfdc_query = {
    "id": "retry_sfdc_query",
    "name": "Retry: SFDC Query",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": pos(880, 400),
    "credentials": {
        "salesforceOAuth2Api": {"id": SFDC_CRED_ID, "name": "Salesforce account 2"}
    },
    "parameters": {
        "method": "GET",
        "url": f"{SFDC_URL}/services/data/v58.0/query",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "salesforceOAuth2Api",
        "sendQuery": True,
        "queryParameters": {
            "parameters": [
                {"name": "q", "value": "={{ $('Retry: Collect Stale').first().json.soql }}"}
            ]
        },
        "options": {},
    },
}

# 4d. Retry: Apply Updates — batchUpdate main sheet + delete from Issue Log
retry_apply_updates = {
    "id": "retry_apply_updates",
    "name": "Retry: Apply Updates",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(1080, 400),
    "parameters": {
        "jsCode": f"""
// Wrap the whole retry in try/catch so a failure surfaces as a Slack alert (L3)
// instead of silently disappearing into the n8n execution log.
try {{
  const sfdc = $input.first().json.records || [];
  const stale = $('Retry: Collect Stale').first().json.stale || [];
  const token = $('Refresh Google Token').first().json.access_token;

  // Map iCalUID → {{recordingId, hasTranscript}}
  const sfMap = {{}};
  for (const r of sfdc) {{
    const hasT = r.Weflow__Transcript__c !== null && r.Weflow__Transcript__c !== undefined && r.Weflow__Transcript__c !== '';
    sfMap[r.Weflow__EventId__c] = {{
      recordingId: r.Id || '',
      hasTranscript: hasT,
    }};
  }}

  // Find stale rows now covered
  const recovered = [];
  for (const s of stale) {{
    const m = sfMap[s.iCalUID];
    if (m && m.hasTranscript) recovered.push({{ ...s, recordingId: m.recordingId }});
  }}

  if (recovered.length === 0) {{
    return [{{ json: {{ recoveredCount: 0, note: 'no stale gaps recovered', error: '' }} }}];
  }}

  // 1. batchUpdate main sheet: col E (status) + col I (recordingId)
  const data = [];
  for (const r of recovered) {{
    data.push({{ range: `Sheet1!E${{r.rowIdx}}`, values: [['\u2705 Covered']] }});
    data.push({{ range: `Sheet1!I${{r.rowIdx}}`, values: [[r.recordingId]] }});
  }}
  await this.helpers.httpRequest({{
    method: 'POST',
    url: 'https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchUpdate',
    headers: {{ Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }},
    json: true,
    body: {{ valueInputOption: 'RAW', data }},
  }});

  // 2. Remove recovered gaps from Issue Log sheet — match by (title, csm, date) (B1)
  //    Issue log schema: [Issue(A), Status(B), Meeting Title(C), CSM(D), Meeting Date(E)]
  //    Main sheet schema: alert_date, ptDateTime, csms(C=2), team, status, title(F=5), ...
  //    Including CSM avoids collisions when two different meetings share title+date.
  const ilResp = await this.helpers.httpRequest({{
    method: 'GET',
    url: 'https://sheets.googleapis.com/v4/spreadsheets/{ISSUE_LOG_SHEET_ID}/values/Issues!A:E',
    headers: {{ Authorization: 'Bearer ' + token }},
    json: true,
  }});
  const ilRows = ilResp.values || [];

  const mainResp = await this.helpers.httpRequest({{
    method: 'GET',
    url: 'https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sheet1!A:K',
    headers: {{ Authorization: 'Bearer ' + token }},
    json: true,
  }});
  const mainRows = mainResp.values || [];
  const recoveredKeys = new Set();
  for (const r of recovered) {{
    const mr = mainRows[r.rowIdx - 1];
    if (!mr) continue;
    const title = mr[5] || '';
    const csms = mr[2] || '';
    const meetingDate = (mr[1] || '').split(' ')[0];  // "YYYY-MM-DD HH:MM" → "YYYY-MM-DD"
    recoveredKeys.add(title + '|' + csms + '|' + meetingDate);
  }}

  const issueRowsToDelete = [];
  for (let i = 1; i < ilRows.length; i++) {{
    const r = ilRows[i];
    if (!r) continue;
    // Issue Log: title=C(2), csm=D(3), date=E(4)
    const key = (r[2] || '') + '|' + (r[3] || '') + '|' + (r[4] || '');
    if (recoveredKeys.has(key)) issueRowsToDelete.push(i + 1);
  }}

  issueRowsToDelete.sort((a, b) => b - a);
  for (const row of issueRowsToDelete) {{
    await this.helpers.httpRequest({{
      method: 'POST',
      url: 'https://sheets.googleapis.com/v4/spreadsheets/{ISSUE_LOG_SHEET_ID}:batchUpdate',
      headers: {{ Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }},
      json: true,
      body: {{
        requests: [{{
          deleteDimension: {{
            range: {{ sheetId: 0, dimension: 'ROWS', startIndex: row - 1, endIndex: row }}
          }}
        }}]
      }},
    }});
  }}

  return [{{ json: {{
    recoveredCount: recovered.length,
    sheetsUpdated: recovered.length,
    issueLogRowsDeleted: issueRowsToDelete.length,
    error: '',
  }} }}];
}} catch (err) {{
  return [{{ json: {{
    recoveredCount: 0,
    error: (err && err.message) ? err.message.slice(0, 500) : String(err).slice(0, 500),
    stack: (err && err.stack) ? err.stack.split('\\n').slice(0, 3).join(' | ') : '',
  }} }}];
}}
""",
    },
}

# 4e. Retry: Had Error? — route to Slack alert if retry threw
retry_had_error = {
    "id": "retry_had_error",
    "name": "Retry: Had Error?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 2.3,
    "position": pos(1280, 400),
    "parameters": {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": ""},
            "combinator": "and",
            "conditions": [{
                "leftValue": "={{ $json.error }}",
                "rightValue": "",
                "operator": {"type": "string", "operation": "notEmpty"},
            }],
        }
    },
}

# 4f. Retry: Format Error Slack Message
retry_error_format = {
    "id": "retry_error_format",
    "name": "Retry: Format Error Slack",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(1480, 400),
    "parameters": {
        "jsCode": """
const { error, stack } = $json;
const message = '\\u26a0\\ufe0f *Weflow Retry Failed* \\n' +
  '`' + (error || 'unknown error').replace(/`/g, '\\'') + '`\\n' +
  (stack ? '_trace:_ `' + stack.replace(/`/g, '\\'') + '`' : '');
return [{ json: { message } }];
"""
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
// C1/S1: INTERNAL_DOMAINS + FREEMAIL_DOMAINS loaded from shared JSON config
// at /Users/andi.deng/Desktop/andi-ai/data/config/meeting-filter-constants.json
// so weflow-monitoring and csm-weekly-review stay in sync.
const INTERNAL_DOMAINS = """ + json.dumps(FILTER_CONSTANTS["INTERNAL_DOMAINS"]) + """;
const FREEMAIL_DOMAINS = """ + json.dumps(FILTER_CONSTANTS["FREEMAIL_DOMAINS"]) + """;

function getDomain(email) {
  return (email || "").split("@")[1] || "";
}
function isExternal(email) {
  const d = getDomain(email);
  return !INTERNAL_DOMAINS.includes(d) && !FREEMAIL_DOMAINS.includes(d);
}

const seen = {};

// Filter logic aligned with csm-weekly-review (single source of truth for
// "is this a meeting we care about?"):
//   - exclude gmail/yahoo/etc. addresses that share a prefix with an
//     internal attendee (e.g. someone@gmail.com where someone@hginsights.com
//     is also on the invite — personal alias, not a real external)
//   - skip the meeting entirely if the CSM themselves declined
//   - skip if all externals declined (no-show). `needsAction` is kept as a
//     legitimate pending invite rather than treated as no-show.
for (const item of $input.all()) {
  const calendarId = item.json.calendarId;
  const events = item.json.items || [];

  for (const ev of events) {
    const attendees = ev.attendees || [];

    // Internal attendee name prefixes (for gmail-match exclusion)
    const internalPrefixes = new Set(
      attendees
        .filter(a => a.email && !isExternal(a.email))
        .map(a => a.email.split("@")[0].toLowerCase().replace(/\\./g, ""))
    );

    const external = attendees.filter(a => {
      if (!isExternal(a.email || "")) return false;
      const prefix = (a.email || "").split("@")[0].toLowerCase().replace(/\\./g, "");
      return !internalPrefixes.has(prefix);
    });
    if (external.length === 0) continue;

    // Skip if the CSM (calendar owner) declined — meeting didn't happen on their side
    const csmAtt = attendees.find(a => a.email === calendarId);
    if (csmAtt && csmAtt.responseStatus === "declined") continue;

    // Skip if all externals declined (effective no-show)
    const nonDeclined = external.filter(a => a.responseStatus !== "declined");
    if (nonDeclined.length === 0) continue;

    const iCalUID = ev.iCalUID || ev.id;

    if (seen[iCalUID]) {
      if (!seen[iCalUID].csms.includes(calendarId)) {
        seen[iCalUID].csms.push(calendarId);
      }
    } else {
      const firstExt = external[0] || {};
      seen[iCalUID] = {
        iCalUID,
        instanceId: ev.id,
        summary: ev.summary || "(no title)",
        externalCount: external.length,
        csms: [calendarId],
        startIso: ev.start && (ev.start.dateTime || ev.start.date) || "",
        customerDomain: getDomain(firstExt.email || ""),
        externalResponses: external.map(a => a.responseStatus || "needsAction"),
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
        "jsCode": f"""
// Build lookup: iCalUID -> {{recordingId, hasTranscript}}
const sfdc = $input.all().map(i => i.json);
const sfMap = {{}};
for (const rec of sfdc) {{
  const records = rec.records || [];
  for (const r of records) {{
    const eid = r.Weflow__EventId__c;
    const hasTranscript = r.Weflow__Transcript__c !== null &&
                          r.Weflow__Transcript__c !== undefined &&
                          r.Weflow__Transcript__c !== "";
    sfMap[eid] = {{ recordingId: r.Id || "", hasTranscript }};
  }}
}}

const GROWTH = new Set({json.dumps(GROWTH_CSMS)});
const ENT = new Set({json.dumps(ENT_CSMS)});
function teamOf(email) {{
  if (GROWTH.has(email)) return "Growth";
  if (ENT.has(email)) return "ENT";
  return "";
}}
function teamLabel(csms) {{
  const teams = new Set(csms.map(teamOf).filter(Boolean));
  if (teams.size === 0) return "";
  if (teams.size === 1) return [...teams][0];
  return "Mixed";
}}
function nameFromEmail(email) {{
  return email.split('@')[0].split('.').map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
}}
function ptDateTime(iso) {{
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-CA', {{
    timeZone: 'America/Los_Angeles',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false
  }}).replace(',', '');
}}

const alertDate = new Date().toLocaleDateString('en-CA', {{ timeZone: 'America/Los_Angeles' }});
const meetings = $('Filter + Dedup').all().map(i => i.json);

let gapCount = 0, coveredCount = 0, skippedCount = 0;
const sheetValues = [];

for (const m of meetings) {{
  const sf = sfMap[m.iCalUID] || {{ recordingId: "", hasTranscript: false }};

  // Transcript-first: if Weflow recorded it, the meeting happened. Period.
  // Aligned with csm-weekly-review: needsAction is kept as legitimate pending
  // (not treated as no-show). Filter + Dedup already dropped all-declined +
  // csm-declined meetings, so no further RSVP gating needed here.

  const status = sf.hasTranscript ? "✅ Covered" : "❌ Gap";
  if (sf.hasTranscript) coveredCount++; else gapCount++;

  const csmNames = m.csms.map(nameFromEmail).join(", ");
  sheetValues.push([
    alertDate,
    ptDateTime(m.startIso),
    csmNames,
    teamLabel(m.csms),
    status,
    m.summary,
    m.customerDomain || "",
    m.externalCount,
    sf.recordingId,
    m.instanceId,  // unique per recurrence instance
    m.iCalUID,     // SFDC Weflow__EventId__c key — used by Retry: Collect Stale
  ]);
}}

return [{{ json: {{ sheetValues, gapCount, coveredCount, skippedCount, totalMeetings: meetings.length }} }}];
""",
    },
}

# 23b. Dedup Rows — skip meetings already logged in sheet (by gcal_event_id = instance ID)
dedup_rows_code = {
    "id": "dedup_rows",
    "name": "Dedup Rows",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(2200, -150),
    "parameters": {
        "jsCode": f"""
const sheetValues = $json.sheetValues || [];
if (sheetValues.length === 0) return [{{ json: {{ sheetValues: [], skipped: 0, appended: 0 }} }}];

const token = $('Refresh Google Token').first().json.access_token;
const existingResp = await this.helpers.httpRequest({{
  method: 'GET',
  url: 'https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sheet1!J:J',
  headers: {{ Authorization: 'Bearer ' + token }},
  json: true,
}});

const existing = new Set();
for (const row of (existingResp.values || []).slice(1)) {{
  if (row && row[0]) existing.add(row[0]);
}}

const newValues = sheetValues.filter(r => !existing.has(r[9]));  // col 9 = gcal_event_id
return [{{ json: {{ sheetValues: newValues, skipped: sheetValues.length - newValues.length, appended: newValues.length }} }}];
""",
    },
}

# 23c. Append to Google Sheet via HTTP (only new rows)
sheet_append = {
    "id": "sheet_append",
    "name": "Append to Sheet",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": pos(2400, -150),
    "parameters": {
        "method": "POST",
        "url": f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sheet1!A:K:append",
        "authentication": "none",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "Authorization", "value": "=Bearer {{ $('Refresh Google Token').first().json.access_token }}"},
                {"name": "Content-Type", "value": "application/json"},
            ]
        },
        "sendQuery": True,
        "queryParameters": {
            "parameters": [
                {"name": "valueInputOption", "value": "RAW"},
                {"name": "insertDataOption", "value": "INSERT_ROWS"},
            ]
        },
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ values: $json.sheetValues }) }}",
        "options": {},
    },
}

# 23d. Build Issue Log rows — filter to gaps only, map to Issue Log schema
build_issue_log_code = {
    "id": "build_issue_log",
    "name": "Build Issue Log Rows",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(2200, -300),
    "parameters": {
        "jsCode": """
const sheetValues = $('Transcript Check').first().json.sheetValues || [];
const gaps = sheetValues.filter(r => r[4] === "\u274c Gap");
if (gaps.length === 0) return [];
const issueRows = gaps.map(r => [
  "",                        // Issue — blank for ops to fill
  "Open",                    // status
  r[5],                      // Meeting Title (= summary)
  r[2],                      // CSM names
  r[1].split(" ")[0],        // Meeting Date (date portion of ptDateTime)
]);
return [{ json: { issueRows, count: issueRows.length } }];
""",
    },
}

# 23e. Append to Issue Log sheet (INSERT_ROWS so mid-sheet deletions don't cause overwrites)
issue_log_append = {
    "id": "issue_log_append",
    "name": "Append to Issue Log",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": pos(2400, -300),
    "parameters": {
        "method": "POST",
        "url": f"https://sheets.googleapis.com/v4/spreadsheets/{ISSUE_LOG_SHEET_ID}/values/Issues!A:E:append",
        "authentication": "none",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "Authorization", "value": "=Bearer {{ $('Refresh Google Token').first().json.access_token }}"},
                {"name": "Content-Type", "value": "application/json"},
            ]
        },
        "sendQuery": True,
        "queryParameters": {
            "parameters": [
                {"name": "valueInputOption", "value": "USER_ENTERED"},
                {"name": "insertDataOption", "value": "INSERT_ROWS"},
            ]
        },
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ values: $json.issueRows }) }}",
        "options": {},
    },
}

# 24. Format Slack Message Code Node (terse: counts + sheet link)
slack_format_code = {
    "id": "slack_format",
    "name": "Format Slack Message",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(2400, 0),
    "parameters": {
        "jsCode": f"""
const dateLabel = $('Compute Date Range').first().json.dateLabel;
const SHEET = '{SHEET_URL}';

const buildSoql = $('Build SOQL').first().json;
if (buildSoql.noMeetings) {{
  return [{{ json: {{
    message: '📋 *Weflow Transcript Report — ' + dateLabel + '*\\nNo CSM customer meetings found.'
  }}}}];
}}

const tc = $('Transcript Check').first().json;
const line = '❌ ' + tc.gapCount + ' missing | ✅ ' + tc.coveredCount + ' recorded';
const message = '📋 *Weflow Transcript Report — ' + dateLabel + '*\\n' +
  line + '\\n' +
  '🔗 <' + SHEET + '|Details in Google Sheet>';

return [{{ json: {{ message }} }}];
""",
    },
}

# ── Weekly summary path (Monday-only) ─────────────────────────────────────────
# 24a. IF Weekly Summary — branches execution on the `mode` field from date-range
if_weekly = {
    "id": "if_weekly",
    "name": "If Weekly Summary",
    "type": "n8n-nodes-base.if",
    "typeVersion": 2,
    "position": pos(600, 100),
    "parameters": {
        "conditions": {
            "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "strict",
            },
            "conditions": [{
                "id": "mode_equals_weekly",
                "leftValue": "={{ $('Compute Date Range').first().json.mode }}",
                "rightValue": "weekly",
                "operator": {"type": "string", "operation": "equals"},
            }],
            "combinator": "and",
        },
        "options": {},
    },
}

# 24b. Read Sheet Last Week — aggregates coverage from alert_date range
read_sheet_week_code = {
    "id": "read_sheet_week",
    "name": "Read Sheet Last Week",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(800, -100),
    "parameters": {
        "jsCode": f"""
const {{ weeklyMin, weeklyMax, dateLabel }} = $('Compute Date Range').first().json;
const token = $('Refresh Google Token').first().json.access_token;

const resp = await this.helpers.httpRequest({{
  method: 'GET',
  url: 'https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sheet1!A:K',
  headers: {{ Authorization: 'Bearer ' + token }},
  json: true,
}});

const rows = (resp.values || []).slice(1);  // skip header
const lastWeek = rows.filter(r => r && r[0] && r[0] >= weeklyMin && r[0] <= weeklyMax);

let coveredCount = 0, gapCount = 0;
for (const r of lastWeek) {{
  const status = r[4] || "";
  if (status.includes("Covered")) coveredCount++;
  else if (status.includes("Gap")) gapCount++;
}}

return [{{ json: {{
  coveredCount,
  gapCount,
  totalCount: coveredCount + gapCount,
  dateLabel,
  weeklyMin,
  weeklyMax,
}} }}];
""",
    },
}

# 24c. Format Weekly Slack Message — stats-only summary
slack_format_weekly_code = {
    "id": "slack_format_weekly",
    "name": "Format Weekly Slack Message",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": pos(1000, -100),
    "parameters": {
        "jsCode": f"""
const {{ coveredCount, gapCount, totalCount, dateLabel }} = $json;
const SHEET = '{SHEET_URL}';

if (totalCount === 0) {{
  return [{{ json: {{
    message: '📊 *Weflow Weekly Coverage — ' + dateLabel + '*\\nNo alerts logged last week.'
  }} }}];
}}

const pct = Math.round((coveredCount / totalCount) * 100);
const line = '✅ ' + coveredCount + ' recorded (' + pct + '%) | ❌ ' + gapCount + ' gaps | 📅 ' + totalCount + ' total';
const message = '📊 *Weflow Weekly Coverage — ' + dateLabel + '*\\n' +
  line + '\\n' +
  '🔗 <' + SHEET + '|Details in Google Sheet>';

return [{{ json: {{ message }} }}];
""",
    },
}

# 25. Slack DM Node
slack_dm = {
    "id": "slack_dm",
    "name": "Slack: #weflow-daily-alert",
    "type": "n8n-nodes-base.slack",
    "typeVersion": 2.4,
    "position": pos(2600, 0),
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
    retry_collect_stale,
    retry_if_stale,
    retry_sfdc_query,
    retry_apply_updates,
    retry_had_error,
    retry_error_format,
    if_weekly,
    read_sheet_week_code,
    slack_format_weekly_code,
    *gcal_nodes,
    *tag_nodes,
    merge_gcal,
    filter_dedup_code,
    build_soql_code,
    if_has_meetings,
    sfdc_query,
    transcript_check_code,
    dedup_rows_code,
    sheet_append,
    build_issue_log_code,
    issue_log_append,
    slack_format_code,
    slack_dm,
]

# ── Build connections ─────────────────────────────────────────────────────────

CONNECTIONS = {
    # Both triggers → Date Range
    "Daily 7 AM PT": {"main": [[{"node": "Compute Date Range", "type": "main", "index": 0}]]},
    "Manual Test Trigger": {"main": [[{"node": "Compute Date Range", "type": "main", "index": 0}]]},
    "Webhook Test Trigger": {"main": [[{"node": "Compute Date Range", "type": "main", "index": 0}]]},
    # Date Range → Refresh Token → fan out to (a) If Weekly Summary and (b) Retry chain
    "Compute Date Range": {"main": [[{"node": "Refresh Google Token", "type": "main", "index": 0}]]},
    "Refresh Google Token": {"main": [[
        {"node": "If Weekly Summary", "type": "main", "index": 0},
        {"node": "Retry: Collect Stale", "type": "main", "index": 0},
    ]]},
    # Retry chain (side-effect only; does not feed Slack alert)
    "Retry: Collect Stale": {"main": [[{"node": "Retry: Has Stale?", "type": "main", "index": 0}]]},
    "Retry: Has Stale?": {"main": [
        [{"node": "Retry: SFDC Query", "type": "main", "index": 0}],
        [],  # noStale=false branch: dead end
    ]},
    "Retry: SFDC Query": {"main": [[{"node": "Retry: Apply Updates", "type": "main", "index": 0}]]},
    "Retry: Apply Updates": {"main": [[{"node": "Retry: Had Error?", "type": "main", "index": 0}]]},
    "Retry: Had Error?": {"main": [
        [{"node": "Retry: Format Error Slack", "type": "main", "index": 0}],
        [],  # no error — dead end
    ]},
    "Retry: Format Error Slack": {"main": [[{"node": "Slack: #weflow-daily-alert", "type": "main", "index": 0}]]},
    # If Weekly Summary: true → weekly path, false → daily GCal fan-out
    "If Weekly Summary": {
        "main": [
            [{"node": "Read Sheet Last Week", "type": "main", "index": 0}],
            [],  # false branch populated below by CSM fan-out
        ]
    },
    # Weekly path: Read Sheet → Format Weekly Slack → Slack DM
    "Read Sheet Last Week": {
        "main": [[{"node": "Format Weekly Slack Message", "type": "main", "index": 0}]]
    },
    "Format Weekly Slack Message": {
        "main": [[{"node": "Slack: #weflow-daily-alert", "type": "main", "index": 0}]]
    },
}

for i, email in enumerate(CSM_CALENDARS):
    first_name = email.split(".")[0].title()
    gcal_name = f"GCal: {first_name}"
    tag_name = f"Tag: {first_name}"

    # Daily path fans out from If Weekly Summary (false branch, index 1)
    CONNECTIONS["If Weekly Summary"]["main"][1].append(
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
# Transcript Check fans out: dedup→sheet append + slack format + issue log funnel (parallel)
CONNECTIONS["Transcript Check"] = {
    "main": [[
        {"node": "Dedup Rows", "type": "main", "index": 0},
        {"node": "Format Slack Message", "type": "main", "index": 0},
        {"node": "Build Issue Log Rows", "type": "main", "index": 0},
    ]]
}
CONNECTIONS["Dedup Rows"] = {
    "main": [[{"node": "Append to Sheet", "type": "main", "index": 0}]]
}
CONNECTIONS["Append to Sheet"] = {"main": [[]]}
CONNECTIONS["Build Issue Log Rows"] = {
    "main": [[{"node": "Append to Issue Log", "type": "main", "index": 0}]]
}
CONNECTIONS["Append to Issue Log"] = {"main": [[]]}
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
