package quota

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func newServer() *Server {
	return &Server{
		Ledger: NewLedger(map[string]int{"acme": 100}),
		Log:    slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
}

func post(s *Server, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	s.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/v1/spend", strings.NewReader(body)))
	return w
}

func TestHandlerSpend(t *testing.T) {
	w := post(newServer(), `{"tenant":"acme","tokens":30}`)
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"remaining":70`) {
		t.Fatalf("got %d %s", w.Code, w.Body)
	}
}

func TestHandlerOverBudget(t *testing.T) {
	w := post(newServer(), `{"tenant":"acme","tokens":101}`)
	if w.Code != http.StatusPaymentRequired {
		t.Fatalf("got %d, want 402", w.Code)
	}
}

func TestHandlerBadBody(t *testing.T) {
	w := post(newServer(), `{`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("got %d, want 400", w.Code)
	}
}
