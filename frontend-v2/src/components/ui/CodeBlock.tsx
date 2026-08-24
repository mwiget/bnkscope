/**
 * Read-only code view with line numbers and syntax highlighting.
 *
 * Reading code is the common case in a troubleshooting tool — an iRule, a
 * resource's YAML, a config fragment — and it does not need an editor. Monaco
 * costs 3.8 MB and now loads only when something is genuinely being edited
 * (`components/k8s/MonacoEditor.tsx`); this covers everything else at zero
 * bytes of dependency.
 *
 * The highlighting is deliberately shallow: a single regex pass per line,
 * no parser, no state carried between lines except the fenced-comment case
 * that does not arise in the two languages here. It is enough to make
 * structure visible at a glance, which is what a reader wants, and it cannot
 * mangle the text because the original substring is always what gets rendered.
 */
import { useMemo } from 'react';

import { cn } from '@/lib/utils';

export type CodeLanguage = 'yaml' | 'tcl' | 'json' | 'plain';

interface CodeBlockProps {
  code: string;
  language?: CodeLanguage;
  /** Hide the gutter. Useful for one-liners and inline fragments. */
  showLineNumbers?: boolean;
  /** Tailwind height/max-height utilities for the scroll container. */
  className?: string;
  'aria-label'?: string;
}

type Token = { text: string; className?: string };

// Token colours come from the theme's syntax tokens, which are a documented
// data-viz exemption to the token-purity rule (D-020) — a syntax palette that
// followed the chrome tokens would be unreadable.
const C = {
  key: 'text-info',
  string: 'text-success',
  number: 'text-warning',
  comment: 'text-muted-foreground italic',
  keyword: 'text-primary font-medium',
  variable: 'text-warning',
  punctuation: 'text-muted-foreground',
} as const;

// Ordered: the first pattern to match at a position wins, so comments and
// strings must precede anything that could match inside them.
const RULES: Record<Exclude<CodeLanguage, 'plain'>, [RegExp, string][]> = {
  yaml: [
    [/^\s*#.*/, C.comment],
    [/^\s*-\s/, C.punctuation],
    [/^\s*[\w.\-/]+(?=\s*:)/, C.key],
    [/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/, C.string],
    [/\b(?:true|false|null|yes|no|on|off)\b/, C.keyword],
    [/\b\d+(?:\.\d+)?\b/, C.number],
  ],
  tcl: [
    [/^\s*#.*/, C.comment],
    [/"(?:[^"\\]|\\.)*"/, C.string],
    // iRules are read for their event handlers first — `when HTTP_REQUEST`
    // is the thing an eye should land on.
    [/\bwhen\b|\b(?:if|elseif|else|switch|foreach|while|return|set|proc)\b/, C.keyword],
    [/\$\{?[\w:]+\}?/, C.variable],
    [/\[|\]|\{|\}/, C.punctuation],
    [/\b\d+\b/, C.number],
  ],
  json: [
    [/"(?:[^"\\]|\\.)*"(?=\s*:)/, C.key],
    [/"(?:[^"\\]|\\.)*"/, C.string],
    [/\b(?:true|false|null)\b/, C.keyword],
    [/-?\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\b/, C.number],
    [/[{}[\],:]/, C.punctuation],
  ],
};

/** Split one line into styled runs. Unmatched text passes through verbatim. */
function tokenize(line: string, language: CodeLanguage): Token[] {
  if (language === 'plain' || !line) return [{ text: line }];
  const rules = RULES[language];
  const tokens: Token[] = [];
  let rest = line;
  let plain = '';

  while (rest) {
    let matched = false;
    for (const [pattern, className] of rules) {
      // Anchor each attempt at the current position rather than searching
      // ahead, so a later rule cannot reach inside an earlier rule's match.
      const anchored = new RegExp(`^(?:${pattern.source})`);
      const m = anchored.exec(rest);
      if (m && m[0]) {
        if (plain) {
          tokens.push({ text: plain });
          plain = '';
        }
        tokens.push({ text: m[0], className });
        rest = rest.slice(m[0].length);
        matched = true;
        break;
      }
    }
    if (!matched) {
      plain += rest[0];
      rest = rest.slice(1);
    }
  }
  if (plain) tokens.push({ text: plain });
  return tokens;
}

export function CodeBlock({
  code,
  language = 'plain',
  showLineNumbers = true,
  className,
  'aria-label': ariaLabel,
}: CodeBlockProps) {
  const lines = useMemo(() => {
    const raw = code.replace(/\n$/, '').split('\n');
    return raw.map((line) => tokenize(line, language));
  }, [code, language]);

  const gutterWidth = `${String(lines.length).length + 1}ch`;

  return (
    <div
      className={cn(
        'overflow-auto rounded-md border border-border bg-muted/30 font-mono text-[13px] leading-[1.6]',
        className,
      )}
      role="region"
      aria-label={ariaLabel ?? `${language} code`}
      tabIndex={0}
    >
      <pre className="min-w-full p-3">
        <code>
          {lines.map((tokens, index) => (
            <div key={index} className="flex whitespace-pre hover:bg-muted/50">
              {showLineNumbers && (
                <span
                  className="flex-none select-none pr-4 text-right text-muted-foreground/60"
                  style={{ width: gutterWidth }}
                  aria-hidden="true"
                >
                  {index + 1}
                </span>
              )}
              <span className="flex-1">
                {tokens.map((token, i) => (
                  <span key={i} className={token.className}>
                    {token.text}
                  </span>
                ))}
                {/* Keeps an empty line clickable and the same height. */}
                {tokens.length === 0 && ' '}
              </span>
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
}
