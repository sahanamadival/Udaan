
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_email():
    print("--- Starting Email Test ---")
    
    # Get credentials
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com').strip()
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    email_user = os.getenv('EMAIL_ADDRESS', '').strip()
    email_password = os.getenv('EMAIL_PASSWORD', '').strip()
    
    print(f"SMTP Server: '{smtp_server}'")
    print(f"SMTP Port: {smtp_port}")
    print(f"Email User: '{email_user}'")
    print(f"Email Password: {'*' * len(email_password) if email_password else 'NOT SET'}")
    
    if not email_user or not email_password:
        print("❌ ERROR: Email credentials missing in .env file")
        return

    recipient = email_user # Send to self for testing
    
    msg = MIMEMultipart()
    msg['From'] = email_user
    msg['To'] = recipient
    msg['Subject'] = "Udaan Local Email Test"
    
    body = "If you are reading this, your local email configuration is WORKING!"
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        print("Connecting to SMTP server...")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.set_debuglevel(1) # Show low-level SMTP communication
        
        print("Starting TLS...")
        server.starttls()
        
        print("Logging in...")
        server.login(email_user, email_password)
        
        print(f"Sending test email to {recipient}...")
        server.sendmail(email_user, recipient, msg.as_string())
        
        print("Quitting server...")
        server.quit()
        
        print("\n✅ SUCCESS! Email sent. Check your inbox (and spam folder) for 'Udaan Local Email Test'")
        
    except Exception as e:
        print(f"\n❌ FAILED: {str(e)}")

if __name__ == "__main__":
    test_email()
