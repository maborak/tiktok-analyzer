# API Context

## Base URLs & Authentication
- **Base URL**: Configurable (Referenced as generic in OpenAPI definition).
- **Authentication Schemes**:
  - `HTTPBearer`: JWT Token (Header: `Authorization: Bearer <token>`).
  - `OAuth2PasswordBearer`: OAuth2 flow (Token URL: `/auth/token`). Note: Uses `username` field for email.

## Endpoint Index

### Authentication
- `POST /auth/login`: User Login
- `POST /auth/token`: OAuth2 Token (Login with Email)
- `POST /auth/register`: User Registration
- `POST /auth/refresh`: Refresh Token
- `POST /auth/logout`: User Logout
- `POST /auth/change-password`: Change Password
- `POST /auth/request-password-reset`: Request Password Reset
- `POST /auth/reset-password`: Reset Password
- `GET /auth/me`: Get Current User
- `GET /auth/api-keys`: List API Keys
- `POST /auth/api-keys`: Create API Key
- `POST /auth/verify`: Verify Email
- `POST /auth/resend-verification`: Resend Verification Email

### Products
- `GET /products`: List All Products
- `GET /products/states`: Get Available Product States
- `POST /products/add`: Add New Product
- `GET /products/{product_id}`: Get Product Details
- `GET /products/{asin}/price-history`: Get Product Price History

### User
- `GET /user/account`: Get Current User Account
- `PUT /user/account/edit`: Edit User Account
- `DELETE /user/account/delete`: Delete User Account
- `GET /user/account/tracked-products`: List Tracked Products
- `POST /user/account/tracked-products`: Add Tracked Product
- `DELETE /user/account/tracked-products/{id}`: Remove Tracked Product
- `PUT /user/account/tracked-products/{id}`: Update Tracked Product
- `GET /user/account/price-alerts`: List Price Alerts
- `POST /user/account/price-alerts`: Create Price Alert
- `DELETE /user/account/price-alerts/{id}`: Delete Price Alert
- `PUT /user/account/price-alerts/{id}`: Update Price Alert
- `GET /user/account/recipients`: List Recipients
- `POST /user/account/recipients`: Create Recipient
- `DELETE /user/account/recipients/{id}`: Delete Recipient
- `PUT /user/account/recipients/{id}`: Update Recipient
- `POST /user/account/recipients/verify`: Verify Recipient

### Admin
- `GET /admin/`: Admin Root
- `GET /admin/synthetics/tasks`: List All Synthetics Runs
- `GET /admin/synthetics/tasks/screenshot/{screenshot_url}`: Get Synthetics Screenshot
- `GET /admin/tasks/{task_name}`: Get Task Details
- `GET /admin/users`: List Users
- `POST /admin/users`: Create User
- `GET /admin/users/{user_id}`: Get User by ID
- `PUT /admin/users/{user_id}`: Update User
- `DELETE /admin/users/{user_id}`: Delete User
- `GET /admin/cookies`: List Cookies
- `POST /admin/cookies`: Create Cookie
- `GET /admin/cookies/{cookie_id}`: Get Cookie by ID
- `PUT /admin/cookies/{cookie_id}`: Update Cookie
- `DELETE /admin/cookies/{cookie_id}`: Delete Cookie
- `GET /admin/countries`: List Countries
- `POST /admin/countries`: Create Country
- `GET /admin/countries/{country_id}`: Get Country by ID
- `PUT /admin/countries/{country_id}`: Update Country
- `DELETE /admin/countries/{country_id}`: Delete Country

### Admin (RBAC)
- `GET /admin/rbac/permissions`: List Permissions
- `POST /admin/rbac/permissions`: Create Permission
- `GET /admin/rbac/permissions/{permission_id}`: Get Permission by ID
- `PUT /admin/rbac/permissions/{permission_id}`: Update Permission
- `DELETE /admin/rbac/permissions/{permission_id}`: Delete Permission
- `GET /admin/rbac/roles`: List Roles
- `POST /admin/rbac/roles`: Create Role
- `GET /admin/rbac/roles/{role_id}`: Get Role by ID
- `PUT /admin/rbac/roles/{role_id}`: Update Role
- `DELETE /admin/rbac/roles/{role_id}`: Delete Role
- `GET /admin/rbac/roles/{role_id}/permissions`: Get Role Permissions
- `POST /admin/rbac/roles/{role_id}/permissions`: Assign Permission to Role
- `DELETE /admin/rbac/roles/{role_id}/permissions/{permission_id}`: Remove Permission from Role
- `GET /admin/rbac/users/{user_id}/permissions`: Get User Permissions
- `POST /admin/rbac/users/{user_id}/permissions`: Assign Permission to User
- `DELETE /admin/rbac/users/{user_id}/permissions/{permission_id}`: Remove Permission from User

### Monitoring & Queue
- `GET /monitoring/status`: Get Monitoring Status
- `GET /queue`: Get Product IDs from Queue

### Billing & Payments
- Admin & User endpoints for credit packages, payment methods, processing orders, and invoices.

### Tickets & Support
- Admin, User & Guest endpoints for creating, managing, and replying to support tickets, including categories.

### Live Chat
- Endpoints for initializing chat sessions, sending/receiving messages (user & admin roles), and session metadata.

### Public
- Contact form submission and guest ticket access.

### General & Utility
- `GET /`: API Root
- `GET /health`: Health Check
- `GET /currency`: Get Available Currencies
- `GET /country/list`: Get All Countries
- `GET /screenshot/view/{screenshot_url}.png`: Get Screenshot
- `GET /bench/*`: Benchmark Endpoints (Multiple)

## Key Flows & Contracts

### Login
- **Endpoint**: `POST /auth/login`
- **Auth**: None
- **Request Body Fields**: `email`, `password`, `remember_me`
- **Response Fields**: `success`, `message`, `data` (contains tokens)
- **Error Cases**: 401 (Invalid credentials), 423 (Account locked), 422 (Validation)

### Register
- **Endpoint**: `POST /auth/register`
- **Auth**: None
- **Request Body Fields**: `email`, `password`, `first_name`, `last_name`, `captcha_token`
- **Response Fields**: `success`, `message`, `data`
- **Error Cases**: 201 (Created), 400 (Invalid data), 409 (Email exists), 422 (Validation)

### Get Current User (Me)
- **Endpoint**: `GET /auth/me`
- **Auth**: Bearer Token
- **Request Body**: None
- **Response Fields**: `success`, `message`, `data` (User object)
- **Error Cases**: 401 (Unauthorized)

### Refresh Token
- **Endpoint**: `POST /auth/refresh`
- **Auth**: None (Token passed in query)
- **Request Params**: `refresh_token` (Query)
- **Response Fields**: `success`, `message`, `data`
- **Error Cases**: 401 (Invalid refresh token), 422 (Validation)

### User Account Read/Update
- **Read**: `GET /user/account`
  - **Auth**: Bearer Token
  - **Response Fields**: `username`, `email`, `first_name`, `last_name`, `full_name`, `is_active`, `is_verified`...
- **Update**: `PUT /user/account/edit`
  - **Auth**: Bearer Token
  - **Request Body Fields**: `username`, `email`, `first_name`, `last_name`
  - **Response Fields**: (Same as Read)

## Conventions
- **Naming**: `snake_case` utilized for all JSON fields (e.g., `first_name`, `is_active`).
- **Pagination**: Responses calling `Paginated*` schemas include a `pagination` object with `page`, `page_size`, `total_items`, `total_pages`, `has_next`, `has_previous`.
- **Wrappers**: Most responses are wrapped in a generic `ApiResponse` with `success`, `message`, and `data` fields.
- **Validation**: 422 Unprocessable Entity returns detailed `loc`, `msg`, `type` array.

## Hard Rules
- “Never assume endpoints not in openapi.json”
- “When implementing UI flows, map actions to endpoints from API_CONTEXT.md”
