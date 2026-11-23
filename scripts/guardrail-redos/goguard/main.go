// Guardrail service with Go's regexp: POST /check with a text body runs every rule.
//
//	go run . <rules.json> <naive|hardened> <port>
//
// net/http, one goroutine per request. Reply: {"flagged": [rule names], "ms": guard time}.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"
)

type rule struct {
	Name, Flags, Mode, Naive, Hardened string
}

type compiled struct {
	name    string
	replace bool
	rx      *regexp.Regexp
}

func main() {
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	var cfg struct{ Rules []rule }
	if err := json.Unmarshal(raw, &cfg); err != nil {
		panic(err)
	}
	variant := os.Args[2]
	var rules []compiled
	for _, r := range cfg.Rules {
		pat := r.Naive
		if variant == "hardened" {
			pat = r.Hardened
		}
		if strings.Contains(r.Flags, "i") {
			pat = "(?i)" + pat
		}
		rules = append(rules, compiled{r.Name, r.Mode == "replace", regexp.MustCompile(pat)})
	}
	http.HandleFunc("/check", func(w http.ResponseWriter, req *http.Request) {
		b, _ := io.ReadAll(req.Body)
		text := string(b)
		t := time.Now()
		flagged := []string{}
		for _, r := range rules {
			if r.replace {
				next := r.rx.ReplaceAllString(text, "#")
				if next != text {
					flagged = append(flagged, r.name)
					text = next
				}
			} else if r.rx.MatchString(text) {
				flagged = append(flagged, r.name)
			}
		}
		ms := float64(time.Since(t).Nanoseconds()) / 1e6
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"flagged": flagged, "ms": ms})
	})
	fmt.Printf("go guard (%s) on :%s\n", variant, os.Args[3])
	panic(http.ListenAndServe("127.0.0.1:"+os.Args[3], nil))
}
