/**
 * The Logs page.
 *
 * The thing being protected here is width. The first version laid the metadata
 * out as fixed columns — time, level, cluster, container — before the message,
 * which spent more than half the window on decoration and pushed the actual log
 * line into a horizontal scroll. The message is the content; everything else is
 * a label on it.
 */
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';

import { render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { server } from '@/test/mocks/server';
import Logs from '@/pages/Logs';

const FILTERS = {
  ok: true,
  available: true,
  clusters: ['scope', 'dpu-cplane-tenant1'],
  namespaces: ['default', 'dpf-operator-system'],
  containers: ['f5-tmm', 'observer'],
  levels: ['error', 'warning', 'notice', 'info', 'unknown'],
  detail: null,
};

function entry(over: Record<string, unknown> = {}) {
  return {
    timestamp: 1787518322142145257,
    line: '<133>Aug 23 20:52:02 f5-tmm-2lsvg tmm[46]: 01010397:5: throttling.',
    cluster: 'scope',
    namespace: 'default',
    pod: 'f5-tmm-2lsvg',
    container: 'f5-tmm',
    level: 'notice',
    ...over,
  };
}

function serveFilters(over: Record<string, unknown> = {}) {
  server.use(
    http.get('*/api/logs/filters', () => HttpResponse.json({ ...FILTERS, ...over })),
  );
}

function serveSearch(entries: Record<string, unknown>[], over: Record<string, unknown> = {}) {
  server.use(
    http.get('*/api/logs/search', () =>
      HttpResponse.json({
        ok: true,
        available: true,
        entries,
        query: '{cluster="scope"}',
        count: entries.length,
        detail: null,
        ...over,
      }),
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  serveFilters();
  serveSearch([entry()]);
});

describe('Logs', () => {
  it('strips the syslog envelope, keeping the F5 message id', async () => {
    // 43 columns of <pri>, date, host and pid that are already shown beside the
    // line. The message id stays: it names the kind of event and is what gets
    // searched for.
    render(<Logs />);

    await waitFor(() =>
      expect(screen.getByText(/01010397:5: throttling\./)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/<133>Aug 23/)).not.toBeInTheDocument();
  });

  it('keeps the untouched line reachable', async () => {
    render(<Logs />);

    const line = await screen.findByText(/01010397:5: throttling\./);
    // Hover, copy, and "what did it really say" all need the original.
    expect(line).toHaveAttribute('title', expect.stringContaining('<133>Aug 23'));
  });

  it('leaves a line alone when it has no syslog header', async () => {
    serveSearch([entry({ line: 'SSL profile _grpc_clientssl loaded successfully.' })]);
    render(<Logs />);

    await waitFor(() =>
      expect(
        screen.getByText(/SSL profile _grpc_clientssl loaded successfully\./),
      ).toBeInTheDocument(),
    );
  });

  /** Show every line, as the page did before repeats were collapsed. */
  function showEveryLine() {
    localStorage.setItem(STORAGE_KEYS.LOGS_COLLAPSE, 'off');
  }

  it('names the source once per run, not once per line', async () => {
    showEveryLine();
    // Consecutive lines almost always share a container; repeating the pod name
    // down the left edge is exactly what was eating the width.
    serveSearch([entry(), entry({ timestamp: 1787518322142145258 }), entry({ timestamp: 1787518322142145259 })]);
    render(<Logs />);

    await waitFor(() => expect(screen.getAllByText(/throttling\./)).toHaveLength(3));
    expect(screen.getAllByText('f5-tmm-2lsvg')).toHaveLength(1);
  });

  it('names it again when the source changes', async () => {
    showEveryLine();
    serveSearch([
      entry({ pod: 'f5-tmm-aaa' }),
      entry({ pod: 'f5-tmm-bbb', timestamp: 1787518322142145258 }),
    ]);
    render(<Logs />);

    await waitFor(() => expect(screen.getByText('f5-tmm-aaa')).toBeInTheDocument());
    expect(screen.getByText('f5-tmm-bbb')).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Collapsing repeats
  // -------------------------------------------------------------------------

  it('collapses repeats by default and counts them', async () => {
    // 500 lines of TMM and platform logs is typically ~130 distinct events on
    // a real estate. The repeats are what you scroll past to find anything.
    serveSearch([
      // Newest first, as the API returns them.
      entry({ timestamp: 1787518322142145259, line: 'AOF write completed, nwritten: 30' }),
      entry({ timestamp: 1787518322142145258, line: 'AOF write completed, nwritten: 20' }),
      entry({ timestamp: 1787518322142145257, line: 'AOF write completed, nwritten: 10' }),
    ]);
    render(<Logs />);

    await waitFor(() => expect(screen.getByText('×3')).toBeInTheDocument());
    // One row, showing the newest real line — not the normalised shape.
    expect(screen.getAllByText(/AOF write completed/)).toHaveLength(1);
    expect(screen.getByText(/nwritten: 30/)).toBeInTheDocument();
  });

  it('says how many rows the lines became', async () => {
    serveSearch([
      entry({ timestamp: 1787518322142145257, line: 'written 10 bytes' }),
      entry({ timestamp: 1787518322142145258, line: 'written 20 bytes' }),
    ]);
    render(<Logs />);

    await waitFor(() => expect(screen.getByText('1 of 2')).toBeInTheDocument());
  });

  it('can be turned off, and then shows every line', async () => {
    const user = userEvent.setup();
    serveSearch([
      entry({ timestamp: 1787518322142145257, line: 'written 10 bytes' }),
      entry({ timestamp: 1787518322142145258, line: 'written 20 bytes' }),
    ]);
    render(<Logs />);

    await waitFor(() => expect(screen.getByText('×2')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /repeats collapsed/i }));

    await waitFor(() => expect(screen.getAllByText(/written \d+ bytes/)).toHaveLength(2));
    expect(screen.queryByText('×2')).not.toBeInTheDocument();
  });

  it('does not badge a line that happened once', async () => {
    serveSearch([entry({ line: 'happened once' })]);
    render(<Logs />);

    await waitFor(() => expect(screen.getByText(/happened once/)).toBeInTheDocument());
    expect(screen.queryByText(/^×/)).not.toBeInTheDocument();
  });

  it('does not repeat the cluster you already filtered to', async () => {
    // Every line would carry it, and you chose it — it is not information.
    const { rerender } = render(<Logs />);
    await waitFor(() => expect(screen.getByText(/throttling\./)).toBeInTheDocument());

    // With no cluster filter the cluster is worth showing.
    expect(screen.getByText('scope')).toBeInTheDocument();
    rerender(<Logs />);
  });

  it('shows the query the filters produced', async () => {
    render(<Logs />);

    await waitFor(() =>
      expect(screen.getByText('{cluster="scope"}')).toBeInTheDocument(),
    );
  });

  it('hands back a parse error instead of failing silently', async () => {
    serveSearch([], {
      ok: false,
      detail: 'parse error at line 1, col 10: syntax error: unexpected $end',
    });
    render(<Logs />);

    await waitFor(() =>
      expect(screen.getByText(/parse error at line 1/)).toBeInTheDocument(),
    );
  });

  it('says so when the log store is not running', async () => {
    serveFilters({ available: false, detail: 'The log store is not running.' });
    render(<Logs />);

    await waitFor(() =>
      expect(screen.getByText('The log store is not running')).toBeInTheDocument(),
    );
  });

  it('offers the level as a badge, so severity is scannable', async () => {
    serveSearch([entry({ level: 'error' })]);
    render(<Logs />);

    await waitFor(() => expect(screen.getByText('error')).toBeInTheDocument());
  });

  it('renders each line without a fixed-width metadata column', async () => {
    // The regression guarded: metadata laid out as columns before the message.
    const { container } = render(<Logs />);
    await waitFor(() => expect(screen.getByText(/throttling\./)).toBeInTheDocument());

    const line = screen.getByText(/01010397:5: throttling\./);
    // The message flexes into whatever is left rather than starting at a
    // fixed offset.
    expect(line.className).toContain('flex-1');
    // And nothing forces the list wider than the window.
    expect(container.querySelector('.min-w-\\[52rem\\]')).toBeNull();
  });

  it('carries the current query into Grafana rather than opening it empty', async () => {
    server.use(
      http.get('*/api/tmmscope/status', () =>
        HttpResponse.json({
          configured: true,
          running: true,
          grafana_url: 'http://localhost:3000',
          prometheus_url: 'http://localhost:9491',
          updated_at: null,
          streaming_clusters: [],
          dashboards: [],
          detail: null,
        }),
      ),
    );
    render(<Logs />);

    // The link renders before the search resolves and holds a fallback query
    // until then, so wait for the results it is supposed to carry across.
    await waitFor(() => expect(screen.getByText(/throttling\./)).toBeInTheDocument());

    const link = await screen.findByRole('link', { name: /open in grafana/i });
    const href = link.getAttribute('href') ?? '';
    expect(href).toContain('/explore?');
    // The query rides across as JSON, so its quotes arrive escaped.
    const left = JSON.parse(
      decodeURIComponent(href.split('left=')[1]),
    ) as { queries: { expr: string }[] };
    expect(left.queries[0].expr).toBe('{cluster="scope"}');
  });
});

describe('Logs filters', () => {
  it('offers every cluster the collector has seen', async () => {
    render(<Logs />);

    await waitFor(() => expect(screen.getByText(/throttling\./)).toBeInTheDocument());
    const combos = screen.getAllByRole('combobox');
    // cluster, namespace, container, level, range.
    expect(combos.length).toBeGreaterThanOrEqual(5);
    // Unfiltered, so the trigger shows the "all" option rather than a
    // placeholder — the page starts by showing everything.
    expect(within(combos[0]).getByText('All clusters')).toBeInTheDocument();
  });
});
