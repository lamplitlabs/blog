package quota

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Upstream forwards completions to the model server.
type Upstream struct {
	URL     string
	Key     string
	HTTP    *http.Client
	Timeout time.Duration
}

// Reply is the part of the upstream answer the gateway uses.
type Reply struct {
	Text   string `json:"text"`
	Tokens int    `json:"tokens"`
}

// Complete sends prompt upstream and returns the reply.
func (u *Upstream) Complete(ctx context.Context, prompt string) (*Reply, error) {
	ctx, cancel := context.WithTimeout(ctx, u.Timeout)
	defer cancel()
	body, err := json.Marshal(map[string]string{"prompt": prompt})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u.URL, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+u.Key)
	req.Header.Set("Content-Type", "application/json")
	resp, err := u.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("upstream: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("upstream: status %d: %s", resp.StatusCode, bytes.TrimSpace(msg))
	}
	var r Reply
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return nil, fmt.Errorf("upstream: decode: %w", err)
	}
	return &r, nil
}
