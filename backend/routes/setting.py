from flask import jsonify, request, Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.model import db, Business, Users
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy.exc import IntegrityError
import traceback

setting_bp = Blueprint("setting", __name__)


# ─── Profile ────────────────────────────────────────────────────────────────

@setting_bp.route("/profile/<int:user_id>", methods=["PUT"])
@jwt_required()
def update_profile(user_id):
    try:
        current_user_id = get_jwt_identity()

        if str(current_user_id) != str(user_id):            
            return jsonify({"error": "Forbidden"}), 403

        # BUG FIX: .get() returns the object directly — never call .first() on it
        user = db.session.get(Users, user_id)

        if not user:
            return jsonify({"message": "User not found"}), 404

        data = request.get_json()

        user.full_name = data.get("full_name", user.full_name)
        user.username  = data.get("username",  user.username)
        user.email     = data.get("email",     user.email)
        user.phone     = data.get("phone",     user.phone)
        user.location  = data.get("location",  user.location)
        # NOTE: password changes are handled by /change-password below,
        #       so we intentionally exclude it here.

        db.session.commit()

        return jsonify({
            "message": "Profile updated successfully",
            "user": {
                "id":        user.id,
                "full_name": user.full_name,
                "username":  user.username,
                "email":     user.email,
                "phone":     user.phone,
                "location":  user.location,
            }
        }), 200

    except IntegrityError:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "Username or email already in use"}), 409

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "An error occurred", "error": str(e)}), 500


# ─── Change password ─────────────────────────────────────────────────────────
# Matches the "Change Password" modal in settings.html

@setting_bp.route("/profile/<int:user_id>/change-password", methods=["PUT"])
@jwt_required()
def change_password(user_id):
    try:
        current_user_id = get_jwt_identity()

        if str(current_user_id) != str(user_id):
            return jsonify({"error": "Forbidden"}), 403
        
        user = db.session.get(Users, user_id)
        if not user:
            return jsonify({"message": "User not found"}), 404

        data = request.get_json()
        current_password = data.get("current_password", "")
        new_password     = data.get("new_password",     "")
        confirm_password = data.get("confirm_password", "")

        # Verify the current password before allowing a change
        if not check_password_hash(user.password, current_password):
            return jsonify({"message": "Current password is incorrect"}), 401

        if new_password != confirm_password:
            return jsonify({"message": "New passwords do not match"}), 400

        if len(new_password) < 8:
            return jsonify({"message": "Password must be at least 8 characters"}), 400

        # BUG FIX: always hash passwords — never store plain text
        user.password = generate_password_hash(new_password)
        db.session.commit()

        return jsonify({"message": "Password updated successfully"}), 200

    except Exception as e:
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"message": "An error occurred", "error": str(e)}), 500


# ─── Business ────────────────────────────────────────────────────────────────

@setting_bp.route("/business/<int:business_id>", methods=["PUT"])
@jwt_required()
def update_business(business_id):
    try:
        current_user_id = get_jwt_identity()

        user = db.session.get(Users, int(current_user_id))
        if not user:
            return jsonify({"message": "User not found"}), 404

        business = db.session.get(Business, business_id)
        if not business:
            return jsonify({"message": "Business not found"}), 404

        # FIX: ownership lives on Users.business_id, not Business.user_id
        if str(user.business_id) != str(business_id):
            return jsonify({"message": "Unauthorized"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"message": "No data provided"}), 400

        business.name    = data.get("name",    business.name)
        business.type    = data.get("type",    business.type)
        business.city    = data.get("city",    business.city)
        business.address = data.get("address", business.address)
        business.tax     = data.get("tax",     business.tax)

        db.session.commit()

        return jsonify({
            "message": "Business updated successfully",
            "business": {
                "id":      business.id,
                "name":    business.name,
                "type":    business.type,
                "city":    business.city,
                "address": business.address,
                "tax":     business.tax,
            }
        }), 200

    except Exception as e:
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"message": "An error occurred", "error": str(e)}), 500


    
@setting_bp.route("/profile/<int:user_id>", methods=["GET"])
@jwt_required()
def get_profile(user_id):
    current_user_id = get_jwt_identity()
    if str(current_user_id) != str(user_id):
        return jsonify({"error": "Forbidden"}), 403

    user = db.session.get(Users, user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404

    return jsonify({
        "user": {
            "id": user.id, "full_name": user.full_name, "username": user.username,
            "email": user.email, "phone": user.phone, "location": user.location,
        }
    }), 200


@setting_bp.route("/business/<int:business_id>", methods=["GET"])
@jwt_required()
def get_business(business_id):
    current_user_id = get_jwt_identity()

    user = db.session.get(Users, int(current_user_id))
    if not user:
        return jsonify({"message": "User not found"}), 404

    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({"message": "Business not found"}), 404

    # FIX: same correction here
    if str(user.business_id) != str(business_id):
        return jsonify({"message": "Unauthorized"}), 403

    return jsonify({
        "business": {
            "id": business.id, "name": business.name, "type": business.type,
            "city": business.city, "address": business.address, "tax": business.tax,
        }
    }), 200