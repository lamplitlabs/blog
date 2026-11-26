# T03: Over-budget errors carry details

Clients that get a 402 cannot tell how much budget is left. Replace the `ErrOverBudget` sentinel
with a `*BudgetError` type that carries the tenant, tokens already spent, tokens requested and the
limit. The handler's 402 response must be JSON with those four fields. Update the tests.
