# invoicing - agent instructions

Small invoicing library used by the billing service.

- Python 3.9, standard library only. Do not add third-party dependencies.
- Money is always `decimal.Decimal`; round with `invoicing.money.to_money` (half-up to cents).
- Domain errors subclass `invoicing.errors.InvoicingError` (itself a `ValueError`).
- Tests live in `tests/`, use `unittest`, and run with:
  `python3 -m unittest discover -s tests -t .`
- Keep changes small and focused on the ticket. Do not edit unrelated modules or existing tests.
