/**
 * The bnkscope mark.
 *
 * It is inlined rather than loaded through <img> so CSS can reach the `.beam`
 * path and sweep it. That is the one thing worth testing here — an <img> would
 * look identical and silently lose the animation — plus the size-based build
 * switch, since the full mark's code rain turns to mud below 32px.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { BnkscopeMark } from '@/components/branding/BnkscopeMark';

describe('BnkscopeMark', () => {
  it('inlines the SVG so the beam is reachable from CSS', () => {
    const { container } = render(<BnkscopeMark />);

    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    // The generated asset marks the sweep path; without it there is nothing
    // for the animation to attach to.
    expect(container.querySelector('.beam')).not.toBeNull();
  });

  it('normalises the beam length so one animation works at any size', () => {
    const { container } = render(<BnkscopeMark size={128} />);
    expect(container.querySelector('.beam')).toHaveAttribute('pathLength', '100');
  });

  it('only sweeps when asked', () => {
    const { container, rerender } = render(<BnkscopeMark />);
    expect(container.firstElementChild?.className).not.toContain('bnkscope-mark--sweep');

    rerender(<BnkscopeMark animate />);
    expect(container.firstElementChild?.className).toContain('bnkscope-mark--sweep');
  });

  it('is announced as an image named bnkscope', () => {
    render(<BnkscopeMark />);
    expect(screen.getByRole('img', { name: 'bnkscope' })).toBeInTheDocument();
  });

  it('takes a custom label', () => {
    render(<BnkscopeMark title="bnkscope home" />);
    expect(screen.getByRole('img', { name: 'bnkscope home' })).toBeInTheDocument();
  });

  it('renders at the requested size', () => {
    const { container } = render(<BnkscopeMark size={34} />);
    expect(container.firstElementChild).toHaveStyle({ width: '34px', height: '34px' });
  });

  it('fills its box rather than the asset’s own dimensions', () => {
    const { container } = render(<BnkscopeMark size={64} />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('width', '100%');
    expect(svg).toHaveAttribute('height', '100%');
  });

  it('switches to the small build below 32px, where the rain turns to mud', () => {
    const { container: big } = render(<BnkscopeMark size={64} />);
    const { container: small } = render(<BnkscopeMark size={16} />);

    // The small build is the one without the code rain and the blur filters,
    // so it is materially shorter — that difference is the switch.
    expect(small.innerHTML.length).toBeLessThan(big.innerHTML.length);
  });

  it('is not focusable — it is decoration next to a real link', () => {
    const { container } = render(<BnkscopeMark />);
    expect(container.querySelector('svg')).toHaveAttribute('focusable', 'false');
  });
});
