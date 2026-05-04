# Database Reorganization Implementation Plan

## Phase 1: Create New Structure (Week 1)

### Step 1: Create New Directory Structure

```bash
# Create new module directories
mkdir -p database/{core,auth,product,price,currency,monitoring,performance,user_products,shared}

# Create __init__.py files
touch database/{core,auth,product,price,currency,monitoring,performance,user_products,shared}/__init__.py
```

### Step 2: Move Models to Appropriate Modules

#### Core Module (`database/core/`)
```python
# database/core/base.py
from sqlalchemy import Column, Integer, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class BaseModel(Base):
    """Base model with common fields"""
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id})>"
```

```python
# database/core/connection.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import get_database_url

def create_database_engine():
    """Create database engine with connection pooling"""
    database_url = get_database_url()
    return create_engine(database_url)

def get_session_maker(engine):
    """Create session maker for database operations"""
    return sessionmaker(bind=engine)
```

#### Auth Module (`database/auth/`)
```python
# database/auth/models.py
from ..core.base import BaseModel
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
import secrets
import hashlib

class User(BaseModel):
    """User accounts with authentication and authorization"""
    __tablename__ = "users"
    
    # User identification
    username = Column(String(50), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    
    # Authentication
    password_hash = Column(String(255), nullable=False)
    salt = Column(String(64), nullable=False)
    
    # Profile information
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_verified = Column(Boolean, default=False, nullable=False, index=True)
    
    # Account settings
    role = Column(String(20), default="user", nullable=False, index=True)
    max_products = Column(Integer, default=100, nullable=False)
    api_rate_limit = Column(Integer, default=1000, nullable=False)
    
    # Security
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True, index=True)
    password_changed_at = Column(DateTime, nullable=True)
    
    # Relationships
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    user_products = relationship("UserProduct", back_populates="user", cascade="all, delete-orphan")

class UserSession(BaseModel):
    """User session management"""
    __tablename__ = "user_sessions"
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    
    # Session information
    session_token = Column(String(255), nullable=False, unique=True, index=True)
    refresh_token = Column(String(255), nullable=False, unique=True, index=True)
    
    # Session metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Expiration
    expires_at = Column(DateTime, nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="sessions")

class ApiKey(BaseModel):
    """API key management"""
    __tablename__ = "api_keys"
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    
    # API key information
    key_name = Column(String(100), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    key_prefix = Column(String(8), nullable=False, index=True)
    
    # Permissions
    permissions = Column(String(500), nullable=True)
    rate_limit = Column(Integer, default=1000, nullable=False)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    last_used = Column(DateTime, nullable=True, index=True)
    
    # Expiration
    expires_at = Column(DateTime, nullable=True, index=True)
    
    # Relationships
    user = relationship("User", back_populates="api_keys")

class PasswordReset(BaseModel):
    """Password reset tokens"""
    __tablename__ = "password_resets"
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    
    # Reset token
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    
    # Expiration
    expires_at = Column(DateTime, nullable=False, index=True)
    
    # Usage
    used_at = Column(DateTime, nullable=True)
    is_used = Column(Boolean, default=False, nullable=False, index=True)
```

#### Product Module (`database/product/`)
```python
# database/product/models.py
from ..core.base import BaseModel
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from config import get_table_name

class ProductState(BaseModel):
    """Product availability states"""
    __tablename__ = get_table_name("product_states")
    
    # State information
    code = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(50), nullable=False)
    description = Column(String(200), nullable=True)
    
    # State behavior flags
    can_be_scraped = Column(Boolean, default=True, nullable=False)
    can_be_monitored = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    product_checks = relationship("ProductCheck", back_populates="state")
    
    def __repr__(self):
        return f"<ProductState(code='{self.code}', name='{self.name}')>"

class ProductCheck(BaseModel):
    """Product check results"""
    __tablename__ = get_table_name("product_checks")
    
    # Product identification
    product_id = Column(String(10), nullable=False, index=True)
    url = Column(String(500), nullable=False)
    title = Column(Text, nullable=True)
    image = Column(String(1000), nullable=True)
    
    # Foreign keys
    state_id = Column(Integer, ForeignKey(f'{get_table_name("product_states")}.id'), nullable=False, index=True)
    
    # Worker locking mechanism
    worker_id = Column(Integer, default=0, nullable=False, index=True)
    
    # Metadata
    check_timestamp = Column(DateTime, nullable=False, index=True)
    
    # Optional fields
    saved_html_path = Column(String(500), nullable=True)
    
    # Relationships
    state = relationship("ProductState", back_populates="product_checks")
    price_histories = relationship("PriceHistory", back_populates="product_check", cascade="all, delete-orphan")
    
    @property
    def latest_price_history(self):
        """Get the most recent price history entry"""
        if self.price_histories:
            return max(self.price_histories, key=lambda ph: ph.recorded_at)
        return None
    
    @property
    def current_price(self):
        """Get the current total price with currency symbol"""
        latest = self.latest_price_history
        if latest and latest.total_price and latest.currency:
            return f"{latest.currency.symbol}{latest.total_price}"
        return None
```

#### Price Module (`database/price/`)
```python
# database/price/models.py
from ..core.base import BaseModel
from sqlalchemy import Column, Integer, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from config import get_table_name

class PriceHistory(BaseModel):
    """Historical price data with complete cost breakdown"""
    __tablename__ = get_table_name("price_history")
    
    # Foreign keys
    product_check_id = Column(Integer, ForeignKey(f'{get_table_name("product_checks")}.id'), nullable=False, index=True)
    currency_id = Column(Integer, ForeignKey(f'{get_table_name("currencies")}.id'), nullable=False, index=True)
    
    # Price information
    base_price = Column(Numeric(10, 2), nullable=True)
    shipping_fee = Column(Numeric(10, 2), nullable=True)
    import_fees = Column(Numeric(10, 2), nullable=True)
    total_price = Column(Numeric(10, 2), nullable=True)
    
    # Metadata
    recorded_at = Column(DateTime, nullable=False, index=True)
    
    # Relationships
    product_check = relationship("ProductCheck", back_populates="price_histories")
    currency = relationship("Currency", back_populates="price_histories")
    
    def __repr__(self):
        return f"<PriceHistory(product_check_id={self.product_check_id}, total_price={self.total_price})>"
```

#### Currency Module (`database/currency/`)
```python
# database/currency/models.py
from ..core.base import BaseModel
from sqlalchemy import Column, String
from sqlalchemy.orm import relationship
from config import get_table_name

class Currency(BaseModel):
    """Currency information"""
    __tablename__ = get_table_name("currencies")
    
    # Currency information
    code = Column(String(3), nullable=False, unique=True, index=True)
    name = Column(String(50), nullable=False)
    symbol = Column(String(5), nullable=False)
    
    # Relationships
    price_histories = relationship("PriceHistory", back_populates="currency")
    
    def __repr__(self):
        return f"<Currency(code='{self.code}', name='{self.name}', symbol='{self.symbol}')>"
```

#### Monitoring Module (`database/monitoring/`)
```python
# database/monitoring/models.py
from ..core.base import BaseModel
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from config import get_table_name

class ProcessState(BaseModel):
    """Process state enumeration"""
    __tablename__ = get_table_name("process_states")
    
    # State information
    code = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(50), nullable=False)
    description = Column(String(200), nullable=True)
    
    # State behavior flags
    is_active = Column(Boolean, default=True, nullable=False)
    can_be_resumed = Column(Boolean, default=True, nullable=False)
    is_final = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    monitoring_states = relationship("MonitoringState", back_populates="state")

class MonitoringState(BaseModel):
    """Monitoring execution history"""
    __tablename__ = get_table_name("monitoring_states")
    
    # Execution tracking
    last_check = Column(DateTime, nullable=True, index=True)
    start_check_date = Column(DateTime, nullable=True, index=True)
    state_id = Column(Integer, ForeignKey(f'{get_table_name("process_states")}.id'), nullable=False, index=True)
    
    # Process information
    pid = Column(Integer, nullable=True, index=True)
    hostname = Column(String(255), nullable=True, index=True)
    
    # Monitoring information
    batch_limit = Column(Integer, nullable=True, index=True)
    batch_interval = Column(Integer, nullable=True, index=True)
    cooldown_limit = Column(Integer, nullable=True, index=True)
    cooldown_duration = Column(Integer, nullable=True, index=True)
    
    # Relationships
    state = relationship("ProcessState", back_populates="monitoring_states")
```

#### Performance Module (`database/performance/`)
```python
# database/performance/models.py
from ..core.base import BaseModel
from sqlalchemy import Column, String, Text

class BenchmarkRecord(BaseModel):
    """Performance benchmark data"""
    __tablename__ = "bench"
    
    # Benchmark data
    key = Column(String(255), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)
    
    def __repr__(self):
        return f"<BenchmarkRecord(key='{self.key}', value='{self.value}')>"
```

#### User Products Module (`database/user_products/`)
```python
# database/user_products/models.py
from ..core.base import BaseModel
from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

class UserProduct(BaseModel):
    """User-product monitoring relationships"""
    __tablename__ = "user_products"
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    product_id = Column(String(10), nullable=False, index=True)
    
    # User preferences
    is_monitoring = Column(Boolean, default=True, nullable=False, index=True)
    alert_on_availability = Column(Boolean, default=True, nullable=False)
    alert_on_price_change = Column(Boolean, default=False, nullable=False)
    price_threshold = Column(String(20), nullable=True)
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'product_id', name='uq_user_product'),
    )
    
    # Relationships
    user = relationship("User", back_populates="user_products")
```

### Step 3: Create Service Classes

#### Auth Service (`database/auth/services.py`)
```python
from typing import Optional, List
from datetime import datetime, timedelta
import secrets
import hashlib
from sqlalchemy.orm import Session
from .models import User, UserSession, ApiKey, PasswordReset

class AuthService:
    def __init__(self, session: Session):
        self.session = session
    
    def create_user(self, username: str, email: str, password: str, **kwargs) -> User:
        """Create a new user account"""
        salt = self._generate_salt()
        password_hash = self._hash_password(password, salt)
        
        user = User(
            username=username,
            email=email,
            password_hash=password_hash,
            salt=salt,
            **kwargs
        )
        
        self.session.add(user)
        self.session.commit()
        return user
    
    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """Authenticate user with username and password"""
        user = self.session.query(User).filter(User.username == username).first()
        
        if user and self._verify_password(password, user.salt, user.password_hash):
            user.last_login = datetime.utcnow()
            user.failed_login_attempts = 0
            self.session.commit()
            return user
        
        if user:
            user.increment_failed_attempts()
            self.session.commit()
        
        return None
    
    def create_session(self, user: User, ip_address: str = None) -> UserSession:
        """Create a new user session"""
        session_token = self._generate_session_token()
        refresh_token = self._generate_session_token()
        
        session = UserSession(
            user_id=user.id,
            session_token=session_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
        
        self.session.add(session)
        self.session.commit()
        return session
    
    def validate_session(self, session_token: str) -> Optional[UserSession]:
        """Validate a session token"""
        session = self.session.query(UserSession).filter(
            UserSession.session_token == session_token,
            UserSession.is_active == True,
            UserSession.expires_at > datetime.utcnow()
        ).first()
        
        return session
    
    def create_api_key(self, user: User, key_name: str, **kwargs) -> ApiKey:
        """Create a new API key for user"""
        api_key, key_hash = self._generate_api_key()
        
        api_key_obj = ApiKey(
            user_id=user.id,
            key_name=key_name,
            key_hash=key_hash,
            key_prefix=api_key[:8],
            **kwargs
        )
        
        self.session.add(api_key_obj)
        self.session.commit()
        return api_key_obj
    
    def validate_api_key(self, key_hash: str) -> Optional[ApiKey]:
        """Validate an API key"""
        api_key = self.session.query(ApiKey).filter(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active == True,
            (ApiKey.expires_at == None) | (ApiKey.expires_at > datetime.utcnow())
        ).first()
        
        if api_key:
            api_key.last_used = datetime.utcnow()
            self.session.commit()
        
        return api_key
    
    def _generate_salt(self) -> str:
        """Generate a random salt for password hashing"""
        return secrets.token_hex(32)
    
    def _hash_password(self, password: str, salt: str) -> str:
        """Hash password with salt"""
        return hashlib.sha256((password + salt).encode()).hexdigest()
    
    def _verify_password(self, password: str, salt: str, password_hash: str) -> bool:
        """Verify password against hash"""
        return self._hash_password(password, salt) == password_hash
    
    def _generate_session_token(self) -> str:
        """Generate a secure session token"""
        return secrets.token_urlsafe(32)
    
    def _generate_api_key(self) -> tuple[str, str]:
        """Generate API key and hash"""
        api_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return api_key, key_hash
```

#### Product Service (`database/product/services.py`)
```python
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from .models import ProductCheck, ProductState

class ProductService:
    def __init__(self, session: Session):
        self.session = session
    
    def create_product_check(self, product_id: str, **kwargs) -> ProductCheck:
        """Create a new product check record"""
        product_check = ProductCheck(
            product_id=product_id,
            check_timestamp=datetime.utcnow(),
            **kwargs
        )
        
        self.session.add(product_check)
        self.session.commit()
        return product_check
    
    def get_latest_product_check(self, product_id: str) -> Optional[ProductCheck]:
        """Get the latest product check for a product"""
        return self.session.query(ProductCheck).filter(
            ProductCheck.product_id == product_id
        ).order_by(desc(ProductCheck.check_timestamp)).first()
    
    def update_product_state(self, product_id: str, state_code: str) -> bool:
        """Update product state"""
        product_check = self.get_latest_product_check(product_id)
        if not product_check:
            return False
        
        state = self.session.query(ProductState).filter(
            ProductState.code == state_code
        ).first()
        
        if not state:
            return False
        
        product_check.state_id = state.id
        self.session.commit()
        return True
    
    def get_products_by_state(self, state_code: str, limit: int = 50) -> List[ProductCheck]:
        """Get products by state"""
        return self.session.query(ProductCheck).join(ProductState).filter(
            ProductState.code == state_code
        ).order_by(desc(ProductCheck.check_timestamp)).limit(limit).all()
    
    def get_all_products(self, limit: int = 50, offset: int = 0) -> List[ProductCheck]:
        """Get all products with pagination"""
        return self.session.query(ProductCheck).order_by(
            desc(ProductCheck.check_timestamp)
        ).offset(offset).limit(limit).all()
    
    def search_products(self, query: str, limit: int = 50) -> List[ProductCheck]:
        """Search products by title"""
        return self.session.query(ProductCheck).filter(
            ProductCheck.title.ilike(f"%{query}%")
        ).order_by(desc(ProductCheck.check_timestamp)).limit(limit).all()
    
    def delete_product(self, product_id: str) -> bool:
        """Delete a product and all its data"""
        product_checks = self.session.query(ProductCheck).filter(
            ProductCheck.product_id == product_id
        ).all()
        
        for check in product_checks:
            self.session.delete(check)
        
        self.session.commit()
        return True
```

### Step 4: Update Imports

Create a new `database/__init__.py` that exports all models:

```python
# database/__init__.py

# Core
from .core.base import Base, BaseModel
from .core.connection import create_database_engine, get_session_maker

# Auth
from .auth.models import User, UserSession, ApiKey, PasswordReset
from .auth.services import AuthService

# Product
from .product.models import ProductCheck, ProductState
from .product.services import ProductService

# Price
from .price.models import PriceHistory
from .price.services import PriceService

# Currency
from .currency.models import Currency
from .currency.services import CurrencyService

# Monitoring
from .monitoring.models import MonitoringState, ProcessState
from .monitoring.services import MonitoringService

# Performance
from .performance.models import BenchmarkRecord
from .performance.services import PerformanceService

# User Products
from .user_products.models import UserProduct
from .user_products.services import UserProductService

# Shared
from .shared.enums import UserRole, ProductStateEnum, ProcessStateEnum
from .shared.utils import get_or_create_currency, get_or_create_product_state

__all__ = [
    # Core
    'Base', 'BaseModel', 'create_database_engine', 'get_session_maker',
    
    # Auth
    'User', 'UserSession', 'ApiKey', 'PasswordReset', 'AuthService',
    
    # Product
    'ProductCheck', 'ProductState', 'ProductService',
    
    # Price
    'PriceHistory', 'PriceService',
    
    # Currency
    'Currency', 'CurrencyService',
    
    # Monitoring
    'MonitoringState', 'ProcessState', 'MonitoringService',
    
    # Performance
    'BenchmarkRecord', 'PerformanceService',
    
    # User Products
    'UserProduct', 'UserProductService',
    
    # Shared
    'UserRole', 'ProductStateEnum', 'ProcessStateEnum',
    'get_or_create_currency', 'get_or_create_product_state',
]
```

## Phase 2: Update Dependencies (Week 2)

### Step 1: Update CLI Commands
Update all CLI commands to use the new service classes:

```python
# cli/commands/crud.py
from database import ProductService, AuthService, PriceService

# Instead of direct model access, use services
def add_product(ctx, asin, force, debug):
    session = ctx.obj['session']
    product_service = ProductService(session)
    
    result = product_service.create_product_check(asin, force=force)
    # ... rest of the logic
```

### Step 2: Update API Routes
Update API routes to use the new service classes:

```python
# routes/products.py
from database import ProductService, PriceService

@router.post("/products/check")
def check_product(product_data: ProductCheckRequest):
    session = get_session()
    product_service = ProductService(session)
    price_service = PriceService(session)
    
    # Use services instead of direct model access
    product_check = product_service.create_product_check(product_data.url)
    # ... rest of the logic
```

### Step 3: Update Tests
Update all tests to use the new structure:

```python
# tests/test_product_service.py
from database import ProductService, ProductCheck

def test_create_product_check():
    session = create_test_session()
    product_service = ProductService(session)
    
    product_check = product_service.create_product_check("B01G5ATZAE")
    assert product_check.product_id == "B01G5ATZAE"
```

## Phase 3: Cleanup (Week 3)

### Step 1: Remove Old Files
```bash
# Remove old files after migration is complete
rm database/models.py
rm database/auth_models.py
rm database/performance_monitor.py
```

### Step 2: Update Documentation
Update all documentation to reflect the new structure.

### Step 3: Create Migration Scripts
Create migration scripts to handle the transition:

```python
# database/migrations/v1_to_v2.py
"""Migration from old structure to new modular structure"""

def migrate_v1_to_v2():
    """Migrate from old single-file structure to new modular structure"""
    # This will be implemented after the new structure is in place
    pass
```

## Benefits After Implementation

### ✅ **Maintainability**
- Each module is focused and small (50-200 lines)
- Clear separation of concerns
- Easy to find and modify specific functionality

### ✅ **Testability**
- Each service can be tested independently
- Clear interfaces make mocking easier
- Better unit test coverage

### ✅ **Scalability**
- Easy to add new modules
- Independent development of different domains
- Better team collaboration

### ✅ **Performance**
- Smaller files load faster
- Better memory usage
- More efficient imports

This reorganization will transform the messy database structure into a clean, maintainable, and scalable architecture! 🎯 