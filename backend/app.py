from flask import Flask, jsonify, request
from extensions.extension import jwt, db, migrate, mail
import os
from datetime import timedelta
from dotenv import load_dotenv
from auth.auth import auth_bp
from models.model import Users, TokenBlockList
from flask_cors import CORS
from services.product import product_bp
from services.sales import sale_bp
from services.reports import report_bp
from services.supplier import supplier_bp
from services.payments import pay_bp
from services.receipt import receipt_bp
from services.sync_service import sync_bp, start_sync_service
from services.network_status import start_network_monitor
from routes.users import user_bp
from routes.customers import customer_bp
from routes.setting import setting_bp

load_dotenv()

app = Flask(__name__)

#Cross Origin Resource Sharing
CORS(
    app,
    resources={
        r"/*": {
            "origins": [
                "https://codexlabspos.netlify.app",
                "http://localhost:5500",
                "http://127.0.0.1:5500"
            ]
        }
    },
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)

# Core configigurations
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")

database_url = os.getenv("DATABASE_URL")

if database_url:
    database_url = database_url.strip()
    database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)

print(f"DATABASE CONNECTING TO: {database_url}")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["FRONTEND_URL"] = os.getenv("FRONTEND_URL")
app.config["FRONTEND_URL"] = os.getenv("FRONTEND_URL")

# JWT config — explicitly header-based, no CSRF
app.config["JWT_TOKEN_LOCATION"] = ["headers"]
app.config["JWT_HEADER_NAME"] = "Authorization"
app.config["JWT_HEADER_TYPE"] = "Bearer"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)

#Mail configuration for sending emails
# ================= MAIL CONFIG =================
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USE_SSL"] = False
app.config["MAIL_USERNAME"] = os.getenv("DEL_EMAIL")
app.config["MAIL_PASSWORD"] = os.getenv("PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("SENDGRID_SENDER")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("DEL_EMAIL")


print("MAIL_USERNAME:", current_app.config["MAIL_USERNAME"])
print("MAIL_SERVER:", current_app.config["MAIL_SERVER"])
print("MAIL_PORT:", current_app.config["MAIL_PORT"])
print("MAIL_USE_TLS:", current_app.config["MAIL_USE_TLS"])
print("MAIL_PASSWORD SET:", bool(current_app.config["MAIL_PASSWORD"]))

# Image upload config 
# image beyond 16MB RAM should not be allowed
app.config["MAX_CONTENT_LENGTH"] = 16*1024*1024 
app.config["ALLOWED_EXTENSIONS"] = [".jpg", ".webp", ".png", ".jfif", ".jpeg", ".gif"]
app.config["UPLOAD_DIRECTORY"] = os.path.join("static", "uploads")

print("DATABASE CONNECTING TO:", app.config["SQLALCHEMY_DATABASE_URI"])

# Initialisations 
db.init_app(app)
jwt.init_app(app)
mail.init_app(app)
migrate.init_app(app, db)

with app.app_context():    
    print(">>> Creating tables...")
    db.create_all()
    print(">>> Tables created.")

start_network_monitor()
start_sync_service(app)

# Blueprint registrations
app.register_blueprint(auth_bp, url_prefix="/auth/auth")
app.register_blueprint(product_bp, url_prefix="/services/product")
app.register_blueprint(sale_bp, url_prefix="/services/sales")
app.register_blueprint(report_bp, url_prefix="/services/report")
app.register_blueprint(supplier_bp, url_prefix="/services/supplier")
app.register_blueprint(user_bp, url_prefix="/users")
app.register_blueprint(customer_bp, url_prefix="/routes/customers")
app.register_blueprint(pay_bp, url_prefix="/services/payments")
app.register_blueprint(setting_bp, url_prefix="/routes/setting")
app.register_blueprint(receipt_bp, url_prefix="/services/receipts")
app.register_blueprint(sync_bp, url_prefix="/services/sync")

@app.route("/health")
def health():
    return {"status": "ok"}, 200

@app.before_request
def log_request():
    print(f">>> AUTH HEADER: {request.headers.get('Authorization')}")


@jwt.user_lookup_loader
def user_lookup_callback(jwt_headers, jwt_data):
    identity = jwt_data["sub"]  # now a plain string e.g. "2"
    print(f">>> LOOKUP CALLED: {identity}")
    return Users.query.filter_by(id=int(identity)).one_or_none()


@jwt.token_in_blocklist_loader
def token_in_blocklist_callback(jwt_header, jwt_data):
    print(">>> BLOCKLIST ENTERED")
    jti = jwt_data["jti"]
    try:
        token = db.session.query(TokenBlockList).filter(
            TokenBlockList.jti == jti
        ).scalar()
        print(f">>> BLOCKED: {token is not None}")
        return token is not None
    except Exception as e:
        print(f">>> BLOCKLIST ERROR: {e}")
        db.session.rollback()
        return False


@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_data):
    print(">>> TOKEN EXPIRED")
    return jsonify({"message": "Token has expired", "error": "expired_token"}), 401


@jwt.invalid_token_loader
def invalid_token_callback(error):
    print(f">>> INVALID TOKEN: {error}")
    return jsonify({"message": "Invalid token", "error": str(error)}), 401


@jwt.unauthorized_loader
def missing_token_callback(error):
    print(f">>> UNAUTHORIZED: {error}")
    return jsonify({"message": "No valid token", "error": str(error)}), 401


@jwt.revoked_token_loader
def revoked_token_callback(jwt_header, jwt_data):
    print(">>> TOKEN REVOKED")
    return jsonify({"message": "Token has been revoked"}), 401


if __name__ == "__main__":    
    app.run(host="0.0.0.0", port=5000, debug=True)
