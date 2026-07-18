from flask import Blueprint, request, jsonify
from flask_jwt_extended import current_user, jwt_required
from models.model import Supplier, Purchase, PurchaseItem, Products, StockMovement
from extensions.extension import db
from datetime import datetime, timezone, timedelta
from sqlalchemy import func


supplier_bp = Blueprint("supplier", __name__)


@supplier_bp.route("/add_supplier", methods=["POST"])
@jwt_required()
def create_supplier():
    try:
        data = request.get_json()

        if not data.get("name") or not data.get("phone"):
            return jsonify({"error": "Name and phone are required"}), 400

        supplier = Supplier(
            name=data.get("name"),
            email=data.get("email"),
            phone=data.get("phone"),
            business_id=current_user.business_id
        )

        db.session.add(supplier)
        db.session.commit()

        return jsonify({
            "message": "Supplier created successfully",
            "supplier_id": supplier.id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@supplier_bp.route("/purchases", methods=["POST"])
@jwt_required()
def create_purchases():
    try:
        data = request.get_json()

        supplier_id = data.get("supplier_id")
        items = data.get("items")

        if not supplier_id or not items:
            return jsonify({"error": "Supplier_id and items are required"}), 400

        supplier = Supplier.query.filter_by(
            id=supplier_id,
            business_id=current_user.business_id
        ).first()

        if not supplier:
            return jsonify({"error": "Supplier not found"}), 404

        total_amount = 0
        purchase_items = []

        for item in items:
            quantity = item.get("quantity")
            cost_price = item.get("cost_price")

            if not quantity or not cost_price:
                return jsonify({"error": "Each item requires quantity and cost_price"}), 400

            if quantity <= 0 or cost_price <= 0:
                return jsonify({"error": "Quantity and cost_price must be greater than 0"}), 400

            product = Products.query.filter_by(
                id=item.get("product_id"),
                business_id=current_user.business_id
            ).first()

            if not product:
                return jsonify({"error": f"Product {item.get('product_id')} not found"}), 404

            subtotal = quantity * cost_price

            product.quantity += quantity
            product.cost_price = cost_price

            movement = StockMovement(
                product_id=product.id,
                business_id=current_user.business_id,
                quantity=quantity,
                movement_type="in"
            )
            db.session.add(movement)

            purchase_item = PurchaseItem(
                product_id=product.id,
                quantity=quantity,
                cost_price=cost_price,
                subtotal=subtotal
            )

            total_amount += subtotal
            purchase_items.append(purchase_item)

        purchase = Purchase(
            supplier_id=supplier_id,
            business_id=current_user.business_id,
            total_amount=total_amount
        )

        db.session.add(purchase)
        db.session.flush()

        for purchase_item in purchase_items:
            purchase_item.purchase_id = purchase.id
            db.session.add(purchase_item)

        db.session.commit()

        return jsonify({
            "message": "Purchase recorded",
            "purchase_id": purchase.id,
            "total": total_amount
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@supplier_bp.route("/suppliers", methods=["GET"])
@jwt_required()
def suppliers():
    all_suppliers = Supplier.query.filter_by(
        business_id=current_user.business_id
    ).all()

    return jsonify({
        "suppliers": [
            {
                "id": s.id,
                "name": s.name,
                "phone": s.phone,
                "email": s.email,
                "status": s.status
            } for s in all_suppliers
        ]
    }), 200


@supplier_bp.route("/purchase_history", methods=["GET"])
@jwt_required()
def purchase_history():
    purchases = Purchase.query.filter_by(
        business_id=current_user.business_id
    ).order_by(Purchase.created_at.desc()).all()

    results = []

    for p in purchases:
        results.append({
            "purchase_id": p.id,
            "supplier_id": p.supplier_id,
            "supplier_name": p.supplier.name,
            "total": p.total_amount,
            # Serialize datetime — raw datetime object is not JSON serializable
            "date": p.created_at.isoformat() if p.created_at else None,
            "items": [
                {
                    "product_id": i.product_id,
                    "product_name": i.product.name,
                    "quantity": i.quantity,
                    "cost_price": i.cost_price,
                    "subtotal": i.subtotal
                } for i in p.purchase_items
            ]
        })

    return jsonify({"purchases": results}), 200


@supplier_bp.route("/update_supplier/<int:id>", methods=["PUT"])
@jwt_required()
def update_supplier(id):
    try:
        data = request.get_json()

        supplier = Supplier.query.filter_by(
            id=id, business_id=current_user.business_id
        ).first()

        if not supplier:
            return jsonify({"error": "Supplier not found"}), 404

        supplier.name = data.get("name", supplier.name)
        supplier.phone = data.get("phone", supplier.phone)
        supplier.email = data.get("email", supplier.email)
        # Allow status updates so "pending" / "inactive" can actually be set
        if data.get("status") in ("active", "pending", "inactive"):
            supplier.status = data["status"]

        db.session.commit()

        return jsonify({
            "message": "Supplier updated successfully",
            "supplier": {
                "id": supplier.id,
                "name": supplier.name,
                "phone": supplier.phone,
                "email": supplier.email,
                "status": supplier.status
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@supplier_bp.route("/delete_supplier/<int:id>", methods=["DELETE"])
@jwt_required()
def delete_supplier(id):
    try:
        supplier = Supplier.query.filter_by(
            id=id, business_id=current_user.business_id
        ).first()

        if not supplier:
            return jsonify({"error": "Supplier not found"}), 404

        existing_purchase = Purchase.query.filter_by(supplier_id=id).first()

        if existing_purchase:
            return jsonify({
                "error": "Cannot delete supplier with existing purchases"
            }), 400

        db.session.delete(supplier)
        db.session.commit()

        return jsonify({"message": "Supplier deleted successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@supplier_bp.route("/supplier_stats", methods=["GET"])
@jwt_required()
def supplier_stats():
    business_id = current_user.business_id

    total = Supplier.query.filter_by(business_id=business_id).count()
    active = Supplier.query.filter_by(business_id=business_id, status="active").count()
    pending = Supplier.query.filter_by(business_id=business_id, status="pending").count()

    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    new_suppliers = Supplier.query.filter(
        Supplier.business_id == business_id,
        Supplier.created_at >= seven_days_ago
    ).count()

    return jsonify({
        "total_suppliers": total,
        "active_suppliers": active,
        "pending_suppliers": pending,
        "new_suppliers": new_suppliers
    }), 200


@supplier_bp.route("/top_suppliers", methods=["GET"])
@jwt_required()
def top_suppliers():
    business_id = current_user.business_id

    results = db.session.query(
        Supplier.id,
        Supplier.name,
        func.sum(Purchase.total_amount).label("total_spent"),
        func.count(Purchase.id).label("total_orders")
    ).join(Purchase, Supplier.id == Purchase.supplier_id)\
     .filter(Supplier.business_id == business_id)\
     .group_by(Supplier.id)\
     .order_by(func.sum(Purchase.total_amount).desc())\
     .limit(5)\
     .all()

    return jsonify({
        "top_suppliers": [
            {
                "supplier_id": r.id,
                "name": r.name,
                "total_spent": float(r.total_spent),
                "total_orders": r.total_orders
            } for r in results
        ]
    }), 200