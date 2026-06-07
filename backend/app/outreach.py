import os
import asyncio
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from .config import settings
from .models import Request, User, OutreachEvent, Bridge
from .matching import rank_donors
from .database import SessionLocal

# Local file log for simulating outgoing notifications
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except (PermissionError, OSError):
    # Fallback to writable temp directory if the application path is read-only (e.g. AWS Elastic Beanstalk)
    import tempfile
    LOG_DIR = os.path.join(tempfile.gettempdir(), "bloodmatch_logs")
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
    try:
        print(f"NOTIFICATION: {message}")
    except UnicodeEncodeError:
        try:
            print(f"NOTIFICATION: {message.encode('ascii', errors='replace').decode('ascii')}")
        except Exception:
            pass

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


async def simulate_scheduled_transfusion_orchestration(patient_id: str, request_id: int):
    """
    Simulates Pillar 2 Scheduled Transfusion Outreach:
    - Stage 1: Alerts assigned eligible bridge donors (up to 10).
    - If all decline or ignore, triggers Stage 2 Emergency Escalation.
    - Stage 2: Wave 1 (contacts top 10 global donors).
    - Stage 2: Wave 2 (contacts next top 15 global donors).
    - Escalates to coordinator if unanswered.
    """
    print(f"[Orchestrator] Starting Scheduled Transfusion Outreach for Patient: {patient_id}")
    db: Session = SessionLocal()
    try:
        request = db.query(Request).filter(Request.id == request_id).first()
        if not request:
            return
            
        patient = db.query(User).filter(User.id == patient_id).first()
        if not patient:
            return
            
        # Get patient's bridge
        bridge = db.query(Bridge).filter(Bridge.patient_id == patient_id, Bridge.bridge_status == True).first()
        if not bridge:
            log_notification(f"⚠️ No active bridge found for Patient {patient.masked_name}. Escalating request immediately.")
            request.status = "escalated"
            db.commit()
            return
            
        # 1. STAGE 1: Bridge Donor Outreach
        # Find assigned bridge donors
        from .models import BridgeDonorLink
        links = db.query(BridgeDonorLink).filter(BridgeDonorLink.bridge_id == bridge.id).all()
        bridge_donor_ids = [link.donor_id for link in links]
        
        eligible_bridge_donors = db.query(User).filter(
            User.id.in_(bridge_donor_ids),
            User.eligibility_status == "eligible",
            User.user_donation_active_status == "Active"
        ).all()
        
        if not eligible_bridge_donors:
            log_notification(f"⚠️ Stage 1: No eligible bridge donors found in the group of Patient {patient.masked_name}. Moving directly to Stage 2 Emergency Escalation.")
        else:
            log_notification(f"🌊 Stage 1: Contacting {len(eligible_bridge_donors)} assigned eligible bridge donors for Patient {patient.masked_name} (transfusion scheduled in 3 days).")
            
            for donor in eligible_bridge_donors:
                # Create OutreachEvent in pending state
                event = OutreachEvent(
                    request_id=request_id,
                    donor_id=donor.id,
                    channel=donor.preferred_channel,
                    wave_number=1, # Bridge Wave
                    sent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    response="pending"
                )
                db.add(event)
                
                # Format notification message
                message = f"Hello {donor.name}, your matched patient (Fighter {patient.masked_name}) has a scheduled transfusion in 3 days. Are you available to support? Reply CONFIRM to accept or DECLINE to snooze."
                log_notification(f"Sending via {donor.preferred_channel} to Bridge Donor {donor.masked_name} ({donor.phone}): \"{message}\"")
                
            db.commit()
            
            # Wait for responses (demo timeout)
            for elapsed in range(DEMO_WAVE_DELAY):
                await asyncio.sleep(1)
                db.refresh(request)
                if request.status in ("in_progress", "fulfilled"):
                    log_notification(f"✅ Stage 1 SUCCESS: Bridge donor confirmed donation intent. Transactional token generated.")
                    return
            
            # If wave ends and not confirmed, mark pending outreaches as ignored/declined
            for donor in eligible_bridge_donors:
                ev = db.query(OutreachEvent).filter(
                    OutreachEvent.request_id == request_id,
                    OutreachEvent.donor_id == donor.id,
                    OutreachEvent.response == "pending"
                ).first()
                if ev:
                    ev.response = "ignored"
                    ev.response_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.commit()
            log_notification(f"🚨 Stage 1 FALLBACK: No bridge members confirmed for Patient {patient.masked_name}. Initiating global Emergency Escalation.")
            
        # 2. STAGE 2: Emergency Escalation (Global Rank Fallback)
        # Get up to 25 ranked compatible donors globally (exclude current bridge members who ignored/declined)
        ranked = rank_donors(
            db=db,
            blood_group=patient.blood_group,
            patient_lat=request.hospital_lat or patient.latitude,
            patient_lon=request.hospital_lon or patient.longitude,
            gender_preference=patient.gender,
            limit=25 + len(bridge_donor_ids),
            force_eligible_only=True
        )
        # Filter out donors who already declined this request
        ranked = [d for d in ranked if d["donor_id"] not in bridge_donor_ids]
        
        if not ranked:
            log_notification(f"⚠️ CRISIS: No eligible emergency donors found for Patient {patient.masked_name}! Alerting NGO Coordinator.")
            request.status = "escalated"
            db.commit()
            return
            
        # Wave 1 (Top 10 ranked donors)
        wave_1_donors = ranked[:10]
        log_notification(f"🌊 Stage 2 - Wave 1: Contacting top {len(wave_1_donors)} ranked compatible emergency donors globally for Request ID {request_id}")
        
        for d in wave_1_donors:
            donor_id = d["donor_id"]
            event = OutreachEvent(
                request_id=request_id,
                donor_id=donor_id,
                channel=d["preferred_channel"],
                wave_number=2, # Emergency Wave 1
                sent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                response="pending"
            )
            db.add(event)
            
            message = f"URGENT: A Thalassemia patient needs a transfusion of {d['blood_group']} blood at {request.hospital_name}. Since you are eligible, can you support? Reply CONFIRM to accept or DECLINE."
            # Mask name in notification console for anonymity
            masked_name = d["name"][0] + "*" * (len(d["name"]) - 1) if d["name"] else "Donor"
            log_notification(f"Sending via {d['preferred_channel']} to {masked_name} ({d['phone']}): \"{message}\"")
        db.commit()
        
        # Wait for responses
        for elapsed in range(DEMO_WAVE_DELAY):
            await asyncio.sleep(1)
            db.refresh(request)
            if request.status in ("in_progress", "fulfilled"):
                log_notification(f"✅ Stage 2 SUCCESS: Emergency donor confirmed donation intent during Wave 1.")
                return
                
        # Mark ignored
        for d in wave_1_donors:
            ev = db.query(OutreachEvent).filter(
                OutreachEvent.request_id == request_id,
                OutreachEvent.donor_id == d["donor_id"],
                OutreachEvent.response == "pending"
            ).first()
            if ev:
                ev.response = "ignored"
                ev.response_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
        
        # Wave 2 (Next top 15 ranked donors)
        wave_2_donors = ranked[10:25]
        if wave_2_donors:
            log_notification(f"🌊 Stage 2 - Wave 2: Contacting next {len(wave_2_donors)} ranked compatible emergency donors globally for Request ID {request_id}")
            for d in wave_2_donors:
                donor_id = d["donor_id"]
                event = OutreachEvent(
                    request_id=request_id,
                    donor_id=donor_id,
                    channel=d["preferred_channel"],
                    wave_number=3, # Emergency Wave 2
                    sent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    response="pending"
                )
                db.add(event)
                
                message = f"URGENT: A Thalassemia patient needs a transfusion of {d['blood_group']} blood at {request.hospital_name}. Since you are eligible, can you support? Reply CONFIRM to accept or DECLINE."
                masked_name = d["name"][0] + "*" * (len(d["name"]) - 1) if d["name"] else "Donor"
                log_notification(f"Sending via {d['preferred_channel']} to {masked_name} ({d['phone']}): \"{message}\"")
            db.commit()
            
            # Wait for responses
            for elapsed in range(DEMO_WAVE_DELAY):
                await asyncio.sleep(1)
                db.refresh(request)
                if request.status in ("in_progress", "fulfilled"):
                    log_notification(f"✅ Stage 2 SUCCESS: Emergency donor confirmed donation intent during Wave 2.")
                    return
                    
            # Mark ignored
            for d in wave_2_donors:
                ev = db.query(OutreachEvent).filter(
                    OutreachEvent.request_id == request_id,
                    OutreachEvent.donor_id == d["donor_id"],
                    OutreachEvent.response == "pending"
                ).first()
                if ev:
                    ev.response = "ignored"
                    ev.response_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.commit()
            
        # If we reach here, check if it's rare blood type or urgent and alert coordinator
        db.refresh(request)
        if request.status not in ("in_progress", "fulfilled"):
            is_rare = patient.blood_group in ("O Negative", "B Negative", "AB Negative")
            log_notification(
                f"🚨 ESCALATION: All emergency waves completed without donor confirmation. "
                f"Alerting NGO Coordinator. Rare Type status: {is_rare}. Transfusion is in 3 days."
            )
            request.status = "escalated"
            db.commit()
            
    except Exception as e:
        print(f"[Orchestrator] Error during scheduled outreach: {e}")
        db.rollback()
    finally:
        db.close()

def trigger_scheduled_outreach_background(patient_id: str, request_id: int):
    """Triggers the async simulation of scheduled transfusion in the background."""
    asyncio.create_task(simulate_scheduled_transfusion_orchestration(patient_id, request_id))

