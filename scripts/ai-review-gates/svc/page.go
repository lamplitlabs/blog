package quota

import "fmt"

// Page returns the 1-based page of items with the given page size. A page past
// the end is empty, not an error.
func Page[T any](items []T, page, size int) ([]T, error) {
	if page < 1 || size < 1 {
		return nil, fmt.Errorf("page %d size %d: both must be >= 1", page, size)
	}
	start := (page - 1) * size
	if start >= len(items) {
		return []T{}, nil
	}
	end := start + size
	if end > len(items) {
		end = len(items)
	}
	return items[start:end], nil
}
