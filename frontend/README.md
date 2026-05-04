# Phoveus - Frontend

A production-ready React frontend foundation built with **TypeScript**, **Vite**, and **Tailwind CSS**. Provides authentication, billing, admin dashboard, live chat, and theming out of the box.

## Architecture

The frontend follows a **modular domain-driven** structure with React Context for state management.

```
src/
├── modules/                # Feature modules
│   ├── auth/               # Authentication flows
│   │   ├── application/    # Auth logic & hooks
│   │   ├── infrastructure/ # API integration
│   │   └── domain/         # Auth types & models
│   ├── user/               # User account & billing
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── domain/
│   ├── admin/              # Admin dashboard
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── domain/
│   └── livechat/           # Live chat widget
├── contexts/               # Global state
│   ├── AuthContext.tsx      # Authentication & session
│   ├── ThemeContext.tsx     # Theme management
│   ├── ConnectivityContext.tsx  # API health monitoring
│   ├── ProgressContext.tsx  # Operation progress tracking
│   ├── ApiUrlContext.tsx    # Dynamic API endpoint config
│   └── GlobalCountryContext.tsx
├── api/                    # HTTP client layer
│   ├── client.ts           # Axios client with retry, dedup, caching
│   └── cache.ts            # Request caching with TTL
├── config/                 # Configuration
│   ├── env.ts              # Environment variable parsing
│   └── appConfig.ts        # API endpoints & app settings
├── components/             # Shared UI components
│   ├── Layout.tsx          # Main app layout
│   ├── Dashboard.tsx       # Overview page
│   ├── DataTable.tsx       # Reusable table with sorting/filtering
│   ├── ui/                 # Button, Input, Modal, Pagination, etc.
│   └── guards/             # RequireAuth, RequireAdmin, RequireGuest
├── hooks/                  # Custom hooks
│   ├── useApiClient.ts     # Typed API requests
│   ├── useApiConnectivity.ts
│   └── useCaptcha.ts
├── routes/                 # Router configuration
├── styles/                 # Global CSS
├── types/                  # TypeScript definitions
└── utils/                  # Helpers (routes, dates, roles, cn)
```

## Tech Stack

| Category | Technology |
|----------|-----------|
| Framework | React 19 + TypeScript 5.9 |
| Build | Vite 7 |
| Styling | Tailwind CSS 4 |
| Routing | React Router 7 |
| Forms | React Hook Form + Zod validation |
| HTTP | Axios with interceptors, retry, caching |
| Charts | Chart.js 4 + react-chartjs-2 |
| Auth | Google OAuth, GitHub OAuth, Facebook OAuth |
| Payments | Stripe, PayPal |
| Icons | Lucide React |
| Notifications | react-hot-toast |

## Built-in Features

- **Authentication**: Login, register, password recovery, OAuth (Google, GitHub, Facebook), email verification
- **User Account**: Profile management, recipients, support tickets
- **Billing**: Subscription packages, checkout (Stripe/PayPal), order history, invoices, credits
- **Admin Dashboard**: User management, RBAC, app config, event monitoring, ticket admin, live chat console
- **Live Chat**: Customer support widget with admin console
- **Theme System**: 15+ color palettes with CSS variable-based theming
- **Route Obfuscation**: Configurable admin/account route prefixes for security
- **Multi-Build Modes**: `full`, `client`, or `admin` builds from a single codebase
- **API Layer**: Request deduplication, caching with TTL, automatic retry on 429/5xx
- **CAPTCHA**: Cloudflare Turnstile and Google reCAPTCHA v3 support
- **Responsive Design**: Mobile-first with card layouts for small screens, tables for desktop

## Quick Start

### Prerequisites

- Node.js 24+ (see `.nvmrc`)
- npm

### Installation

```bash
npm install
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your API URL, branding, and service keys
```

Key environment variables:

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE_URL` | Backend API URL |
| `VITE_APP_NAME` | Application display name |
| `VITE_APP_LEGAL_ENTITY` | Legal entity name |
| `VITE_APP_MODE` | Build mode: `full`, `client`, or `admin` |
| `VITE_ADMIN_ROUTE_PREFIX` | Admin route prefix (obfuscation) |
| `VITE_USER_ROUTE_PREFIX` | User route prefix (obfuscation) |
| `VITE_CAPTCHA_PROVIDER` | CAPTCHA: `none`, `recaptcha_v3`, `turnstile` |
| `VITE_DEBUG_MODE` | Enable debug logging |

### Development

```bash
npm run dev       # Start dev server (http://localhost:5173)
npm run lint      # Run ESLint
npm run build     # Production build
npm run preview   # Preview production build
```

### Docker

```bash
# Build
docker build -t maborak/framework-ui:latest .

# Run with env vars
docker run -d -p 80:80 \
  -e VITE_API_BASE_URL=http://api:8000 \
  maborak/framework-ui:latest
```

The Docker image builds at container startup from environment variables, allowing config changes without rebuilding the image.

## CI/CD

GitHub Actions workflow at `.github/workflows/docker-build-push.yml`:

- Triggers on push to `main` or manual dispatch
- Multi-architecture builds (amd64, arm64)
- Pushes to Docker Hub

Required GitHub secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`

## License

[Add your license information here]
