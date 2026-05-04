import { forwardRef } from 'react';
import { cn } from '../../utils/cn';

interface SwitchProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'> {
    checked: boolean;
    onCheckedChange: (checked: boolean) => void;
    label?: string;
    description?: string;
    size?: 'sm' | 'md' | 'lg';
}

export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(
    ({ checked, onCheckedChange, label, description, size = 'md', className, disabled, ...props }, ref) => {
        // Size configurations
        const sizes = {
            sm: {
                switch: 'w-8 h-4',
                thumb: 'h-3 w-3',
                translate: 'translate-x-4',
                thumbOffset: 'translate-x-0.5',
            },
            md: {
                switch: 'w-11 h-6',
                thumb: 'h-5 w-5',
                translate: 'translate-x-5',
                thumbOffset: 'translate-x-0.5',
            },
            lg: {
                switch: 'w-14 h-7',
                thumb: 'h-6 w-6',
                translate: 'translate-x-7',
                thumbOffset: 'translate-x-0.5',
            },
        };

        const currentSize = sizes[size];

        return (
            <div className={cn("flex items-start", className)}>
                <div className="flex items-center h-5">
                    <button
                        ref={ref}
                        type="button"
                        role="switch"
                        aria-checked={checked}
                        disabled={disabled}
                        onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            if (!disabled) onCheckedChange(!checked);
                        }}
                        className={cn(
                            "relative inline-flex flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary-600 focus:ring-offset-2",
                            currentSize.switch,
                            checked ? "bg-primary-600" : "bg-gray-200",
                            disabled && "opacity-50 cursor-not-allowed"
                        )}
                        {...props}
                    >
                        <span className="sr-only">{label || 'Toggle'}</span>
                        <span
                            aria-hidden="true"
                            className={cn(
                                "pointer-events-none absolute top-1/2 -translate-y-1/2 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
                                currentSize.thumb,
                                checked ? currentSize.translate : currentSize.thumbOffset
                            )}
                        />
                    </button>
                </div>
                {(label || description) && (
                    <div className="ml-3 text-sm">
                        {label && (
                            <label
                                onClick={() => !disabled && onCheckedChange(!checked)}
                                className={cn(
                                    "font-medium text-gray-700 cursor-pointer",
                                    disabled && "opacity-50 cursor-not-allowed"
                                )}
                            >
                                {label}
                            </label>
                        )}
                        {description && <p className="text-gray-500">{description}</p>}
                    </div>
                )}
            </div>
        );
    }
);

Switch.displayName = 'Switch';
