# T04: Enforce MAX_TOKENS per request

`Config.MaxTokens` is loaded but never used. A single spend request above `MaxTokens` must be
rejected by the HTTP handler with `413 Request Entity Too Large` before the ledger is touched.
Give the `Server` what it needs to know the cap; when no cap is configured (zero) do not enforce one.
