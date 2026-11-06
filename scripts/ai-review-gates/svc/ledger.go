// Package quota is a small token-budget service for an LLM gateway. It is the
// base tree that every seeded agent patch in ../corpus.py is applied to.
package quota

import (
	"errors"
	"fmt"
	"sync"
)

// ErrOverBudget is returned when a spend would take a tenant past its limit.
var ErrOverBudget = errors.New("over budget")

// Ledger tracks tokens spent per tenant against a per-tenant limit.
type Ledger struct {
	mu    sync.Mutex
	limit map[string]int
	spent map[string]int
}

// NewLedger returns a ledger with the given per-tenant limits.
func NewLedger(limits map[string]int) *Ledger {
	l := &Ledger{limit: map[string]int{}, spent: map[string]int{}}
	for t, n := range limits {
		l.limit[t] = n
	}
	return l
}

// Spend records n tokens for tenant. A spend that lands exactly on the limit
// is allowed; one token more is not.
func (l *Ledger) Spend(tenant string, n int) error {
	if n <= 0 {
		return fmt.Errorf("spend %d tokens: must be positive", n)
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	lim, ok := l.limit[tenant]
	if !ok {
		return fmt.Errorf("tenant %q: unknown", tenant)
	}
	if l.spent[tenant]+n > lim {
		return fmt.Errorf("tenant %q: %w (%d + %d > %d)", tenant, ErrOverBudget, l.spent[tenant], n, lim)
	}
	l.spent[tenant] += n
	return nil
}

// Remaining returns the tokens tenant may still spend.
func (l *Ledger) Remaining(tenant string) int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.limit[tenant] - l.spent[tenant]
}

// SpendAll applies the spends concurrently and returns how many succeeded.
func (l *Ledger) SpendAll(tenant string, spends []int) int {
	var wg sync.WaitGroup
	var mu sync.Mutex
	ok := 0
	for _, n := range spends {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if l.Spend(tenant, n) == nil {
				mu.Lock()
				ok++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	return ok
}
