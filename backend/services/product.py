from flask import Blueprint, jsonify, request
from models.model import Products
from flask_jwt_extended import current_user, jwt_required
from extensions.extension import db
from sqlalchemy import or_

product_bp = Blueprint("product", __name__)


@product_bp.route("/add_products", methods=["POST"])
@jwt_required()
def add_products():
    data = request.get_json()

    name = data.get("name")
    sku = data.get("sku")
    category = data.get("category")
    price = data.get("price")
    cost_price = data.get("cost_price", 0.0)  
    quantity = data.get("quantity")
    image_url = data.get("image_url")

    if not name or not sku or not category:
        return jsonify({"error": "Name, sku and category are required"}), 400

    if price is None:
        return jsonify({"error": "Price is required"}), 400

    try:
        price = float(price)
        cost_price = float(cost_price)
        quantity = int(quantity) if quantity is not None else 0
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid price, cost_price or quantity"}), 400

    if price < 0 or cost_price < 0 or quantity < 0:
        return jsonify({"error": "Price, cost_price and quantity must be positive"}), 400

    # scope SKU check to current business only
    if Products.query.filter_by(sku=sku, business_id=current_user.business_id).first():
        return jsonify({"error": "SKU already exists"}), 400

    product = Products(
        name=name,
        sku=sku,
        category=category,
        price=price,
        cost_price=cost_price,
        quantity=quantity,
        image_url=image_url,
        business_id=current_user.business_id
    )

    try:
        db.session.add(product)
        db.session.commit()

        return jsonify({
            "message": "Product added successfully",
            "product_id": product.id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@product_bp.route("/update_product/<int:product_id>", methods=["PUT"])
@jwt_required()
def update_product(product_id):
    data = request.get_json()

    product = Products.query.filter_by(
        id=product_id,
        business_id=current_user.business_id
    ).first()

    if not product:
        return jsonify({"error": "Product not found"}), 404

    
    new_sku = data.get("sku")
    if new_sku and new_sku != product.sku:
        existing = Products.query.filter(
            Products.sku == new_sku,
            Products.id != product_id,
            Products.business_id == current_user.business_id
        ).first()

        if existing:
            return jsonify({"error": "SKU already exists"}), 400

    product.name = data.get("name", product.name)
    product.sku = data.get("sku", product.sku)
    product.category = data.get("category", product.category)
    product.price = data.get("price", product.price)
    product.cost_price = data.get("cost_price", product.cost_price)
    product.quantity = data.get("quantity", product.quantity)
    product.image_url = data.get("image_url", product.image_url)
    product.low_stock_threshold = data.get("low_stock_threshold", product.low_stock_threshold)

    try:
        db.session.commit()
        return jsonify({
            "message": "Product updated successfully",
            "product": {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "price": product.price,
                "cost_price": product.cost_price,
                "quantity": product.quantity,
                "category": product.category
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@product_bp.route("/delete/<int:product_id>", methods=["DELETE"])
@jwt_required()
def delete_product(product_id):
    product = Products.query.filter_by(
        id=product_id,
        business_id=current_user.business_id
    ).first()

    if not product:
        return jsonify({"error": "Product not found"}), 404
    
    if product.sale_items:
        return jsonify({"error": "Cannot delete product with associated sales"}), 400

    try:
        db.session.delete(product)
        db.session.commit()
        return jsonify({"message": "Product deleted successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@product_bp.route("/products", methods=["GET"])
@jwt_required()
def get_products():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    search = request.args.get("search", "", type=str)
    category = request.args.get("category", "", type=str)
    low_stock = request.args.get("low_stock", "false").lower() == "true"

    sort = request.args.get("sort", "created_at", type=str)
    order = request.args.get("order", "desc", type=str)

    query = Products.query.filter_by(
        business_id=current_user.business_id
    )

    # Search by name or SKU
    if search:
        query = query.filter(
            or_(
                Products.name.ilike(f"%{search}%"),
                Products.sku.ilike(f"%{search}%")
            )
        )

    # Filter by category
    if category:
        query = query.filter(Products.category == category)

    # Low stock filter
    if low_stock:
        query = query.filter(
            Products.quantity <= Products.low_stock_threshold
        )

    # Allowed sorting fields
    sortable_columns = {
        "name": Products.name,
        "price": Products.price,
        "quantity": Products.quantity,
        "category": Products.category,
        "created_at": Products.created_at
    }

    sort_column = sortable_columns.get(sort, Products.created_at)

    if order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    pagination = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    return jsonify({
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "sku": p.sku,
                "category": p.category,
                "price": p.price,
                "cost_price": p.cost_price,
                "quantity": p.quantity,
                "low_stock_threshold": p.low_stock_threshold,
                "image_url": p.image_url
            }
            for p in pagination.items
        ],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total_items": pagination.total,
            "total_pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev
        }
    }), 200


@product_bp.route("/products/<int:product_id>", methods=["GET"])
@jwt_required()
def get_single_product(product_id):
    product = Products.query.filter_by(
        id=product_id,
        business_id=current_user.business_id
    ).first()

    if not product:
        return jsonify({"error": "Product not found"}), 404

    return jsonify({
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "category": product.category,
        "price": product.price,
        "cost_price": product.cost_price,
        "quantity": product.quantity,
        "low_stock_threshold": product.low_stock_threshold,
        "image_url": product.image_url,
        "created_at": product.created_at
    }), 200