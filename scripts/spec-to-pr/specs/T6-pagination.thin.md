# T6: Paginate invoice listing

Listing all invoices is slow for big customers. Add pagination:
`InvoiceStore.list(customer=None, page=1, page_size=20)` in `invoicing/store.py`.
