from flask import request, jsonify, Blueprint, send_file, Response
from datetime import datetime, timedelta, timezone
from flask_jwt_extended import jwt_required, current_user
from sqlalchemy import func
from models.model import SaleItems, Sales, Products, TransactionLog, Business, Users, SaleReturn
from extensions.extension import db
import pandas as pd
import io
from reportlab.platypus import SimpleDocTemplate, Table


report_bp = Blueprint("report", __name__)

#Business sales data retrieval function
def get_sales_data(business_id, start_date=None, end_date=None):
    period = request.args.get("period")
    now = datetime.utcnow()

    if period == "daily":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start_date = now - timedelta(days=7)
    elif period == "monthly":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start_date = None

    query = db.session.query(
        Sales.id, Sales.total_amount, Sales.payment_method,
        Sales.created_at, Users.full_name
    ).join(Users).filter(Sales.business_id == business_id)

    if start_date:
        query = query.filter(Sales.created_at >= start_date)
    if end_date:
        query = query.filter(Sales.created_at <= end_date)

    return query.all()


def refund_data(business_id):
    return db.session.query(
        SaleReturn.sale_id,
        SaleReturn.product_id,
        SaleReturn.quantity,
        SaleReturn.refunded_amount,
        SaleReturn.created_at
    ).join(Sales).filter(Sales.business_id == business_id).all()


# ── Sales Exports ─────────────────

@report_bp.route("/report_csv", methods=["GET"])         
@jwt_required()
def sales_csv():                                          
    business_id = current_user.business_id
    data = get_sales_data(business_id)

    df = pd.DataFrame(data, columns=["Sale ID", "Total", "Payment", "Date", "Seller"])

    output = io.StringIO()
    df.to_csv(output, index=False)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=sales.csv"}
    )


@report_bp.route("/report_excel", methods=["GET"])      
@jwt_required()
def sales_excel():                                         
    business_id = current_user.business_id
    data = get_sales_data(business_id)

    df = pd.DataFrame(data, columns=["Sale ID", "Total", "Payment", "Date", "Seller"])

    output = io.BytesIO()                                 
    df.to_excel(output, index=False, engine="openpyxl")
    output.seek(0)

    return send_file(output, download_name="sales.xlsx", as_attachment=True)


@report_bp.route("/report_pdf", methods=["GET"])       
@jwt_required()
def sales_pdf():                                         
    business_id = current_user.business_id
    data = get_sales_data(business_id)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)

    table_data = [["Sale ID", "Total", "Payment", "Date", "Seller"]]
    for row in data:
        table_data.append([row[0], row[1], row[2], str(row[3]), row[4]])

    doc.build([Table(table_data)])
    buffer.seek(0)

    return send_file(buffer, download_name="sales.pdf", as_attachment=True)


# ── Refund Exports ───────────────────────────────────────────────────────────

@report_bp.route("/refund_csv", methods=["GET"])      
@jwt_required()
def refund_csv():                                     
    business_id = current_user.business_id
    data = refund_data(business_id)

    df = pd.DataFrame(data, columns=[                     
        "Sale ID", "Product ID", "Quantity", "Refunded Amount", "Date"
    ])

    output = io.StringIO()
    df.to_csv(output, index=False)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=refunded.csv"}
    )


@report_bp.route("/refund_excel", methods=["GET"]) 
@jwt_required()
def refund_excel():                                   
    business_id = current_user.business_id
    data = refund_data(business_id)

    df = pd.DataFrame(data, columns=[                  
        "Sale ID", "Product ID", "Quantity", "Refunded Amount", "Date"
    ])

    output = io.BytesIO()                            
    df.to_excel(output, index=False, engine="openpyxl")
    output.seek(0)

    return send_file(output, download_name="refunded.xlsx", as_attachment=True)


@report_bp.route("/refund_pdf", methods=["GET"])         
@jwt_required()
def refund_pdf():                                       
    business_id = current_user.business_id
    data = refund_data(business_id)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)

    table_data = [["Sale ID", "Product ID", "Quantity", "Refunded Amount", "Date"]]
    for row in data:
        table_data.append([row[0], row[1], row[2], row[3], str(row[4])])  

    doc.build([Table(table_data)])
    buffer.seek(0)

    return send_file(buffer, download_name="refunded.pdf", as_attachment=True)