from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os
import logging
import traceback

def send_receipt_email(to_email, subject, html_content):
    try:
        message = Mail(
            from_email=os.environ["SENDGRID_FROM_EMAIL"],
            to_emails=to_email,
            subject=subject,
            html_content=html_content
        )
        sg = SendGridAPIClient(os.environ["SENDGRID_API_KEY"])
        response = sg.send(message)

        # SendGrid returns 2xx on success (202 is the normal "accepted" code)
        if response.status_code >= 400:
            logging.error(f"SendGrid error {response.status_code}: {response.body}")
            return False, f"SendGrid error {response.status_code}"

        logging.info(f"Receipt email sent to {to_email} with subject '{subject}'")
        return True, "Receipt sent successfully"

    except Exception as e:
        logging.error(f"Error sending receipt email: {e}")
        traceback.print_exc()
        return False, str(e)