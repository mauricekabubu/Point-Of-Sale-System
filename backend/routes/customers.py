from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, current_user
from extensions.extension import db
from models.model import Customer
from datetime import datetime, timedelta


customer_bp = Blueprint("customers", __name__)


@customer_bp.route("/add_customer", methods=["POST"])
@jwt_required()
def add_customer():
    try:
        user = current_user

        data = request.get_json()

        full_name = data.get("full_name")
        phone = data.get("phone")
        email = data.get("email")
    

        if not full_name or not phone:
            return jsonify({"error": "Full name and phone are required"}), 400

        # Scope duplicate phone check to the business, not globally
        if Customer.query.filter_by(phone=phone, business_id=user.business_id).first():
            return jsonify({"error": "Customer already exists"}), 400

        customer = Customer(
            full_name=full_name,
            phone=phone,
            email=email,
            business_id=user.business_id
        )

        db.session.add(customer)
        db.session.commit()

        return jsonify({"message": "Customer added successfully"}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@customer_bp.route("/edit_customer/<int:id>", methods=["PUT"])
@jwt_required()
def edit_customer(id):
    try:
        user = current_user

        customer = Customer.query.filter_by(
            id=id,
            business_id=user.business_id
        ).first()

        if not customer:
            return jsonify({"error": "Customer not found"}), 404

        data = request.get_json()

        customer.full_name = data.get("full_name", customer.full_name)
        customer.phone = data.get("phone", customer.phone)
        customer.email = data.get("email", customer.email)

        db.session.commit()

        return jsonify({"message": "Customer updated successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@customer_bp.route("/delete_customer/<int:id>", methods=["DELETE"])
@jwt_required()
def delete_customer(id):
    try:
        user = current_user

        customer = Customer.query.filter_by(
            id=id,
            business_id=user.business_id
        ).first()

        if not customer:
            return jsonify({"error": "Customer not found"}), 404

        db.session.delete(customer)
        db.session.commit()

        return jsonify({"message": "Customer deleted successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@customer_bp.route("/customers", methods=["GET"])
@jwt_required()
def customers():
    user = current_user

    all_customers = Customer.query.filter_by(business_id=user.business_id).all()

    results = [
        {
            "id": c.id,
            "full_name": c.full_name,
            "phone": c.phone,
            "email": c.email,
            # Serialize datetime to string — jsonify can't handle raw datetime objects
            "created_at": c.created_at.isoformat() if c.created_at else None
        }
        for c in all_customers
    ]

    return jsonify({"customers": results}), 200



@customer_bp.route("/customer_stats", methods=["GET"])
@jwt_required()
def customer_stats():
    business_id = current_user.business_id

    total = Customer.query.filter_by(business_id=business_id).count()

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    monthly_count = Customer.query.filter(
        Customer.business_id == business_id,
        Customer.created_at >= thirty_days_ago
    ).count()

    return jsonify({
        "total_customers": total,
        "monthly_count": monthly_count
    }), 200