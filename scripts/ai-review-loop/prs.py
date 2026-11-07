"""The 14 pull requests of the review-loop experiment.

Each PR reuses one seeded change from ../ai-review-gates/corpus.py (same edits,
same base tree) and gives it the title and description an authoring agent
would write: the intent, never the defect. The 7 defects are the ones that got
past every blocking CI gate in the earlier gates post; the 7 correct changes are
the benign PRs that passed every blocking gate there (B06 is left out because a
gate already blocked it). `pr` is the neutral number the agents see; it comes
from a fixed shuffle so the numbering says nothing about the label.
"""
import random

PRS = [
    {"src": "D02", "label": "defect", "oracle": [],
     "title": "config: don't fail start-up on a malformed MAX_TOKENS",
     "body": "A typo in MAX_TOKENS took the gateway down at deploy time last week. Fall back to the default instead of refusing to start."},
    {"src": "D03", "label": "defect", "oracle": [],
     "title": "upstream: simplify reply decoding",
     "body": "Collapse the decode step in Upstream.Complete to one line. No behaviour change intended."},
    {"src": "D08", "label": "defect", "oracle": [],
     "title": "store: tidy the usage report query",
     "body": "Small cleanup of UsageQuery while I was in the file."},
    {"src": "D09", "label": "defect", "oracle": [],
     "title": "ledger: fix off-by-one in the limit check",
     "body": "A tenant could spend its limit exactly; the limit should be exclusive. Updated the test to match."},
    {"src": "D12", "label": "defect", "oracle": ["oracle_refund_test.go"],
     "title": "ledger: add Refund for cancelled completions",
     "body": "When a completion is cancelled we bill tokens we never used. Add Ledger.Refund so the handler can give them back. Test included."},
    {"src": "D20", "label": "defect", "oracle": [],
     "title": "ledger: shorten the critical section in Spend",
     "body": "Profiling showed lock contention on the ledger under load. Hold the mutex only around the map reads and the write."},
    {"src": "D21", "label": "defect", "oracle": [],
     "title": "upstream: close the response body next to the decode",
     "body": "Move `defer resp.Body.Close()` down to where the body is read, so the error path reads top to bottom."},
    {"src": "B01", "label": "correct", "oracle": [],
     "title": "page: rename start to offset and clarify the doc comment",
     "body": "Readability only."},
    {"src": "B02", "label": "correct", "oracle": [],
     "title": "page: test a page size larger than the list",
     "body": "Adds one table case."},
    {"src": "B03", "label": "correct", "oracle": [],
     "title": "page: use the min builtin",
     "body": "Go 1.21+ has min; replace the manual clamp."},
    {"src": "B04", "label": "correct", "oracle": ["oracle_tenants_test.go"],
     "title": "ledger: add Tenants() for the admin listing",
     "body": "The admin page needs the known tenant ids in a stable order. Test included."},
    {"src": "B05", "label": "correct", "oracle": ["oracle_default_tokens_test.go"],
     "title": "config: raise the default MAX_TOKENS to 8192",
     "body": "Product asked for longer replies by default (ticket QUOTA-88: default 8192). Test updated to the new default."},
    {"src": "B07", "label": "correct", "oracle": [],
     "title": "handler: log the remaining balance after a spend",
     "body": "Support wants the balance in the logs when a tenant asks why they hit 402."},
    {"src": "B08", "label": "correct", "oracle": [],
     "title": "config: errors.New where fmt.Errorf had nothing to format",
     "body": "Tiny cleanup."},
]

_order = list(range(len(PRS)))
random.Random(20261107).shuffle(_order)
for n, i in enumerate(_order, 1):
    PRS[i]["pr"] = f"PR-{n:02d}"
BY_PR = {p["pr"]: p for p in PRS}
