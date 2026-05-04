"""
Price and currency utilities

Centralized price parsing and currency handling utilities to eliminate
duplicated logic across the application.
"""

import re
from typing import Tuple, Optional
from decimal import Decimal
from domain.entities.models import Currency

def parse_price_string(price_str: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Parse price string to extract numeric value and currency symbol.
    
    Args:
        price_str: Price string to parse (e.g., "$29.99", "€25.50")
        
    Returns:
        Tuple of (numeric_price, currency_symbol)
    """
    if not price_str:
        return None, None
    
    # Remove whitespace
    price_str = price_str.strip()
    
    # Pattern to match currency symbol and price
    # Matches patterns like: $29.99, €25.50, £20.00, ¥3000
    pattern = r'([^\d.,\s]+)[\s]*([0-9,]+\.?[0-9]*)'
    match = re.search(pattern, price_str)
    
    if match:
        symbol = match.group(1)
        price_part = match.group(2).replace(',', '')
        try:
            return float(price_part), symbol
        except ValueError:
            return None, symbol
    
    # If no symbol found, try to extract just the numeric part
    numeric_pattern = r'([0-9,]+\.?[0-9]*)'
    numeric_match = re.search(numeric_pattern, price_str)
    if numeric_match:
        price_part = numeric_match.group(1).replace(',', '')
        try:
            return float(price_part), None
        except ValueError:
            return None, None
    
    return None, None

def get_currency_from_symbol(symbol: Optional[str]) -> Optional[Currency]:
    """
    Get currency object from currency symbol.
    
    Args:
        symbol: Currency symbol (e.g., "$", "€", "£")
        
    Returns:
        Currency object or None
    """
    if not symbol:
        return None
        
    # Common currency mappings
    currency_mappings = {
        '$': Currency(code='USD', name='US Dollar', symbol='$'),
        '€': Currency(code='EUR', name='Euro', symbol='€'),
        '£': Currency(code='GBP', name='British Pound', symbol='£'),
        '¥': Currency(code='JPY', name='Japanese Yen', symbol='¥'),
        '₹': Currency(code='INR', name='Indian Rupee', symbol='₹'),
        'C$': Currency(code='CAD', name='Canadian Dollar', symbol='C$'),
        'A$': Currency(code='AUD', name='Australian Dollar', symbol='A$'),
    }
    
    # Default to USD if symbol not found
    return currency_mappings.get(symbol, Currency(code='USD', name='US Dollar', symbol='$'))

def format_price(price: Optional[float], currency: Optional[Currency]) -> str:
    """
    Format price with currency symbol.
    
    Args:
        price: Numeric price
        currency: Currency object
        
    Returns:
        Formatted price string
    """
    if price is None:
        return "Price not available"
    
    if currency and currency.symbol:
        return f"{currency.symbol}{price:.2f}"
    elif currency and currency.code:
        return f"{price:.2f} {currency.code}"
    else:
        return f"{price:.2f}"

def extract_price_from_text(text: str) -> Tuple[Optional[float], Optional[Currency]]:
    """
    Extract price and currency from text.
    
    Args:
        text: Text containing price information
        
    Returns:
        Tuple of (price, currency)
    """
    numeric_price, currency_symbol = parse_price_string(text)
    currency = get_currency_from_symbol(currency_symbol)
    return numeric_price, currency

def is_valid_price(price: Optional[float]) -> bool:
    """
    Check if price is valid (not None and positive).
    
    Args:
        price: Price to validate
        
    Returns:
        True if price is valid
    """
    return price is not None and price > 0

def compare_prices(price1: Optional[float], price2: Optional[float]) -> int:
    """
    Compare two prices, handling None values.
    
    Args:
        price1: First price
        price2: Second price
        
    Returns:
        -1 if price1 < price2, 0 if equal, 1 if price1 > price2
        None values are treated as the highest value
    """
    if price1 is None and price2 is None:
        return 0
    elif price1 is None:
        return 1  # None is treated as highest
    elif price2 is None:
        return -1
    else:
        if price1 < price2:
            return -1
        elif price1 > price2:
            return 1
        else:
            return 0 