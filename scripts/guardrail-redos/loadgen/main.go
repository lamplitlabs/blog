// Open-loop load against a guard service: benign lines at a fixed rate, plus a few
// poison requests at fixed times. Latency is measured from each request's scheduled
// send time (no coordinated omission), so a stalled server shows up in every request
// that should have been sent while it was stalled.
//
//	go run . -url http://127.0.0.1:PORT/check -benign benign.txt -poison poison.txt \
//	         -rps 200 -secs 20 -poison-every 2s -timeout 5s -seed 1 > requests.tsv
//
// Output: one row per request: kind (benign|poison) sched_ms latency_ms status.
// status is the HTTP code, or timeout / reset / refused / eof / error:<message>.
package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"math/rand"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"syscall"
	"time"
)

type result struct {
	kind    string
	sched   time.Duration
	latency time.Duration
	status  string
}

func classify(err error) string {
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return "timeout"
	}
	switch {
	case errors.Is(err, syscall.ECONNRESET), errors.Is(err, syscall.EPIPE):
		return "reset"
	case errors.Is(err, syscall.ECONNREFUSED):
		return "refused"
	case errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF):
		return "eof"
	}
	return "error:" + strings.ReplaceAll(err.Error(), "\t", " ")
}

func main() {
	url := flag.String("url", "", "guard /check URL")
	benignPath := flag.String("benign", "", "benign corpus, one request per line")
	poisonPath := flag.String("poison", "", "poison body (whole file is one request)")
	rps := flag.Float64("rps", 200, "benign requests per second (fixed interval)")
	secs := flag.Float64("secs", 20, "run length")
	every := flag.Duration("poison-every", 2*time.Second, "one poison request this often, first at 1s")
	timeout := flag.Duration("timeout", 5*time.Second, "client timeout per request")
	seed := flag.Int64("seed", 1, "seed for benign line order")
	flag.Parse()

	braw, err := os.ReadFile(*benignPath)
	if err != nil {
		panic(err)
	}
	benign := strings.Split(strings.TrimSuffix(string(braw), "\n"), "\n")
	poison, err := os.ReadFile(*poisonPath)
	if err != nil {
		panic(err)
	}
	rng := rand.New(rand.NewSource(*seed))

	type req struct {
		kind string
		at   time.Duration
		body []byte
	}
	var plan []req
	total := time.Duration(*secs * float64(time.Second))
	step := time.Duration(float64(time.Second) / *rps)
	for at := time.Duration(0); at < total; at += step {
		plan = append(plan, req{"benign", at, []byte(benign[rng.Intn(len(benign))])})
	}
	if *every > 0 {
		for at := time.Second; at < total; at += *every {
			plan = append(plan, req{"poison", at, poison})
		}
	}
	// stable order by scheduled time
	for i := 1; i < len(plan); i++ {
		for j := i; j > 0 && plan[j].at < plan[j-1].at; j-- {
			plan[j], plan[j-1] = plan[j-1], plan[j]
		}
	}

	client := &http.Client{
		Timeout: *timeout,
		Transport: &http.Transport{
			MaxIdleConns:        4096,
			MaxIdleConnsPerHost: 4096,
			DialContext:         (&net.Dialer{Timeout: *timeout}).DialContext,
		},
	}
	results := make([]result, len(plan))
	var wg sync.WaitGroup
	start := time.Now()
	for i, r := range plan {
		// sleep to 1 ms before the slot, then spin: macOS coalesces short timers.
		for {
			left := r.at - time.Since(start)
			if left <= 0 {
				break
			}
			if left > 2*time.Millisecond {
				time.Sleep(left - time.Millisecond)
			}
		}
		wg.Add(1)
		go func(i int, r req) {
			defer wg.Done()
			resp, err := client.Post(*url, "text/plain", bytes.NewReader(r.body))
			status := ""
			if err != nil {
				status = classify(err)
			} else {
				_, _ = io.Copy(io.Discard, resp.Body)
				resp.Body.Close()
				status = fmt.Sprint(resp.StatusCode)
			}
			results[i] = result{r.kind, r.at, time.Since(start) - r.at, status}
		}(i, r)
	}
	wg.Wait()
	for _, r := range results {
		fmt.Printf("%s\t%.3f\t%.3f\t%s\n", r.kind, float64(r.sched.Microseconds())/1e3,
			float64(r.latency.Microseconds())/1e3, r.status)
	}
}
