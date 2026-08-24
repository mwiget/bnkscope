/**
 * Collapsing repeated log lines.
 *
 * A 500-line page of TMM and platform logs is mostly the same handful of
 * events restated. Measured on a live three-cluster estate, 500 lines came
 * from 106 distinct events — the rest were repeats, and the repeats were what
 * you had to scroll past to find anything.
 *
 * Exact text matching barely helps: it collapsed the same sample by only 20%,
 * because almost every line carries something that moves — a timestamp, a byte
 * count, a pod name, a flow cookie. So lines are grouped by their *shape*: the
 * volatile parts are replaced with placeholders and the result is the grouping
 * key. That took the same sample to 106 groups, a 79% cut.
 *
 * The shape is only ever a key. What is displayed is the newest real line in
 * the group, unredacted — `‹n›` is a grouping artefact, not something to read.
 *
 * The risk of normalising is over-collapsing: two genuinely different events
 * folded into one row, which hides information rather than compressing it. The
 * patterns below are therefore narrow and ordered most-specific-first, and the
 * feature has an off switch that shows every line as it arrived.
 */
import type { LogEntry } from '@/types/logs';

/**
 * Drop the syslog envelope TMM prefixes to every line.
 *
 *   <134>Aug 23 20:02:47 f5-tmm-hw4d6 tmm[46]: 01010058:6: audit log: ...
 *
 * The priority, date, host and process are already shown beside the line —
 * printing them again costs about sixty columns of the message. The F5 message
 * id is kept: it identifies the *kind* of event and is what you search for.
 */
export function stripSyslogHeader(line: string): string {
  return line.replace(
    /^<\d+>[A-Z][a-z]{2}\s+\d+\s+[\d:]+\s+\S+\s+[^[\]]+\[\d+\]:\s*/,
    '',
  );
}

/**
 * The grouping key: a line with everything that varies between occurrences
 * replaced by a placeholder.
 *
 * Order matters. Each pattern consumes text the later, broader ones would
 * otherwise chew into — an IPv4 address has to be matched before the bare
 * number rule turns it into `‹n›.‹n›.‹n›.‹n›`, and an ISO timestamp before its
 * digits go the same way. The bare-number rule is deliberately last.
 */
export function messageShape(line: string): string {
  return (
    stripSyslogHeader(line)
      // ISO-8601, with or without fractional seconds and zone.
      .replace(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/g, '‹ts›')
      // IPv4, optionally with a port.
      .replace(/\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b/g, '‹ip›')
      // MAC addresses, before the number rule splits them into six groups.
      .replace(/\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b/gi, '‹mac›')
      .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, '‹uuid›')
      // Kubernetes pod-name suffixes: a ReplicaSet hash and an ordinal, which
      // differ per replica for what is otherwise the same message.
      .replace(/-[0-9a-f]{8,10}-[a-z0-9]{5}\b/g, '-‹pod›')
      // Long hex runs: flow cookies, image digests, request ids. Seven is the
      // shortest that is reliably an identifier rather than an English word
      // spelled in [a-f] — "decade", "efface", "defaced" are all six.
      //
      // The 0x form is matched separately: after the `x` there is no word
      // boundary, so a single \b-anchored pattern silently skips exactly the
      // identifiers most likely to appear — OVS flow cookies.
      .replace(/\b0x[0-9a-f]+\b/gi, '‹hex›')
      .replace(/\b[0-9a-f]{7,}\b/gi, '‹hex›')
      // Clock times left over after the ISO rule.
      .replace(/\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b/g, '‹time›')
      // Sizes with a unit, before the digits go.
      .replace(/\b\d+(?:\.\d+)?\s?(?:[KMGT]i?B|ms|µs|ns|s)\b/g, '‹size›')
      .replace(/\b\d+\b/g, '‹n›')
  );
}

export interface LogGroup {
  /** The newest line in the group, shown verbatim. */
  latest: LogEntry;
  /** How many lines share this shape. 1 means it did not repeat. */
  count: number;
  /** Oldest occurrence in the window, for "seen N times since …". */
  firstTimestamp: number;
  /** Distinct pods the group spans; 1 unless the same event hit several. */
  podCount: number;
}

/**
 * Group entries by shape, newest first.
 *
 * Scoped by cluster, namespace and container as well as shape: the same
 * message from two different containers is two events that happen to read
 * alike, and merging them would attribute one container's output to another.
 * Pods are deliberately *not* part of the key — one event across three TMM
 * replicas is the case this is most useful for — so the pod of the newest
 * occurrence is shown, with a count when the group spans more.
 *
 * **Order comes from the array, not from comparing timestamps.** Loki stores
 * nanoseconds since the epoch, so a timestamp is ~1.79e18 — nearly two hundred
 * times `Number.MAX_SAFE_INTEGER`. In JavaScript two lines a few hundred
 * nanoseconds apart are literally `===`, and sorting on them silently keeps
 * whichever came first. The backend already sorts newest-first, in Python,
 * where the integers are exact (`logs_service.query_range`), so the first
 * occurrence seen here is the newest and the last is the oldest. The values
 * are still fine to *display*: `formatTime` divides down to milliseconds,
 * well inside precision.
 */
export function groupEntries(entries: LogEntry[]): LogGroup[] {
  const groups = new Map<string, LogGroup & { pods: Set<string> }>();

  for (const e of entries) {
    const key = [e.cluster, e.namespace, e.container, messageShape(e.line)].join(' ');
    const existing = groups.get(key);
    if (!existing) {
      groups.set(key, {
        latest: e,
        count: 1,
        firstTimestamp: e.timestamp,
        podCount: 1,
        pods: new Set(e.pod ? [e.pod] : []),
      });
      continue;
    }
    existing.count += 1;
    if (e.pod) existing.pods.add(e.pod);
    // Newest-first input: `latest` is the first one seen, and every later
    // occurrence is older — so the last one wins `firstTimestamp`.
    existing.firstTimestamp = e.timestamp;
  }

  // Insertion order is first-appearance order, which for newest-first input is
  // newest-group-first. Not re-sorted, for the same precision reason.
  return [...groups.values()].map(({ pods, ...g }) => ({
    ...g,
    podCount: Math.max(pods.size, 1),
  }));
}
