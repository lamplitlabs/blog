# T05: Batch spend endpoint

Batch jobs send hundreds of small spends. Add `POST /v1/spend/batch` with body
`{"tenant": "acme", "tokens": [10, 20, 30]}` that applies the spends with `Ledger.SpendAll` and
answers `{"accepted": K, "remaining": N}`. `POST /v1/spend` must keep working as today.
