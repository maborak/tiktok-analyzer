import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// JetBrains Mono Variable — used for auth-page display type and any
// monospace surface that needs character. Self-hosted via @fontsource so
// it doesn't depend on a CDN. Inter is loaded via @font-face from rsms.me
// in index.css and stays the body font.
import '@fontsource-variable/jetbrains-mono/wght.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
