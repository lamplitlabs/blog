# T01: Spend returns the remaining balance

The handler calls `Ledger.Spend` and then `Ledger.Remaining`, taking the lock twice; another
request can land in between, so the `remaining` in the response can be stale.

Change `Ledger.Spend` so it returns the tenant's remaining balance together with the error,
computed under the same lock. Update every caller (including the HTTP handler, which must use
the returned value) and the tests.
