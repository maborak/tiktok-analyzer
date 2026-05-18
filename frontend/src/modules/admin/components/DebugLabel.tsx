/**
 * Admin-only "name tag" labels for UI boxes.
 *
 * Two pieces:
 *   1. `DebugOverlay` — global. Mount once at the app root. Watches
 *      the DOM for any element with the `data-debug` attribute and
 *      attaches a tiny 4-character code label to its top-right
 *      corner. Uses a MutationObserver so labels follow React
 *      re-renders + route changes without per-page wiring.
 *   2. `DebugToggle` — tiny floating "🏷" button. Mount once. Click
 *      toggles labels on/off; state persists in localStorage.
 *
 * To label an element from a component, just add the attribute:
 *
 *     <div className="..." data-debug>...</div>
 *
 * No component import needed — the overlay sees it automatically.
 *
 * Codes are random 4 chars per element instance, reshuffled on a
 * hard reload. Collision risk on 1k+ labels is negligible. Each
 * code is also written back to the labelled element as
 * `data-debug-id` so it can be queried in DevTools.
 *
 * Toggle methods (any one):
 *   • Click the "🏷" button in the bottom-right of any admin page.
 *   • Keyboard: Ctrl+Shift+L (or Cmd+Shift+L on macOS).
 *   • URL: `?debug=1` enables (persists), `?debug=0` clears.
 *   • DevTools: `localStorage.setItem('tiktok-debug-labels', '1')`.
 */

import { useEffect, useState } from 'react';

const STORAGE_KEY = 'tiktok-debug-labels';
const CHANGE_EVENT = 'tiktok-debug-labels-changed';

function readStoredFlag(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function writeStoredFlag(on: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    if (on) window.localStorage.setItem(STORAGE_KEY, '1');
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Quota / privacy mode — toggle is ephemeral.
  }
}

/** Reads + reactively tracks the current debug-labels flag. */
export function useDebugLabels(): [boolean, () => void] {
  const [on, setOn] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const q = params.get('debug');
      if (q === '1') {
        writeStoredFlag(true);
        return true;
      }
      if (q === '0') {
        writeStoredFlag(false);
        return false;
      }
    }
    return readStoredFlag();
  });

  useEffect(() => {
    function handleStorage(e: StorageEvent) {
      if (e.key === STORAGE_KEY) setOn(readStoredFlag());
    }
    function handleCustom() {
      setOn(readStoredFlag());
    }
    function handleKey(e: KeyboardEvent) {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.shiftKey && (e.key === 'L' || e.key === 'l')) {
        e.preventDefault();
        const next = !readStoredFlag();
        writeStoredFlag(next);
        window.dispatchEvent(new Event(CHANGE_EVENT));
      }
    }
    window.addEventListener('storage', handleStorage);
    window.addEventListener(CHANGE_EVENT, handleCustom);
    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener(CHANGE_EVENT, handleCustom);
      window.removeEventListener('keydown', handleKey);
    };
  }, []);

  const toggle = () => {
    const next = !readStoredFlag();
    writeStoredFlag(next);
    setOn(next);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  };

  return [on, toggle];
}

function generateCode(): string {
  return Math.random().toString(36).slice(2, 6).padStart(4, '0');
}

// Inline styles for the badge. `pointerEvents: 'auto'` so the badge
// itself is clickable (the labeled element is otherwise untouched —
// the badge sits in absolute layer on top, and we cancel propagation
// on click so the underlying element doesn't receive the click).
const BADGE_STYLE: Partial<CSSStyleDeclaration> = {
  position:    'absolute',
  top:         '0',
  right:       '0',
  transform:   'translate(50%, -50%)',
  zIndex:      '9999',
  fontSize:    '8px',
  lineHeight:  '1',
  fontFamily:  'ui-monospace, SFMono-Regular, Menlo, monospace',
  background:  'rgb(192 38 211 / 0.95)',
  color:       'white',
  padding:     '1px 4px',
  borderRadius:'3px',
  pointerEvents:'auto',
  cursor:      'pointer',
  userSelect:  'text',  // selectable so you can copy the code manually
  whiteSpace:  'nowrap',
  boxShadow:   '0 1px 2px rgb(0 0 0 / 0.2)',
};

const BADGE_FLAG = '__tiktokDebugBadge';
const POSITION_PATCHED_FLAG = '__tiktokDebugPosPatched';
const BLINK_STYLE_ID = '__tiktokDebugBlinkStyle';
const BLINK_CLASS = '__tiktok-debug-blink';

/** Inject the blink keyframes once. Called from `attach` on first
 *  badge mount so the style tag only exists when labels are active.
 *  Animation is intentionally LOUD — 4 px fuchsia outline pulses
 *  twice over 1.8 s, with a translucent fuchsia overlay rendered
 *  via `box-shadow inset` (so it's clipped to the element's bounds
 *  even when the element has no background). `outline` (not
 *  `border`) so the element's own layout / sizing doesn't shift. */
function ensureBlinkStyle(): void {
  if (document.getElementById(BLINK_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = BLINK_STYLE_ID;
  // Use `!important` on the animation so any conflicting transition
  // / animation rule on the labeled element can't suppress it.
  style.textContent = `
    @keyframes __tiktok_debug_blink_kf {
      0%   { outline-color: rgba(217, 70, 239, 0);  outline-offset: 0px;  box-shadow: inset 0 0 0 9999px rgba(217, 70, 239, 0); }
      15%  { outline-color: rgba(217, 70, 239, 1);  outline-offset: 6px;  box-shadow: inset 0 0 0 9999px rgba(217, 70, 239, 0.20); }
      30%  { outline-color: rgba(217, 70, 239, 0.4);outline-offset: 2px;  box-shadow: inset 0 0 0 9999px rgba(217, 70, 239, 0.05); }
      50%  { outline-color: rgba(217, 70, 239, 1);  outline-offset: 6px;  box-shadow: inset 0 0 0 9999px rgba(217, 70, 239, 0.20); }
      70%  { outline-color: rgba(217, 70, 239, 0.4);outline-offset: 2px;  box-shadow: inset 0 0 0 9999px rgba(217, 70, 239, 0.05); }
      85%  { outline-color: rgba(217, 70, 239, 1);  outline-offset: 6px;  box-shadow: inset 0 0 0 9999px rgba(217, 70, 239, 0.20); }
      100% { outline-color: rgba(217, 70, 239, 0);  outline-offset: 0px;  box-shadow: inset 0 0 0 9999px rgba(217, 70, 239, 0); }
    }
    .${BLINK_CLASS} {
      /* Initialize outline so keyframes can interpolate its color
         from frame 0. NO !important — that would lock the base value
         and suppress the animation's color interpolation (browsers
         skip animations on !important properties unless the keyframes
         themselves use !important, which they can't). */
      outline-width: 4px;
      outline-style: solid;
      outline-color: rgba(217, 70, 239, 0);
      animation: __tiktok_debug_blink_kf 1.8s ease-in-out 1;
    }
  `;
  document.head.appendChild(style);
}

/** Global overlay. Scans the DOM for `[data-debug]` elements and
 *  attaches one label per element. Re-runs on subtree mutations so
 *  React re-renders are picked up. Removes everything when the
 *  toggle goes off. */
export function DebugOverlay() {
  const [on] = useDebugLabels();

  useEffect(() => {
    if (!on) return;
    if (typeof document === 'undefined') return;

    ensureBlinkStyle();

    function blinkTarget(target: Element): void {
      // Scroll into view so the operator actually sees the blink when
      // the clicked label belongs to an offscreen ancestor (e.g. a
      // card the user scrolled past).
      try {
        target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
      } catch {
        // Older browsers — fall through.
      }
      target.classList.remove(BLINK_CLASS);
      // Force reflow so re-adding the class restarts the animation
      // even if it was already mid-blink (rapid double-click).
      void (target as HTMLElement).offsetWidth;
      target.classList.add(BLINK_CLASS);
      // Auto-clean when the animation finishes so the class doesn't
      // linger and override the element's own outline / shadow.
      const onEnd = (e: Event) => {
        if ((e as AnimationEvent).animationName !== '__tiktok_debug_blink_kf') return;
        target.classList.remove(BLINK_CLASS);
        target.removeEventListener('animationend', onEnd);
      };
      target.addEventListener('animationend', onEnd);
    }

    function copyToClipboard(text: string): Promise<boolean> {
      // Modern path — async, requires secure context. Localhost
      // qualifies as secure, so this is the normal path in dev.
      if (navigator.clipboard?.writeText) {
        return navigator.clipboard.writeText(text)
          .then(() => true)
          .catch(() => execCopyFallback(text));
      }
      return Promise.resolve(execCopyFallback(text));
    }

    function execCopyFallback(text: string): boolean {
      // Synchronous fallback for non-secure contexts (e.g. plain HTTP
      // staging, very old browsers, or when the async clipboard API
      // is blocked by permissions policy). Drops a hidden <textarea>,
      // selects, copies, removes.
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        // Keep it offscreen but selectable.
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.left = '-1000px';
        ta.style.opacity = '0';
        ta.setAttribute('readonly', 'true');
        document.body.appendChild(ta);
        ta.select();
        ta.setSelectionRange(0, text.length);
        const ok = document.execCommand('copy');
        ta.remove();
        return ok;
      } catch {
        return false;
      }
    }

    function flashCopied(badge: HTMLSpanElement, originalText: string): void {
      // Brief visual ack so the operator sees the copy worked. Same
      // pill, swap text to "✓ copied" + green background, revert
      // after 900 ms.
      const prevBg = badge.style.background;
      badge.textContent = `✓ ${originalText}`;
      badge.style.background = 'rgb(16 185 129 / 0.95)';
      window.setTimeout(() => {
        badge.textContent = originalText;
        badge.style.background = prevBg;
      }, 900);
    }

    function attach(target: Element) {
      // Idempotent — don't double-attach.
      const t = target as HTMLElement & { [k: string]: unknown };
      if (t[BADGE_FLAG]) return;

      const code = generateCode();
      target.setAttribute('data-debug-id', code);

      const span = document.createElement('span');
      span.textContent = code;
      span.setAttribute('aria-hidden', 'true');
      span.setAttribute('data-debug-badge', code);
      span.title = `Click to blink + copy "${code}"`;
      Object.assign(span.style, BADGE_STYLE);

      // Click leak guard: when the labelled element is inside a
      // TanStack <Link> (or any router-aware <a>), the navigation
      // is wired via pointerdown / mousedown delegation — a plain
      // `stopPropagation()` on `click` is too late. Cancel ALL
      // pointer-precursor events on the badge so the click never
      // reaches the link layer, then prevent the click itself.
      const swallow = (e: Event) => {
        e.stopPropagation();
        e.stopImmediatePropagation();
        e.preventDefault();
      };
      span.addEventListener('pointerdown', swallow, true);
      span.addEventListener('mousedown',  swallow, true);
      span.addEventListener('mouseup',    swallow, true);
      span.addEventListener('pointerup',  swallow, true);
      span.addEventListener('auxclick',   swallow, true);

      span.addEventListener('click', (e) => {
        swallow(e);
        blinkTarget(target);
        copyToClipboard(code).then((ok) => {
          if (ok) flashCopied(span, code);
          // eslint-disable-next-line no-console
          console.log(
            `%c🏷 ${code}%c → ${ok ? 'copied to clipboard' : 'COPY FAILED'} + blinked. Element:`,
            'background:#c026d3;color:#fff;padding:2px 5px;border-radius:3px;font-family:monospace;',
            'color:inherit;',
            target,
          );
        });
      }, true);

      // Make sure the parent is a positioning context so the
      // absolute badge anchors correctly. Only patch when needed,
      // and remember we did so we can revert on cleanup.
      const cs = getComputedStyle(target);
      if (cs.position === 'static') {
        t.style.position = 'relative';
        t[POSITION_PATCHED_FLAG] = true;
      }

      target.appendChild(span);
      t[BADGE_FLAG] = span;
    }

    function detach(target: Element) {
      const t = target as HTMLElement & { [k: string]: unknown };
      const badge = t[BADGE_FLAG] as HTMLElement | undefined;
      if (badge) {
        badge.remove();
        delete t[BADGE_FLAG];
      }
      if (t[POSITION_PATCHED_FLAG]) {
        t.style.position = '';
        delete t[POSITION_PATCHED_FLAG];
      }
      target.classList.remove(BLINK_CLASS);
      target.removeAttribute('data-debug-id');
    }

    // Elements to auto-label without per-component opt-in. Keeps the
    // attribute opt-in (`data-debug`) for precise control AND grabs
    // existing semantic containers (cards, sections, asides) so the
    // operator gets coverage across pages that haven't been touched
    // yet. `main` is the page root inside PageShell — labelling it
    // gives the operator a "scope-of-page" handle.
    const AUTO_SELECTOR =
      '[data-debug],.card,section,aside,[role="region"],[role="article"]';

    function scan() {
      document.querySelectorAll(AUTO_SELECTOR).forEach(attach);
    }

    scan();

    const obs = new MutationObserver((mutations) => {
      for (const m of mutations) {
        m.addedNodes.forEach((node) => {
          if (!(node instanceof Element)) return;
          if (node.matches(AUTO_SELECTOR)) attach(node);
          node.querySelectorAll(AUTO_SELECTOR).forEach(attach);
        });
        m.removedNodes.forEach((node) => {
          if (!(node instanceof Element)) return;
          if (node.hasAttribute('data-debug-id')) detach(node);
          node.querySelectorAll('[data-debug-id]').forEach(detach);
        });
        if (m.type === 'attributes' && m.target instanceof Element) {
          const has = m.target.hasAttribute('data-debug');
          const had = m.target.hasAttribute('data-debug-id');
          if (has && !had) attach(m.target);
          else if (!has && had) detach(m.target);
        }
      }
    });
    obs.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-debug'],
    });

    return () => {
      obs.disconnect();
      document.querySelectorAll('[data-debug-id]').forEach(detach);
      // Tear down the keyframes <style> too — it shouldn't linger in
      // the DOM when debug mode is off.
      document.getElementById(BLINK_STYLE_ID)?.remove();
    };
  }, [on]);

  return null;
}

/** Floating toggle pill, fixed at the TOP of the viewport, centered
 *  and above every other UI layer. Always rendered; the pill flips
 *  fuchsia (on) / neutral gray (off) so the operator sees the
 *  current mode at a glance. */
export function DebugToggle() {
  const [on, toggle] = useDebugLabels();
  return (
    <button
      type="button"
      onClick={toggle}
      title={`Debug labels: ${on ? 'ON' : 'off'} — click or Ctrl/Cmd+Shift+L to toggle`}
      aria-label={`Toggle debug labels (currently ${on ? 'on' : 'off'})`}
      style={{
        position: 'fixed',
        top: '8px',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 10000,
        padding: '4px 10px',
        borderRadius: '999px',
        background: on
          ? 'rgb(192 38 211 / 0.95)'
          : 'rgb(75 85 99 / 0.55)',
        color: 'white',
        border: 'none',
        cursor: 'pointer',
        fontSize: '11px',
        lineHeight: '1',
        boxShadow: '0 2px 6px rgb(0 0 0 / 0.25)',
        fontFamily: 'ui-monospace, monospace',
        userSelect: 'none',
        letterSpacing: '0.04em',
      }}
    >
      {on ? '🏷 DEBUG ON' : '🏷 debug off'}
    </button>
  );
}

/** Legacy: explicit per-element label (kept as backward-compatible
 *  shim — equivalent to setting `data-debug` on the parent). New
 *  code should prefer the attribute; this still works for places
 *  that already use it. */
interface LegacyDebugLabelProps {
  corner?: 'tl' | 'tr' | 'bl' | 'br'; // ignored — always top-right now
}
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function DebugLabel(_props: LegacyDebugLabelProps = {}) {
  // The legacy component used to render the badge itself. Now the
  // overlay does it via `data-debug` on the parent. We keep this
  // export as a no-op so old call sites compile; the next pass
  // will migrate them to the attribute form.
  return null;
}

export default DebugOverlay;
