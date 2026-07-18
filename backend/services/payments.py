import requests
import base64
import logging
from dotenv import load_dotenv
from flask import Blueprint, jsonify, request
import os
from datetime import datetime
from models.model import db, MpesaTranscation, Sales, Products
from flask_jwt_extended import jwt_required, get_jwt_identity
import json
from zoneinfo import ZoneInfo

# ── OFFLINE-FIRST ────────────────────────────────────────────────────────────
# Shared internet-reachability monitor. Every Daraja-dependent code path
# checks this FIRST and, if offline, returns a clean JSON error instead of
# attempting the call (which would otherwise hang/timeout and could leave
# things in a confusing state). This never creates a false successful
# payment and never creates a duplicate sale.
from services.network_status import is_internet_available, NoInternetError

KENYA_TZ = ZoneInfo("Africa/Nairobi")

def kenya_now():
    return datetime.now(KENYA_TZ)

load_dotenv()



logger = logging.getLogger(__name__)

pay_bp = Blueprint("payments", __name__)

CONSUMER_KEY    = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
SHORT_CODE      = os.getenv("SHORT_CODE")
PASSKEY         = os.getenv("PASSKEY")
PHONE_NUMBER    = os.getenv("PHONE_NUMBER")
INITIATOR_NAME  = os.getenv("INITIATOR_NAME")
INITIATOR_PASSWORD = os.getenv("INITIATOR_PASSWORD")
PARTY_A         = os.getenv("PARTY_A")
PARTY_B         = os.getenv("PARTY_B")
C2B_SHORT_CODE = os.getenv("C2B_SHORT_CODE", SHORT_CODE)  # default to SHORT_CODE if not set
C2B_SAFARICOM_SANDBOX_URL = os.getenv("C2B_SAFARICOM_SANDBOX_URL")
SAFARICOM_SANDBOX_TOKEN_URL = os.getenv("SAFARICOM_SANDBOX_TOKEN_URL")
SAFARICOM_SANDBOX_STK_PUSH_URL = os.getenv("SAFARICOM_SANDBOX_STK_PUSH_URL")

# Callback URL must be a publicly reachable URL (e.g. ngrok tunnel).
# Set MPESA_CALLBACK_URL in your .env file — never hardcode it here.
CALLBACK_URL        = os.getenv("CALLBACK_URL")
C2B_VALIDATION_URL  = os.getenv("C2B_VALIDATION_URL")
C2B_CONFIRMATION_URL= os.getenv("C2B_CONFIRMATION_URL")

print("=" * 40)
print("SHORT_CODE      =", repr(SHORT_CODE))
print("C2B_SHORT_CODE  =", repr(C2B_SHORT_CODE))
print("CALLBACK_URL    =", repr(CALLBACK_URL))
print("VALIDATION_URL  =", repr(C2B_VALIDATION_URL))
print("CONFIRMATION_URL=", repr(C2B_CONFIRMATION_URL))
print("=" * 40)

def _required_env_present():
    """Returns a list of required env var names that are missing/blank."""
    required = {
        "CONSUMER_KEY": CONSUMER_KEY,
        "CONSUMER_SECRET": CONSUMER_SECRET,
        "SHORT_CODE": SHORT_CODE,
        "PASSKEY": PASSKEY,
        "PARTY_A": PARTY_A,
        "PARTY_B": PARTY_B,
        "CALLBACK_URL": CALLBACK_URL,
        "C2B_VALIDATION_URL": C2B_VALIDATION_URL,
        "C2B_CONFIRMATION_URL": C2B_CONFIRMATION_URL,
    }
    return [name for name, val in required.items() if not val]


def _safe_json(response):
    """
    Parses a requests.Response as JSON, raising a clear, descriptive
    exception (instead of a bare JSONDecodeError) if the body isn't JSON.
    This is what turns 'Expecting value: line 1 column 1 (char 0)' into
    something you can actually act on.
    """
    try:
        return response.json()
    except ValueError:
        snippet = (response.text or "")[:300]
        raise Exception(
            f"Safaricom returned a non-JSON response (HTTP {response.status_code}). "
            f"Body snippet: {snippet!r}"
        )


@pay_bp.route("/home", methods=["POST"])
def home():
    return jsonify({"message": "Welcome to the payment service!"}), 200


# ── Access Token ──────────────────────────────────────────────────────────────

def access_token():
    """Fetch a fresh Safaricom OAuth token. Returns the token string or None."""
    # OFFLINE-FIRST: don't even attempt this without internet.
    if not is_internet_available():
        raise NoInternetError("Internet unavailable. Cannot reach M-Pesa while offline.")

    missing = _required_env_present()
    if missing:
        logger.error("STK | missing required env vars: %s", missing)
        raise Exception(f"Missing required M-Pesa env vars: {', '.join(missing)}")

    url = SAFARICOM_SANDBOX_TOKEN_URL
    credentials = f"{CONSUMER_KEY}:{CONSUMER_SECRET}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
    except requests.exceptions.RequestException as e:
        logger.exception("STK | network error fetching access token: %s", e)
        raise Exception(f"Could not reach Safaricom OAuth endpoint: {e}")

    if response.status_code == 200:
        data = _safe_json(response)
        token = data.get("access_token")
        if not token:
            logger.error("STK | 200 response but no access_token present: %s", data)
            raise Exception(f"Safaricom OAuth response missing access_token: {data}")
        logger.info("STK | access token fetched successfully")
        return token
    else:
        # Log + surface the actual status/body instead of silently returning None,
        # which was previously masked by a generic 'Failed to retrieve access token'
        # exception with no detail.
        snippet = (response.text or "")[:300]
        logger.error("STK | failed to fetch access token: %s %s",
                     response.status_code, snippet)
        raise Exception(
            f"Failed to fetch M-Pesa access token (HTTP {response.status_code}). "
            f"Check CONSUMER_KEY/CONSUMER_SECRET. Body: {snippet!r}"
        )


@pay_bp.route("/api/mpesa", methods=["GET"])
def get_access_token():
    try:
        token = access_token()
        return jsonify({"access_token": token,
                        "message": "Access token retrieved successfully."}), 200
    except NoInternetError as e:
        return jsonify({"success": False, "message": str(e)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── STK Push helper (imported by sales.py) ───────────────────────────────────

def initiate_stk_push(phone, amount, sale_id):
    """
    Sends an STK push request to Safaricom and records the MpesaTransaction.
    Returns the raw Safaricom response dict.
    Raises an exception on failure so the caller can handle it.

    OFFLINE-FIRST: raises NoInternetError immediately if the server has no
    internet connectivity, before touching Safaricom or creating any
    MpesaTransaction record. Callers (sales.py, the /stkpush route below)
    must catch NoInternetError and respond with the required
    {"success": false, "message": "..."} shape — never a false success,
    never a duplicate sale.
    """
    if not is_internet_available():
        logger.info("STK | offline — refusing to initiate push for sale_id=%s", sale_id)
        raise NoInternetError("Internet unavailable. STK Push cannot be initiated while offline.")

    logger.info("STK | initiating push — sale_id=%s phone=%s amount=%s",
                sale_id, phone, amount)

    # access_token() now raises a descriptive exception on failure instead
    # of returning None, so this bubbles up a real reason.
    token = access_token()

    # Fetch the sale so we can use its randomly-generated payment_reference
    # (e.g. "HS-7KQ2PX9M") as the AccountReference sent to Safaricom, instead
    # of the generic "TestPayment" placeholder. This keeps the reference the
    # customer/cashier sees consistent across STK and C2B (Lipa na M-Pesa).
    sale = Sales.query.get(sale_id)
    if not sale:
        logger.error("STK | no sale found for sale_id=%s", sale_id)
        raise Exception(f"Sale {sale_id} not found — cannot initiate STK push.")

    account_reference = sale.payment_reference

    timestamp = kenya_now().strftime("%Y%m%d%H%M%S")
    password  = base64.b64encode(
        f"{SHORT_CODE}{PASSKEY}{timestamp}".encode("utf-8")
    ).decode()

    payload = {
        "BusinessShortCode": SHORT_CODE,
        "Password":          password,
        "Timestamp":         timestamp,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            amount,
        "PartyA":            PARTY_A,
        "PartyB":            PARTY_B,
        "PhoneNumber":       phone,
        "CallBackURL":       CALLBACK_URL,
        "AccountReference":  account_reference,
        "TransactionDesc":   "Payment for testing purposes",
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    url = SAFARICOM_SANDBOX_STK_PUSH_URL
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        logger.exception("STK | network error sending STK push: %s", e)
        raise Exception(f"Could not reach Safaricom STK push endpoint: {e}")

    response_data = _safe_json(response)

    logger.info("STK | Safaricom response %s: %s", response.status_code, response_data)

    if response.status_code == 200:
        mpesa_tx = MpesaTranscation(
            sale_id=sale_id,
            phone_number=phone,
            amount=amount,
            response_code=response_data.get("ResponseCode"),
            response_description=response_data.get("ResponseDescription"),
            merchant_request_id=response_data.get("MerchantRequestID"),
            checkout_request_id=response_data.get("CheckoutRequestID"),
            business_short_code=SHORT_CODE,
            status="Pending",
        )
        db.session.add(mpesa_tx)
        db.session.commit()
        logger.info("STK | MpesaTransaction created — checkout_request_id=%s",
                    response_data.get("CheckoutRequestID"))
    else:
        logger.error("STK | Safaricom rejected the push: %s", response_data)
        raise Exception(
            f"Safaricom rejected the STK push (HTTP {response.status_code}): "
            f"{response_data.get('errorMessage') or response_data}"
        )

    return response_data


# ── Direct STK push route (for manual/API testing) ───────────────────────────

@pay_bp.route("/api/mpesa/stkpush", methods=["POST"])
def stk_push():
    try:
        data = request.get_json()

        sale_id = data.get("sale_id")
        phone   = data.get("phone")
        amount  = data.get("amount")

        if not sale_id:
            return jsonify({"error": "Sale ID is required."}), 400
        if not phone:
            return jsonify({"error": "Phone number is required."}), 400
        if not amount:
            return jsonify({"error": "Amount is required."}), 400

        # OFFLINE-FIRST: fail fast with the exact shape required, without
        # touching the sale or Safaricom at all.
        if not is_internet_available():
            return jsonify({
                "success": False,
                "message": "Internet unavailable. STK Push cannot be initiated while offline."
            }), 200

        sale = Sales.query.get(sale_id)
        if not sale:
            return jsonify({"error": "Sale not found."}), 404

        response_data = initiate_stk_push(phone, amount, sale_id)
        return jsonify(response_data), 200

    except NoInternetError as e:
        return jsonify({"success": False, "message": str(e)}), 200
    except Exception as e:
        db.session.rollback()
        logger.exception("STK push route error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ── Callback Endpoint ─────────────────────────────────────────────────────────
# UNCHANGED — STK callback logic, CheckoutRequestID / MerchantRequestID
# handling, inventory deduction, and idempotency checks are untouched.
# (Safaricom is the one reaching us here — this route itself needs no
# outbound-internet check, only inbound reachability, which is an
# infrastructure/ngrok concern outside the scope of this change.)

@pay_bp.route("/api/pay/callback", methods=["POST"])
def callback():
    """
    Safaricom posts the payment result here after the customer enters their PIN.
    Must return HTTP 200 quickly so Safaricom does not retry.
    """
    try:
        # ── 1. Read & log raw payload ────────────────────────────────────────
        raw = request.get_data(as_text=True)
        logger.info("CALLBACK | received raw payload: %s", raw)

        try:
            data = json.loads(raw)
        except Exception:
            logger.error("CALLBACK | payload is not valid JSON: %s", raw)
            return jsonify({"error": "Invalid JSON"}), 400

        # ── 2. Extract IDs and result ────────────────────────────────────────
        stk = data.get("Body", {}).get("stkCallback", {})

        merchant_request_id = stk.get("MerchantRequestID")
        checkout_request_id = stk.get("CheckoutRequestID")
        result_code         = stk.get("ResultCode")
        result_desc         = stk.get("ResultDesc")

        logger.info(
            "CALLBACK | MerchantRequestID=%s CheckoutRequestID=%s ResultCode=%s ResultDesc=%s",
            merchant_request_id, checkout_request_id, result_code, result_desc
        )

        # ── 3. Look up the MpesaTransaction ─────────────────────────────────
        mpesa_tx = MpesaTranscation.query.filter_by(
            merchant_request_id=merchant_request_id,
            checkout_request_id=checkout_request_id,
        ).first()

        if not mpesa_tx:
            logger.error(
                "CALLBACK | no MpesaTransaction found for checkout_request_id=%s",
                checkout_request_id
            )
            # Still return 200 so Safaricom stops retrying
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

        logger.info("CALLBACK | found MpesaTransaction id=%s current_status=%s",
                    mpesa_tx.id, mpesa_tx.status)

        # ── 4. Prevent double-processing ────────────────────────────────────
        if mpesa_tx.status in ["Completed", "Failed"]:
            logger.info("CALLBACK | already processed — skipping")
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

        # ── 5. Update MpesaTransaction fields ───────────────────────────────
        mpesa_tx.response_code        = result_code
        mpesa_tx.response_description = result_desc
        mpesa_tx.transaction_date     = kenya_now()

        # ── 6. Look up the Sale ──────────────────────────────────────────────
        sale = Sales.query.get(mpesa_tx.sale_id)
        logger.info("CALLBACK | sale id=%s current_status=%s",
                    mpesa_tx.sale_id, sale.status if sale else "NOT FOUND")

        # ── 7. Apply result ──────────────────────────────────────────────────
        if result_code is not None and int(result_code) == 0:
            # Payment succeeded
            metadata = {}
            callback_metadata = stk.get("CallbackMetadata")
            if callback_metadata:
                for item in callback_metadata.get("Item", []):
                    metadata[item["Name"]] = item.get("Value")

            mpesa_tx.mpesa_receipt_number = metadata.get("MpesaReceiptNumber")
            mpesa_tx.status= "Completed"

            if sale:
                # FIX: was sale.payment_status = "Paid" — that column does not exist.
                # sale.status is the field used everywhere in sales.py.
                sale.status = "completed"
                # OFFLINE-FIRST: this is where the sale actually gets confirmed by
                # the cloud, so it's a natural point to also mark it synced — the
                # cloud already knows about it via this very callback.
                if hasattr(sale, "synced"):
                    sale.synced = True
                logger.info("CALLBACK | sale %s → completed", sale.id)

                # Deduct stock now that payment is confirmed.
                # (create_sale() skipped this for pending M-Pesa sales.)
                for sale_item in sale.sale_items:
                    product = Products.query.get(sale_item.product_id)
                    if product:
                        product.quantity -= sale_item.quantity
                        db.session.add(product)
                        logger.info(
                            "CALLBACK | stock deducted — product_id=%s qty=%s",
                            product.id, sale_item.quantity
                        )

        else:
            # Payment failed or was cancelled
            mpesa_tx.status = "Failed"

            if sale:
                # FIX: same wrong-field bug as above
                sale.status = "failed"
                logger.info("CALLBACK | sale %s → failed (result_code=%s)",
                            sale.id, result_code)

        # ── 8. Commit everything ─────────────────────────────────────────────
        db.session.commit()
        logger.info("CALLBACK | db.session.commit() succeeded")

        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

    except Exception as e:
        db.session.rollback()
        logger.exception("CALLBACK | unhandled exception: %s", e)
        # Always return 200 to Safaricom — otherwise they keep retrying
        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200
    

# ── C2B Register URL ──────────────────────────────────────────────────────────

@pay_bp.route("/api/pay/c2b/register", methods=["POST"])
def c2b_register():
    try:
        # OFFLINE-FIRST: nothing to register without internet — refuse
        # cleanly instead of hanging on a timeout.
        if not is_internet_available():
            return jsonify({
                "success": False,
                "message": "Internet unavailable. Cannot register C2B URLs while offline."
            }), 200

        token = access_token()

        url = C2B_SAFARICOM_SANDBOX_URL
        payload = {
            "ShortCode":       C2B_SHORT_CODE,
            "ResponseType":    "Completed",
            "ConfirmationURL": C2B_CONFIRMATION_URL,
            "ValidationURL":   C2B_VALIDATION_URL,
        }
        
        
        logger.info("C2B REGISTER | payload: %s", payload)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }

        response = requests.post(url, json=payload, headers=headers, timeout=15)
        response_data = _safe_json(response)
        logger.info("C2B REGISTER | Safaricom response %s: %s",
                    response.status_code, response_data)
        
        print("C2B REGISTER | Safaricom response %s: %s" % (response.status_code, response_data))

        return jsonify(response_data), response.status_code

    except NoInternetError as e:
        return jsonify({"success": False, "message": str(e)}), 200
    except Exception as e:
        logger.exception("C2B REGISTER | exception: %s", e)
        return jsonify({"error": str(e)}), 500


# ── C2B Validation ─────────────────────────────────────────────────────────────
# Sales are now looked up by `payment_reference` (e.g. "HS-7KQ2PX9M") instead
# of the raw numeric sale.id. BillRefNumber is therefore a string, not an
# integer, so there is no int() conversion / ValueError-TypeError handling
# needed any more.
# (Inbound from Safaricom — no outbound-internet check needed here either.)

@pay_bp.route("/api/pay/c2b/validate", methods=["POST"])
def c2b_validation():
    try:
        raw = request.get_data(as_text=True)
        logger.info("C2B VALIDATION | received raw payload: %s", raw)

        data = request.get_json(silent=True) or {}

        bill_ref_number = data.get("BillRefNumber")
        msisdn          = data.get("MSISDN")
        amount          = data.get("TransAmount")

        logger.info(
            "C2B VALIDATION | MSISDN=%s BillRefNumber=%s Amount=%s",
            msisdn, bill_ref_number, amount
        )

        # ── Look up sale by payment_reference (BillRefNumber = sale.payment_reference) ──
        if bill_ref_number:
            bill_ref = str(bill_ref_number).strip()

            sale = Sales.query.filter_by(
                payment_reference=bill_ref
            ).first()

            if not sale:
                logger.warning(
                    "C2B VALIDATION | no sale found for payment_reference=%s — rejecting",
                    bill_ref
                )
                return jsonify({"ResultCode": "C2B00012",
                                "ResultDesc": "Invalid Account Number"}), 200

            if sale.status == "completed":
                logger.warning(
                    "C2B VALIDATION | sale with payment_reference=%s already completed — rejecting",
                    bill_ref
                )
                return jsonify({"ResultCode": "C2B00011",
                                "ResultDesc": "Account Already Paid"}), 200

            print("C2B VALIDATION | sale with payment_reference %s found, status=%s — accepting" %
                  (bill_ref, sale.status))

        return jsonify({"ResultCode": "0", "ResultDesc": "Accepted"}), 200

    except Exception as e:
        logger.exception("C2B VALIDATION | unhandled exception: %s", e)
        return jsonify({"ResultCode": "1", "ResultDesc": "Rejected"}), 200


# ── C2B Confirmation ────────────────────────────────────────────────────────────
# Same lookup change as validation: BillRefNumber is matched against
# Sales.payment_reference rather than converted to an int and used with
# Sales.query.get(). Everything else (idempotency guard, MpesaTransaction
# creation, sale completion, stock deduction, commit) is unchanged.

@pay_bp.route("/api/pay/c2b/confirm", methods=["POST"])
def c2b_confirmation():
    try:
        raw = request.get_data(as_text=True)
        print("=" * 80)
        print("RAW CALLBACK")
        print(raw)
        print("=" * 80)
        
        logger.info("C2B CONFIRMATION | received raw payload: %s", raw)

        data = request.get_json(silent=True) or {}
        
        print("Parsed JSON:", data)
        print("BillRefNumber:", repr(data.get("BillRefNumber")))
        print("TransID:", data.get("TransID"))

        transaction_id      = data.get("TransID")
        trans_amount        = data.get("TransAmount")
        business_short_code = data.get("BusinessShortCode")
        bill_ref_number     = data.get("BillRefNumber")
        msisdn              = data.get("MSISDN")

        logger.info(
            "C2B CONFIRMATION | TransID=%s MSISDN=%s Amount=%s BillRefNumber=%s",
            transaction_id, msisdn, trans_amount, bill_ref_number
        )

        # ── Idempotency guard ─────────────────────────────────────────────
        existing = MpesaTranscation.query.filter_by(
            mpesa_receipt_number=transaction_id
        ).first()
        if existing:
            logger.info("C2B CONFIRMATION | TransID=%s already recorded — skipping",
                        transaction_id)
            return jsonify({"ResultCode": "0", "ResultDesc": "Accepted"}), 200

        # ── Resolve sale from BillRefNumber (now sale.payment_reference) ──
        sale = None

        print("=" * 60)
        print("BillRefNumber received:", bill_ref_number)
        print("Type:", type(bill_ref_number))

        bill_ref = str(bill_ref_number).strip()
        print("Normalised payment_reference:", bill_ref)

        sale = Sales.query.filter_by(
            payment_reference=bill_ref
        ).first()

        if sale:
            print("Sale ID:", sale.id)
            print("Sale Payment Reference:", sale.payment_reference)
            print("Sale Status:", sale.status)
        else:
            print("SALE NOT FOUND for payment_reference:", bill_ref)

        print("=" * 60)
        
        sale_items = list(sale.sale_items)


        # ── Record the transaction ────────────────────────────────────────
        mpesa_tx = MpesaTranscation(
            sale_id=sale.id if sale else None,          # nullable=True after migration
            phone_number=msisdn,
            amount=trans_amount,
            response_code="0",
            response_description="C2B payment confirmed",
            mpesa_receipt_number=transaction_id,
            business_short_code=business_short_code,
            transaction_date=kenya_now(),
            status="Completed",
            transaction_type="C2B",                     # distinguish from STK records
            # checkout_request_id / merchant_request_id stay NULL (C2B has neither)
        )
        db.session.add(mpesa_tx)

        # ── Update sale + deduct stock ────────────────────────────────────
        if sale:
            if sale.status == "completed":
                logger.info(
                    "C2B CONFIRMATION | sale with payment_reference=%s already completed — skipping stock deduction",
                    sale.payment_reference
                )
            else:
                sale.status = "completed"
                if hasattr(sale, "synced"):
                    sale.synced = True
                logger.info(
                    "C2B CONFIRMATION | sale with payment_reference=%s → completed",
                    sale.payment_reference
                )

                for sale_item in sale_items:
                    product = Products.query.get(sale_item.product_id)
                    if product:
                        product.quantity -= sale_item.quantity
                        db.session.add(product)
                        logger.info(
                            "C2B CONFIRMATION | stock deducted — product_id=%s qty=%s",
                            product.id, sale_item.quantity
                        )

        db.session.commit()
        logger.info("C2B CONFIRMATION | db.session.commit() succeeded")
        print("C2B CONFIRMATION | db.session.commit() succeeded")

        return jsonify({"ResultCode": "0", "ResultDesc": "Accepted"}), 200

    except Exception as e:
        db.session.rollback()
        logger.exception("C2B CONFIRMATION | unhandled exception: %s", e)
        return jsonify({"ResultCode": "0", "ResultDesc": "Accepted"}), 200