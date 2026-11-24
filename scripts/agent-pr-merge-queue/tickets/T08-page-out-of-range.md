# T08: Page past the end is an error

API clients loop until they see an error, so `Page` returning an empty page past the end makes
them loop one request too far, forever on a buggy client. Make `Page` return a new
`ErrPageOutOfRange` sentinel error when the requested page starts past the end of the items.
Page 1 of an empty list is still a valid empty page. Update the tests.
