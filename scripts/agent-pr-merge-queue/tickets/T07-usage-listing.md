# T07: Usage listing

Operators want to see who is using the gateway. Add `Ledger.Usage()` returning one entry per
tenant (tenant, spent, limit) sorted by tenant id, and `GET /v1/usage?page=P&size=S` that returns
one page of it as JSON using the existing `Page` helper (defaults: page 1, size 20). Asking for a
page past the end returns an empty list with status 200.
