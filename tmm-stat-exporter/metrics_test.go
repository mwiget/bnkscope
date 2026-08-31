package main

import (
	"compress/gzip"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAcceptsGzip(t *testing.T) {
	cases := map[string]bool{
		"":                           false,
		"identity":                   false,
		"gzip":                       true,
		"gzip, deflate, br":          true,
		"deflate, gzip":              true,
		"GZIP":                       true,
		"gzip;q=1.0, identity;q=0.5": true,
		// An explicit refusal is the only way to ask for the plain body.
		"gzip;q=0":   false,
		"gzip;q=0.0": false,
	}
	for header, want := range cases {
		r := httptest.NewRequest(http.MethodGet, "/metrics", nil)
		if header != "" {
			r.Header.Set("Accept-Encoding", header)
		}
		if got := acceptsGzip(r); got != want {
			t.Errorf("Accept-Encoding %q: got %v, want %v", header, got, want)
		}
	}
	// The -once path calls the handler with no request at all.
	if acceptsGzip(nil) {
		t.Error("nil request: got true, want false")
	}
}

// A scrape must carry the same bytes whether or not it was compressed, and must
// only claim Content-Encoding when it actually compressed something.
func TestHandleMetricsGzipRoundTrip(t *testing.T) {
	e := &exporter{segments: []string{"testdata-does-not-exist"}, tables: []string{"tmm_stat"}}

	plainRec := httptest.NewRecorder()
	e.handleMetrics(plainRec, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if enc := plainRec.Header().Get("Content-Encoding"); enc != "" {
		t.Errorf("no Accept-Encoding: got Content-Encoding %q, want none", enc)
	}
	plain := plainRec.Body.String()
	if !strings.Contains(plain, "f5tmm_up") {
		t.Fatalf("plain body missing f5tmm_up: %q", plain)
	}

	gzReq := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	gzReq.Header.Set("Accept-Encoding", "gzip")
	gzRec := httptest.NewRecorder()
	e.handleMetrics(gzRec, gzReq)
	if enc := gzRec.Header().Get("Content-Encoding"); enc != "gzip" {
		t.Fatalf("Content-Encoding: got %q, want gzip", enc)
	}
	if v := gzRec.Header().Get("Vary"); v != "Accept-Encoding" {
		t.Errorf("Vary: got %q, want Accept-Encoding", v)
	}
	zr, err := gzip.NewReader(gzRec.Body)
	if err != nil {
		t.Fatalf("gzip.NewReader: %v", err)
	}
	got, err := io.ReadAll(zr)
	if err != nil {
		t.Fatalf("read gzip body: %v", err)
	}
	// f5tmm_scrape_duration_seconds differs between the two calls, so compare
	// everything else line for line.
	if want, have := dropVarying(plain), dropVarying(string(got)); want != have {
		t.Errorf("decompressed body differs from plain body:\nplain: %q\ngzip:  %q", want, have)
	}
}

func dropVarying(body string) string {
	var keep []string
	for _, line := range strings.Split(body, "\n") {
		if strings.HasPrefix(line, "f5tmm_scrape_duration_seconds ") {
			continue
		}
		keep = append(keep, line)
	}
	return strings.Join(keep, "\n")
}
