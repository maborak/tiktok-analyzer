from sqlalchemy import Column, Integer, DateTime, func, event
from sqlalchemy.orm import declarative_base
from datetime import datetime

# Create base class for all models
Base = declarative_base()

# Note: Seeding is now centralized in DatabaseDataPersistenceAdapter.seed_database()
# This ensures all seed data (currencies, product states, countries) is managed in one place

class BaseModel:
    """Base model with common fields for all database models"""
    
    # These will be inherited by child classes
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id})>"
    
    def __str__(self):
        return f"{self.__class__.__name__}(id={self.id})" 