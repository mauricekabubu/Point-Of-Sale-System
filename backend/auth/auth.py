from flask import Blueprint,request, jsonify,current_app
from werkzeug.security import check_password_hash, generate_password_hash
from models.model import Users, Cashier, Business,TokenBlockList
from extensions.extension import db
from flask_jwt_extended import jwt_required, get_jwt,create_access_token, create_refresh_token,current_user, get_jwt_identity
import phonenumbers
import os
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from flask_mail import Message
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from dotenv import load_dotenv
load_dotenv()

auth_bp = Blueprint("auth", __name__)


 
@auth_bp.route("/uploads", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["image"]

    # correct validation
    if not file or file.filename == "":
        return jsonify({"error": "File not selected"}), 400

    try:
        extension = os.path.splitext(file.filename)[1].lower()

        if extension not in current_app.config["ALLOWED_EXTENSIONS"]:
            return jsonify({"error": "Invalid image format"}), 400

        filename = secure_filename(file.filename)

        file_path = os.path.join(
            current_app.config["UPLOAD_DIRECTORY"],
            filename
        )

        file.save(file_path)

        image_url = f"/uploads/{filename}"

        return jsonify({
            "message": "File uploaded successfully",
            "image_url": image_url
        }), 200

    except RequestEntityTooLarge:
        return jsonify({"error": "File exceeds 16MB"}), 400
    


@auth_bp.route("/register", methods=["POST"])
def register():
    try:
        data = request.get_json()
        print(f"Incomining data: {data}")

        # User details
        full_name = data.get("full_name")
        username = data.get("username")
        email = data.get("email")
        phone = data.get("phone")
        password = data.get("password")

        # Business details
        name = data.get("business_name")
        business_type = data.get("business_type")
        city = data.get("city")
        address = data.get("address")

        try:
            tax = float(data.get("tax") or 0)
        except ValueError:
            return jsonify({"error": "Tax must be a number"}), 400

        # ── Validate required fields FIRST ──────────────────────────
        if not username or not password:
            return jsonify({"error": "Username and password are required"}), 400

        if not email or "@" not in email:
            return jsonify({"error": "Invalid email format"}), 400

        if not name or not city:
            return jsonify({"error": "Business name and city are required"}), 400

        # ── Validate business type (guard against placeholder) ───────
        valid_types = ["Retail Shop", "Grocery", "Electronics", "Pharmacy", "Supermarket", "Clothing shop"]
        if not business_type or business_type not in valid_types:
            return jsonify({"error": "Please select a valid business type"}), 400

        # ── Password length ──────────────────────────────────────────
        if len(password) < 8:
            return jsonify({"error": "Password must be at least 8 characters"}), 400

        # ── Phone validation ─────────────────────────────────────────
        if phone:
            try:
                parsed = phonenumbers.parse(phone, "KE")
                if not phonenumbers.is_valid_number(parsed):
                    return jsonify({"error": "Invalid phone number format"}), 400
            except phonenumbers.NumberParseException:
                return jsonify({"error": "Invalid phone number format"}), 400

        # ── Duplicate checks AFTER field validation ──────────────────
        if Users.query.filter_by(username=username).first():
            return jsonify({"error": "Username already taken"}), 400

        if Users.query.filter_by(email=email).first():
            return jsonify({"error": "Email already registered"}), 400

        if Business.query.filter_by(name=name).first():
            return jsonify({"error": "A business with that name already exists"}), 400

        # ── Create records ───────────────────────────────────────────
        new_business = Business(
            name=name,
            type=business_type,
            city=city,
            address=address,
            tax=tax
        )
        db.session.add(new_business)
        db.session.flush()

        new_user = Users(
            full_name=full_name,
            username=username,
            email=email,
            phone=phone,
            password=generate_password_hash(password),
            business_id=new_business.id
        )
        db.session.add(new_user)
        db.session.commit()

        return jsonify({
            "message": "Account created successfully",
            "business_id": new_business.id,
            "user":{
                "full_name": new_user.full_name,
                "username": new_user.username,
                "email": new_user.email,
                "phone": new_user.phone
            },
            "business":{
                "name": new_business.name,
                "type": new_business.type,
                "city": new_business.city,
                "address": new_business.address,
                "tax": new_business.tax
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500 
    
#login route
@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    
    username = data.get("username")
    password = data.get("password")
    
    user = Users.query.filter_by(username=username).first()
    
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not check_password_hash(user.password, password):
        return jsonify({"error": "Invalid password"}), 401
    

    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    print(f"Access token: {access_token}\nRefresh token: {refresh_token}")
    #print(f"username: {user.username}, business_id: {user.business_id}, role: {user.role}   ")
    
    return jsonify(
        {
            "message":"Login successful",
            "jwt_tokens":{
                "access_token":access_token,
                "refresh_token":refresh_token
            },
            "user":{
                "id": user.id,
                "full_name": user.full_name,
                "username": user.username,
                "email": user.email,
                "phone": user.phone,
                "business_id": user.business_id,
                "role": user.role
            },
            "business":{
                "id": user.business.id,
                "name": user.business.name,
                "type": user.business.type,
                "city": user.business.city,
                "address": user.business.address,
                "tax": user.business.tax
            }
        }
    ),200
        

#identity of users
@auth_bp.route("/identity", methods=["GET"])
@jwt_required()
def identity():
    
    return jsonify({
        "id": current_user.id,
        "username": current_user.username,
        "business_id": current_user.business_id,
        "role": current_user.role
    }), 200
    
#refresh_access_token
@auth_bp.route("/refresh", methods=["GET"])
@jwt_required(refresh=True)
def refresh_access_token():
    identity = get_jwt_identity()
    
    new_access_token = create_access_token(identity=identity)
    
    return jsonify(
        {
            "new_access_token":new_access_token
        }
    ),200


@auth_bp.route("/cashier/login", methods=["POST"])
def cashier_login():
    data = request.get_json()

    cashier_id = data.get("id")
    pin = data.get("pin")

    if not cashier_id or not pin:
        return jsonify({"error": "cashier id and pin are required"}), 400

    cashier = Users.query.get(cashier_id)

    if not cashier:
        return jsonify({"error": "Cashier not found"}), 404

    if not check_password_hash(cashier.pin, pin):
        return jsonify({"error": "Invalid pin"}), 401

    access_token = create_access_token(identity=str(cashier.id))
    refresh_access_token = create_refresh_token(identity=str(cashier.id))
    
    print("access_token:", access_token)
    print("refresh_token:", refresh_access_token)


    return jsonify({
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_access_token,
        "cashier": {
            "id": cashier.id,
            "full_name": cashier.full_name,
            "username": cashier.username,
            "email": cashier.email,
            "phone": cashier.phone,
            "business_id": cashier.business_id,
            "role": cashier.role
        },
    }), 200

#logout route
@auth_bp.route("/logout",methods=["POST"])
@jwt_required()
def logout():
    jwt = get_jwt()
    
    jti = jwt["jti"]
    
    tokenblocklist = TokenBlockList(jti=jti)
    print(f"Tokenblocklist: {tokenblocklist}")
    db.session.add(tokenblocklist)
    db.session.commit()
    
    return jsonify(
        {
            "message":"logout successfully"
        }
    ),200
    
    
@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    try:
        print("STEP 1")
        data = request.get_json()

        print("STEP 2")
        email = data.get("email")

        print("STEP 3")
        user = Users.query.filter_by(email=email).first()

        print("STEP 4")
        if user:
            token = user.generate_reset_token()

            print("STEP 5")
            reset_link = f"{current_app.config['FRONTEND_URL']}/reset.html?token={token}"

            print("STEP 6")
            try:
                print("Sending via SendGrid...")

                message = Mail(
                    from_email=os.environ["SENDGRID_FROM_EMAIL"],
                    to_emails=user.email,
                    subject="Password Reset — CodexLabs POS",
                    html_content=f'<p>Reset your password using the link below:</p><p><a href="{reset_link}">{reset_link}</a></p>'
                )

                sg = SendGridAPIClient(os.environ["SENDGRID_API_KEY"])
                response = sg.send(message)

                if response.status_code >= 400:
                    print("SendGrid error:", response.status_code, response.body)
                    return jsonify({"error": f"SendGrid error {response.status_code}"}), 500

                print("Email sent, status:", response.status_code)

            except Exception as e:
                print("SENDGRID ERROR:", repr(e))
                return jsonify({"error": str(e)}), 500

            print("STEP 7")
            mail.send(msg)

            print("STEP 8")

        return jsonify({
            "message": "If that email is registered, a reset link has been sent."
        }), 200

    except Exception:
        import traceback
        traceback.print_exc()
        raise
    
    
# Verify token (frontend calls this when user lands on the reset page)
@auth_bp.route("/reset-password/<path:token>", methods=["GET"])
def verify_reset_token(token):
    try:
        user = Users.verify_reset_token(token)
        if not user:
            return jsonify({"error": "Invalid or expired reset link"}), 401
        return jsonify({"message": "Token is valid"}), 200
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


#Submit new password (frontend calls this on form submit)
@auth_bp.route("/reset-password/<path:token>", methods=["POST"])
def reset_password(token):
    try:
        user = Users.verify_reset_token(token)
        if not user:
            return jsonify({"error": "Invalid or expired reset link"}), 401

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Request body must be valid JSON"}), 400

        password = data.get("password")
        confirm  = data.get("confirm_password")

        if not password or not confirm:
            return jsonify({"error": "Both password fields are required"}), 400
        if len(password) < 8:
            return jsonify({"error": "Password must be at least 8 characters"}), 400
        if password != confirm:
            return jsonify({"error": "Passwords do not match"}), 400

        user.password = generate_password_hash(password)
        db.session.commit()

        return jsonify({"message": "Password reset successful. You can now log in."}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    
