# Edge Cases

Known edge cases observed during operation, and how the workflow handles them.

## Handled Automatically

| Scenario | How It's Handled |
|----------|-----------------|
| Shared meeting on 2+ CSM calendars | Deduplicated by iCalUID; all CSMs listed |
| Internal meeting with external freemail (e.g. personal Gmail) | Freemail domains excluded from "external" count |
| All external attendees declined / 0 accepted | Skipped — meeting likely cancelled |
| CSM declined the meeting | Skipped — CSM didn't attend |
| No customer meetings on a given day | Sends "No CSM customer meetings found" confirmation |
| Weekend | Cron only runs Mon-Fri |

## Known Limitations

| Scenario | Impact | Workaround |
|----------|--------|------------|
| Exchange/Outlook event IDs (non-Google format) | Will never match Weflow `EventId__c` | Ops team to triage manually |
| PDT vs PST timezone switch (November) | Date range code hardcodes UTC-7 (PDT, Apr-Oct) | Needs UTC-8 update for Nov-Mar |
| Weflow recording exists but transcript is null | Flagged as gap (correct behavior — no transcript = no value) | None needed |
| Weflow creates placeholder records at calendar sync | ~62% of Weflow records never get transcripts | Monitoring uses transcript presence, not record existence |
| FourFour may have transcript when Weflow doesn't | Not checked by this workflow (Weflow/SFDC only) | Could add FourFour/Vitally cross-check in future |

## Coverage Snapshot (Week of Apr 7-8, 2026)

Based on 13 active customer meetings across 7 Growth CSMs:

| Bucket | Count | % |
|--------|-------|---|
| Both Weflow + FourFour | 6 | 46% |
| Weflow only | 4 | 31% |
| FourFour only | 0 | 0% |
| Neither (true gap) | 3 | 23% |
| **Weflow hit rate** | **10/13** | **76%** |
