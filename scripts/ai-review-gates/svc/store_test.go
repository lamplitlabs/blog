package quota

import (
	"context"
	"errors"
	"testing"
	"time"
)

type fakeStore map[string]Tenant

func (f fakeStore) Get(_ context.Context, id string) (Tenant, error) {
	t, ok := f[id]
	if !ok {
		return Tenant{}, ErrNotFound
	}
	return t, nil
}

func TestDisplayName(t *testing.T) {
	d := &Directory{Store: fakeStore{"t1": {ID: "t1", Name: "Acme"}}}
	got, err := d.DisplayName(context.Background(), "t1")
	if err != nil || got != "Acme" {
		t.Fatalf("DisplayName = %q, %v", got, err)
	}
}

func TestDisplayNameNotFound(t *testing.T) {
	d := &Directory{Store: fakeStore{}}
	_, err := d.DisplayName(context.Background(), "nope")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("err = %v, want ErrNotFound", err)
	}
}

func TestUsageQueryArgs(t *testing.T) {
	since := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	q, args := UsageQuery("acme", since)
	if q == "" || len(args) != 2 || args[0] != "acme" {
		t.Fatalf("UsageQuery = %q %v", q, args)
	}
}
