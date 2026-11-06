package quota

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
)

// Server is the HTTP front of the gateway.
type Server struct {
	Ledger *Ledger
	Log    *slog.Logger
}

type spendRequest struct {
	Tenant string `json:"tenant"`
	Tokens int    `json:"tokens"`
}

type spendResponse struct {
	Remaining int `json:"remaining"`
}

// ServeHTTP handles POST /v1/spend.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req spendRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
		http.Error(w, "bad request body", http.StatusBadRequest)
		return
	}
	s.Log.Info("spend", "tenant", req.Tenant, "tokens", req.Tokens)
	if err := s.Ledger.Spend(req.Tenant, req.Tokens); err != nil {
		if errors.Is(err, ErrOverBudget) {
			http.Error(w, "token budget exhausted", http.StatusPaymentRequired)
			return
		}
		http.Error(w, "invalid spend", http.StatusBadRequest)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(spendResponse{Remaining: s.Ledger.Remaining(req.Tenant)})
}
