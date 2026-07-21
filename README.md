# CodexLabs POS

> A modern, Dockerized Point of Sale (POS) system built for retail businesses, supermarkets, pharmacies, cafés, and small-to-medium enterprises. Designed with an offline-first architecture, secure authentication, inventory management, sales tracking, reporting, and receipt generation.

---

## Overview

**CodexLabs POS** is a full-stack Point of Sale solution developed to simplify day-to-day retail operations while remaining reliable in environments with unstable internet connectivity.

The application provides a modern user interface, secure backend services, business analytics, inventory management, cashier management, and multiple payment options, making it suitable for both single-store and multi-user businesses.

---

## Features

### Sales Management

* Fast product search
* Barcode scanning
* Shopping cart management
* Multiple payment methods
* Automatic tax calculations
* Digital and printable receipts
* Transaction history
* Sales cancellation (permissions-based)

### Inventory Management

* Product catalog
* Category management
* Stock level tracking
* Low stock alerts
* SKU management
* Cost and selling price management
* Supplier information

### User Management

* Secure authentication
* Administrator accounts
* Cashier accounts
* PIN-based cashier login
* Role-based authorization
* User status management

### Business Management

* Business profile configuration
* Custom tax settings
* Currency configuration
* Receipt customization
* Business information management

### Reports & Analytics

* Daily sales summary
* Weekly trends
* Monthly reports
* Revenue analytics
* Profit tracking
* Product performance
* Transaction reports

### Payment Support

* Cash
* Mobile Money (M-Pesa Ready)
* Card Payments (Extensible)

### Offline-First Support

* Continue operating during internet outages
* Automatic synchronization when connectivity returns
* Offline transaction queue
* Network status monitoring

### Receipt Management

* Printable receipts
* Email receipts
* WhatsApp receipt sharing
* PDF-ready receipt templates

### Security

* Password hashing
* JWT authentication
* Protected REST APIs
* Role-based access control
* Secure environment variable configuration

---

# Technology Stack

## Backend

* Python
* Flask
* SQLAlchemy
* Flask-JWT-Extended
* Flask-Migrate
* Flask-Mail
* Marshmallow
* Gunicorn

## Frontend

* HTML5
* CSS3
* JavaScript (ES6)
* Bootstrap

## Database

* MySQL 8

## Infrastructure

* Docker
* Docker Compose
* Nginx

---

# Project Structure

```text
CodexLabs-POS/
│
├── backend/
│   ├── app/
│   ├── migrations/
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── assets/
│   ├── css/
│   ├── js/
│   ├── nginx/
│   └── Dockerfile
│
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

# Getting Started

## Clone the Repository

```bash
git clone https://github.com/yourusername/CodexLabs-POS.git
cd CodexLabs-POS
```

---

## Configure Environment Variables

Create a local `.env` file from the provided example.

```bash
cp .env.example .env
```

Update all required environment variables before running the application.

---

## Run with Docker

Build and start all services.

```bash
docker compose up --build
```

Run in detached mode.

```bash
docker compose up -d
```

Stop the application.

```bash
docker compose down
```

---

# Environment Variables

Example configuration:

```env
# ==========================
# Flask
# ==========================
SECRET_KEY=your-secret-key
JWT_SECRET_KEY=your-jwt-secret-key

# ==========================
# Database
# ==========================
MYSQL_ROOT_PASSWORD=your-root-password
MYSQL_DATABASE=pos_db
MYSQL_USER=your-db-user
MYSQL_PASSWORD=your-db-password

DB_HOST=db
DB_PORT=3306

# SQLAlchemy (optional)
DATABASE_URL=mysql+pymysql://your-db-user:your-db-password@db:3306/pos_db

# ==========================
# SendGrid
# ==========================
SENDGRID_API_KEY=your-sendgrid-api-key
SENDGRID_SENDER=you@example.com

# ==========================
# Email (SMTP)
# ==========================
DEL_EMAIL=you@example.com
PASSWORD=your-email-app-password

# ==========================
# Frontend
# ==========================
FRONTEND_URL=http://localhost:5500

# ==========================
# Safaricom Daraja
# ==========================
CONSUMER_KEY=your-consumer-key
CONSUMER_SECRET=your-consumer-secret

SHORT_CODE=174379
PASSKEY=your-passkey

PARTY_A=174379
PARTY_B=174379

INITIATOR_NAME=your-initiator-name
INITIATOR_PASSWORD=your-initiator-password

PHONE_NUMBER=254700000000

CALLBACK_URL=https://your-domain.com/services/payments/api/pay/callback
C2B_CONFIRMATION_URL=https://your-domain.com/services/payments/api/pay/c2b/confirm
C2B_VALIDATION_URL=https://your-domain.com/services/payments/api/pay/c2b/validate

C2B_SHORT_CODE=600992

NGROK_AUTH_TOKEN=your-ngrok-token

# ==========================
# Safaricom Endpoints
# ==========================
C2B_SAFARICOM_SANDBOX_URL=https://sandbox.safaricom.co.ke/mpesa/c2b/v1/registerurl
SAFARICOM_SANDBOX_TOKEN_URL=https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials
SAFARICOM_SANDBOX_STK_PUSH_URL=https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest
MYSQL_ROOT_PASSWORD=your_root_password
MYSQL_DATABASE=database_name
MYSQL_USER=Your_username
MYSQL_PASSWORD=Your_Mysql_password
DB_HOST=host_name
DB_PORT=3306
DB_USER=user
DB_PASSWORD=password
DB_NAME=database_name
```

---

# Docker Services

The project is composed of multiple containers.

* Frontend (Nginx)
* Backend (Flask + Gunicorn)
* MySQL Database

All services communicate over an isolated Docker network using Docker Compose.

---

# API

The backend exposes RESTful APIs for:

* Authentication
* Users
* Cashiers
* Products
* Inventory
* Categories
* Sales
* Reports
* Receipts
* Payments
* Synchronization

---

# Deployment

CodexLabs POS is designed for containerized deployments and can be deployed to cloud platforms that support Docker.

Examples include:

* Railway
* Render
* DigitalOcean
* Azure Container Apps
* AWS ECS
* Google Cloud Run

---

# Future Roadmap

* Multi-branch support
* Customer loyalty program
* Expense management
* Purchase orders
* Supplier portal
* Advanced analytics dashboard
* AI-powered sales insights
* Mobile companion application
* Multi-language support
* Multi-currency support

---

# Contributing

Contributions, feature requests, and bug reports are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Commit your changes.
4. Open a Pull Request.

---

# License

This project is proprietary software developed by **CodexLabs**.

All rights reserved.

Unauthorized copying, modification, distribution, or commercial use without written permission is prohibited.

---

# Author

**CodexLabs**

Building reliable software solutions for modern businesses.

---

If you find this project useful, consider giving the repository a ⭐.
