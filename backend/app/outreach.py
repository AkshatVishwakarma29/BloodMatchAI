import os
import asyncio
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from .config import settings
from .models import Request, User, OutreachEvent
from .matching import rank_donors
from .database import SessionLocal

# Local file log for simulating outgoing notifications
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
NOTIFICATION_LOG_PATH = os.path.join(LOG_DIR, "notifications.log")

# Time delay between waves in seconds for DEMO purposes (instead of 4 hours)
DEMO_WAVE_DELAY = 15

def log_notification(message: str):
    """Writes a notification payload to the local log file for verification."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    with open(NOTIFICATION_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(log_entry)
    print(f"NOTIFICATION: {message}")

def get_outreach_template(donor_name: str, blood_group: str, hospital_name: str, language: str) -> str:
    """Generates localized outreach messages."""
    templates = {
        "English": f"Hello {donor_name}, a Thalassemia patient needs a transfusion of {blood_group} blood at {hospital_name}. Since you are eligible and match, can you support? Reply CONFIRM to accept or DECLINE to snooze for 30 days.",
        "Hindi": f"नमस्ते {donor_name}, एक थैलेसीमिया रोगी को {hospital_name} में {blood_group} रक्त की आवश्यकता है। आप इसके पात्र हैं, क्या आप दान कर सकते हैं? स्वीकार करने के लिए CONFIRM या 30 दिनों के लिए टालने के लिए DECLINE उत्तर दें।",
        "Telugu": f"హలో {donor_name}, {hospital_name} లో ఒక తలసేమియా రోగికి {blood_group} రక్తం అవసరం. మీరు దానం చేయగలరా? అంగీకరించడానికి CONFIRM అని లేదా తిరస్కరించడానికి DECLINE అని రిప్లై ఇవ్వండి.",
        "Tamil": f"வணக்கம் {donor_name}, {hospital_name} இல் ஒரு தலசீமியா நோயாளிக்கு {blood_group} இரத்தம் தேவைப்படுகிறது. நீங்கள் உதவ முடியுமா? ஒப்புக்கொள்ள CONFIRM என்றும் மறுக்க DECLINE என்றும் பதிலளிக்கவும்."
    }
    return templates.get(language, templates["English"])

async def simulate_outreach_orchestration(request_id: int):
    """
    Simulates the AWS Step Function workflow:
    - Ranks and targets donors in waves of 3.
    - Waits for responses.
    - Escalates if unanswered.
    """
    print(f"[Orchestrator] Starting outreach orchestration for Request ID: {request_id}")
    
    db: Session = SessionLocal()
    try:
        request = db.query(Request).filter(Request.id == request_id).first()
        if not request:
            print(f"[Orchestrator] Request {request_id} not found.")
            return

        patient = db.query(User).filter(User.id == request.patient_id).first()
        if not patient:
            print(f"[Orchestrator] Patient not found for Request {request_id}.")
            return
            
        # Get up to 9 ranked compatible donors
        ranked = rank_donors(
            db=db,
            blood_group=patient.blood_group,
            patient_lat=request.hospital_lat or patient.latitude,
            patient_lon=request.hospital_lon or patient.longitude,
            gender_preference=patient.gender,  # Soft constraint matching patient gender
            limit=9,
            force_eligible_only=True
        )
        
        if not ranked:
            log_notification(f"⚠️ CRISIS: No eligible donors found for Request ID {request_id} (Patient blood: {patient.blood_group})! Escalating to coordinator immediately.")
            request.status = "escalated"
            db.commit()
            return

        print(f"[Orchestrator] Found {len(ranked)} eligible donors for Request {request_id}.")
        request.status = "in_progress"
        db.commit()

        # Run up to 3 waves of 3 donors
        wave_size = 3
        for wave in range(1, 4):
            # Refresh request state from DB to check if it's already fulfilled
            db.refresh(request)
            if request.status == "fulfilled":
                print(f"[Orchestrator] Request {request_id} is already FULFILLED. Stopping orchestration.")
                return

            start_idx = (wave - 1) * wave_size
            end_idx = wave * wave_size
            wave_donors = ranked[start_idx:end_idx]
            
            if not wave_donors:
                print(f"[Orchestrator] No more donors available for Wave {wave}.")
                break
                
            log_notification(f"🌊 Dispatching Outreach Wave {wave} to {len(wave_donors)} donors for Request ID {request_id}")
            
            for d in wave_donors:
                donor_id = d["donor_id"]
                channel = d["preferred_channel"]
                lang = d["preferred_language"]
                
                # Check if this donor already has a pending or confirmed outreach for this request
                existing_event = db.query(OutreachEvent).filter(
                    OutreachEvent.request_id == request_id,
                    OutreachEvent.donor_id == donor_id
                ).first()
                
                if existing_event:
                    continue
                
                # Create OutreachEvent in pending state
                event = OutreachEvent(
                    request_id=request_id,
                    donor_id=donor_id,
                    channel=channel,
                    wave_number=wave,
                    sent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    response="pending"
                )
                db.add(event)
                
                # Format notification message
                message = get_outreach_template(d["name"], d["blood_group"], request.hospital_name or "General Hospital", lang)
                log_notification(f"Sending via {channel} to {d['name']} ({d['phone']}): \"{message}\"")
            
            db.commit()

            # Wait for response during this wave's timeout
            # We poll the database every second to see if the request gets fulfilled
            for elapsed in range(DEMO_WAVE_DELAY):
                await asyncio.sleep(1)
                db.refresh(request)
                if request.status == "fulfilled":
                    print(f"[Orchestrator] Confirmed donation during Wave {wave}! Stopping orchestration.")
                    return
            
            # If wave ends and not fulfilled, mark pending outreaches of this wave as 'ignored'
            for d in wave_donors:
                ev = db.query(OutreachEvent).filter(
                    OutreachEvent.request_id == request_id,
                    OutreachEvent.donor_id == d["donor_id"],
                    OutreachEvent.response == "pending"
                ).first()
                if ev:
                    ev.response = "ignored"
                    ev.response_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.commit()
            
        # If we exit the loop and still not fulfilled, escalate
        db.refresh(request)
        if request.status != "fulfilled":
            log_notification(f"🚨 ESCALATION: All 3 waves completed without donor confirmation for Request ID {request_id}. Alerting NGO Coordinator.")
            request.status = "escalated"
            db.commit()
            
    except Exception as e:
        print(f"[Orchestrator] Error during outreach orchestration: {e}")
        db.rollback()
    finally:
        db.close()

def trigger_outreach_background(request_id: int):
    """Triggers the async simulation in the background."""
    asyncio.create_task(simulate_outreach_orchestration(request_id))
