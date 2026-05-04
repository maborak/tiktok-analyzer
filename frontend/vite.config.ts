import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { TanStackRouterVite } from '@tanstack/router-plugin/vite'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Helper to resolve paths relative to this config file
  const resolve = (p: string) => fileURLToPath(new URL(p, import.meta.url))

  return {
    plugins: [
      TanStackRouterVite({
        routesDirectory: './src/routes',
        generatedRouteTree: './src/routeTree.gen.ts',
        quoteStyle: 'single',
      }),
      react(),
    ],
    resolve: {
      alias: {
        // Path aliases — mirrored in tsconfig.app.json "paths".
        // Order matters: more specific aliases must come before '@/' so
        // '@auth' etc. are resolved to module roots, not 'src/auth'.
        '@auth': resolve('src/modules/auth'),
        '@user': resolve('src/modules/user'),
        '@admin': resolve('src/modules/admin'),
        '@livechat': resolve('src/modules/livechat'),
        '@modules': resolve('src/modules'),
        '@': resolve('src'),
      },
    },
    server: {
      host: true, // Allow external connections
      port: 5173,
      allowedHosts: [
        'localhost',
        '127.0.0.1',
        '.ngrok-free.app', // Allow all ngrok subdomains
        '.ngrok.io',       // Allow legacy ngrok domains
        '.ngrok.app',      // Allow newer ngrok domains
      ],
      // Enable CORS for development
      cors: true,
    },
    preview: {
      host: true,
      port: 5173,
    },
    esbuild: {
      // Strip console.log/debug/info in production builds to avoid leaking info
      drop: mode === 'production' ? ['console', 'debugger'] : [],
    },
  }
})
