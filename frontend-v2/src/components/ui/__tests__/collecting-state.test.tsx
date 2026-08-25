import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, screen } from '@testing-library/react';
import { render } from '@/test/test-utils';
import { CollectingState } from '../collecting-state';

describe('CollectingState', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('names what is being collected and lists what the read covers', () => {
    render(
      <CollectingState
        title="Collecting NICo inventory"
        detail="One read covers both halves."
        steps={['nico-api pods', 'Forge session']}
      />
    );
    expect(screen.getByText('Collecting NICo inventory')).toBeTruthy();
    expect(screen.getByText('One read covers both halves.')).toBeTruthy();
    expect(screen.getByText('nico-api pods')).toBeTruthy();
    expect(screen.getByText('Forge session')).toBeTruthy();
  });

  it('counts real elapsed seconds', () => {
    render(<CollectingState title="Collecting" />);
    expect(screen.getByText('0s')).toBeTruthy();
    act(() => void vi.advanceTimersByTime(3000));
    expect(screen.getByText('3s')).toBeTruthy();
  });

  it('withholds the slow note until the wait is actually long', () => {
    render(
      <CollectingState title="Collecting" slowAfterSeconds={12} slowNote="reflection is the slow part" />
    );
    expect(screen.queryByText('reflection is the slow part')).toBeNull();
    act(() => void vi.advanceTimersByTime(12_000));
    expect(screen.getByText('reflection is the slow part')).toBeTruthy();
  });

  it('marks itself busy for assistive tech', () => {
    const { container } = render(<CollectingState title="Collecting" />);
    const status = container.querySelector('[role="status"]');
    expect(status?.getAttribute('aria-busy')).toBe('true');
    expect(status?.getAttribute('aria-live')).toBe('polite');
  });
});
