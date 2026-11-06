package quota

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestComplete(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer k" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.Write([]byte(`{"text":"hi","tokens":3}`))
	}))
	defer ts.Close()
	u := &Upstream{URL: ts.URL, Key: "k", HTTP: ts.Client(), Timeout: 2 * time.Second}
	r, err := u.Complete(context.Background(), "hello")
	if err != nil {
		t.Fatal(err)
	}
	if r.Text != "hi" || r.Tokens != 3 {
		t.Fatalf("reply = %+v", r)
	}
}

func TestCompleteUpstreamError(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "model overloaded", http.StatusServiceUnavailable)
	}))
	defer ts.Close()
	u := &Upstream{URL: ts.URL, HTTP: ts.Client(), Timeout: 2 * time.Second}
	_, err := u.Complete(context.Background(), "hello")
	if err == nil || !strings.Contains(err.Error(), "503") {
		t.Fatalf("err = %v, want a 503 error", err)
	}
}
