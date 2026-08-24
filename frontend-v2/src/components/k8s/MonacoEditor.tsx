/**
 * Monaco, loaded only when someone actually edits something.
 *
 * Monaco is 3.8 MB — 85% of what the browser used to download before the app
 * rendered a single pixel, for an editor most sessions never open. bnkscope is
 * a troubleshooting tool: you read resources constantly and edit one
 * occasionally, so the editor belongs behind a dynamic import and the reading
 * belongs in `CodeBlock`, which needs no library at all.
 *
 * The eager import in `main.tsx` was not gratuitous — it existed to keep
 * `@monaco-editor/react` from fetching Monaco off jsDelivr, which fails in the
 * air-gapped networks BNK clusters tend to live on. That requirement survives:
 * the local package is still what gets configured, just from inside this lazy
 * chunk instead of the entry bundle. Nothing is ever fetched from a CDN.
 */
import { Suspense, lazy } from 'react';
import { Loader2 } from 'lucide-react';

import type { MonacoEditorProps } from './monaco-types';

// One dynamic import pulls Monaco, its worker, and the React wrapper into a
// single chunk. Vite keeps them together because they are only reachable
// through here.
const LazyMonaco = lazy(async () => {
  const [{ default: Editor, loader }, monaco, { default: EditorWorker }] = await Promise.all([
    import('@monaco-editor/react').then((m) => ({ default: m.Editor, loader: m.loader })),
    import('monaco-editor'),
    import('monaco-editor/esm/vs/editor/editor.worker?worker'),
  ]);

  // Point the worker factory and the loader at the bundled copy, exactly as
  // main.tsx used to at startup. Idempotent: remounting reuses what is set.
  self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
  loader.config({ monaco });

  return { default: Editor };
});

export function MonacoEditor(props: MonacoEditorProps) {
  return (
    <Suspense
      fallback={
        <div
          className="flex items-center justify-center bg-muted/30 text-sm text-muted-foreground"
          style={{ height: props.height ?? '400px' }}
        >
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading editor…
        </div>
      }
    >
      <LazyMonaco {...props} />
    </Suspense>
  );
}
