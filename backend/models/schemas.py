from marshmallow import Schema, fields, validates, ValidationError
from models.model import Users
from models import db   # your DB instance


class UserSchema(Schema):
    id = fields.Int(dump_only=True)

    username = fields.String(required=True)

    email = fields.Email(
        required=True,
        error_messages={
            "required": "Email is required",
            "invalid": "Invalid email format!"
        }
    )

    #using validate decorater
    @validates("email")
    def validate_email_unique(self, value):
        existing_user = db.session.query(Users).filter_by(email=value).one_or_none()
        if existing_user:
            raise ValidationError("Email already exists!")