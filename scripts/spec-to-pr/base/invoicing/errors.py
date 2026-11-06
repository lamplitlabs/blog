class InvoicingError(ValueError):
    """Base class for domain errors."""


class NotFound(InvoicingError):
    pass
