// gogate: the Go policy gates of the tool-call argument differential bench.
//
//	gogate v1|v2 <payloads.b64>
//
// For each base64 line (one raw `arguments` string), decode it into a struct
// with encoding/json (v1) or encoding/json/v2 (v2), apply the shared policy
// (relative path under workspace/, no ".." component) and print one JSON line:
// {"allow":bool,"path":string|null,"err":string}.
package main

import (
	"bufio"
	"encoding/base64"
	jsonv1 "encoding/json"
	jsonv2 "encoding/json/v2"
	"fmt"
	"os"
	"strings"
)

type readFile struct {
	Path *string `json:"path"`
}

func policyOK(p string) bool {
	if !strings.HasPrefix(p, "workspace/") {
		return false
	}
	for _, c := range strings.Split(p, "/") {
		if c == ".." {
			return false
		}
	}
	return true
}

func main() {
	mode, file := os.Args[1], os.Args[2]
	f, err := os.Open(file)
	if err != nil {
		panic(err)
	}
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		raw, err := base64.StdEncoding.DecodeString(sc.Text())
		if err != nil {
			panic(err)
		}
		var a readFile
		switch mode {
		case "v1":
			err = jsonv1.Unmarshal(raw, &a)
		case "v2":
			err = jsonv2.Unmarshal(raw, &a)
		default:
			panic("mode")
		}
		res := map[string]any{"allow": false, "path": nil, "err": ""}
		if err != nil {
			res["err"] = err.Error()
		} else if a.Path != nil {
			res["path"] = *a.Path
			res["allow"] = policyOK(*a.Path)
		}
		b, _ := jsonv1.Marshal(res)
		fmt.Fprintln(out, string(b))
	}
}
