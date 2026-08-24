# D-037: F5 High Speed Logging as a bnkscope feature

**Status:** Deferred — built, verified against a live cluster, then removed
pending a decision on the namespace problem below.
**Date:** 2026-08-24
**Removed in:** the commit carrying this file. The implementation is recoverable
from `a9f70a3..47e679a`.

---

## Context & Problem Statement

The Logs page collects pod stdout through the Kubernetes API. That is everything
the *pods* say, and none of what TMM **does** to traffic — connections accepted,
ACL rules matched, requests proxied. Those never reach container stdout. F5's
answer is High Speed Logging: TMM dials out to a syslog listener and streams
dataplane events to it.

bnkscope already runs the receiver it would need (Alloy, feeding Loki with a 24h
window matching Prometheus). The missing half is the cluster-side config: an
`F5BigLogHslpub` naming bnkscope as the destination, and an `F5BigLogProfile`
selecting which events to publish.

This would be **the only bnkscope feature that writes persistent config to an
operator's cluster.** Everything else is read-only or ephemeral — the metrics
exporter is an ephemeral container that dies with the pod. That asymmetry drove
the whole design: preview before write, a `managed-by` label gating deletion,
and a refusal to attach the profile to anyone's traffic config.

## What was built

- `services/hsl_service.py` — `preview` / `enable` / `disable` / `status`, with
  the manifests rendered for the UI before the button that creates them.
- `routes/hsl.py`, a **Dataplane Logs** page, and an `loki.source.syslog` block
  on port 1514 in the generated Alloy config.
- Objects created in the **TMM namespace**, derived from the running `f5-tmm`
  pods rather than asked for.

It reached the cluster and reconciled. Both objects report
`CR config sent to all grpc endpoints`. What it never did was produce a log line
from TMM itself.

## What was learned

Each of these was measured on a live BNK 2.3.1 cluster, not inferred.

### The wire format is not negotiable

`protocol: tcp` + `format: rfc3164` in the publisher, matching Alloy's listener
exactly. Anything else and TMM connects, sends, and every line is dropped at the
far end — a working publisher with no logs.

Alloy's syslog parser also rejects the connection outright, not the line, when
framing is wrong: a message that does not start with `<PRI>` fails as
`invalid or unsupported framing. first byte: 'c'`, and nothing on that
connection arrives.

### An enabled profile logs nothing until something references it

`BNKSecPolicy.spec.extensionRefs` is the attachment point, and it is the
operator's own traffic config. bnkscope creates the objects and stops there —
which means the honest state after "Enable" is *two green ticks and no logs*.
A `prerequisites()` check was added to say so rather than let it be discovered.

The stock profile publishes **firewall ACL match** events. With no
`F5BigFwPolicy` on the cluster there is no ACL to match, so `configview acl` is
empty and TMM correctly logs nothing.

### **The blocker: `extensionRefs` are namespace-local**

The profile has to live in the TMM namespace (`default`) to be reconciled. Every
real Gateway lives somewhere else. A `BNKSecPolicy` in the Gateway's namespace
referencing it fails:

```
F5BigLogProfile CR "scn-httproute-e2e"/"bnkscope-hsl" does not exist
```

`extensionRefs` has `group`, `kind` and `name` and **no namespace field**.
Copying the profile into the Gateway's namespace resolves it immediately — so
the mechanism works, and bnkscope's placement is what does not.

This is what the feature founders on: bnkscope would have to create a profile
per Gateway namespace, and then the "one object, one owner, delete only what we
labelled" story becomes N objects across namespaces bnkscope does not otherwise
touch. Note the profile→publisher edge *does* resolve cross-namespace; only
secpolicy→profile does not.

### An HSL line carries no cluster identity

`loki.source.syslog` sees a TCP connection and a line. The source address is a
TMM pod's, which bnkscope has no map from, so every line landed under `job="hsl"`
with no `cluster` label and the per-cluster panel was structurally always empty.

Three fixes were considered. A per-cluster listener port is exact but makes
enabling a cluster need a collector restart. Relabelling from
`__syslog_connection_ip_address` against each cluster's TMM subnet needs no
restart but is a heuristic. **The chosen one — the profile stamps the name into
the message** — is exact and needs no restart:

```
spec.firewall.network.format:
  type: user-defined
  userDefinedFieldList: "cluster=scope event=${event_name} action=${action} ..."
```

and the collector reads it back with `(^| )cluster=(?P<cluster>[^ ]+)`. This was
implemented and verified end to end: the CRD accepts the format, the profile
reconciles, and a line carrying the stamp arrives labelled
`cluster=scope level=info f5_msgid=01010058`.

Its cost: it only covers messages the *profile* formats. An operator's own iRule
has to include `cluster=<name>` by convention, and nothing enforces it. The
CRD's `userDefinedFieldList` pattern also forbids a literal `$`, and the
collector reads to the next space, so the cluster name needs sanitising for two
readers at once.

### An iRule can feed the publisher directly

`HSL::open` / `HSL::send` ([clouddocs](https://clouddocs.f5.com/api/irules/HSL.html))
turn an access log of every request through a Gateway into a few lines of TCL.
Two things are BNK-specific and undocumented:

- **The publisher name is the CR name with `-hslpublisher` appended** —
  `bnkscope-hsl-hslpublisher`. Neither the bare CR name nor the namespaced id
  `configview hsl_publisher` prints resolves.
- **The iRule writes the whole syslog line.** Despite the destination being
  declared `format: rfc3164`, TMM passes an iRule's payload through untouched:
  priority, timestamp, host, `tag[pid]:` and a trailing newline all have to be
  in the string.

Also: `IP::local_addr` in `HTTP_RESPONSE` is the *pool member*, not the VIP. The
VIP has to be captured in `CLIENT_ACCEPTED`.

This path needs no log profile and no `BNKSecPolicy` — only the publisher — so
it sidesteps the namespace blocker entirely. It is attached with a
`BNKNetPolicy`, and a Gateway section accepts exactly one of those
(`RefCollision` otherwise).

For a handful of events an iRule does not need HSL at all: `log local0.info`
lands in the TMM container log, which the Logs page already collects, tagged
with the rule and event that fired it:

```
<134>Aug 24 07:41:21 f5-tmm-tjvvg tmm[46]: Rule scn-aitok-dssm-aitok-counter <HTTP_RESPONSE_DATA>: TOK_COUNT vs=llm-chat prompt=6 completion=72 total=78
```

## Decision

Remove the feature; keep this record.

The namespace problem is not a bug to fix in an afternoon — it changes what
bnkscope owns on someone's cluster, from two labelled objects in one namespace
to a set that follows the operator's Gateways around. That is a decision about
the tool's boundary, not an implementation detail, and it should be made
deliberately rather than inherited from a feature that shipped before the
question was asked.

Removing it also closes `0.0.0.0:1514`, which had no producer.

## Consequences

- bnkscope is read-only and ephemeral again, with no exception to explain.
- Dataplane events are not collectable. The Logs page carries pod stdout only,
  and that limit is now the honest description of it.
- The iRule path above still works for anyone who wants it, using their own
  publisher. It is the cheaper half of this feature and does not need bnkscope
  to own anything.

## Resume trigger

Reopen when there is an answer to: **what does bnkscope own, and where, when the
Gateways it must attach to are spread across namespaces it otherwise only
reads?** A per-namespace profile is the obvious implementation; whether that is
a tool that reads your cluster or one that configures it is the actual question.

## References

- [D-036](D-036-tmmscope-injection-in-bnkscope.md) — the ephemeral-injection
  precedent, and why HSL could not follow it
- `a9f70a3`, `a2c0d01`, `824ead0`, `47e679a` — the implementation
- F5 iRules HSL: <https://clouddocs.f5.com/api/irules/HSL.html>
