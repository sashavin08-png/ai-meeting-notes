"""
Stripe billing: upgrading a user from the free plan to a paid subscription.

Flow:
  1. User clicks "Upgrade" -> create_checkout_session() -> redirected to
     Stripe's own hosted checkout page (we never see their card details)
  2. Stripe processes payment, redirects back to our success_url
  3. Stripe also sends a webhook event (checkout.session.completed) to
     our server — THIS is the reliable signal to actually mark the user
     as paid, not the redirect (the person could close the tab before
     the redirect completes, but the webhook always fires)
  4. If they later cancel, Stripe sends customer.subscription.deleted —
     we downgrade them back to the free plan

Requires:
  STRIPE_SECRET_KEY     — from the Stripe dashboard (test mode to start)
  STRIPE_PRICE_ID       — the Price ID for the subscription product
  STRIPE_WEBHOOK_SECRET — from the webhook endpoint's settings in Stripe
"""

import os

import stripe


def _get_api_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError(
            "STRIPE_SECRET_KEY is not set. Export it before using billing features:\n"
            "  export STRIPE_SECRET_KEY='sk_test_...'"
        )
    return key


def create_checkout_session(user_id: str, user_email: str, success_url: str, cancel_url: str) -> str:
    """Returns the URL to redirect the user to (Stripe's hosted checkout page)."""
    stripe.api_key = _get_api_key()
    price_id = os.environ.get("STRIPE_PRICE_ID")
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_ID is not set.")

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=user_email,
        success_url=success_url,
        cancel_url=cancel_url,
        # Carries our internal user id through to the webhook, so we know
        # which local account this Stripe customer corresponds to.
        client_reference_id=user_id,
    )
    return session.url


def create_billing_portal_session(stripe_customer_id: str, return_url: str) -> str:
    """Returns a URL to Stripe's hosted subscription management page
    (cancel, update card, view invoices) — no custom UI needed."""
    stripe.api_key = _get_api_key()
    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )
    return session.url


def verify_webhook(payload: bytes, sig_header: str):
    """
    Verifies a webhook request actually came from Stripe (not someone
    forging a "you're now paid" event) using the signing secret. Raises
    stripe.error.SignatureVerificationError if the signature is invalid.
    """
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set.")

    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
