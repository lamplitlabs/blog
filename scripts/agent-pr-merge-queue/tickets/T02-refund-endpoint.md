# T02: Refund tokens

When the upstream model call fails after the gateway has charged a tenant, the tokens must be
given back.

Add `Ledger.Refund(tenant string, n int) error`. A refund can never take a tenant's spend below
zero; refunding an unknown tenant or a non-positive amount is an error. Expose it over HTTP as
`POST /v1/refund` with the same JSON body as `/v1/spend` (`tenant`, `tokens`), answering
`{"remaining": N}`. `POST /v1/spend` must keep working as today.
