# Database Module

This module contains the database models and services organized in a clean, modular structure.

## Structure

```
database/
├── core/           # Base models and connection management
├── auth/           # User authentication and authorization
├── product/        # Product management and state tracking
├── price/          # Price history and cost tracking
├── currency/       # Currency management
├── monitoring/     # Process monitoring and execution
├── performance/    # Performance monitoring and benchmarking
├── user_products/  # User-product relationships
├── shared/         # Shared utilities and constants
└── docs/           # Documentation
```

## Quick Start

```python
from database import (
    Base, create_database_engine, get_session_maker,
    Currency, ProductCheck, PriceHistory, User
)

# Create database engine
engine = create_database_engine()

# Create session
SessionLocal = get_session_maker(engine)
session = SessionLocal()

# Use models
currency = session.query(Currency).first()
products = session.query(ProductCheck).all()
```

## Modules

### Core
- **Base**: SQLAlchemy declarative base
- **Connection**: Database engine and session management

### Auth
- **User**: User accounts and authentication
- **UserSession**: Session management
- **ApiKey**: API key management
- **PasswordReset**: Password reset tokens

### Product
- **ProductCheck**: Product check results
- **ProductState**: Product availability states

### Price
- **PriceHistory**: Historical price data with complete cost breakdown

### Currency
- **Currency**: Currency information and exchange rates

### Monitoring
- **MonitoringState**: Monitoring execution history
- **ProcessState**: Process state management

### Performance
- **BenchmarkRecord**: Performance benchmark data

### User Products
- **UserProduct**: User-product monitoring relationships

### Shared
- **Enums**: Shared enums (UserRole, ProductState, ProcessState)
- **Utils**: Shared database utilities

## Documentation

See the `docs/` folder for detailed documentation:
- `REFACTORING_SUMMARY.md`: Summary of the refactoring process
- `REORGANIZATION_PROPOSAL.md`: Original proposal
- `IMPLEMENTATION_PLAN.md`: Implementation details
- `DATABASE_CONFIG.md`: Database configuration guide 