# UI Rules

**Source of truth**: the code. This document describes conventions derived from the existing codebase.

---

## Component Size Rules

| Type | Max Lines | Guideline |
|------|-----------|-----------|
| Page component | 300 | Orchestrates sub-components — no business logic |
| Feature component | 250 | Owns a specific UI interaction area |
| UI primitive | 100 | Single-responsibility, highly reusable |
| Modal component | 200 | Includes form + submit handler |

When a component exceeds its limit, split it:
- Extract repeated JSX sections into named sub-components
- Move form sections into `{Name}Form.tsx`
- Move modal content into `{Name}Modal.tsx`
- Move list items into `{Name}Item.tsx` or `{Name}Row.tsx`

---

## Naming Conventions

### Files

| Pattern | Convention | Example |
|---------|------------|---------|
| Page component | `{Name}Page.tsx` | `TrackedProductsPage.tsx` |
| Feature component | `{Name}.tsx` (PascalCase) | `TrackedProductAlertsModal.tsx` |
| UI primitive | `{Name}.tsx` (PascalCase) | `Button.tsx`, `Modal.tsx` |
| Repository implementation | `{Entity}RepositoryImpl.ts` | `TrackingRepositoryImpl.ts` |
| Repository port | `{Entity}Repository.ts` | `TrackingRepository.ts` |
| Domain entity | `{Entity}.ts` (PascalCase) | `TrackedProduct.ts` |
| API type | `{Name}Response` / `{Name}Request` | `TrackedProductResponse` |
| Admin API function file | `{section}.ts` (lowercase) | `billing.ts`, `tickets.ts` |
| Utility | camelCase | `dateUtils.ts`, `imageUtils.ts` |

### Variables and Functions

```typescript
// Components: PascalCase
export function TrackedProductsPage() {}

// Hooks: use prefix
const [isOpen, setIsOpen] = useState(false);
const data = useLoaderData();

// Event handlers: handle prefix
const handleSubmit = async () => {};
const handleDelete = (id: number) => {};

// API response variables: match shape
const { tracks, pagination } = loaderData;

// Repository instances: camelCase
const repo = new TrackingRepositoryImpl();
```

### Props Interfaces

```typescript
// Co-locate with component, not in a separate types file
interface TrackedProductRowProps {
  product: TrackedProduct;
  onDelete: (id: number) => void;
  onEdit: (id: number) => void;
}
```

---

## Folder Structure

### Module Internal Structure

```
src/modules/{name}/
  domain/
    {Entity}.ts                    # Plain interface — no infrastructure imports
  application/
    ports/
      {Entity}Repository.ts        # Abstract interface (port)
  infrastructure/
    api/
      {Entity}RepositoryImpl.ts    # Implements port
    ui/
      pages/
        {Name}Page.tsx             # Page — composes components
      components/
        {Name}Modal.tsx            # Module-specific components
        {Name}Form.tsx
```

### Shared vs Module-Specific Components

| Location | When to use |
|----------|------------|
| `src/components/ui/` | Pure UI primitives — no domain knowledge |
| `src/components/` | Domain-aware but used by multiple modules |
| `src/modules/{name}/infrastructure/ui/components/` | Only used within this module |

Never create a new primitive in `src/components/ui/` for a one-time use. Only extract to shared when the pattern appears in 2+ modules.

---

## Design System Usage

### Always Use Before Creating

Before writing any UI element, check if a primitive exists:

```tsx
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Modal } from '../../components/ui/Modal';
import { FormField } from '../../components/ui/FormField';
import { LoadingState } from '../../components/ui/LoadingState';
import { EmptyState } from '../../components/ui/EmptyState';
import { Skeleton } from '../../components/ui/Skeleton';
import { Switch } from '../../components/ui/Switch';
import { Select } from '../../components/ui/Select';
import { ProgressBar } from '../../components/ui/ProgressBar';
```

### Tailwind Conventions

```tsx
// Card container (standard throughout app)
<div className="bg-white rounded-lg border border-gray-200 p-6">

// Page header
<div className="flex items-center justify-between mb-6">
  <h1 className="text-2xl font-bold text-gray-900">Page Title</h1>
</div>

// Section header
<h2 className="text-lg font-semibold text-gray-900 mb-4">Section Title</h2>

// Danger zone
<div className="border border-red-200 rounded-lg p-4 bg-red-50">

// Muted text
<span className="text-sm text-gray-500">Secondary information</span>

// Status colors
// active/enabled/success: text-green-600, bg-green-100
// paused/warning: text-yellow-600, bg-yellow-100
// error/danger: text-red-600, bg-red-100
// inactive/neutral: text-gray-500, bg-gray-100
```

### Conditional Classes

Always use `cn()` from `src/utils/cn.ts`:

```tsx
import { cn } from '../../utils/cn';

// NOT this:
className={`px-4 py-2 ${isActive ? 'bg-blue-600' : 'bg-gray-200'}`}

// DO this:
className={cn('px-4 py-2', isActive ? 'bg-blue-600' : 'bg-gray-200')}

// For more complex conditions:
className={cn(
  'rounded-lg px-3 py-1 text-sm font-medium',
  {
    'bg-green-100 text-green-700': status === 'active',
    'bg-yellow-100 text-yellow-700': status === 'paused',
    'bg-gray-100 text-gray-500': status === 'disabled',
  }
)}
```

---

## State Management Rules

### Local State Only

This app has no global state manager. All state is:
- Route loader data (server state, pre-fetched)
- Component `useState` (local UI state)
- `localStorage` (auth tokens, user preferences)

### When to Use `useState`

```tsx
// YES — local UI state
const [isOpen, setIsOpen] = useState(false);    // modal open/close
const [isLoading, setIsLoading] = useState(false);  // mutation in progress
const [error, setError] = useState<string | null>(null);  // mutation error

// YES — local form state managed by react-hook-form
const { register, handleSubmit } = useForm<FormData>();

// NO — data that could come from a loader
const [trackedProducts, setTrackedProducts] = useState([]); // use useLoaderData instead
```

### When to Use `useLoaderData`

```tsx
const loaderData = useLoaderData() as MyPageData | null;
// Always handle null (unauthenticated or fetch failed)
if (!loaderData) return <LoadingState />;
```

### URL as State for Pagination/Filters

```tsx
// For paginated lists:
const [searchParams, setSearchParams] = useSearchParams();
const page = parseInt(searchParams.get('page') || '1');
const search = searchParams.get('search') || '';
```

---

## Form Rules

### Always Use react-hook-form + zod

```tsx
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const schema = z.object({
  name: z.string().min(1, 'Name is required'),
  email: z.string().email('Invalid email'),
  amount: z.number().positive('Must be positive'),
});

type FormData = z.infer<typeof schema>;

const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({
  resolver: zodResolver(schema),
});
```

### Form Field Pattern

```tsx
<FormField label="Name" error={errors.name?.message}>
  <Input {...register('name')} placeholder="Enter name" />
</FormField>
```

### Submit Handler

```tsx
const onSubmit = async (data: FormData) => {
  try {
    const repo = new SomeRepositoryImpl();
    const result = await repo.create(data);
    if (result.success) {
      toast.success('Created successfully');
      // refresh or navigate
    }
  } catch (err) {
    toast.error('Something went wrong');
  }
};
```

---

## Loading and Error States

### Every Page Must Handle

```tsx
// Loading (data not yet available)
if (!loaderData) return <LoadingState />;

// Empty (data loaded but empty)
if (loaderData.items.length === 0) {
  return <EmptyState message="No items found" />;
}

// Error (mutation failed) → use react-hot-toast, not inline error
toast.error(error.message || 'Something went wrong');
```

### Skeleton Loading (shimmer/skeleton loader type)

When `VITE_LOADER_TYPE=skeleton`, loaders are skipped. Pages must render a skeleton first:

```tsx
if (isLoading) return <TableSkeleton rows={5} />;
```

---

## Icons

Use `lucide-react` exclusively:

```tsx
import { Search, Plus, Trash2, Edit, ChevronRight, AlertTriangle } from 'lucide-react';

// Standard sizes:
<Search className="w-4 h-4" />       // small (inline with text)
<Plus className="w-5 h-5" />         // medium (button icon)
<AlertTriangle className="w-6 h-6" /> // large (standalone)
```

No custom SVG icons unless the icon doesn't exist in lucide-react.

---

## Comments

- Do not add comments to self-evident code
- Add comments only for:
  - Non-obvious business logic (e.g., why `price_alert_id` is singular vs. `price_alert_ids`)
  - Backend API quirks documented in backend CLAUDE.md
  - `// TODO: ...` for known gaps (link to GitHub issue if possible)
  - Type casts with `as any` must explain why

---

## TypeScript Rules

- No `any` in repository implementations where a type exists in `src/types/api.ts`
- `as any` is acceptable only as a last resort for backend response normalization — must have a comment
- All component props must have explicit interfaces (not `React.FC<any>`)
- Prefer `null` over `undefined` for optional API fields (matches backend JSON)
- Domain entity types (`src/modules/*/domain/`) must not use `any`
