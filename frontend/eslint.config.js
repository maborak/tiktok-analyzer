import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import unusedImports from 'eslint-plugin-unused-imports'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'unused-imports': unusedImports,
    },
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      ...reactHooks.configs['recommended-latest'].rules,
      ...reactRefresh.configs.vite.rules,
      'unused-imports/no-unused-imports': 'error',
      '@typescript-eslint/no-explicit-any': 'off',
      'react-hooks/exhaustive-deps': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'react-refresh/only-export-components': 'off',
      // Enforce module boundaries: cross-module imports must go through the barrel (index.ts).
      // Within a module, use relative imports. Between modules, use @auth, @user, @admin, @livechat.
      'no-restricted-imports': ['error', {
        patterns: [
          { group: ['@auth/pages/*', '@auth/components/*', '@auth/services/*'], message: 'Import from @auth (barrel) instead of reaching into internal paths.' },
          { group: ['@user/pages/*', '@user/components/*', '@user/services/*'], message: 'Import from @user (barrel) instead of reaching into internal paths.' },
          { group: ['@admin/pages/*', '@admin/components/*', '@admin/services/*'], message: 'Import from @admin (barrel) instead of reaching into internal paths.' },
          { group: ['@livechat/components/*', '@livechat/services/*'], message: 'Import from @livechat (barrel) instead of reaching into internal paths.' },
        ],
      }],
    },
  },
  // Route definitions legitimately reach into module pages — exempt them.
  // This file goes away entirely in Phase 4c (TanStack Router).
  {
    files: ['**/routes/**'],
    rules: { 'no-restricted-imports': 'off' },
  },
)
