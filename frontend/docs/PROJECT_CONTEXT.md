# Project Context

## Project Purpose & Scope
**Explore Marketplace Monitor Dashboard**
A React-based Single Page Application (SPA) designed to discover and monitor Amazon product availability, prices, and shipping costs. Key terminology: "Products" are referred to as "Explore" or "Items" in the UI to emphasize discovery.

## Architectural Style & Mental Model
- **Framework**: React 19 + Vite (SPA).
- **Language**: TypeScript.
- **Styling**: Tailwind CSS v4 (Mobile-first, Utility-first).
- **Routing**: `react-router-dom` v7 using data APIs (`createBrowserRouter`, `loaders`).
- **Modules**: Hexagonal Architecture (Ports & Adapters) organized by domain (`admin`, `auth`, `products`, `user`).
- **State Management**:
  - **Global**: React Context API (`AuthContext`, `ThemeContext`, `GlobalCountryContext`, etc.) for app-wide state.
  - **Server State**: Managed via `axios` client and React Router loaders (now co-located in module infrastructure).
  - **Local**: `useState`/`useReducer` within components.

## Folder-Level Responsibilities
- `src/api`: Low-level HTTP client configuration (`axios`), interceptors (auth injection, error handling), and caching logic.
- `src/modules`: Feature-based modules (`admin`, `auth`, `products`, `user`) following hexagonal architecture:
  - `domain`: Entities, interfaces, DTOs (pure TypeScript, no React/API dependencies).
  - `application`: Business logic, ports (interfaces for repositories/services).
  - `infrastructure`: Concrete implementations (API adapters, React UI pages/components, Routes).
- `src/components`: Shared/Reusable UI components ("dumb" components, generic layouts).
  - `src/components/ui`: Primitive UI components (buttons, inputs, modals).
- `src/config`: Environment configuration and app constants.
- `src/contexts`: React Context Providers for cross-cutting concerns (Auth, Theme, Connectivity, Progress, Favorites).
- `src/hooks`: Custom React hooks.
- `src/routes`: Route definitions (`router.tsx`) and data loaders (`loaders.ts`).
- `src/services`: Business logic and API service wrappers that utilize the `api/client`.
- `src/types`: TypeScript type definitions (interfaces for API responses, entities).
- `src/utils`: Helper functions.

## Component Philosophy & Patterns
- **Naming Convention**: User-facing text uses "Explore" for listing pages and "Item" for specific records. Internal technical identifiers (URLs, variables) remain as "Product".
- **Composition**: Heavy use of composition, with a layout component (`Layout.tsx`) wrapping the main application pages.
- **Separation of Concerns**: Data fetching logic is often separated into `loaders.ts` rather than being hardcoded inside components (React Router pattern).

## State Management Strategy
- **Authentication**: `AuthContext` manages user session, tokens (localStorage), and login/logout methods.
- **Global Settings**: `ThemeContext` (UI theme), `GlobalCountryContext` (country selection), `ApiUrlContext` (dynamic API URL).
- **Feedback**: `ProgressContext` for global loading states; `react-hot-toast` for notifications.
- **Favorites**: `FavoritesContext` manages state and synchronization for user-favorited items across components.

## Routing Strategy
- **Declarative definition**: Routes defined in `src/routes/router.tsx` using `createBrowserRouter`.
- **Guards**: Logic within components (like `RouteErrorBoundary`) handles 401 redirects.
- **Loaders**: Heavy usage of route loaders to pre-fetch data before rendering route components.
- **Layouts**: Nested routes support shared layouts (e.g., standard authenticated layout vs. public auth pages).

## Tailwind/Styling Conventions
- **Utility-First**: Styles applied directly via className using Tailwind utility classes.
- **Dynamic Classes**: `clsx` and `tailwind-merge` used for conditional and clean class merging.
- **Theme Config**: `tailwind.config.js` extends screens (`xs`), animations (`fade-in`, `slide-up`), and keyframes.
- **CSS Variables**: `index.css` likely maps theme colors to CSS variables for dark/light mode support.

## High-Level Data Flow
1. **Request**: Component initiates action (or Route Loader acts).
2. **Client**: `src/api/client.ts` prepares request.
   - Interceptors inject `Authorization: Bearer <token>`.
   - Caching/deduping logic checks if request is in flight or cached.
3. **API**: Request sent to external API.
4. **Response**: Data returned. Interceptors check for 401/403 (emit events for `AuthContext` to handle logout/redirect).
5. **Update**: UI updates via Loader data revalidation or local state change.

## Constraints & Assumptions
- **Auth**: Relies on `localStorage` for `auth_token` and `refresh_token`.
- **API dependency**: Tightly coupled to the specific `openapi.json` contract (expected schemas).
- **Environment**: Depends on specific environment variables for API URL configuration.
