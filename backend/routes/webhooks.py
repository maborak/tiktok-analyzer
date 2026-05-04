from fastapi import APIRouter, Request, HTTPException
import logging
from domain.entities.billing_models import PaymentProvider

router = APIRouter(tags=["Webhooks"])
logger = logging.getLogger(__name__)

payment_service = None

# Max webhook payload size (64 KB — typical webhook events are under 10 KB)
MAX_WEBHOOK_PAYLOAD_BYTES = 64 * 1024

@router.post("/paypal")
async def paypal_webhook(request: Request):
    """Receive asynchronous payment updates from PayPal"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")

    # Read raw bytes for signature verification
    payload = await request.body()
    if len(payload) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    headers = dict(request.headers)
    
    try:
        success = payment_service.process_webhook(PaymentProvider.PAYPAL, headers, payload)
        if success:
            return {"status": "ok"}
        else:
            return {"status": "ignored"}
    except ValueError as e:
        logger.warning(f"PayPal webhook validation failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"PayPal webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal webhook processing error")

@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Receive asynchronous payment updates from Stripe"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
        
    payload = await request.body()
    if len(payload) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    headers = dict(request.headers)

    try:
        success = payment_service.process_webhook(PaymentProvider.STRIPE, headers, payload)
        if success:
            return {"status": "ok"}
        else:
            return {"status": "ignored"}
    except ValueError as e:
        logger.warning(f"Stripe webhook validation failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Stripe webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal webhook processing error")
