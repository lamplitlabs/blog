package quota

import (
	"context"
	"errors"
	"fmt"
	"time"
)

// ErrNotFound is returned by a Store when the tenant does not exist.
var ErrNotFound = errors.New("not found")

// Tenant is one row of the tenants table.
type Tenant struct {
	ID   string
	Name string
	Plan string
}

// Store reads tenants; the real one is Postgres, tests use a fake.
type Store interface {
	Get(ctx context.Context, id string) (Tenant, error)
}

// Directory resolves tenant ids for the admin API.
type Directory struct {
	Store Store
}

// DisplayName returns the tenant's name, or ErrNotFound wrapped with the id.
func (d *Directory) DisplayName(ctx context.Context, id string) (string, error) {
	t, err := d.Store.Get(ctx, id)
	if err != nil {
		return "", fmt.Errorf("tenant %q: %w", id, err)
	}
	return t.Name, nil
}

// UsageQuery builds the usage report query. Values go in as parameters.
func UsageQuery(tenant string, since time.Time) (string, []any) {
	q := "SELECT model, SUM(tokens) FROM usage WHERE tenant = $1 AND ts >= $2 GROUP BY model ORDER BY model"
	return q, []any{tenant, since}
}
