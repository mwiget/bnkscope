/**
 * stores/uiStore — theme state
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useUIStore } from '../uiStore';

describe('useUIStore', () => {
  beforeEach(() => {
    // Reset store to defaults (D-020: default theme is light, dark is opt-in)
    useUIStore.setState({
      theme: 'light',
    });
  });

  it('has initial theme = light', () => {
    expect(useUIStore.getState().theme).toBe('light');
  });

  it('setTheme changes theme', () => {
    useUIStore.getState().setTheme('light');
    expect(useUIStore.getState().theme).toBe('light');

    useUIStore.getState().setTheme('dark');
    expect(useUIStore.getState().theme).toBe('dark');
  });

  it('toggleTheme flips between light and dark', () => {
    useUIStore.getState().setTheme('dark');
    useUIStore.getState().toggleTheme();
    expect(useUIStore.getState().theme).toBe('light');

    useUIStore.getState().toggleTheme();
    expect(useUIStore.getState().theme).toBe('dark');
  });
});
