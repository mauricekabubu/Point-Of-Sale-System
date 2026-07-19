"""
sync_service.py
----------------
Offline-first synchronization service.

- Exposes GET  /services/sync/status  -> current internet + last sync info
          (polled by the frontend every ~8s to drive the connection badge
          and to enable/disable internet-only buttons)
- Exposes POST /services/sync/run     -> manually trigger a sync pass
- Runs a background thread that automatically syncs whenever internet
  becomes available, without interrupting cashier operations (it never
  touches request-handling threads; it just flips `synced` flags).

This module deliberately does NOT change any existing sale/product/report
logic. It only reads what's already unsynced and marks it synced after a
(stubbed) push to a cloud endpoint. Wire in your real cloud API call inside
`_push_sale_to_cloud()` / `_push_product_to_cloud()` when ready.
"""

import logging
import threading
import time

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, current_user

from extensions.extension import db
from models.model import Sales, Products
from services.network_status import is_internet_available, get_status, start_network_monitor

logger = logging.getLogger(__name__)

sync_bp = Blueprint("sync", __name__)

AUTO_SYNC_INTERVAL_SECONDS = 60
_last_sync_summary = {"synced_sales": 0, "synced_products": 0, "ran_at": None, "errors": 0}
_sync_lock = threading.Lock()


def _push_sale_to_cloud(sale):
    """
    Stub — replace with the real cloud API call for this business.
    Must raise on failure so the caller does NOT mark it synced.
    """
    return True


def _push_product_to_cloud(product):
    """Stub — same contract as _push_sale_to_cloud."""
    return True


def synchronize_now(business_id=None):
    """
    Pushes unsynced sales and recently-modified products to the cloud.
    Safe to call repeatedly; only acts when internet is available and
    never blocks/raises into the caller for individual item failures.
    """
    global _last_sync_summary

    if not is_internet_available():
        return {"skipped": True, "reason": "offline"}

    with _sync_lock:
        synced_sales = 0
        synced_products = 0
        errors = 0

        query = Sales.query.filter_by(synced=False) if hasattr(Sales, "synced") else Sales.query.filter(False)
        if business_id:
            query = query.filter_by(business_id=business_id)

        for sale in query.limit(200).all():
            try:
                _push_sale_to_cloud(sale)
                sale.synced = True
                db.session.add(sale)
                synced_sales += 1
            except Exception as e:
                logger.warning("sync | failed to push sale %s: %s", sale.id, e)
                errors += 1

        if hasattr(Products, "last_modified"):
            prod_query = Products.query.filter(Products.last_modified.isnot(None))
            if business_id:
                prod_query = prod_query.filter_by(business_id=business_id)
            for product in prod_query.limit(500).all():
                try:
                    _push_product_to_cloud(product)
                    synced_products += 1
                except Exception as e:
                    logger.warning("sync | failed to push product %s: %s", product.id, e)
                    errors += 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.exception("sync | commit failed: %s", e)
            errors += 1

        _last_sync_summary = {
            "synced_sales": synced_sales,
            "synced_products": synced_products,
            "ran_at": time.time(),
            "errors": errors,
        }
        return _last_sync_summary


@sync_bp.route("/status", methods=["GET"])
def sync_status():
    """
    No auth required — the connection badge needs to poll this constantly
    and cheaply, even around login/logout transitions.
    """
    status = get_status()
    status["last_sync"] = _last_sync_summary
    return jsonify(status), 200


@sync_bp.route("/run", methods=["POST"])
@jwt_required()
def sync_run():
    result = synchronize_now(business_id=getattr(current_user, "business_id", None))
    return jsonify(result), 200


def _auto_sync_loop():
    while True:
        try:
            if is_internet_available():
                synchronize_now()
        except Exception as e:
            logger.exception("sync | auto-sync loop error: %s", e)
        time.sleep(AUTO_SYNC_INTERVAL_SECONDS)


_auto_sync_started = False


def start_sync_service(app=None):
    """
    Call once at app startup, e.g.:

        from services.network_status import start_network_monitor
        from services.sync_service import start_sync_service

        start_network_monitor()
        start_sync_service(app)
    """
    global _auto_sync_started
    start_network_monitor()
    if _auto_sync_started:
        return
    _auto_sync_started = True

    def _run():
        if app is not None:
            with app.app_context():
                _auto_sync_loop()
        else:
            _auto_sync_loop()

    thread = threading.Thread(target=_run, name="auto-sync", daemon=True)
    thread.start()
    logger.info("sync_service | auto-sync thread started")
