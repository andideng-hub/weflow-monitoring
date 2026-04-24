# Edge Cases

Known edge cases observed during operation, and how the workflow handles them.

## Handled Automatically

| Scenario | How It's Handled |
|----------|-----------------|
| Shared meeting on 2+ CSM calendars | Deduplicated by iCalUID; all CSMs listed |
| Internal meeting with external freemail (e.g. personal Gmail) | Freemail domains excluded from "external" count |
| All externals declined/needsAction, no transcript | Skipped — effective no-show, meeting didn't happen |
| All externals declined/needsAction, but Weflow recorded | ✅ Covered — transcript wins; meeting happened regardless of RSVPs |
| CSM declined but meeting was recorded | ✅ Covered — transcript wins |
| No customer meetings on a given day | Sends "No CSM customer meetings found" confirmation |
| Monday (weekly summary) | Reads prior week's alerts from sheet, no GCal/SFDC query |
| Saturday (Friday catch-up) | Normal daily alert for yesterday = Friday |
| Sunday | Cron skipped; Friday covered by Saturday, Saturday covered by Mon summary |
| Recurring meeting — iCalUID collides with past instances | Main + retry SOQL filter by `Weflow__StartDateTime__c` window; code matches by iCalUID AND start-time proximity (PR #13) |
| Event cancelled after cron ran but before meeting time | `Retry: Cleanup No-shows` re-checks with `showDeleted=true` >25h after meeting start and deletes row from both sheets (PR #11) |
| SFDC long-text SOQL paginated response (>250 records) | Both SFDC HTTP nodes use `responseContainsNextURL` pagination + `Flatten SFDC Pages` code node concatenates (PR #15) |
| Transient Google Sheets 503 on Dedup Rows | 3-attempt exponential backoff (500ms/1500ms/4500ms) on 5xx + network errors (PR #12) |
| Zoom/Meet/Teams link needed for gap triage | `meeting_link` column (Sheet1 col L, Issue Log col F) extracted from GCal `conferenceData.entryPoints` → `hangoutLink` → location/description regex (PR #14) |

## Known Limitations

| Scenario | Impact | Workaround |
|----------|--------|------------|
| Exchange/Outlook event IDs (non-Google format) | Will never match Weflow `EventId__c` | Ops team to triage manually |
| PDT vs PST timezone switch (November) | Date range code + retry date-windowing hardcodes UTC-7 (PDT, Apr-Oct) | Needs UTC-8 update for Nov-Mar (all 3 places: Compute Date Range, retry cleanup no-shows, Retry: Apply Updates date match) |
| Weflow recording exists but transcript is null | Flagged as gap (correct behavior — no transcript = no value) | None needed |
| Weflow creates placeholder records at calendar sync | ~62% of Weflow records never get transcripts | Monitoring uses transcript presence, not record existence |
| FourFour may have transcript when Weflow doesn't | Not checked by this workflow (Weflow/SFDC only) | Could add FourFour/Vitally cross-check in future |
| `events.list?iCalUID=` misses some confirmed events that `events.get` finds | Backfill/repair scripts that used list-filter would silently drop rows | For point lookups use `events.get` with `gcal_event_id` (col J), not `events.list` with iCalUID+timeMin filter |
| `build_workflow.py` has no `if __name__ == "__main__":` guard | Importing the module deploys to prod | Reviewer flagged — low risk for now; add guard in a follow-up PR |

## Coverage Snapshot (Week of Apr 7-8, 2026)

Based on 13 active customer meetings across 7 Growth CSMs:

| Bucket | Count | % |
|--------|-------|---|
| Both Weflow + FourFour | 6 | 46% |
| Weflow only | 4 | 31% |
| FourFour only | 0 | 0% |
| Neither (true gap) | 3 | 23% |
| **Weflow hit rate** | **10/13** | **76%** |
