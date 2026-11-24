# T12: Audit log for spends

Finance wants one structured log line per spend decision. The handler must log, at Info level,
the tenant, the tokens requested, the outcome (`ok`, `over_budget` or `invalid`) and, for `ok`,
the remaining balance, as slog attributes named `tenant`, `tokens`, `outcome`, `remaining`.
Add a test that captures the log output and checks the attributes.
