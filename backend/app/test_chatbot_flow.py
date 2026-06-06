import os
import sys
import json
from datetime import datetime, timedelta

# Add backend directory to path so app can be imported
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.append(backend_dir)

# Force the environment database URL to be a test database
os.environ["DATABASE_URL"] = "sqlite:///./test_bloodbridge.db"

# Remove test database if it exists
if os.path.exists("test_bloodbridge.db"):
    try:
        os.remove("test_bloodbridge.db")
    except Exception as e:
        print(f"Error removing old test DB: {e}")

from app.database import engine, Base, SessionLocal
from app.models import User, Bridge, BridgeDonorLink, Request, OutreachEvent, ChatSession, ChatHistory
from app.chatbot import process_bot_message, get_chat_history

# Create all tables on the clean test database
Base.metadata.create_all(bind=engine)

def safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            pass

def print_separator(title):
    safe_print(f"\n==================== {title} ====================")

def test_chatbot_flows():
    db = SessionLocal()
    phone = "+91 9999991111"
    
    print_separator("1. SETUP COMPATIBLE BRIDGE PATIENT")
    # Setup a patient with an active bridge to verify registration auto-allotment
    patient = User(
        id="patient_alice",
        name="Alice Patel",
        phone="+91 8888888888",
        role="Patient",
        blood_group="O Positive",
        gender="Female",
        latitude=17.39,
        longitude=78.46,
        eligibility_status="not eligible",
        user_donation_active_status="Active"
    )
    db.add(patient)
    db.commit()
    
    bridge = Bridge(
        id="bridge_alice",
        patient_id=patient.id,
        bridge_status=True,
        bridge_blood_group="O Positive",
        bridge_gender="Female",
        quantity_required=1.0,
        frequency_in_days=30,
        expected_next_transfusion_date="2026-06-12"
    )
    db.add(bridge)
    db.commit()
    safe_print(f"Created bridge patient Alice: blood group O Positive.")

    print_separator("2. START SLOT FILLING REGISTRATION")
    # Send "REGISTER" intent
    reply = process_bot_message(phone, "I want to register as a donor", db)
    safe_print(f"User: I want to register as a donor")
    safe_print(f"Bot: {reply}")
    assert "What is your Full Name?" in reply
    
    # Check session was created
    session = db.query(ChatSession).filter(ChatSession.phone == phone).first()
    assert session is not None
    assert session.step == "reg_name"

    print_separator("3. VALIDATE FULL NAME INPUT")
    # Send invalid name (too short)
    reply = process_bot_message(phone, "R", db)
    safe_print(f"User: R")
    safe_print(f"Bot: {reply}")
    assert "Please provide a valid Full Name." in reply
    
    # Send valid name
    reply = process_bot_message(phone, "Rahul Sharma", db)
    safe_print(f"User: Rahul Sharma")
    safe_print(f"Bot: {reply}")
    assert "What is your Blood Group?" in reply
    
    session = db.query(ChatSession).filter(ChatSession.phone == phone).first()
    assert session.step == "reg_blood"

    print_separator("4. VALIDATE BLOOD GROUP INPUT")
    # Send invalid blood group
    reply = process_bot_message(phone, "X Positive", db)
    safe_print(f"User: X Positive")
    safe_print(f"Bot: {reply}")
    assert "Invalid blood group format." in reply
    
    # Send valid blood group (e.g. O+)
    reply = process_bot_message(phone, "o+", db)
    safe_print(f"User: o+")
    safe_print(f"Bot: {reply}")
    assert "What is your Gender?" in reply
    
    session = db.query(ChatSession).filter(ChatSession.phone == phone).first()
    assert session.step == "reg_gender"

    print_separator("5. VALIDATE GENDER INPUT")
    # Send invalid gender
    reply = process_bot_message(phone, "Alien", db)
    safe_print(f"User: Alien")
    safe_print(f"Bot: {reply}")
    assert "Invalid gender. Please reply with Male, Female, or Other." in reply
    
    # Send valid gender
    reply = process_bot_message(phone, "m", db)
    safe_print(f"User: m")
    safe_print(f"Bot: {reply}")
    assert "What is your preferred channel for transfusion alerts?" in reply
    
    session = db.query(ChatSession).filter(ChatSession.phone == phone).first()
    assert session.step == "reg_channel"

    print_separator("6. VALIDATE CHANNEL INPUT")
    # Send invalid channel
    reply = process_bot_message(phone, "Signal", db)
    safe_print(f"User: Signal")
    safe_print(f"Bot: {reply}")
    assert "Invalid channel option. Please reply with WhatsApp, SMS, or Email." in reply
    
    # Send valid channel
    reply = process_bot_message(phone, "whatsapp", db)
    safe_print(f"User: whatsapp")
    safe_print(f"Bot: {reply}")
    assert "What is your preferred language for messages?" in reply
    
    session = db.query(ChatSession).filter(ChatSession.phone == phone).first()
    assert session.step == "reg_lang"

    print_separator("7. VALIDATE LANGUAGE INPUT")
    # Send invalid language
    reply = process_bot_message(phone, "Sanskrit", db)
    safe_print(f"User: Sanskrit")
    safe_print(f"Bot: {reply}")
    assert "Invalid language. Please choose from English, Hindi, Telugu, or Tamil." in reply
    
    # Send valid language
    reply = process_bot_message(phone, "English", db)
    safe_print(f"User: English")
    safe_print(f"Bot: {reply}")
    assert "Would you like to join a patient bridge to support a specific patient?" in reply
    
    session = db.query(ChatSession).filter(ChatSession.phone == phone).first()
    assert session.step == "reg_bridge"

    print_separator("8. COMPLETE REGISTRATION FLOW")
    # Send invalid bridge answer
    reply = process_bot_message(phone, "maybe", db)
    safe_print(f"User: maybe")
    safe_print(f"Bot: {reply}")
    assert "Please reply with Yes or No." in reply
    
    # Send valid bridge answer
    reply = process_bot_message(phone, "Yes", db)
    safe_print(f"User: Yes")
    safe_print(f"Bot: {reply}")
    assert "Registration Successful!" in reply
    assert "R**** S*****" in reply or "R* S*" in reply or "Rahul Sharma" in reply or "R****" in reply
    
    # Check database status
    session = db.query(ChatSession).filter(ChatSession.phone == phone).first()
    assert session is None, "Chat session was not deleted after registration completion"
    
    donor = db.query(User).filter(User.phone == phone).first()
    assert donor is not None
    assert donor.role == "Bridge Donor"
    assert donor.blood_group == "O Positive"
    assert donor.gender == "Male"
    assert donor.preferred_channel == "WhatsApp"
    assert donor.preferred_language == "English"
    
    # Check that donor was auto-allocated to Alice's bridge
    link = db.query(BridgeDonorLink).filter(BridgeDonorLink.donor_id == donor.id).first()
    assert link is not None
    assert link.bridge_id == "bridge_alice"
    safe_print("Verified: Donor registered and successfully auto-allotted to Alice's compatible bridge!")

    print_separator("9. VERIFY SESSION MEMORY LOGS")
    history_text = get_chat_history(phone, db, limit=8)
    safe_print("Last 8 chat history logs:")
    safe_print(history_text)
    assert len(history_text.strip().split("\n")) >= 8
    safe_print("Verified: Session memory retrieves the last 8 messages successfully.")

    print_separator("10. VERIFY SNOOZE AVAILABILITY")
    # Test snooze command
    reply = process_bot_message(phone, "snooze 15", db)
    safe_print(f"User: snooze 15")
    safe_print(f"Bot: {reply}")
    assert "snoozed all requests" in reply and "15 days" in reply
    
    db.refresh(donor)
    assert donor.eligibility_status == "not eligible"
    expected_snooze_date = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
    assert donor.next_eligible_date == expected_snooze_date
    safe_print(f"Verified: snooze 15 updated next_eligible_date to {donor.next_eligible_date} and set eligibility to 'not eligible'.")

    print_separator("11. VERIFY NEAREST COMPATIBLE BLOOD BANK")
    # Test blood bank command
    reply = process_bot_message(phone, "where is the nearest blood bank?", db)
    safe_print(f"User: where is the nearest blood bank?")
    safe_print(f"Bot: {reply}")
    assert "Nearest Compatible Blood Centers" in reply
    assert any(b in reply for b in ["Aarohi", "NTR", "Gandhi", "Red Cross", "Chiranjeevi"])
    safe_print("Verified: Nearest blood bank search list returned successfully.")

    print_separator("12. VERIFY RESCHEDULE TRANSACTION")
    # Setup an outreach event for the donor
    req = Request(
        patient_id="patient_alice",
        requested_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        needed_by="2026-06-12",
        status="in_progress",
        blood_units_needed=1.0,
        hospital_name="Hyderabad General Hospital",
        hospital_lat=17.39,
        hospital_lon=78.46
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    
    event = OutreachEvent(
        request_id=req.id,
        donor_id=donor.id,
        channel="WhatsApp",
        wave_number=1,
        sent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        response="confirmed",
        response_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        verification_token="BB-ABCDEF"
    )
    db.add(event)
    db.commit()
    
    # Send reschedule intent
    reply = process_bot_message(phone, "I need to reschedule my donation", db)
    safe_print(f"User: I need to reschedule my donation")
    safe_print(f"Bot: {reply}")
    assert "postponed your scheduled donation request" in reply
    
    db.refresh(req)
    # Postponed by 7 days from 2026-06-12 is 2026-06-19
    assert req.needed_by == "2026-06-19"
    safe_print(f"Verified: Reschedule intent postponed transfusion request needed_by date to {req.needed_by}.")

    print_separator("ALL CHATBOT TESTS PASSED SUCCESSFULLY!")
    db.close()

if __name__ == "__main__":
    test_chatbot_flows()
