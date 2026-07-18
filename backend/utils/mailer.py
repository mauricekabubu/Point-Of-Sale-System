from flask_mail import Message
from extensions.extension import mail
import traceback
import logging

def send_receipt_email(to_email, subject, html_content):
    try:
        msg = Message(
            subject=subject,
            recipients=[to_email],
            html=html_content
        )

        mail.send(msg)
        logging.info(f"Receipt email sent to {to_email} with subject '{subject}'")
        return True, "Receipt sent successfully"

    except Exception as e:
        logging.error(f"Error sending receipt email: {e}")
        traceback.print_exc()
        logging.error(f"Traceback: {traceback.format_exc()}")
        return False, str(e)