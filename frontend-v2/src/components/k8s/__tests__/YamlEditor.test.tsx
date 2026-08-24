/**
 * Tests for YamlEditor component
 *
 * Mocks Monaco editor to test validation behavior.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@/test/test-utils';
import { YamlEditor } from '../YamlEditor';

// Mock Monaco editor
// Monaco itself is behind a dynamic import now (Phase 6 took it out of the
// initial payload), so the seam to stub is the wrapper, not the library.
vi.mock('../MonacoEditor', () => ({
  MonacoEditor: ({ value, onChange }: { value: string; onChange?: (v: string) => void }) => (
    <textarea
      data-testid="mock-editor"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

describe('YamlEditor', () => {
  it('shows Valid YAML badge for valid K8s manifest', () => {
    const validYaml = 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: test\n';
    render(<YamlEditor value={validYaml} onChange={vi.fn()} showValidation />);
    expect(screen.getByText('Valid YAML')).toBeInTheDocument();
  });

  it('shows warning for missing apiVersion', () => {
    const noApiVersion = 'kind: ConfigMap\nmetadata:\n  name: test\n';
    render(<YamlEditor value={noApiVersion} onChange={vi.fn()} showValidation />);
    expect(screen.getByText('Missing apiVersion field')).toBeInTheDocument();
  });

  it('shows error for invalid YAML syntax', () => {
    const invalidYaml = ':\n  bad: [\nyaml';
    render(<YamlEditor value={invalidYaml} onChange={vi.fn()} showValidation />);
    // Should show some error badge
    expect(screen.queryByText('Valid YAML')).not.toBeInTheDocument();
  });
});
