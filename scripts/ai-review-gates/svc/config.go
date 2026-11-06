package quota

import (
	"fmt"
	"net/url"
	"strconv"
	"time"
)

// Config is read from the environment at start-up.
type Config struct {
	UpstreamURL string
	MaxTokens   int
	Timeout     time.Duration
}

// LoadConfig reads the config through getenv so tests need no real environment.
func LoadConfig(getenv func(string) string) (Config, error) {
	c := Config{MaxTokens: 4096, Timeout: 30 * time.Second}
	u := getenv("UPSTREAM_URL")
	if u == "" {
		return Config{}, fmt.Errorf("UPSTREAM_URL is required")
	}
	if _, err := url.ParseRequestURI(u); err != nil {
		return Config{}, fmt.Errorf("UPSTREAM_URL: %w", err)
	}
	c.UpstreamURL = u
	if v := getenv("MAX_TOKENS"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n <= 0 {
			return Config{}, fmt.Errorf("MAX_TOKENS=%q: want a positive integer", v)
		}
		c.MaxTokens = n
	}
	if v := getenv("UPSTREAM_TIMEOUT"); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return Config{}, fmt.Errorf("UPSTREAM_TIMEOUT: %w", err)
		}
		c.Timeout = d
	}
	return c, nil
}
