# T09: Remaining reports unknown tenants

`Ledger.Remaining` returns 0 for a tenant it does not know, which looks exactly like an exhausted
budget. Change it to `Remaining(tenant string) (int, error)` returning an error for unknown
tenants. Update every caller and the tests.
