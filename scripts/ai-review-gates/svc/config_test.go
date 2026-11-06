package quota

import (
	"testing"
	"time"
)

func env(m map[string]string) func(string) string {
	return func(k string) string { return m[k] }
}

func TestLoadConfigDefaults(t *testing.T) {
	c, err := LoadConfig(env(map[string]string{"UPSTREAM_URL": "http://llm:8080/v1/complete"}))
	if err != nil {
		t.Fatal(err)
	}
	if c.MaxTokens != 4096 || c.Timeout != 30*time.Second {
		t.Fatalf("defaults = %+v", c)
	}
}

func TestLoadConfigOverrides(t *testing.T) {
	c, err := LoadConfig(env(map[string]string{
		"UPSTREAM_URL": "http://llm:8080/v1/complete", "MAX_TOKENS": "512", "UPSTREAM_TIMEOUT": "5s",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if c.MaxTokens != 512 || c.Timeout != 5*time.Second {
		t.Fatalf("overrides = %+v", c)
	}
}

func TestLoadConfigRequiresURL(t *testing.T) {
	if _, err := LoadConfig(env(nil)); err == nil {
		t.Fatal("missing UPSTREAM_URL accepted")
	}
}
