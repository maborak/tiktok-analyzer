"""
Public billing routes — no authentication required.

Exposes credit packages so the landing/pricing page can display
real, admin-managed pricing without forcing visitors to log in.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter()

# Injected by setup_routes() in routes/main.py
payment_service = None


@router.get("/packages")
async def get_public_packages():
    """Get active credit packages — public, no auth required."""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")

    packages = payment_service.get_active_credit_packages()
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "amount": p.amount,
            "currency": p.currency,
            "credits": p.credits,
        }
        for p in packages
    ]
