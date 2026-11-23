# T06: Unknown tenant is a 404

A spend for a tenant the ledger does not know currently gets `400 invalid spend`, which clients
retry. Add an `ErrUnknownTenant` sentinel error, return it (wrapped) from the ledger, and make the
handler answer `404 Not Found` for it. Other invalid spends stay 400.
