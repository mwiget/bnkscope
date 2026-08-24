#!/usr/bin/env python3
"""LOC report for the bnkscope reduction (docs/BNKSCOPE_PLAN.md).

Assigns every tracked .py/.ts/.tsx file under backend/, frontend-v2/src/ and
mcp-server/ to exactly one feature bucket by path (first matching rule wins),
so each phase can report what it actually removed instead of what it hoped to.

    ./scripts/loc-report.py                     # human table
    ./scripts/loc-report.py --json > loc.json   # machine-readable snapshot
    ./scripts/loc-report.py --compare loc.json  # delta vs a saved snapshot

Buckets prefixed KEEP survive into bnkscope; RM buckets are slated for removal.
OTHER is shared code (UI kit, lib/, generated types) that shrinks in proportion
to what it served.
"""

import argparse
import collections
import json
import os
import re
import sys

ROOTS = ["backend", "frontend-v2/src", "mcp-server"]
EXT = (".py", ".ts", ".tsx")

# Ordered rules: (bucket, regex matched against the lowercased relative path).
# First match wins, so KEEP rules are listed before the broad RM rules that
# would otherwise swallow them (e.g. routes/k8s/f5bnk.py before "RM modules").
RULES = [
    # ---- KEEP: the monitoring / troubleshooting core ----
    ("KEEP k8s-core", r"(services/kubernetes/|routes/k8s/(resources|clusters|crds|topology|_shared|__init__)|models/kubernetes|schemas/kubernetes|k8s_websocket|components/k8s/(k8sresource|k8sclusterlist|podlogs|podexec|resourcedescribe|resourceevents|resourcemetrics|resourcetopology|clusterconfigdialog|addclusterflow|clusterprereq|yamleditor)|hooks/usek8s|hooks/k8s/|pages/kubernetes)"),
    ("KEEP bnk-tmm", r"(services/bnk/|routes/k8s/(f5bnk|tmm_debug|recovery)|routes/qkview|services/qkview|components/k8s/(f5bnktopology|f5bnkpolicy|f5irule|bnkhealth|tmmdebug|qkview|trafficflow|gatewaydetail|httproutedetail|backend)|hooks/usetmm|hooks/useqkview|hooks/usek8sbnk|pages/f5bnk)"),
    ("KEEP observ", r"(llm_observability|useLlmObservability|pages/observability|components/observability|components/health|routes/connectivity|services/reachability|hooks/useconnectivity)"),
    ("KEEP system", r"(routes/system|services/system_service|core/|database\.py|main\.py|utils/)"),

    # ---- RM: everything that builds, deploys or governs infrastructure ----
    ("RM tofu/exec", r"(opentofu|_tofu_|services/execution/|workspace_manager|state_viewer|state_parser|state_decrypt|config_export|parallel_|project_orchestration|components/execution)"),
    ("RM projects", r"(project)"),
    ("RM modules", r"(module|blueprint|catalog|stack|preset|registry|helm)"),
    ("RM fleet/oper", r"(fleet|operator)"),
    ("RM auth/users", r"(auth|users|audit|rbac|login|credential|secret|jwt|role)"),
    ("RM benchmarks", r"(benchmark)"),
    ("RM dpu/bm", r"(dpu|dpf|bare_metal|bare-metal|baremetal|bluefield|rshim|bf_conf|infrastructure)"),
    ("RM drift", r"(drift)"),
    ("RM proxy-mig", r"(proxy_|proxymigration|translate_cis)"),
    ("RM snapshots", r"(snapshot|promotion|usecase_artifact|backup|runbook)"),
    ("RM upgrade/lic", r"(bnk_upgrade|bnkupgrade|licens)"),
    ("RM discovery", r"(discovery|scanner|target_discovery|clusterscanresults)"),
    ("RM tasks/queue", r"(celery|tasks/|routes/tasks|notification|alert)"),
    ("RM cloud/ssh", r"(cloud_auth|ssh|tunnel|f5_device|tmos|ansible|container_task)"),
]


def bucket_for(path: str) -> str:
    lowered = path.lower()
    for name, pattern in RULES:
        if re.search(pattern, lowered):
            return name
    return "OTHER"


def scan() -> dict:
    agg = collections.defaultdict(lambda: {"src": 0, "test": 0})
    for root in ROOTS:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != "node_modules"]
            for name in files:
                if not name.endswith(EXT):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path, errors="ignore") as fh:
                        lines = sum(1 for _ in fh)
                except OSError:
                    continue
                lowered = path.lower()
                kind = "test" if ("test" in lowered or "mocks" in lowered) else "src"
                agg[bucket_for(path)][kind] += lines
    return {k: dict(v) for k, v in agg.items()}


def render(agg: dict) -> None:
    rows = sorted(agg.items(), key=lambda kv: -(kv[1]["src"] + kv[1]["test"]))
    print(f"{'bucket':18} {'src':>8} {'test':>8} {'total':>8}")
    totals = {"src": 0, "test": 0}
    for name, counts in rows:
        total = counts["src"] + counts["test"]
        print(f"{name:18} {counts['src']:8} {counts['test']:8} {total:8}")
        totals["src"] += counts["src"]
        totals["test"] += counts["test"]
    grand = totals["src"] + totals["test"]
    print(f"{'TOTAL':18} {totals['src']:8} {totals['test']:8} {grand:8}")
    keep = sum(c["src"] + c["test"] for n, c in agg.items() if n.startswith("KEEP"))
    remove = sum(c["src"] + c["test"] for n, c in agg.items() if n.startswith("RM"))
    other = grand - keep - remove
    print(f"\n  KEEP {keep:>8}   RM {remove:>8}   OTHER(shared) {other:>8}")


def compare(agg: dict, baseline: dict) -> None:
    names = sorted(set(agg) | set(baseline))
    print(f"{'bucket':18} {'baseline':>10} {'now':>10} {'delta':>10}")
    b_tot = n_tot = 0
    for name in names:
        b = baseline.get(name, {"src": 0, "test": 0})
        n = agg.get(name, {"src": 0, "test": 0})
        bs, ns = b["src"] + b["test"], n["src"] + n["test"]
        b_tot += bs
        n_tot += ns
        if bs or ns:
            print(f"{name:18} {bs:10} {ns:10} {ns - bs:+10}")
    print(f"{'TOTAL':18} {b_tot:10} {n_tot:10} {n_tot - b_tot:+10}")
    if b_tot:
        print(f"\n  removed {b_tot - n_tot} LOC ({100 * (b_tot - n_tot) / b_tot:.1f}% of baseline)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit a JSON snapshot")
    parser.add_argument("--compare", metavar="SNAPSHOT", help="diff against a saved JSON snapshot")
    args = parser.parse_args()

    agg = scan()
    if args.compare:
        with open(args.compare) as fh:
            compare(agg, json.load(fh))
    elif args.json:
        json.dump(agg, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        render(agg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
