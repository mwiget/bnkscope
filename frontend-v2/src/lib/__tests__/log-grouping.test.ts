/**
 * Collapsing repeated log lines.
 *
 * Two failure modes, pulling in opposite directions. Under-collapsing leaves
 * the page as it was — exact text matching cut a real 500-line sample by only
 * 20%, because nearly every line carries something that moves. Over-collapsing
 * is worse: it folds genuinely different events into one row and hides them
 * behind a count, which is the opposite of what a troubleshooting view is for.
 *
 * So the tests come in pairs — what must collapse, and what must not.
 */
import { describe, expect, it } from 'vitest';

import { groupEntries, messageShape, stripSyslogHeader } from '@/lib/log-grouping';
import type { LogEntry } from '@/types/logs';

function entry(over: Partial<LogEntry> = {}): LogEntry {
  return {
    timestamp: 1787518322142145257,
    line: 'a message',
    cluster: 'scope',
    namespace: 'default',
    pod: 'f5-tmm-aaa',
    container: 'f5-tmm',
    level: 'info',
    ...over,
  };
}

describe('stripSyslogHeader', () => {
  it('drops the envelope and keeps the F5 message id', () => {
    expect(
      stripSyslogHeader('<133>Aug 23 20:52:02 f5-tmm-2lsvg tmm[46]: 01010397:5: throttling.'),
    ).toBe('01010397:5: throttling.');
  });

  it('leaves a line with no envelope alone', () => {
    expect(stripSyslogHeader('SSL profile loaded.')).toBe('SSL profile loaded.');
  });
});

describe('messageShape', () => {
  it('collapses a counter that moves between occurrences', () => {
    expect(messageShape('AOF write completed, nwritten: 1024')).toBe(
      messageShape('AOF write completed, nwritten: 4096'),
    );
  });

  it('collapses addresses, ports and timestamps', () => {
    expect(messageShape('client=10.0.0.1:5000 at 2026-08-24T10:00:00Z')).toBe(
      messageShape('client=192.168.1.9:31337 at 2026-08-24T11:22:33Z'),
    );
  });

  it('collapses the replica suffix of a pod name', () => {
    expect(messageShape('pod f5-downloader-5b578f874d-gfxdk is ready')).toBe(
      messageShape('pod f5-downloader-5b578f874d-zzzzz is ready'),
    );
  });

  it('collapses flow cookies and other long hex', () => {
    expect(messageShape('cookie=0xdeadbeef1234, table=2')).toBe(
      messageShape('cookie=0xfeedface5678, table=9'),
    );
  });

  // ── and what must NOT collapse ──────────────────────────────────────────

  it('keeps different messages apart', () => {
    expect(messageShape('AOF write started..')).not.toBe(
      messageShape('AOF write completed, nwritten: 12'),
    );
  });

  it('keeps different F5 message ids apart', () => {
    // The id names the kind of event. Folding two ids into one row would hide
    // a new failure inside the count of a familiar one.
    expect(messageShape('<133>Aug 23 20:52:02 h tmm[46]: 01010397:5: throttling.')).not.toBe(
      messageShape('<133>Aug 23 20:52:02 h tmm[46]: 01010058:6: audit log.'),
    );
  });

  it('keeps a changed verdict apart from an unchanged one', () => {
    expect(messageShape('acl match: action=drop src=10.0.0.1')).not.toBe(
      messageShape('acl match: action=accept src=10.0.0.1'),
    );
  });

  it('does not collapse a singular and a plural noun', () => {
    // Only the digits are normalised, not the words around them, so "1 byte"
    // and "2 bytes" stay separate. Worth pinning: it is a visible limit of
    // this approach, not an oversight.
    expect(messageShape('written 1 byte')).not.toBe(messageShape('written 2 bytes'));
  });

  it('does not treat a short word of hex letters as an identifier', () => {
    // "decade" is six chars of [a-f]; the hex rule starts at seven so ordinary
    // words are not replaced.
    expect(messageShape('cache decade entry')).toBe('cache decade entry');
  });
});

describe('groupEntries', () => {
  it('counts repeats and reports the newest occurrence', () => {
    // Newest-first, as `logs_service.query_range` returns them.
    const [g] = groupEntries([
      entry({ timestamp: 300, line: 'written 3 bytes' }),
      entry({ timestamp: 200, line: 'written 2 bytes' }),
      entry({ timestamp: 100, line: 'written 1 bytes' }),
    ]);

    expect(g.count).toBe(3);
    expect(g.firstTimestamp).toBe(100);
    // The newest *real* line, not the normalised shape — `‹n›` is a key, not
    // something to read.
    expect(g.latest.line).toBe('written 3 bytes');
  });

  it('keeps the order the backend sent', () => {
    const groups = groupEntries([
      entry({ timestamp: 900, line: 'newer event' }),
      entry({ timestamp: 100, line: 'older event' }),
    ]);

    expect(groups.map((g) => g.latest.line)).toEqual(['newer event', 'older event']);
  });

  it('does not depend on comparing nanosecond timestamps', () => {
    // Loki timestamps are ~1.79e18 — nearly two hundred times
    // Number.MAX_SAFE_INTEGER. These two are 2ns apart and JavaScript cannot
    // tell them apart at all: `1787518322142145257 === 1787518322142145259`.
    // Grouping therefore reads order from the array, which the backend sorted
    // in Python where the integers are exact.
    const a = 1787518322142145257;
    const b = 1787518322142145259;
    expect(a).toBe(b); // the hazard itself, pinned

    const [g] = groupEntries([
      entry({ timestamp: b, line: 'written 30 bytes' }),
      entry({ timestamp: a, line: 'written 10 bytes' }),
    ]);

    expect(g.latest.line).toBe('written 30 bytes');
    expect(g.count).toBe(2);
  });

  it('merges the same event across pod replicas, and says how many', () => {
    // The case this is most useful for: three TMMs logging one thing.
    const groups = groupEntries([
      entry({ pod: 'f5-tmm-a', line: 'throttling at 1' }),
      entry({ pod: 'f5-tmm-b', line: 'throttling at 2' }),
      entry({ pod: 'f5-tmm-c', line: 'throttling at 3' }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].podCount).toBe(3);
  });

  it('does not merge across containers', () => {
    // Two containers emitting text that reads alike are two events; merging
    // would attribute one container's output to the other.
    const groups = groupEntries([
      entry({ container: 'f5-tmm', line: 'ready' }),
      entry({ container: 'observer', line: 'ready' }),
    ]);

    expect(groups).toHaveLength(2);
  });

  it('does not merge across clusters', () => {
    const groups = groupEntries([
      entry({ cluster: 'scope', line: 'ready' }),
      entry({ cluster: 'other', line: 'ready' }),
    ]);

    expect(groups).toHaveLength(2);
  });

  it('leaves a one-off as a group of one', () => {
    const groups = groupEntries([entry({ line: 'happened once' })]);
    expect(groups[0].count).toBe(1);
    expect(groups[0].podCount).toBe(1);
  });

  it('handles an empty page', () => {
    expect(groupEntries([])).toEqual([]);
  });
});
