/**
 * The read-only code view that replaced Monaco for reading (Phase 6).
 *
 * The property that actually matters is the boring one: **the rendered text is
 * the input text, exactly.** A highlighter that drops or reorders a character
 * is worse than no highlighter, because the operator is reading this to decide
 * what is wrong with a cluster. Most of these tests check that, and a few check
 * that the highlighting is doing anything at all.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { CodeBlock } from '../CodeBlock';

/** The text content of the code area, gutter excluded. */
function codeText(container: HTMLElement): string {
  return Array.from(container.querySelectorAll('code > div'))
    .map((line) => {
      const spans = line.querySelectorAll(':scope > span');
      // The last span is the content; the first is the gutter when present.
      return spans[spans.length - 1]?.textContent ?? '';
    })
    .join('\n');
}

describe('CodeBlock', () => {
  describe('fidelity', () => {
    it('renders YAML back exactly as given', () => {
      const code = [
        '# a comment',
        'apiVersion: v1',
        'kind: Pod',
        'metadata:',
        '  name: "quoted-name"',
        '  labels:',
        '    app: f5-tmm',
        'spec:',
        '  replicas: 3',
        '  enabled: true',
      ].join('\n');

      const { container } = render(<CodeBlock code={code} language="yaml" />);
      expect(codeText(container)).toBe(code);
    });

    it('renders TCL back exactly as given', () => {
      const code = [
        '# rewrite the host header',
        'when HTTP_REQUEST {',
        '    if { [HTTP::host] equals "old.example.com" } {',
        '        HTTP::header replace Host $newhost',
        '    }',
        '}',
      ].join('\n');

      const { container } = render(<CodeBlock code={code} language="tcl" />);
      expect(codeText(container)).toBe(code);
    });

    it('preserves leading whitespace, which is load-bearing in YAML', () => {
      const code = 'a:\n      deeply: indented';
      const { container } = render(<CodeBlock code={code} language="yaml" />);
      expect(codeText(container)).toBe(code);
    });

    it('does not mangle a line that matches several rules at once', () => {
      const code = 'message: "when 42 true"  # trailing';
      const { container } = render(<CodeBlock code={code} language="yaml" />);
      expect(codeText(container)).toBe(code);
    });

    it('leaves plain text completely alone', () => {
      const code = 'key: value # not yaml here\nwhen { $x }';
      const { container } = render(<CodeBlock code={code} language="plain" />);
      expect(codeText(container)).toBe(code);
    });

    it('handles an empty string without rendering a phantom line', () => {
      const { container } = render(<CodeBlock code="" language="yaml" />);
      expect(container.querySelectorAll('code > div')).toHaveLength(1);
    });

    it('does not add a blank line for a trailing newline', () => {
      const { container } = render(<CodeBlock code={'a: 1\nb: 2\n'} language="yaml" />);
      expect(container.querySelectorAll('code > div')).toHaveLength(2);
    });

    it('keeps interior blank lines', () => {
      const code = 'a: 1\n\nb: 2';
      const { container } = render(<CodeBlock code={code} language="yaml" />);
      expect(container.querySelectorAll('code > div')).toHaveLength(3);
    });

    it('renders text that looks like markup as text', () => {
      const code = 'note: <script>alert(1)</script>';
      const { container } = render(<CodeBlock code={code} language="yaml" />);
      expect(codeText(container)).toBe(code);
      expect(container.querySelector('script')).toBeNull();
    });
  });

  describe('line numbers', () => {
    it('numbers every line from one', () => {
      render(<CodeBlock code={'a\nb\nc'} language="plain" />);
      expect(screen.getByText('1')).toBeInTheDocument();
      expect(screen.getByText('3')).toBeInTheDocument();
    });

    it('can be turned off', () => {
      render(<CodeBlock code={'a\nb'} language="plain" showLineNumbers={false} />);
      expect(screen.queryByText('1')).not.toBeInTheDocument();
    });
  });

  describe('highlighting', () => {
    it('marks a YAML key', () => {
      const { container } = render(<CodeBlock code="apiVersion: v1" language="yaml" />);
      const key = Array.from(container.querySelectorAll('span')).find(
        (s) => s.textContent === 'apiVersion',
      );
      expect(key?.className).toContain('text-info');
    });

    it('marks a comment', () => {
      const { container } = render(<CodeBlock code="# just a note" language="yaml" />);
      // The whole line is one token, so the content wrapper has the same text
      // as the token inside it — take the innermost span.
      const comment = Array.from(container.querySelectorAll('span')).findLast(
        (s) => s.textContent === '# just a note',
      );
      expect(comment?.className).toContain('italic');
    });

    it('marks the iRule event keyword, which is what an eye looks for first', () => {
      const { container } = render(<CodeBlock code="when HTTP_REQUEST {" language="tcl" />);
      const keyword = Array.from(container.querySelectorAll('span')).find(
        (s) => s.textContent === 'when',
      );
      expect(keyword?.className).toContain('text-primary');
    });

    it('marks a TCL variable', () => {
      const { container } = render(<CodeBlock code="set x $host" language="tcl" />);
      const variable = Array.from(container.querySelectorAll('span')).find(
        (s) => s.textContent === '$host',
      );
      expect(variable).toBeDefined();
    });

    it('distinguishes a JSON key from a JSON string value', () => {
      const { container } = render(<CodeBlock code={'{"name": "tmm"}'} language="json" />);
      const spans = Array.from(container.querySelectorAll('span'));
      const key = spans.find((s) => s.textContent === '"name"');
      const value = spans.find((s) => s.textContent === '"tmm"');
      expect(key?.className).toContain('text-info');
      expect(value?.className).toContain('text-success');
    });

    it('does not highlight inside a string', () => {
      // `true` here is part of the value, not a keyword.
      const { container } = render(<CodeBlock code={'msg: "true"'} language="yaml" />);
      const string = Array.from(container.querySelectorAll('span')).find(
        (s) => s.textContent === '"true"',
      );
      expect(string?.className).toContain('text-success');
    });
  });

  describe('accessibility', () => {
    it('is a labelled, focusable region so it can be scrolled by keyboard', () => {
      render(<CodeBlock code="a: 1" language="yaml" aria-label="pod manifest" />);
      const region = screen.getByRole('region', { name: 'pod manifest' });
      expect(region).toHaveAttribute('tabIndex', '0');
    });

    it('falls back to naming the language', () => {
      render(<CodeBlock code="a: 1" language="yaml" />);
      expect(screen.getByRole('region', { name: 'yaml code' })).toBeInTheDocument();
    });

    it('hides the gutter from screen readers', () => {
      const { container } = render(<CodeBlock code={'a\nb'} language="plain" />);
      const gutter = container.querySelector('[aria-hidden="true"]');
      expect(gutter?.textContent).toBe('1');
    });
  });
});
