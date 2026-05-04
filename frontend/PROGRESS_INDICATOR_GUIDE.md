# Progress Indicator Feature

## Overview

The progress indicator is a global feature that shows minimized progress in the top navigation bar when bulk operations are running. It allows users to navigate away from the processing page while still monitoring the progress.

## Features

### Minimized Progress Bar
- Shows in the top navigation bar when processing is active
- Displays current progress (X of Y items)
- Color-coded by operation type:
  - **Blue**: Bulk upload
  - **Green**: Single product check
  - **Purple**: Batch operations

### Expandable Details
- Click the progress bar to expand and see detailed information
- Shows:
  - Current item being processed
  - Success/failure counts
  - Progress percentage
  - Current status message
  - Action buttons (View Details, Cancel)

### Navigation Integration
- "View Details" button navigates to the relevant page
- Progress persists when navigating between pages
- Automatically stops when processing completes

## Supported Operations

### 1. Bulk Upload (`/add-product`)
- Processes multiple products from file upload or manual input
- Shows real-time progress as each product is checked
- Can be cancelled mid-process
- Updates success/failure counts

### 2. Single Product Check (`/add-product`)
- Shows progress when checking individual products
- Brief display showing completion status
- Auto-hides after completion

### 3. Batch Operations (`/batch-operations`)
- Shows progress during batch product checks
- Displays results summary when complete
- Integrates with existing batch functionality

## Technical Implementation

### Components
- `ProgressContext`: Global state management
- `ProgressIndicator`: UI component in top bar
- `ProgressProvider`: Wraps the app to provide context

### State Management
```typescript
interface ProgressState {
  isActive: boolean;
  type: 'bulk-upload' | 'single-product' | 'batch-check' | null;
  current: number;
  total: number;
  message: string;
  currentItem?: string;
  success: number;
  failed: number;
  canCancel: boolean;
  onCancel?: () => void;
}
```

### Usage in Components
```typescript
const { startProgress, updateProgress, stopProgress } = useProgress();

// Start progress
startProgress({
  type: 'bulk-upload',
  current: 0,
  total: urls.length,
  message: 'Processing bulk upload...',
  success: 0,
  failed: 0,
  canCancel: true,
  onCancel: () => {
    // Cancel logic
  }
});

// Update progress
updateProgress({
  current: i + 1,
  success,
  failed,
  message: `Processed ${i + 1} of ${total} products`
});

// Stop progress
stopProgress();
```

## User Experience

### When Processing Starts
1. Progress indicator appears in top bar
2. Shows operation type and current count
3. User can continue navigating the app

### During Processing
1. Progress updates in real-time
2. User can click to see detailed view
3. Can cancel operations that support it

### When Processing Completes
1. Progress indicator shows completion message
2. Auto-hides after a few seconds
3. User can click "View Details" to see results

### Navigation
- Progress persists across page navigation
- "View Details" takes user to relevant page
- Progress stops when user leaves the app

## Styling

The progress indicator uses custom CSS classes:
- `.progress-indicator`: Main button styling
- `.progress-details`: Expanded details panel
- Smooth animations and hover effects
- Responsive design for mobile/desktop

## Error Handling

- Progress automatically stops on errors
- Error messages are displayed in the expanded view
- Failed operations are counted separately
- Users can retry failed operations

## Future Enhancements

- Add progress for other operations (monitoring, etc.)
- Show estimated time remaining
- Add sound notifications for completion
- Support for multiple concurrent operations
- Progress history/logging 