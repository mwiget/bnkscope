package main

import (
	"reflect"
	"testing"
)

// Two per-thread segments, as tmm writes them: the same virtual server in
// both, one forwarding direction in each.
func TestMergeSegmentsSumsCountersAndKeepsFamiliesContiguous(t *testing.T) {
	vs := []label{{"name", "vs-80"}}
	fwd01 := []label{{"port_id", "0"}, {"peer_id", "1"}}
	fwd10 := []label{{"port_id", "1"}, {"peer_id", "0"}}
	in := []sample{
		// tmm0
		{metric: "f5tmm_virtual_server_clientside_bytes_in", labels: vs, value: 100, additive: true},
		{metric: "f5tmm_virtual_server_enabled", labels: vs, value: 1},
		{metric: "f5tmm_doca_flow_fwd_bytes", labels: fwd01, value: 7, additive: true},
		// tmm1
		{metric: "f5tmm_virtual_server_clientside_bytes_in", labels: vs, value: 23, additive: true},
		{metric: "f5tmm_virtual_server_enabled", labels: vs, value: 1},
		{metric: "f5tmm_doca_flow_fwd_bytes", labels: fwd10, value: 9, additive: true},
	}
	want := []sample{
		{metric: "f5tmm_virtual_server_clientside_bytes_in", labels: vs, value: 123, additive: true},
		{metric: "f5tmm_virtual_server_enabled", labels: vs, value: 1},
		{metric: "f5tmm_doca_flow_fwd_bytes", labels: fwd01, value: 7, additive: true},
		{metric: "f5tmm_doca_flow_fwd_bytes", labels: fwd10, value: 9, additive: true},
	}
	if got := mergeSegments(in); !reflect.DeepEqual(got, want) {
		t.Fatalf("mergeSegments:\n got %+v\nwant %+v", got, want)
	}
}

// A label value must not be able to collide with a neighbouring label's name.
func TestMergeSegmentsKeysOnWholeLabelSet(t *testing.T) {
	in := []sample{
		{metric: "m", labels: []label{{"a", "b"}, {"c", "d"}}, value: 1, additive: true},
		{metric: "m", labels: []label{{"a", "bc"}, {"", "d"}}, value: 2, additive: true},
	}
	if got := mergeSegments(in); len(got) != 2 {
		t.Fatalf("distinct label sets were merged: %+v", got)
	}
}
