# T11: Zero-token spends are a no-op

Health checks and cache hits send spends of 0 tokens and get a 400, which pages the on-call.
Make a spend of exactly 0 tokens succeed without changing the balance (unknown tenants are still
an error). Negative spends stay an error. Update the tests.
