# Database Reorganization Proposal

## Current State Analysis

The current `database/` folder has all models mixed together:
- `models.py` (963 lines) - Contains everything: products, prices, currencies, monitoring, etc.
- `auth_models.py` (294 lines) - Authentication models
- `performance_monitor.py` (401 lines) - Performance monitoring
- `schema.sql` - Legacy schema
- `db_init.py` - Database initialization

**Problems:**
- ❌ Single massive file (963 lines)
- ❌ Mixed concerns (auth, products, monitoring, performance)
- ❌ Hard to maintain and extend
- ❌ Difficult to understand domain boundaries
- ❌ No clear separation of responsibilities

## Proposed New Structure

```
database/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── base.py              # Base models and common utilities
│   ├── connection.py         # Database connection management
│   └── migrations.py         # Migration utilities
├── auth/
│   ├── __init__.py
│   ├── models.py            # User, UserSession, ApiKey, PasswordReset
│   ├── services.py          # Authentication business logic
│   └── migrations.py        # Auth-specific migrations
├── product/
│   ├── __init__.py
│   ├── models.py            # ProductCheck, ProductState
│   ├── services.py          # Product business logic
│   └── migrations.py        # Product-specific migrations
├── price/
│   ├── __init__.py
│   ├── models.py            # PriceHistory
│   ├── services.py          # Price tracking business logic
│   └── migrations.py        # Price-specific migrations
├── currency/
│   ├── __init__.py
│   ├── models.py            # Currency
│   ├── services.py          # Currency business logic
│   └── migrations.py        # Currency-specific migrations
├── monitoring/
│   ├── __init__.py
│   ├── models.py            # MonitoringState, ProcessState
│   ├── services.py          # Monitoring business logic
│   └── migrations.py        # Monitoring-specific migrations
├── performance/
│   ├── __init__.py
│   ├── models.py            # BenchmarkRecord
│   ├── monitor.py           # Performance monitoring
│   └── migrations.py        # Performance-specific migrations
├── user_products/
│   ├── __init__.py
│   ├── models.py            # UserProduct (user-product relationships)
│   ├── services.py          # User product management
│   └── migrations.py        # User product migrations
└── shared/
    ├── __init__.py
    ├── enums.py             # Shared enums and constants
    ├── utils.py             # Shared database utilities
    └── validators.py        # Shared validators
```

## Detailed Module Breakdown

### 1. Core Module (`database/core/`)

**Purpose:** Foundation layer for all database operations

**Files:**
- `base.py`: Base model class, common mixins, shared fields
- `connection.py`: Database engine, session management, connection pooling
- `migrations.py`: Migration framework and utilities

**Key Features:**
```python
# base.py
class BaseModel(Base):
    """Base model with common fields"""
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id})>"
```

### 2. Auth Module (`database/auth/`)

**Purpose:** User authentication and authorization

**Models:**
- `User`: User accounts with roles and limits
- `UserSession`: Session management
- `ApiKey`: API key management
- `PasswordReset`: Password reset tokens

**Services:**
```python
# auth/services.py
class AuthService:
    def create_user(self, username: str, email: str, password: str) -> User
    def authenticate_user(self, username: str, password: str) -> Optional[User]
    def create_session(self, user: User, ip_address: str) -> UserSession
    def validate_api_key(self, key_hash: str) -> Optional[ApiKey]
```

### 3. Product Module (`database/product/`)

**Purpose:** Product management and state tracking

**Models:**
- `ProductCheck`: Product check results
- `ProductState`: Product availability states

**Services:**
```python
# product/services.py
class ProductService:
    def create_product_check(self, product_id: str, **kwargs) -> ProductCheck
    def get_latest_product_check(self, product_id: str) -> Optional[ProductCheck]
    def update_product_state(self, product_id: str, state_code: str) -> bool
    def get_products_by_state(self, state_code: str) -> List[ProductCheck]
```

### 4. Price Module (`database/price/`)

**Purpose:** Price history and cost tracking

**Models:**
- `PriceHistory`: Historical price data with complete cost breakdown

**Services:**
```python
# price/services.py
class PriceService:
    def record_price_history(self, product_check_id: int, **kwargs) -> PriceHistory
    def get_price_history(self, product_id: str, limit: int = 10) -> List[PriceHistory]
    def get_price_trends(self, product_id: str) -> Dict[str, Any]
    def calculate_price_changes(self, product_id: str) -> Dict[str, float]
```

### 5. Currency Module (`database/currency/`)

**Purpose:** Currency management and conversion

**Models:**
- `Currency`: Currency information and exchange rates

**Services:**
```python
# currency/services.py
class CurrencyService:
    def get_or_create_currency(self, code: str) -> Currency
    def get_currency_by_code(self, code: str) -> Optional[Currency]
    def convert_price(self, amount: float, from_currency: str, to_currency: str) -> float
    def update_exchange_rates(self) -> bool
```

### 6. Monitoring Module (`database/monitoring/`)

**Purpose:** Process monitoring and execution tracking

**Models:**
- `MonitoringState`: Monitoring execution history
- `ProcessState`: Process state management

**Services:**
```python
# monitoring/services.py
class MonitoringService:
    def start_monitoring_session(self, **kwargs) -> MonitoringState
    def update_monitoring_state(self, state_id: int, **kwargs) -> bool
    def get_active_monitoring_sessions(self) -> List[MonitoringState]
    def cleanup_stale_sessions(self, timeout_minutes: int = 30) -> int
```

### 7. Performance Module (`database/performance/`)

**Purpose:** Performance monitoring and benchmarking

**Models:**
- `BenchmarkRecord`: Performance benchmark data

**Services:**
```python
# performance/services.py
class PerformanceService:
    def record_benchmark(self, key: str, value: Any) -> BenchmarkRecord
    def get_benchmark_history(self, key: str) -> List[BenchmarkRecord]
    def get_performance_metrics(self) -> Dict[str, Any]
    def cleanup_old_benchmarks(self, days: int = 30) -> int
```

### 8. User Products Module (`database/user_products/`)

**Purpose:** User-product relationships and preferences

**Models:**
- `UserProduct`: User-product monitoring relationships

**Services:**
```python
# user_products/services.py
class UserProductService:
    def add_user_product(self, user_id: int, product_id: str, **kwargs) -> UserProduct
    def get_user_products(self, user_id: int) -> List[UserProduct]
    def update_user_preferences(self, user_id: int, product_id: str, **kwargs) -> bool
    def remove_user_product(self, user_id: int, product_id: str) -> bool
```

### 9. Shared Module (`database/shared/`)

**Purpose:** Shared utilities and constants

**Files:**
- `enums.py`: Shared enums (UserRole, ProductState, ProcessState)
- `utils.py`: Database utilities (connection helpers, validators)
- `validators.py`: Data validation functions

## Migration Strategy

### Phase 1: Create New Structure
1. Create new folder structure
2. Move existing models to appropriate modules
3. Update imports throughout the codebase
4. Create new `__init__.py` files with proper exports

### Phase 2: Refactor Services
1. Extract business logic from models into service classes
2. Create proper service interfaces
3. Update CLI and API to use new services

### Phase 3: Update Dependencies
1. Update all import statements
2. Update database initialization
3. Update migration scripts
4. Update tests

### Phase 4: Cleanup
1. Remove old files
2. Update documentation
3. Create new migration scripts
4. Test all functionality

## Benefits of New Structure

### ✅ **Clear Separation of Concerns**
- Each module has a single responsibility
- Easy to understand what each module does
- Clear boundaries between different domains

### ✅ **Maintainability**
- Smaller, focused files (50-200 lines vs 963 lines)
- Easier to find and modify specific functionality
- Reduced cognitive load

### ✅ **Scalability**
- Easy to add new modules
- Independent development of different domains
- Better team collaboration

### ✅ **Testability**
- Each module can be tested independently
- Clear service interfaces
- Easier to mock dependencies

### ✅ **Reusability**
- Services can be reused across different parts of the application
- Clear interfaces make integration easier
- Modular design supports future extensions

## Implementation Timeline

**Week 1:** Create new structure and move models
**Week 2:** Extract services and update imports
**Week 3:** Update CLI and API dependencies
**Week 4:** Testing and cleanup

## File Size Comparison

| Current | Proposed |
|---------|----------|
| `models.py`: 963 lines | `product/models.py`: ~150 lines |
| `auth_models.py`: 294 lines | `auth/models.py`: ~200 lines |
| `performance_monitor.py`: 401 lines | `performance/models.py`: ~100 lines |
| **Total**: 1,658 lines | **Total**: ~800 lines (distributed) |

This reorganization will make the codebase much more maintainable and easier to understand! 🎯 