from flask import Blueprint, request, jsonify
from flask_jwt_extended import current_user, jwt_required
from extensions.extension import db
from models.model import Users,Business
from werkzeug.security import generate_password_hash,check_password_hash


user_bp = Blueprint("users", __name__)


@user_bp.route("/add_cashier", methods=["POST"])
@jwt_required()
def add_user():
    try:
        user = current_user  

        if user.role != "admin":  
            return jsonify({"error": "Unauthorised"}), 403

        data = request.get_json()

        full_name = data.get("full_name")
        username = data.get("username")
        email = data.get("email")
        phone = data.get("phone")
        pin = data.get("pin")

        if not all([full_name, username, email, phone, pin]):
            return jsonify({"error": "All fields are required"}), 400

        
        if Users.query.filter(
            (Users.email == email) | (Users.username == username)
        ).first():
            return jsonify({"error": "User already exists"}), 400

        cashier = Users(
            full_name=full_name,
            username=username,
            phone=phone,
            email=email,
            role="cashier",
            pin=generate_password_hash(pin),
            business_id=user.business_id  
        )

        db.session.add(cashier)
        db.session.commit()

        return jsonify({"message": "Cashier created successfully"}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@user_bp.route("/edit_cashier/<int:id>", methods=["PUT"])
@jwt_required()
def update_cashier(id):
    try:
        user = current_user  

        if user.role != "admin":
            return jsonify({"error": "Unauthorised"}), 403

        cashier = Users.query.filter_by(
            id=id, role="cashier", business_id=user.business_id
        ).first()

        if not cashier:
            return jsonify({"error": "Cashier not found"}), 404

        data = request.get_json()

        cashier.full_name = data.get("full_name", cashier.full_name)
        cashier.username = data.get("username", cashier.username)
        cashier.email = data.get("email", cashier.email)
        cashier.phone = data.get("phone", cashier.phone)

        if data.get("pin"):
            cashier.pin = generate_password_hash(data["pin"])

        db.session.commit()

        return jsonify({"message": "Cashier updated successfully"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@user_bp.route("/delete_cashier/<int:id>", methods=["DELETE"])
@jwt_required()
def delete_cashier(id):
    try:
        user = current_user  

        if user.role != "admin":
            return jsonify({"error": "Unauthorised"}), 403

        cashier = Users.query.filter_by(
            id=id, role="cashier", business_id=user.business_id
        ).first()

        if not cashier:
            return jsonify({"error": "Cashier not found"}), 404

        db.session.delete(cashier)
        db.session.commit()

        return jsonify({"message": "Cashier deleted successfully"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    
    
    
@user_bp.route("/users_stats",methods=["GET"])
@jwt_required()
def users_stats():
    business_id = current_user.business_id
    
    total = Users.query.filter_by(
        business_id=business_id
    ).count()
    
    active = Users.query.filter_by(
        business_id=business_id,
        status="active"
    ).count()
    
    role = Users.query.filter_by(
        business_id=business_id,
        role=current_user.role
    ).count()
    
    return jsonify(
        {
            "total_users":total,
            "active_users":active,
            "role":role
        }
    ),200
    
    
@user_bp.route("/update_profile", methods=["PUT"])
@jwt_required()
def admin_update_profile():
    try:
        user = Users.query.filter_by(id=current_user.id).first()

        if not user:
            return jsonify({"error": "User not found"}), 404

        data = request.get_json()

        #Validate uniqueness BEFORE assigning — prevents dirty state on conflict
        if data.get("username"):
            existing = Users.query.filter(
                Users.username == data["username"],
                Users.id != user.id
            ).first()
            if existing:
                return jsonify({"error": "Username already taken"}), 400

        if data.get("email"):
            existing = Users.query.filter(
                Users.email == data["email"],
                Users.id != user.id
            ).first()
            if existing:
                return jsonify({"error": "Email already taken"}), 400

        # Safe to assign now that uniqueness is confirmed
        user.full_name = data.get("full_name", user.full_name)
        user.username = data.get("username", user.username)
        user.email = data.get("email", user.email)
        user.phone = data.get("phone", user.phone)

        #Actually hash and save the new password — was validated but never applied
        new_password = data.get("new_password")
        current_password = data.get("current_password")

        if new_password:
            if not current_password:
                return jsonify({"error": "Current password required"}), 400
            if not check_password_hash(user.password, current_password):
                return jsonify({"error": "Current password incorrect"}), 401

            user.password = generate_password_hash(new_password)

        db.session.commit()

        return jsonify({
            "message": "Profile updated successfully",
            "user": {
                "id": user.id,
                "full_name": user.full_name,
                "username": user.username,
                "email": user.email,
                "phone": user.phone
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    
        
@user_bp.route("/update_business", methods=["PUT"])
@jwt_required()
def update_business():
    try:
        business = Business.query.get(current_user.business_id)

        if not business:
            return jsonify({"error": "Business not found"}), 404

        data = request.get_json()

        # 🔹 Update fields
        business.name = data.get("name", business.name)
        business.type = data.get("type", business.type)
        business.city = data.get("city", business.city)
        business.address = data.get("address", business.address)
        business.tax = data.get("tax", business.tax)

        db.session.commit()

        return jsonify({
            "message": "Business updated successfully",
            "business": {
                "id": business.id,
                "name": business.name,
                "type": business.type,
                "city": business.city,
                "address": business.address,
                "tax": business.tax
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    
    
@user_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    all_users = Users.query.filter_by(business_id=current_user.business_id).all()
    
    return jsonify(
        {"users": [
            {"id": u.id, "full_name": u.full_name, "username": u.username,
                "email": u.email, "phone": u.phone, "role": u.role, "status": u.status}
            for u in all_users
    ]}),200