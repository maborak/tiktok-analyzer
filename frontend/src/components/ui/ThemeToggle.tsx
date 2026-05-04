import { Sun, Monitor, Moon } from 'lucide-react';
import { useTheme } from '@/contexts/ThemeContext';
import type { ThemePreference } from '@/contexts/ThemeContext';

const options: { value: ThemePreference; icon: typeof Sun; label: string }[] = [
  { value: 'light', icon: Sun, label: 'Light' },
  { value: 'system', icon: Monitor, label: 'System' },
  { value: 'dark', icon: Moon, label: 'Dark' },
];

/**
 * Compact three-option theme switch. Renders as a radio group so keyboard
 * users can arrow between the choices and screen readers announce state.
 *
 * Designed to fit in the sidebar footer: ~84px wide, 28px tall.
 */
export function ThemeToggle() {
  const { preference, setPreference } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="Theme preference"
      className="flex gap-0.5 rounded-md p-0.5"
      style={{
        backgroundColor: 'var(--color-surface-sunken)',
        border: '1px solid var(--color-border-primary)',
      }}
    >
      {options.map(({ value, icon: Icon, label }) => {
        const isActive = preference === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={isActive}
            aria-label={label}
            title={label}
            onClick={() => setPreference(value)}
            className="flex items-center justify-center w-7 h-6 rounded transition-all"
            style={{
              // The primary accent stays saturated indigo in both themes,
              // so hardcoding is intentional — tokens would flip it.
              backgroundColor: isActive ? '#6366f1' : 'transparent',
              color: isActive ? '#ffffff' : 'var(--color-text-tertiary)',
              boxShadow: isActive
                ? '0 0 0 1px rgba(99, 102, 241, 0.5), 0 2px 6px rgba(99, 102, 241, 0.35)'
                : 'none',
            }}
          >
            <Icon className="w-3.5 h-3.5" />
          </button>
        );
      })}
    </div>
  );
}
