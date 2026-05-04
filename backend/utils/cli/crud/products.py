"""
Product Display Utilities for CLI

Utility functions for displaying product information in a consistent format.
This module handles the display logic without interacting with databases or adapters.
"""

from typing import List, Dict, Any
from datetime import datetime, timezone


def format_time_ago(recorded_at: datetime) -> str:
    """
    Format a timestamp as a human-readable "time ago" string
    
    Args:
        recorded_at: The timestamp to format
        
    Returns:
        Formatted string like "(5 mins ago)", "(2 hours ago)", etc.
    """
    now = datetime.now(timezone.utc)
    time_diff = now - recorded_at
    minutes_ago = int(time_diff.total_seconds() / 60)
    
    if minutes_ago < 1:
        return "(just now)"
    elif minutes_ago < 60:
        return f"({minutes_ago} mins ago)"
    elif minutes_ago < 1440:  # less than 24 hours
        hours_ago = minutes_ago // 60
        return f"({hours_ago} hours ago)"
    else:
        days_ago = minutes_ago // 1440
        return f"({days_ago} days ago)"


def display_product_list(products_data: List[Dict[str, Any]]) -> None:
    """
    Display a list of products with country-specific information
    
    Args:
        products_data: List of product data dictionaries with country information
    """
    from click import echo
    
    echo("📋 Product List")
    echo("=" * 40)
    echo(f"📊 Found {len(products_data)} products")
    
    for product_data in products_data:
        product_id = product_data['id']
        title = product_data['title']
        country_data = product_data['country_data']
        
        # Truncate title to make it more readable
        display_title = title[:50] + "..." if len(title) > 50 else title
        echo(f"\n{product_id}: {display_title}")
        echo("    Status:")
        
        # Sort countries by total price in descending order
        sorted_countries = sorted(country_data, key=lambda x: x['total'], reverse=True)
        
        for country_info in sorted_countries:
            country_code = country_info['country_code']
            state = country_info['state']
            
            if country_info['has_pricing'] and country_info['total'] > 0:
                base_price = country_info['base_price']
                shipping = country_info['shipping']
                import_fees = country_info['import_fees']
                total = country_info['total']
                time_ago = country_info['time_ago']
                
                # Format with consistent spacing for better alignment (no commas) and time ago
                echo(f"      {country_code}: {state} (B:{base_price:>8.2f} S:{shipping:>6.2f} I:{import_fees:>6.2f} T:{total:>8.2f}) {time_ago}")
            else:
                echo(f"      {country_code}: {state}")
        
        # Display alert metadata if available
        if 'alert_metadata' in product_data and product_data['alert_metadata']:
            meta = product_data['alert_metadata']
            from utils.debug import colorize
            echo(f"    {colorize('Alert:', 'cyan')} {meta['alert_name']} ({meta['alert_id']})")
            echo(f"    {colorize('Country:', 'green')} {meta.get('country_code', 'N/A')}")
            echo(f"    {colorize('Recipient:', 'magenta')} {meta['recipient_name'] or 'N/A'} ({meta['recipient_id']})")
            echo(f"    {colorize('User:', 'yellow')} {meta['user_email']} ({meta['user_id']})")





def prepare_product_data(product, country_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Prepare product data for display
    
    Args:
        product: Product object
        country_data_list: List of country data dictionaries
        
    Returns:
        Formatted product data dictionary
    """
    return {
        'id': product.id,
        'title': product.title,
        'url': product.url,
        'timestamp': product.timestamp,
        'alert_metadata': getattr(product, 'alert_metadata', None),
        'country_data': country_data_list
    }


def prepare_country_data(country, state_name: str, latest_price: Any = None) -> Dict[str, Any]:
    """
    Prepare country data for display
    
    Args:
        country: Country object
        state_name: State name
        latest_price: Latest price history record (optional)
        
    Returns:
        Formatted country data dictionary
    """
    if latest_price and latest_price.base_price:
        base_price = float(latest_price.base_price) if latest_price.base_price else 0
        shipping = float(latest_price.shipping_fee) if latest_price.shipping_fee else 0
        import_fees = float(latest_price.import_fees) if latest_price.import_fees else 0
        total = float(latest_price.total_price) if latest_price.total_price else 0
        time_ago = format_time_ago(latest_price.recorded_at) if latest_price.recorded_at else None
        
        return {
            'country_code': country.code,
            'state': state_name,
            'base_price': base_price,
            'shipping': shipping,
            'import_fees': import_fees,
            'total': total,
            'has_pricing': True,
            'time_ago': time_ago
        }
    else:
        return {
            'country_code': country.code,
            'state': state_name,
            'base_price': 0,
            'shipping': 0,
            'import_fees': 0,
            'total': 0,
            'has_pricing': False,
            'time_ago': None
        } 