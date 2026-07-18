from email.policy import default

from extensions.extension import db
from datetime import timezone, datetime
from itsdangerous import URLSafeTimedSerializer
from flask import current_app
import string
import secrets
from zoneinfo import ZoneInfo
from sqlalchemy.dialects.mysql import LONGTEXT

KENYA_TZ = ZoneInfo("Africa/Nairobi")

def kenya_now():
    return datetime.now(KENYA_TZ)


# Generate a unique payment reference for each sale
def generate_payment_reference():
    alphabet = string.ascii_uppercase + string.digits
    
    while True:
        ref = "HS-" + ''.join(secrets.choice(alphabet) for _ in range(10))
        # Check if this reference already exists in the database
        existing = Sales.query.filter_by(payment_reference=ref).first()
        if not existing:
            return ref
        

class Users(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(100), nullable=False, unique=True, index=True)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(20), nullable=False)
    location = db.Column(db.String(100), nullable=True)

    password = db.Column(db.String(255), nullable=True)  # admin login
    pin = db.Column(db.String(255), nullable=True)       # cashier login

    role = db.Column(db.String(100), default="admin", nullable=False, index=True)

    status = db.Column(db.String(20), default="active")

    last_login = db.Column(db.DateTime, nullable=True, default = kenya_now, index=True)

    business_id = db.Column(db.Integer, db.ForeignKey("business.id"), nullable=False, index=True)

    sales = db.relationship("Sales", backref="user", lazy=True)
    transaction_logs = db.relationship("TransactionLog", backref="user", lazy=True)
    
    
    def generate_reset_token(self, expires_sec=1800):
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        return s.dumps(self.id, salt="password-reset")  

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            user_id = s.loads(token, salt="password-reset", max_age=expires_sec)
        except Exception as e:
            return None  # ← return None, not a jsonify response (let the route handle errors)
        return Users.query.get(user_id)
            
    def __repr__(self):
        return f"user_{self.username}_{self.email}"
    


class Business(db.Model):
    __tablename__ = "business"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    type = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(100), nullable=False)
    tax = db.Column(db.Float, nullable=True, default=0.0)
    users = db.relationship("Users", backref="business", lazy=True)
    cashiers = db.relationship("Cashier", backref="business", lazy=True)
    products = db.relationship("Products", backref="business", lazy=True)
    sales = db.relationship("Sales", backref="business", lazy=True)
    transaction_logs = db.relationship("TransactionLog", backref="business", lazy=True)
    stock_alerts = db.relationship("StockAlert", backref="business", lazy=True)
    stock_movements = db.relationship("StockMovement", backref="business", lazy=True)
    suppliers = db.relationship("Supplier", backref="business", lazy=True)    
    purchases = db.relationship("Purchase", backref="business", lazy=True)       
    customers = db.relationship("Customer",backref="business", lazy=True)

    def __repr__(self):
        return f"business_{self.name}_{self.address}"


class Cashier(db.Model):
    __tablename__ = "cashier"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    pin = db.Column(db.String(200), nullable=False, unique=True)
    role = db.Column(db.String(100), default="cashier", nullable=False, index=True)
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("business.id", name="fk_cashier_business_id"),
        nullable=False, index=True
    )

    def __repr__(self):
        return f"cashier_{self.name}_{self.email}"


class TokenBlockList(db.Model):
    __tablename__ = "token_blocklist"

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(200), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)

    def __repr__(self):
        return f"<Token {self.jti}>"


class Products(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    sku = db.Column(db.String(200), nullable=False, unique=True,index=True)
    category = db.Column(db.String(100), nullable=True, index=True)
    price = db.Column(db.Float, nullable=False)
    cost_price = db.Column(db.Float, nullable=False, default=0.0)
    quantity = db.Column(db.Integer, default=0)
    low_stock_threshold = db.Column(db.Integer, default=5)
    image_url = db.Column(LONGTEXT)
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("business.id", name="fk_products_business_id"),
        nullable=False, index=True
    )
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)
    sale_items = db.relationship("SaleItems", backref="product", lazy=True)          # was sales_items
    returns = db.relationship("SaleReturn", backref="product", lazy=True)
    stock_alerts = db.relationship("StockAlert", backref="product", lazy=True)
    stock_movements = db.relationship("StockMovement", backref="product", lazy=True)
    purchase_items = db.relationship("PurchaseItem", backref="product", lazy=True)   # was purchaseitem
    last_modified = db.Column(
    db.DateTime,
        default=kenya_now,
        onupdate=kenya_now,
        index=True
    )

    synced = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        index=True
    )
    
    def __repr__(self):
        return f"product_{self.name}_{self.sku}"


class Sales(db.Model):
    __tablename__ = "sales"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=True,
        name="fk_sales_customer_id"
    )
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("business.id", name="fk_sales_business_id"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_sales_user_id"),
        nullable=False,
        index=True
    )

    total_amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(100), nullable=False, index=True)
    status = db.Column(db.String(50), default="pending", nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: kenya_now(), index=True)
    updated_at = db.Column(
        db.DateTime,
        default=kenya_now,
        onupdate=kenya_now, index=True
    )
    sale_items = db.relationship("SaleItems", backref="sale", lazy=True)             
    returns = db.relationship("SaleReturn", backref="sale", lazy=True)
    transaction_logs = db.relationship("TransactionLog", backref="sale", lazy=True)
    mpesa_transactions = db.relationship("MpesaTranscation", backref="sale", lazy=True)
    payment_reference = db.Column(
        db.String(20),
        unique=True,
        nullable=False,
        default=generate_payment_reference
    )
    
    __table_args__ = (
        db.Index(
            "idx_sales_business_user",
            "business_id",
            "user_id"
        ),
        db.Index(
            "idx_sales_business_status_created",
            "business_id",
            "status",
            "created_at"
        ),
    )
    synced = db.Column(db.Boolean,default=False,
        nullable=False,
        index=True
        )

    sync_attempts = db.Column(
        db.Integer,
        default=0
    )


class SaleItems(db.Model):
    __tablename__ = "saleitems"

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(
        db.Integer,
        db.ForeignKey("sales.id", name="fk_saleitems_sale_id"),
        nullable=False,
        index=True
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", name="fk_saleitems_product_id"),
        nullable=False,
        index=True
    )
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Float, nullable=False)
    cost_price = db.Column(db.Float, nullable=False, default=0.0)
    subtotal = db.Column(db.Float, nullable=False, default=0.0)


class TransactionLog(db.Model):
    __tablename__ = "transactionlog"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_transactionlog_user_id"),
        nullable=False, index=True
    )
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("business.id", name="fk_transactionlog_business_id"),
        nullable=False, index=True
    )
    sale_id = db.Column(
        db.Integer,
        db.ForeignKey("sales.id", name="fk_transactionlog_sale_id"),
        nullable=True, index=True
    )
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)


class SaleReturn(db.Model):
    __tablename__ = "salereturn"

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(
        db.Integer,
        db.ForeignKey("sales.id", name="fk_salereturn_sale_id"),
        nullable=False, index=True
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", name="fk_salereturn_product_id"),
        nullable=False, index=True
    )
    quantity = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    refunded_amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)


class StockAlert(db.Model):
    __tablename__ = "stockalert"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", name="fk_stockalert_product_id"),
        nullable=False, index=True
    )
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("business.id", name="fk_stockalert_business_id"),
        nullable=False, index=True
    )
    message = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)


class StockMovement(db.Model):
    __tablename__ = "stockmovement"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", name="fk_stockmovement_product_id"),
        nullable=False, index=True
    )
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("business.id", name="fk_stockmovement_business_id"),
        nullable=False, index=True
    )
    quantity = db.Column(db.Integer, nullable=False)
    movement_type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)
    synced = db.Column(
            db.Boolean,
            default=False
        )


class Supplier(db.Model):
    __tablename__ = "supplier"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100), nullable=True)
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("business.id", name="fk_supplier_business_id"),
        nullable=False, index=True
    )
    status = db.Column(db.String(20), default="active",nullable=False)
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)
    purchases = db.relationship("Purchase", backref="supplier", lazy=True)           # was purchase


class Purchase(db.Model):
    __tablename__ = "purchase"

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier.id", name="fk_purchase_supplier_id"),
        nullable=False, index=True
    )
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("business.id", name="fk_purchase_business_id"),
        nullable=False, index=True
    )
    total_amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)
    purchase_items = db.relationship("PurchaseItem", backref="purchase", lazy=True)  # ✅ was purchaseitem


class PurchaseItem(db.Model):
    __tablename__ = "purchaseitem"

    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(
        db.Integer,
        db.ForeignKey("purchase.id", name="fk_purchaseitem_purchase_id"),
        nullable=False, index=True
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", name="fk_purchaseitem_product_id"),
        nullable=False, index=True
    )
    quantity = db.Column(db.Integer, nullable=False)
    cost_price = db.Column(db.Float, nullable=False, default=0.0)
    subtotal = db.Column(db.Float, nullable=False)
    
class Customer(db.Model):
    __tablename__="customer"
    id = db.Column(db.Integer, primary_key=True)    
    sales = db.relationship("Sales", backref="customer", lazy=True)
    full_name = db.Column(db.String(100),nullable=False)
    phone = db.Column(db.String(20), nullable=False, unique=True)
    email = db.Column(db.String(100), nullable=True)
    
    business_id = db.Column(db.Integer, db.ForeignKey("business.id"),nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=kenya_now, index=True)
    

class MpesaTranscation(db.Model):
    __tablename__ = "mpesa_transaction"

    id = db.Column(db.Integer, primary_key=True)

    sale_id = db.Column(
        db.Integer, db.ForeignKey("sales.id"), nullable=True, index=True   # ← was nullable=False
    )

    # STK-only fields — null for C2B
    checkout_request_id = db.Column(db.String(100), nullable=True, unique=True, index=True)   # ← was nullable=False
    merchant_request_id = db.Column(db.String(100), nullable=True, unique=True, index=True)   # ← was nullable=False

    mpesa_receipt_number = db.Column(db.String(100), nullable=True, unique=True, index=True)
    phone_number         = db.Column(db.String(400),  nullable=False, index=True)
    amount               = db.Column(db.Float,       nullable=False, index=True)
    transaction_date     = db.Column(db.DateTime,    nullable=True, index=True, default=kenya_now)  # ← was nullable=False
    response_code        = db.Column(db.String(20), index=True)
    response_description = db.Column(db.String(255), index=True)
    business_short_code  = db.Column(db.String(20), index=True)
    status               = db.Column(db.String(50),  nullable=True, default="Pending",index=True)
    transaction_type     = db.Column(db.String(20),  nullable=True, default="STK", index=True)  # ← new

    created_at = db.Column(db.DateTime, default=kenya_now, index=True)
    
class ReceiptQueue(db.Model):
    __tablename__ = "receipt_queue"
 
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=False) 
    channel = db.Column(
        db.Enum("email", "whatsapp", name="receipt_channel"),
        nullable=False,
    )
    recipient = db.Column(db.String(255), nullable=False)
    payload = db.Column(db.Text, nullable=True)  # JSON-encoded receipt data
 
    status = db.Column(
        db.Enum("pending", "sent", "failed", name="receipt_queue_status"),
        default="pending",
        nullable=False,
    )
    retry_count = db.Column(db.Integer, default=0, nullable=False)
 
    created_at = db.Column(db.DateTime, default=kenya_now)
 
    sale = db.relationship("Sales", backref="queued_receipts")
    last_attempt = db.Column(db.DateTime, default=kenya_now)
 
    def to_dict(self):
        return {
            "id": self.id,
            "sale_id": self.sale_id,
            "channel": self.channel,
            "recipient": self.recipient,
            "status": self.status,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }