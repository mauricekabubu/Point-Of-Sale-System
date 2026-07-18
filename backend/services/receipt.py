from flask import Blueprint, jsonify, request
from models.model import Sales
from utils.mailer import send_receipt_email
from flask_jwt_extended import jwt_required, current_user

receipt_bp = Blueprint('receipts', __name__)

# api endpoint to send receipt email
@receipt_bp.route('/sendemail_receipt', methods=['POST'])
@jwt_required()
def email_receipt():
    data = request.get_json()
    
    sale_id = data.get('sale_id')
    email = data.get('email')
    receipt_html = data.get('receipt_html')
    
    if not sale_id:
        return jsonify({"message": "Sale ID is required"}), 400
    
    if not email:
        return jsonify({"message": "Email is required"}), 400
    
    if not receipt_html:
        return jsonify({"message": "Receipt HTML content is required"}), 400
    
    sale = Sales.query.filter_by(
        id=sale_id, business_id=current_user.business_id).first()
    
    if not sale:
        return jsonify({"success": False, "message": "Sale not found"}), 404
    
    success, message = send_receipt_email(
        to_email = email,
        subject = f"Receipt for Sale ID: {sale_id}",
        html_content = receipt_html
    )
    
    if success:
        return jsonify({"success": True, "message": message}), 200
    
    else:
        return jsonify({"success": False, "message": message}), 500
    
    
    
    
    
    
    