/**
 * Regression test for the EventTarget.dispatchEvent guard in ../setup.ts.
 *
 * Radix UI's focus-scope schedules a `setTimeout(0)` on unmount that dispatches
 * a CustomEvent. When it fires after jsdom has begun tearing the realm down,
 * dispatchEvent throws "parameter 1 is not of type 'Event'" — an unhandled
 * error that fails the whole vitest run even with every test green. It did
 * exactly that in CI on 2026-08-27: 1106 passed, 2 unhandled errors, red build.
 *
 * The guard has been wrong twice, both times for the same reason — a
 * cross-realm `instanceof` that disagrees with reality. This file pins both
 * halves so there is no third time.
 */
import { describe, it, expect } from 'vitest';

/** An unguarded dispatchEvent, borrowed from a child realm. */
function rawDispatch(): (this: EventTarget, event: Event) => boolean {
  const frame = document.createElement('iframe');
  document.body.appendChild(frame);
  const win = frame.contentWindow as unknown as { EventTarget: typeof EventTarget };
  return win.EventTarget.prototype.dispatchEvent;
}

describe('dispatchEvent post-teardown guard', () => {
  it('drops an object that passes instanceof but that jsdom will not accept', () => {
    // The shape that broke CI. Its prototype chain reaches Event, so
    // `instanceof` says yes, but jsdom holds no implementation entry for it, so
    // convert() rejects it. Guard v1 checked only instanceof and let it through.
    const detached = Object.create(Event.prototype) as Event;
    expect(detached instanceof Event).toBe(true);

    const el = document.createElement('div');
    expect(() => el.dispatchEvent(detached)).not.toThrow();
    expect(el.dispatchEvent(detached)).toBe(false);
  });

  it('recognises the failure by message, because instanceof TypeError is false', () => {
    // jsdom raises `globalObject.TypeError` — the throwing realm's constructor,
    // not this module's. Guard v2 caught on `err instanceof TypeError` and so
    // rethrew the very error it meant to swallow. Assert the mismatch directly,
    // so the reason the guard matches on the message stays visible.
    const el = document.createElement('div');
    let err: unknown;
    try {
      rawDispatch().call(el, Object.create(Event.prototype) as Event);
    } catch (e) {
      err = e;
    }

    expect(err).toBeDefined();
    expect((err as Error).constructor.name).toBe('TypeError');
    expect(err instanceof TypeError).toBe(false); // <- the trap
    expect((err as Error).message).toContain("not of type 'Event'");
  });

  it('still dispatches a real event', () => {
    const el = document.createElement('div');
    let seen = false;
    el.addEventListener('ping', () => {
      seen = true;
    });
    expect(el.dispatchEvent(new CustomEvent('ping'))).toBe(true);
    expect(seen).toBe(true);
  });

  it('still throws on an unrelated dispatch failure', () => {
    // The guard must stay narrow: only the post-teardown message is swallowed,
    // and every other dispatch error still reaches the caller. Re-entrant
    // dispatch is a real one — jsdom raises InvalidStateError for it.
    const el = document.createElement('div');
    const event = new CustomEvent('reentrant');
    let inner: unknown;
    el.addEventListener('reentrant', () => {
      try {
        el.dispatchEvent(event); // same event object, still in flight
      } catch (err) {
        inner = err;
      }
    });
    el.dispatchEvent(event);

    expect(inner).toBeDefined();
    expect((inner as Error).message).toMatch(/uninitialized event/);
    // The point of the case: it is NOT the teardown message, so the guard let
    // it through instead of swallowing it into a silent `false`.
    expect((inner as Error).message).not.toContain("not of type 'Event'");
  });
});
