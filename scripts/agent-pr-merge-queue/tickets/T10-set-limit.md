# T10: Change a tenant's limit at runtime

Add `Ledger.SetLimit(tenant string, n int) error` so an admin can raise or lower a tenant's limit
(also adding a tenant that does not exist yet). `n` must be >= 0. Lowering a limit below what the
tenant already spent is allowed; from then on every spend is refused and `Remaining` must report
0, never a negative number.
