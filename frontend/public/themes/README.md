# Theme System

This folder contains custom theme CSS files that can be applied to the UI.

## Available Themes

- **Default**: The built-in blue theme (no CSS file needed)
- **Dark**: Modern dark mode with enhanced shadows and depth
- **Green**: Professional theme with green accent colors
- **Purple**: Professional theme with purple accent colors
- **Amazon**: Orange-inspired theme with signature warm colors and gradients

## How to Add a New Theme

1. **Create a new CSS file** in this folder (e.g., `orange.css`)

2. **Update the theme list** in `src/contexts/ThemeContext.tsx`:
   ```typescript
   const defaultThemes: Theme[] = [
     // ... existing themes
     {
       id: 'orange',
       name: 'Orange',
       cssFile: '/themes/orange.css',
       description: 'Orange accent theme'
     }
   ];
   ```

3. **CSS Structure**: Your theme CSS should override the default styles using `!important` declarations:

   ```css
   /* Orange Theme Overrides */
   
   /* Primary Colors */
   .btn-primary {
     background-color: #ea580c !important;
   }
   
   .text-primary-600 {
     color: #ea580c !important;
   }
   
   /* Add more overrides as needed */
   ```

## CSS Class Patterns

### Common Classes to Override

- **Buttons**: `.btn-primary`, `.btn-secondary`
- **Text Colors**: `.text-primary-600`, `.text-primary-700`, `.text-primary-900`
- **Backgrounds**: `.bg-primary-50`, `.bg-primary-100`, `.bg-primary-600`
- **Borders**: `.border-primary-600`, `.border-primary-300`
- **Links**: `.text-blue-600`, `.text-blue-800`

### Dark Theme Considerations

For dark themes, override:
- **Body**: `body { background-color: #111827 !important; }`
- **Cards**: `.card, .bg-white { background-color: #1f2937 !important; }`
- **Text**: `.text-gray-900 { color: #f9fafb !important; }`
- **Inputs**: `input, select, textarea { background-color: #374151 !important; }`

## Tips for Theme Development

1. **Use the browser inspector** to identify which CSS classes need overriding
2. **Test all components**: Dashboard, Products, Charts, Forms, etc.
3. **Include hover states**: Don't forget `:hover` variations
4. **Test accessibility**: Ensure good contrast ratios
5. **Use consistent color palettes**: Pick 2-3 main colors and their variations

## Color Palette Suggestions

### Orange Theme
- Primary: #ea580c (orange-600)
- Hover: #c2410c (orange-700)
- Light: #fed7aa (orange-200)

### Red Theme
- Primary: #dc2626 (red-600)
- Hover: #b91c1c (red-700)
- Light: #fecaca (red-200)

### Teal Theme
- Primary: #0d9488 (teal-600)
- Hover: #0f766e (teal-700)
- Light: #99f6e4 (teal-200)

### Amazon Theme
- Primary: #ff9900 (Amazon orange)
- Hover: #e47911 (Dark Amazon orange)
- Background: #f7f8f8 (Amazon gray)
- Text: #0f1111 (Amazon black)

## Theme Switching

Themes are automatically applied when selected from the dropdown in the top-right corner of the application. The selected theme is saved to `localStorage` and will persist across browser sessions. 