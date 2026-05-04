# Current State - 2026-03-23

## Last Completed

### 2026-03-22
- [x] WorkerActivityPage — ASIN numbering, sorted by status, country flag click opens debug modal with latest price/HTML/screenshot from `GET /admin/monitoring/debug/latest/{asin}/{country}`
- [x] QueueOrchestrationPage — admin UI for queue config management (`GET/PUT /admin/queue/config`, per-worker overrides)
- [x] AppConfigPage — generic config editor with namespace support (`GET/PUT/DELETE /admin/config/{namespace}/{key}`)
- [x] New sidebar links: Queue & Workers, App Config under Settings

### 2026-03-21
- [x] PriceChangesCard — collapsible recent price changes with screenshots and state transitions
- [x] PriceChart redesign — gradient fill, crosshair, min/max reference lines, layer toggle pills, chart color palette
- [x] ProductHero price range bar — gradient low/avg/high with current price position indicator
- [x] CountryStrip enhancements — trend arrows, "Near lowest!" badge, watchers count
- [x] TrackingStatusCard — collapsible alerts, watchers count
- [x] PriceHistoryTable mobile optimization — labeled compact breakdown
- [x] CountryStats type — per-country stats from backend (min/max/avg/trend/watchers)

### 2026-03-15
- [x] Watch Product page overhaul (`WatchProductPage`) — replaced legacy `AddProduct.tsx` (1,671 LOC) with modular single/bulk upload
- [x] Tiered product-add rate limiting — unverified 10/min, verified 50/min, configurable via `TRACK_RATE_LIMIT_*` env vars
- [x] CAPTCHA removed from product add flow — rate limiting replaces it
- [x] Rate limit state communicated to frontend via custom response headers (`X-Track-RateLimit-*`)
- [x] `rateLimitStore.ts` — reactive module-level store with `useSyncExternalStore` for live rate limit badge
- [x] Upload queue engine (`useUploadQueue`) — sequential processing, 429 auto-wait countdown, cancel, retry, reset
- [x] Single product form — URL/ASIN input with paste-and-go clipboard detection, multi-country select
- [x] Bulk product form — drag-drop CSV/TXT, paste-and-go, batch preview table with dedup detection
- [x] Product upload progress — 5-phase animated micro-steps with gradient transitions
- [x] Results DataTable — reuses `ProductTable` + `Pagination` from `/products` page (5 per page)
- [x] Countries fetched from backend `GET /country/list` API — no more hardcoded country list
- [x] Fixed `productRepositoryImpl.addProduct` response typing — backend returns raw `ProductByCountriesResponse` (no `ApiResponse` wrapper)

### 2026-03-14
- [x] Landing page (`LandingPage`) — public product pitch with feature highlights and pricing CTA
- [x] Pricing page (section within landing or `/pricing`)
- [x] Terms of Service page (`TermsPage`) — brand-configurable legal page at `/terms`
- [x] Privacy Policy page (`PrivacyPage`) — brand-configurable legal page at `/privacy`
- [x] Brand centralization — `appConfig.name`, `appConfig.legalEntity`, `appConfig.domain`, `appConfig.supportEmail` across all frontend pages
- [x] `appConfig.app.X` bug fix — 9 files fixed where `appConfig.app.name` caused TypeError (double-nesting into undefined)

### 2026-03-13
- [x] Admin Extraction Health monitoring page (`ExtractionHealthPage`) — metric cards, zero-price stats, degraded entries DataTable, debug modal with Source/Live Preview tabs
- [x] Price History Debug page (`PriceHistoryDebugPage`) — admin tool for inspecting raw HTML + screenshot by ID, with Source/Live Preview tabs (sandboxed iframe)
- [x] PriceHistoryTable admin-only debug button — Bug icon opens debug modal inline (no separate page needed), admin-gated via `useAuth().isAdmin`
- [x] Ticket system — full user + admin CRUD pages (`TicketsPage`, `TicketDetailPage`, `TicketsAdminPage`, `TicketAdminDetailPage`), guest ticket portal
- [x] FAQ page (`FAQPage`) — public help page
- [x] Sitemap integration (backend `routes/sitemap.py`)
- [x] Ticket components extraction (`frontend/src/modules/user/infrastructure/ui/components/tickets/`)

### 2026-03-12
- [x] Enterprise UI redesign — PageShell, PageHeader, DataTable, MetricCard, FilterBar, StatusBadge across all pages
- [x] ProductDetailPage decomposition — extracted ProductHero, CountryStrip, PriceChart, ImageModal (~1,400→~300 LOC)

### 2026-03-04
- [x] Dedicated Invoice Detail page with Print/PDF support
- [x] Refactored Invoices history with optimized pagination and rich data
- [x] Integrated "View Invoice" links in Orders and Payment Success screens
- [x] Consolidated payment feedback UX (removed redundant toasts)
- [x] Updated API types for nested invoice data and rich metadata

### 2026-03-19
- [x] AW-109 — Multi-recipient per alert: PriceAlertEditModal multi-toggle UI, RecipientStep returns `recipientIds[]`, PriceAlertsPage shows all recipients, TrackingStatusCard lists all recipients

## In Progress
- [ ] Monitoring build performance (Vite chunk size warnings)
- [ ] Go worker degraded retry + MAP detection needs rebuild and live testing

## Next Planned
- [ ] Implement code-splitting for billing modules
- [ ] Upgrade Node.js to 20.19+ to resolve Vite build warnings
- [ ] Comprehensive E2E testing of the payment-to-invoice flow
- [ ] MyProductsPage needs backend endpoint `/user/account/my-products`
- [ ] LiveChatWidget convert-to-ticket and guest login modal live testing

## Admin Pages (New)
| Page | Route | Backend Endpoint |
|------|-------|-----------------|
| ExtractionHealthPage | `/{ADMIN_PREFIX}/monitoring/extraction-health` | `GET /admin/monitoring/extraction-health`, `GET /admin/monitoring/degraded-entries` |
| PriceHistoryDebugPage | `/{ADMIN_PREFIX}/monitoring/debug` | `GET /admin/monitoring/debug/price-history/{id}` |
| TicketsAdminPage | `/{ADMIN_PREFIX}/tickets` | `GET /admin/tickets` |
| TicketAdminDetailPage | `/{ADMIN_PREFIX}/tickets/:id` | `GET /admin/tickets/{id}`, `PUT /admin/tickets/{id}` |
| WorkerActivityPage | `/{ADMIN_PREFIX}/monitoring/workers` | `GET /admin/monitoring/workers`, `GET /admin/monitoring/debug/latest/{asin}/{country}` |
| QueueOrchestrationPage | (embedded in WorkerActivityPage or separate) | `GET/PUT /admin/queue/config`, `GET/PUT /admin/queue/config/worker/{id}` |
| AppConfigPage | `/{ADMIN_PREFIX}/settings/config` | `GET /admin/config/namespaces`, `GET/PUT/DELETE /admin/config/{namespace}/{key}` |

## Environment Variables (Frontend-Specific)
| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_RECENT_CHANGES_LIMIT` | — | Max number of recent price changes shown in PriceChangesCard |

## Constraints
- Vite build requires Node.js v20.19+ or v22.12+
- Some JS chunks exceed 500kB (performance warning)
