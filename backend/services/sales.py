from flask import jsonify, request, Blueprint
from flask_jwt_extended import jwt_required, current_user
from models.model import SaleItems, Sales, Products, StockMovement, TransactionLog, SaleReturn, StockAlert
from extensions.extension import db
from sqlalchemy import func, or_
from datetime import datetime, timedelta, timezone
from services.payments import initiate_stk_push
from zoneinfo import ZoneInfo
from models.model import Users

# OFFLINE-FIRST: shared internet-reachability check + the exception
# initiate_stk_push() raises when offline.
from services.network_status import is_internet_available, NoInternetError


KENYA_TZ = ZoneInfo("Africa/Nairobi")

def kenya_now():
    return datetime.now(KENYA_TZ)

sale_bp = Blueprint("sales", __name__)


def create_sale(user_id, items, business_id, payment_method, status="completed"):
    """
    Creates a sale record.
    - For cash payments, status defaults to 'completed' and stock is deducted immediately.
    - For M-Pesa payments, pass status='pending'; stock is NOT deducted yet.
      Stock deduction happens inside the M-Pesa callback once payment is confirmed.

    OFFLINE-FIRST: every sale is created locally regardless of internet
    state — this function itself makes no network calls. It additionally
    (best-effort, schema-tolerant) marks the sale as unsynced/local so the
    synchronization service can pick it up later. These fields are guarded
    with hasattr() so this keeps working even before the DB migration in
    offline_migration.sql has been applied.
    """
    try:
        sales_item_list = []
        total_amount = 0

        for item in items:
            product = Products.query.filter_by(
                id=item["product_id"],
                business_id=business_id
            ).first()

            if not product:
                raise Exception(f"Product {item['product_id']} not found")

            quantity = item["quantity"]

            if quantity <= 0:
                raise Exception("Quantity must be greater than 0")

            if product.quantity < quantity:
                raise Exception(f"Stock not enough for {product.name}")

            price = product.price
            subtotal = quantity * price

            # Only deduct stock immediately for completed (cash) sales.
            # For pending (M-Pesa) sales, stock is deducted in the callback.
            if status == "completed":
                product.quantity -= quantity
                db.session.add(product)

            sale_item = SaleItems(
                product_id=product.id,
                quantity=quantity,
                price=price,
                cost_price=product.cost_price,
                subtotal=subtotal
            )

            total_amount += subtotal
            sales_item_list.append(sale_item)

        sale = Sales(
            user_id=user_id,
            business_id=business_id,
            total_amount=total_amount,
            payment_method=payment_method,
            status=status
        )

        # OFFLINE-FIRST: mark every locally-created sale as not-yet-synced.
        # Guarded so this is a no-op until the `synced` / `created_locally`
        # columns exist (see offline_migration.sql).
        if hasattr(sale, "synced"):
            sale.synced = False
        if hasattr(sale, "created_locally"):
            sale.created_locally = True

        db.session.add(sale)
        db.session.flush()

        for sale_item in sales_item_list:
            sale_item.sale_id = sale.id
            db.session.add(sale_item)

        log = TransactionLog(
            action="sale created",
            user_id=user_id,
            business_id=business_id,
            sale_id=sale.id,
            description=f"Sale created with total {total_amount}, status={status}"
        )

        db.session.add(log)
        db.session.commit()

        return sale

    except Exception as e:
        db.session.rollback()
        raise


@sale_bp.route("/sale", methods=["POST"])
@jwt_required()
def sales():
    try:
        data = request.get_json()
        
        items = data.get("items")
        payment_method = data.get("payment_method")
        phone = data.get("phone")
        payment_type = data.get("payment_type", "").lower()
        payment_reference = data.get("payment_reference")

        if not items or not payment_method:
            return jsonify({"error": "Items and payment method are required"}), 400

        # Normalise to lowercase so "Cash", "CASH", "cash" all work
        payment_method_normalised = payment_method.lower().replace(" ", "").replace("-", "")
        # Results: "Cash" → "cash", "M-Pesa" → "mpesa", "Airtel Money" → "airtelmoney", "Card" → "card"

        # ── Cash / Card / Manual — always works, online or offline ─────────
        if payment_method_normalised == "cash" or payment_method_normalised == "card":
            sale = create_sale(
                user_id=current_user.id,
                business_id=current_user.business_id,
                items=items,
                payment_method=payment_method,   # store original value e.g. "Cash"
                status="completed"
            )
            return jsonify({
                "message": "Sale created successfully",
                "sale_id": sale.id,
                "total": sale.total_amount,
                "status": "completed"
            }), 201

        elif payment_method_normalised == "mpesa":
            if phone:
                # ── STK Push flow: prompt sent directly to the customer's phone ──
                # OFFLINE-FIRST: check BEFORE creating any sale record, so a
                # cashier attempting STK while offline never leaves behind an
                # orphaned "pending" sale and never gets a false success.
                if not is_internet_available():
                    return jsonify({
                        "success": False,
                        "message": "Internet unavailable. STK Push cannot be initiated while offline."
                    }), 200

                sale = create_sale(
                    user_id=current_user.id,
                    business_id=current_user.business_id,
                    items=items,
                    payment_method=payment_method,   # store original value e.g. "M-Pesa"
                    status="pending"
                )

                try:
                    stk_response = initiate_stk_push(phone, sale.total_amount, sale.id)
                except NoInternetError as e:
                    # Internet dropped between the check above and now — mark
                    # the sale failed rather than leaving it pending forever,
                    # and report cleanly. No duplicate sale is created; the
                    # cashier can retry once back online.
                    sale.status = "failed"
                    db.session.commit()
                    return jsonify({"success": False, "message": str(e)}), 200

                checkout_request_id = stk_response.get("CheckoutRequestID")
                if checkout_request_id:
                    sale.checkout_request_id = checkout_request_id
                    db.session.commit()

                return jsonify({
                    "message": "Payment initiated, waiting for M-Pesa confirmation",
                    "sale_id": sale.id,
                    "total": sale.total_amount,
                    "status": "pending"
                }), 202
            
            elif payment_type == "manual":
                # Manual Till (Buy Goods) — cashier-confirmed, no Daraja call
                # at all, so this keeps working fully offline.
                sale = create_sale(
                    user_id=current_user.id,
                    business_id=current_user.business_id,
                    items=items,
                    payment_method=payment_method,
                    status="completed"
                )

                return jsonify({
                    "message": "Sale created successfully",
                    "sale_id": sale.id,
                    "total": sale.total_amount,
                    "status": "completed"
                }), 201

            else:
                # ── C2B / Lipa na M-Pesa flow: customer pays manually via Till/Paybill ──
                # This requires Safaricom's webhook to reach us later, so it's
                # only meaningful with internet. Refuse cleanly up front
                # rather than creating a sale that can never be confirmed.
                if not is_internet_available():
                    return jsonify({
                        "success": False,
                        "message": "Internet unavailable. Lipa na M-Pesa requires an internet connection."
                    }), 200

                # No STK push is fired here. sale.id is handed back to the frontend,
                # which shows it to the cashier as the Account Number the customer
                # must enter on their phone. The sale stays "pending" until
                # Safaricom's /c2b/confirm webhook resolves this same sale.id via
                # BillRefNumber and flips it to "completed".
                sale = create_sale(
                    user_id=current_user.id,
                    business_id=current_user.business_id,
                    items=items,
                    payment_method=payment_method,
                    status="pending"
                )

                return jsonify({
                    "message": "Sale created — awaiting C2B payment confirmation",
                    "sale_id": sale.id,
                    "payment_reference": sale.payment_reference,
                    "total": sale.total_amount,
                    "status": "pending"
                }),202
        
        
        elif payment_method_normalised == "airtelmoney":
            # Treat Airtel Money like cash for now — complete immediately
            # Replace with Airtel STK push logic when ready
            sale = create_sale(
                user_id=current_user.id,
                business_id=current_user.business_id,
                items=items,
                payment_method=payment_method,
                status="completed"
            )
            return jsonify({
                "message": "Sale created successfully",
                "sale_id": sale.id,
                "total": sale.total_amount,
                "status": "completed"
            }), 201

        else:
            return jsonify({"error": f"Unsupported payment method: {payment_method}"}), 400

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@sale_bp.route("/history", methods=["GET"])
@jwt_required()
def sale_history():
    business_id = current_user.business_id

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    search = request.args.get("search", "").strip()
    payment = request.args.get("payment", "").strip()
    status = request.args.get("status", "").strip()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = Sales.query.filter(
        Sales.business_id == business_id
    )

    # Search by Sale ID or Cashier
    if search:
        query = query.join(Users).filter(
            or_(
                Sales.id.cast(db.String).ilike(f"%{search}%"),
                Users.full_name.ilike(f"%{search}%"),
                Users.username.ilike(f"%{search}%")
            )
        )

    # Payment filter
    if payment:
        query = query.filter(Sales.payment_method == payment)

    # Status filter
    if status:
        query = query.filter(Sales.status == status)

    # Date range
    if start_date:
        query = query.filter(func.date(Sales.created_at) >= start_date)

    if end_date:
        query = query.filter(func.date(Sales.created_at) <= end_date)

    pagination = (
        query.order_by(Sales.created_at.desc())
             .paginate(page=page, per_page=per_page, error_out=False)
    )

    result = []

    for sale in pagination.items:
        result.append({
            "sale_id": sale.id,
            "total_amount": sale.total_amount,
            "payment_method": sale.payment_method,
            "status": sale.status,
            "synced": getattr(sale, "synced", None),
            "seller": {
                "id": sale.user.id,
                "name": sale.user.full_name,
                "username": sale.user.username
            },
            "date": sale.created_at.isoformat() if sale.created_at else None
        })

    return jsonify({
        "sales": result,
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total_items": pagination.total,
            "total_pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev
        }
    }), 200


@sale_bp.route("/single_sale/<int:id>", methods=["GET"])
@jwt_required()
def single_sale(id):
    business_id = current_user.business_id

    sale = Sales.query.filter_by(id=id, business_id=business_id).first()

    if not sale:
        return jsonify({"error": "Sale not found!"}), 404

    items = [
        {
            "product_name": item.product.name,
            "quantity": item.quantity,
            "price": item.price,
            "subtotal": item.subtotal
        }
        for item in sale.sale_items
    ]
    
    print("SALE STATUS:", sale.status)

    return jsonify({
        "sale_id": sale.id,
        "total": sale.total_amount,
        "payment_method": sale.payment_method,
        "status": sale.status,   # frontend polls this field
        "synced": getattr(sale, "synced", None),
        "seller": {
            "id": sale.user.id,
            "username": sale.user.username
        },
        "items": items,
        # serialize datetime
        "date": sale.created_at.isoformat() if sale.created_at else None
    }), 200


@sale_bp.route("/revenue", methods=["GET"])
@jwt_required()
def revenue():
    business_id = current_user.business_id

    total_revenue = (
        db.session.query(func.sum(Sales.total_amount))
        .filter(
            Sales.business_id == business_id,
            Sales.status == "completed"
        )
        .scalar()
    )

    return jsonify({"total_revenue": total_revenue or 0}), 200


@sale_bp.route("/profit", methods=["GET"])
@jwt_required()
def profit():
    business_id = current_user.business_id

    total_profit = (
        db.session.query(func.sum((SaleItems.price - SaleItems.cost_price) * SaleItems.quantity))
        .join(Sales, SaleItems.sale_id == Sales.id)
        .filter(
            Sales.business_id == business_id,
            Sales.status == "completed"
        )
        .scalar()
    )

    total_returns = db.session.query(
        func.sum(SaleReturn.refunded_amount)
    ).join(Sales, SaleReturn.sale_id == Sales.id).filter(
        Sales.business_id == business_id
    ).scalar()

    final_profit = (total_profit or 0) - (total_returns or 0)

    return jsonify({"total_profit": final_profit}), 200


@sale_bp.route("/summary", methods=["GET"])
@jwt_required()
def summary_today():
    business_id = current_user.business_id
    seven_days_ago = kenya_now() - timedelta(days=7)

    today_sales = db.session.query(
        func.sum(Sales.total_amount)
    ).filter(
        Sales.business_id == business_id,
        Sales.status == "completed",
        func.date(Sales.created_at) == func.current_date()
    ).scalar()

    weekly_sales = db.session.query(
        func.sum(Sales.total_amount)
    ).filter(
        Sales.business_id == business_id,
        Sales.status == "completed",
        Sales.created_at >= seven_days_ago
    ).scalar()

    monthly_sales = db.session.query(
        func.sum(Sales.total_amount)
    ).filter(
        Sales.business_id == business_id,
        Sales.status == "completed",
        func.extract("month", Sales.created_at) == func.extract("month", func.now()),
        func.extract("year", Sales.created_at) == func.extract("year", func.now())
    ).scalar()

    return jsonify({
        "sales": {
            "today_sales": today_sales or 0,
            "weekly_sales": weekly_sales or 0,
            "monthly_sales": monthly_sales or 0
        }
    }), 200


@sale_bp.route("/return", methods=["POST"])
@jwt_required()
def return_item():
    try:
        data = request.get_json()

        sale_id = data.get("sale_id")
        product_id = data.get("product_id")
        quantity = data.get("quantity")
        reason = data.get("reason", "No reason provided")

        if not sale_id or not product_id or not quantity:
            return jsonify({"error": "sale_id, product_id and quantity are required"}), 400

        if quantity <= 0:
            return jsonify({"error": "Quantity must be greater than 0"}), 400

        sale = Sales.query.filter_by(
            id=sale_id,
            business_id=current_user.business_id
        ).first()

        if not sale:
            return jsonify({"error": "Sale not found"}), 404

        # Only allow returns on completed sales
        if sale.status != "completed":
            return jsonify({"error": "Returns can only be processed for completed sales"}), 400

        item = SaleItems.query.filter_by(
            sale_id=sale_id,
            product_id=product_id
        ).first()

        if not item:
            return jsonify({"error": "Item not found in sale"}), 404

        already_returned = db.session.query(
            func.sum(SaleReturn.quantity)
        ).filter_by(sale_id=sale_id, product_id=product_id).scalar() or 0

        returnable_quantity = item.quantity - already_returned

        if quantity > returnable_quantity:
            return jsonify({
                "error": f"Return quantity exceeds returnable quantity. Max returnable: {returnable_quantity}"
            }), 400

        product = Products.query.get(product_id)

        if not product:
            return jsonify({"error": "Product not found"}), 404

        product.quantity += quantity
        refunded_amount = quantity * item.price

        sale.total_amount -= refunded_amount
        db.session.add(sale)

        return_record = SaleReturn(
            sale_id=sale_id,
            product_id=product_id,
            quantity=quantity,
            reason=reason,
            refunded_amount=refunded_amount
        )
        db.session.add(return_record)

        movement = StockMovement(
            product_id=product.id,
            business_id=current_user.business_id,
            quantity=quantity,
            movement_type="in"
        )
        db.session.add(movement)

        log = TransactionLog(
            action="return processed",
            user_id=current_user.id,
            business_id=current_user.business_id,
            sale_id=sale_id,
            description=f"Return of {quantity} unit(s) of product {product_id}. Refunded: {refunded_amount}"
        )
        db.session.add(log)
        db.session.commit()

        return jsonify({
            "message": "Return processed successfully",
            "refunded_amount": refunded_amount,
            "remaining_returnable": returnable_quantity - quantity
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@sale_bp.route("/refund_history", methods=["GET"])
@jwt_required()
def refund_history():
    business_id = current_user.business_id

    returns = SaleReturn.query.join(Sales).filter(
        Sales.business_id == business_id
    ).all()

    result = [
        {
            "user_id": r.sale.user.id,
            "refunder": r.sale.user.username,
            "sale_id": r.sale_id,
            "product_name": r.product.name,
            "quantity": r.quantity,
            "reason": r.reason,
            "refunded_amount": r.refunded_amount,
            # serialize datetime
            "date": r.created_at.isoformat() if r.created_at else None
        }
        for r in returns
    ]

    return jsonify({"returns": result}), 200


@sale_bp.route("/top-selling-products", methods=["GET"])
@jwt_required()
def top_selling_products():
    business_id = current_user.business_id

    results = db.session.query(
        Products.name,
        func.sum(SaleItems.quantity).label("total_sold")
    ).join(SaleItems, Products.id == SaleItems.product_id
    ).join(Sales, SaleItems.sale_id == Sales.id
    ).filter(
        Sales.business_id == business_id,
        Sales.status == "completed"
    ).group_by(Products.id
    ).order_by(func.sum(SaleItems.quantity).desc()
    ).limit(5).all()

    data = [{"product": name, "total_sold": total_sold} for name, total_sold in results]

    return jsonify({"top_products": data}), 200


@sale_bp.route("/analytics", methods=["GET"])
@jwt_required()
def daily_profits():
    business_id = current_user.business_id

    results = db.session.query(
        func.date(Sales.created_at),
        func.sum(
            (SaleItems.price - SaleItems.cost_price) * SaleItems.quantity
        ).label("profit")
    ).join(Sales, SaleItems.sale_id == Sales.id
    ).filter(
        Sales.business_id == business_id,
        Sales.status == "completed"
    ).group_by(func.date(Sales.created_at)
    ).order_by(func.date(Sales.created_at)).all()

    data = [{"date": str(date), "profit": profit or 0} for date, profit in results]

    return jsonify({"daily_profit": data}), 200


@sale_bp.route("/daily_trends", methods=["GET"])
@jwt_required()
def daily_trends():
    business_id = current_user.business_id

    today = kenya_now().replace(hour=0, minute=0, second=0, microsecond=0)

    results = db.session.query(
        func.extract("hour", Sales.created_at),
        func.sum(Sales.total_amount)
    ).filter(
        Sales.business_id == business_id,
        Sales.status == "completed",
        Sales.created_at >= today
    ).group_by(
        func.extract("hour", Sales.created_at)
    ).order_by(
        func.extract("hour", Sales.created_at)
    ).all()

    data = [{"hour": int(hour), "sales": total or 0} for hour, total in results]

    return jsonify({"daily_trend": data}), 200


@sale_bp.route("/weekly_trends", methods=["GET"])
@jwt_required()
def weekly_trends():
    business_id = current_user.business_id

    seven_days_ago = kenya_now() - timedelta(days=7)

    results = db.session.query(
        func.date(Sales.created_at),
        func.sum(Sales.total_amount)
    ).filter(
        Sales.business_id == business_id,
        Sales.status == "completed",
        Sales.created_at >= seven_days_ago
    ).group_by(func.date(Sales.created_at)
    ).order_by(func.date(Sales.created_at)).all()

    data = [{"date": str(date), "sales": total or 0} for date, total in results]

    return jsonify({"weekly_trend": data}), 200


@sale_bp.route("/monthly_trends", methods=["GET"])
@jwt_required()
def monthly_trends():
    business_id = current_user.business_id

    first_day = kenya_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    results = db.session.query(
        func.date(Sales.created_at),
        func.sum(Sales.total_amount)
    ).filter(
        Sales.business_id == business_id,
        Sales.status == "completed",
        Sales.created_at >= first_day
    ).group_by(
        func.date(Sales.created_at)
    ).order_by(
        func.date(Sales.created_at)
    ).all()

    data = [{"date": str(date), "sales": total or 0} for date, total in results]

    return jsonify({"monthly_trend": data}), 200


@sale_bp.route("/overview", methods=["GET"])
@jwt_required()
def overview():
    business_id = current_user.business_id

    total_sales = db.session.query(
        func.sum(Sales.total_amount)
    ).filter_by(business_id=business_id).filter(
        Sales.status == "completed"
    ).scalar()

    total_profit = db.session.query(
        func.sum((SaleItems.price - SaleItems.cost_price) * SaleItems.quantity)
    ).join(Sales, SaleItems.sale_id == Sales.id).filter(
        Sales.business_id == business_id,
        Sales.status == "completed"
    ).scalar()

    total_transactions = db.session.query(
        func.count(Sales.id)
    ).filter_by(business_id=business_id).filter(
        Sales.status == "completed"
    ).scalar()

    total_refunds = db.session.query(
        func.sum(SaleReturn.refunded_amount)
    ).join(Sales, SaleReturn.sale_id == Sales.id).filter(
        Sales.business_id == business_id
    ).scalar()

    refunds_count = db.session.query(
        func.count(SaleReturn.id)
    ).join(Sales, SaleReturn.sale_id == Sales.id).filter(
        Sales.business_id == business_id
    ).scalar()

    total_products_sold = db.session.query(
        func.sum(SaleItems.quantity)
    ).join(Sales, SaleItems.sale_id == Sales.id).filter(
        Sales.business_id == business_id,
        Sales.status == "completed"
    ).scalar()

    low_stock_count = db.session.query(
        func.count(Products.id)
    ).filter(
        Products.business_id == business_id,
        Products.quantity <= Products.low_stock_threshold
    ).scalar()

    return jsonify({
        "total_sales": total_sales or 0,
        "total_profit": total_profit or 0,
        "total_transactions": total_transactions or 0,
        "total_refunds": total_refunds or 0,
        "total_products_sold": total_products_sold or 0,
        "low_stock_count": low_stock_count or 0,
        "refund_count": refunds_count or 0
    }), 200


@sale_bp.route("/low_stock", methods=["GET"])
@jwt_required()
def low_stock():
    business_id = current_user.business_id
    
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    pagination = (
        Products.query.filter(
            Products.business_id == business_id,
            Products.quantity <= Products.low_stock_threshold
        )
        .order_by(Products.name)
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    results = [
        {
            "product_id": product.id,
            "product_name": product.name,
            "product_quantity": product.quantity,
            "product_threshold": product.low_stock_threshold
        }
        for product in pagination.items
    ]

    return jsonify({"low_stock_products": results, "pagination": {
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total_items": pagination.total,
        "total_pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev
    }}), 200


@sale_bp.route("/outof_stock", methods=["GET"])
@jwt_required()
def out_of_stock():
    business_id = current_user.business_id

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    pagination = (
        Products.query.filter(
            Products.business_id == business_id,
            Products.quantity == 0
        )
        .order_by(Products.name)
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    results = [{"product_id": p.id, "product_name": p.name} for p in pagination.items]

    return jsonify({"out_of_stock": results, "pagination": {
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total_items": pagination.total,
        "total_pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev
    }}), 200


@sale_bp.route("/alert", methods=["GET"])
@jwt_required()
def alert():
    business_id = current_user.business_id

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    pagination = (
        StockAlert.query.filter_by(
            business_id=business_id
        )
        .order_by(StockAlert.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    # serialize datetime on alerts
    results = [
        {
            "message": a.message,
            "date": a.created_at.isoformat() if a.created_at else None
        }
        for a in pagination.items
    ]

    return jsonify({"alerts": results, "pagination": {
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total_items": pagination.total,
        "total_pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev
    }}), 200


@sale_bp.route("/add_stock", methods=["POST"])
@jwt_required()
def add_stock():
    try:
        data = request.get_json()

        product_id = data.get("product_id")
        quantity = data.get("quantity")

        if not product_id or not quantity:
            return jsonify({"error": "Product_id and quantity required"}), 400

        if quantity <= 0:
            return jsonify({"error": "Quantity must be greater than 0"}), 400

        product = Products.query.filter_by(
            id=product_id,
            business_id=current_user.business_id
        ).first()

        if not product:
            return jsonify({"error": "Product not found"}), 404

        product.quantity += quantity

        movement = StockMovement(
            product_id=product.id,
            business_id=current_user.business_id,
            quantity=quantity,
            movement_type="in"
        )

        db.session.add(movement)
        db.session.commit()

        return jsonify({
            "message": "Stock updated successfully",
            "product_id": product.id,
            "new_quantity": product.quantity
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@sale_bp.route("/stock_history", methods=["GET"])
@jwt_required()
def stock_history():
    business_id = current_user.business_id

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    pagination = (
        StockMovement.query.filter_by(
            business_id=business_id
        )
        .order_by(StockMovement.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    
    result = [
        {
            "product_id": m.product_id,
            "product_name": m.product.name,
            "quantity": m.quantity,
            "movement_type": m.movement_type,
            # serialize datetime on stock movements
            "date": m.created_at.isoformat() if m.created_at else None
        }
        for m in pagination.items
    ]

    return jsonify({"stock_movements": result, "pagination": {
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total_items": pagination.total,
        "total_pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev
    }}), 200