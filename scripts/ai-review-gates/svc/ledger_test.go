package quota

import (
	"errors"
	"testing"
)

func TestSpendUpToLimit(t *testing.T) {
	l := NewLedger(map[string]int{"acme": 100})
	if err := l.Spend("acme", 60); err != nil {
		t.Fatal(err)
	}
	if err := l.Spend("acme", 40); err != nil {
		t.Fatalf("spend landing exactly on the limit: %v", err)
	}
	if got := l.Remaining("acme"); got != 0 {
		t.Fatalf("remaining = %d, want 0", got)
	}
}

func TestSpendOverLimit(t *testing.T) {
	l := NewLedger(map[string]int{"acme": 100})
	err := l.Spend("acme", 101)
	if !errors.Is(err, ErrOverBudget) {
		t.Fatalf("err = %v, want ErrOverBudget", err)
	}
	if got := l.Remaining("acme"); got != 100 {
		t.Fatalf("a refused spend changed the balance: remaining = %d", got)
	}
}

func TestSpendRejectsNonPositive(t *testing.T) {
	l := NewLedger(map[string]int{"acme": 100})
	for _, n := range []int{0, -5} {
		if err := l.Spend("acme", n); err == nil {
			t.Fatalf("Spend(%d) = nil, want an error", n)
		}
	}
}

func TestSpendUnknownTenant(t *testing.T) {
	l := NewLedger(map[string]int{"acme": 100})
	if err := l.Spend("globex", 1); err == nil {
		t.Fatal("unknown tenant accepted")
	}
}

func TestSpendAll(t *testing.T) {
	l := NewLedger(map[string]int{"acme": 1000})
	spends := make([]int, 50)
	for i := range spends {
		spends[i] = 10
	}
	if got := l.SpendAll("acme", spends); got != 50 {
		t.Fatalf("SpendAll ok = %d, want 50", got)
	}
	if got := l.Remaining("acme"); got != 500 {
		t.Fatalf("remaining = %d, want 500", got)
	}
}
