// Time the guardrail rules in rules.json with Go's regexp (RE2-style, linear time per search).
//
//	go run . <rules.json> <benign.txt> [budget_ms]
//
// Same output columns as bench.py: kind engine rule variant n bytes ms matched.
// Go has no case-insensitive flag argument; flags "i" becomes a (?i) prefix.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

type attack struct{ Prefix, Unit, Suffix string }
type natural struct {
	Prefix, Sep, Suffix string
	Words               []string
}
type rule struct {
	Name, Flags, Mode, Naive, Hardened string
	Attack                             attack
	Natural                            natural
	Positives                          []string
}
type config struct {
	Rules    []rule
	Ladder   []int
	BudgetMs float64 `json:"budget_ms"`
}

func run(rx *regexp.Regexp, mode, s string) bool {
	if mode == "search" {
		return rx.MatchString(s)
	}
	return rx.ReplaceAllString(s, "#") != s
}

func timed(rx *regexp.Regexp, mode, s string) (float64, bool) {
	t := time.Now()
	m := run(rx, mode, s)
	return float64(time.Since(t).Nanoseconds()) / 1e6, m
}

func median(xs []float64) float64 {
	s := append([]float64(nil), xs...)
	sort.Float64s(s)
	k := len(s) / 2
	if len(s)%2 == 1 {
		return s[k]
	}
	return (s[k-1] + s[k]) / 2
}

func row(cols ...any) {
	parts := make([]string, len(cols))
	for i, c := range cols {
		parts[i] = fmt.Sprint(c)
	}
	fmt.Println(strings.Join(parts, "\t"))
}

func tf(b bool) string {
	if b {
		return "True"
	}
	return "False"
}

func main() {
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	var cfg config
	if err := json.Unmarshal(raw, &cfg); err != nil {
		panic(err)
	}
	if len(os.Args) > 3 {
		cfg.BudgetMs, _ = strconv.ParseFloat(os.Args[3], 64)
	}
	braw, err := os.ReadFile(os.Args[2])
	if err != nil {
		panic(err)
	}
	benign := strings.Split(strings.TrimSuffix(string(braw), "\n"), "\n")
	nbytes := 0
	for _, l := range benign {
		nbytes += len(l) + 1
	}
	engine := strings.Replace(runtime.Version(), "go1.", "go1.", 1) + "-regexp"
	for _, r := range cfg.Rules {
		for _, variant := range []string{"naive", "hardened"} {
			pat := r.Naive
			if variant == "hardened" {
				pat = r.Hardened
			}
			if strings.Contains(r.Flags, "i") {
				pat = "(?i)" + pat
			}
			rx := regexp.MustCompile(pat)
			hits := 0
			for _, p := range r.Positives {
				if run(rx, r.Mode, p) {
					hits++
				}
			}
			row("pos", engine, r.Name, variant, hits, len(r.Positives), 0, tf(hits == len(r.Positives)))
			for _, n := range cfg.Ladder {
				s := r.Attack.Prefix + strings.Repeat(r.Attack.Unit, n) + r.Attack.Suffix
				first, m := timed(rx, r.Mode, s)
				samples := []float64{first}
				reps := 1
				if first < 50 {
					reps = 5
				} else if first < 300 {
					reps = 3
				}
				for i := 1; i < reps; i++ {
					ms, _ := timed(rx, r.Mode, s)
					samples = append(samples, ms)
				}
				ms := median(samples)
				row("attack", engine, r.Name, variant, n, len(s), fmt.Sprintf("%.4f", ms), tf(m))
				if ms > cfg.BudgetMs {
					break
				}
			}
			for k := 1; k <= len(r.Natural.Words); k++ {
				s := r.Natural.Prefix + strings.Join(r.Natural.Words[:k], r.Natural.Sep) + r.Natural.Suffix
				first, m := timed(rx, r.Mode, s)
				samples := []float64{first}
				if first < 50 {
					for i := 0; i < 4; i++ {
						ms, _ := timed(rx, r.Mode, s)
						samples = append(samples, ms)
					}
				}
				ms := median(samples)
				row("natural", engine, r.Name, variant, k, len(s), fmt.Sprintf("%.4f", ms), tf(m))
				if ms > cfg.BudgetMs {
					break
				}
			}
			var samples []float64
			hits = 0
			for i := 0; i < 5; i++ {
				hits = 0
				t := time.Now()
				for _, l := range benign {
					if run(rx, r.Mode, l) {
						hits++
					}
				}
				samples = append(samples, float64(time.Since(t).Nanoseconds())/1e6)
			}
			row("benign", engine, r.Name, variant, len(benign), nbytes, fmt.Sprintf("%.4f", median(samples)), hits)
		}
	}
}
