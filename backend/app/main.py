import os
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from .database import get_db, engine, Base
from .models import User, Bridge, Request, OutreachEvent
from . import schemas, crud, matching, outreach, chatbot

# Make sure tables are created
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ThalassemiaFree AI — BloodBridge 2.0 API",
    description="Intelligent Event-Driven Matching and Outreach Platform Backend",
    version="1.0.0"
)

# Enable CORS for frontend connection (Member A's React App)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- DONORS & PATIENTS -----------------

@app.get("/api/donors", response_model=List[schemas.UserResponse])
def read_donors(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    donors = crud.get_donors(db, skip=skip, limit=limit)
    return donors

@app.get("/api/donors/inactive", response_model=List[schemas.UserResponse])
def read_inactive_donors(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    donors = crud.get_inactive_donors(db, skip=skip, limit=limit)
    return donors

@app.get("/api/patients", response_model=List[schemas.UserResponse])
def read_patients(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    patients = db.query(User).filter(User.role == "Patient").offset(skip).limit(limit).all()
    return patients

@app.get("/api/bridges", response_model=List[schemas.BridgeResponse])
def read_bridges(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_bridges(db, skip=skip, limit=limit)

@app.get("/api/bridges/{bridge_id}/donors", response_model=List[schemas.UserResponse])
def read_bridge_donors(bridge_id: str, db: Session = Depends(get_db)):
    return crud.get_bridge_donors(db, bridge_id=bridge_id)


# ----------------- SMART MATCHING & REQUESTS -----------------

@app.post("/api/requests", response_model=schemas.RequestResponse)
def create_blood_request(
    payload: schemas.RequestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Verify patient exists
    patient = crud.get_user(db, payload.patient_id)
    if not patient or patient.role != "Patient":
        raise HTTPException(status_code=404, detail="Patient user not found")
        
    # Create request record
    db_request = crud.create_request(
        db=db,
        patient_id=payload.patient_id,
        blood_units_needed=payload.blood_units_needed,
        hospital_name=payload.hospital_name,
        hospital_lat=payload.hospital_lat or patient.latitude,
        hospital_lon=payload.hospital_lon or patient.longitude,
        needed_by=payload.needed_by
    )
    
    # Trigger Step-Function sequential outreach in the background
    background_tasks.add_task(outreach.simulate_outreach_orchestration, db_request.id)
    
    return db_request

@app.get("/api/requests", response_model=List[schemas.RequestResponse])
def read_requests(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_requests(db, skip=skip, limit=limit)

@app.get("/api/requests/{request_id}", response_model=schemas.RequestResponse)
def read_request(request_id: int, db: Session = Depends(get_db)):
    req = crud.get_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req

@app.post("/api/requests/match-preview")
def preview_matches(
    blood_group: str,
    lat: float,
    lon: float,
    gender_pref: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Allows testing the matching engine ranking score without creating a request."""
    ranked = matching.rank_donors(
        db=db,
        blood_group=blood_group,
        patient_lat=lat,
        patient_lon=lon,
        gender_preference=gender_pref,
        limit=limit,
        force_eligible_only=True
    )
    return ranked


# ----------------- OUTREACH RESPONSE CALLBACKS -----------------

@app.post("/api/outreach/respond")
def submit_donor_response(payload: schemas.ResponseSubmit, db: Session = Depends(get_db)):
    """
    Simulates incoming donor responses (WhatsApp reply callback).
    Translates WhatsApp message into chatbot action or direct confirm/decline.
    """
    # Delegate message processing to chatbot
    reply = chatbot.process_bot_message(payload.phone, payload.message, db)
    return {"reply": reply}

@app.post("/api/outreach/verify-token")
def verify_donation_token(payload: schemas.TokenVerify, db: Session = Depends(get_db)):
    """
    Called by hospital blood banks or coordinators to verify a donor's BB-XXXXXX token.
    Enforces double-blind anonymity (masks identities in the response).
    Marks request as fulfilled, and marks outreach event as donated.
    Updates the donor's next eligibility date and increments donation counts.
    """
    import datetime
    
    # Find the outreach event matching the token
    event = db.query(OutreachEvent).filter(OutreachEvent.verification_token == payload.token).first()
    if not event:
        raise HTTPException(status_code=404, detail="Invalid or expired verification token")
        
    if event.response == "donated":
        return {
            "status": "already_verified",
            "message": "This token was already successfully verified and donation was recorded."
        }

    # Get the associated request and donor
    req = db.query(Request).filter(Request.id == event.request_id).first()
    donor = db.query(User).filter(User.id == event.donor_id).first()
    
    if not donor:
        raise HTTPException(status_code=404, detail="Donor associated with this token not found")

    # Mark the outreach event as donated
    now_dt = datetime.datetime.now()
    event.response = "donated"
    event.response_at = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Mark the request as fulfilled
    if req:
        req.status = "fulfilled"
        req.fulfilled_at = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Update donor record
    donor.last_donation_date = now_dt.strftime("%Y-%m-%d")
    donor.next_eligible_date = (now_dt + datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    donor.eligibility_status = "not eligible"
    if donor.donations_till_date is None:
        donor.donations_till_date = 1.0
    else:
        donor.donations_till_date += 1.0

    db.commit()

    # Log verification to notifications.log
    outreach.log_notification(
        f"✅ TOKEN VERIFIED: Token {payload.token} verified successfully at hospital. "
        f"Donor [Masked: {donor.masked_name}] (Blood group: {donor.blood_group}) donated for Request ID {event.request_id}."
    )

    return {
        "status": "success",
        "message": f"Verification successful! Donation recorded for Donor [Masked: {donor.masked_name}] and Request [Masked].",
        "verification_details": {
            "token": payload.token,
            "donor_masked_name": donor.masked_name,
            "donor_blood_group": donor.blood_group,
            "hospital_name": req.hospital_name if req else "Unknown",
            "verified_at": event.response_at
        }
    }


@app.post("/api/donors/register", response_model=schemas.UserResponse)
def register_donor(payload: schemas.DonorRegister, db: Session = Depends(get_db)):
    import random
    import datetime
    
    # Check if user already exists
    existing = db.query(User).filter(User.phone == payload.phone).first()
    if existing and existing.role != "Guest":
        if payload.phone == "+91 0000000000":
            # Bypassing check for website chatbot demo user to allow re-registrations
            existing.role = "Guest"
            db.commit()
        else:
            raise HTTPException(status_code=400, detail="Phone number is already registered.")
        
    # Generate unique user ID
    user_id = existing.id if (existing and existing.role == "Guest") else f"donor_{hash(payload.phone) & 0xffffffff:x}"
    
    # Random offset around Hyderabad (17.39, 78.46) for coordinates to display on map
    lat_offset = random.uniform(-0.06, 0.06)
    lon_offset = random.uniform(-0.06, 0.06)
    lat = 17.39 + lat_offset
    lon = 78.46 + lon_offset
    
    # Calculate health_score and churn_risk using ML models
    from .seeder import calculate_health_score, calculate_churn_risk
    # Build a mock row for model evaluation
    mock_row = {
        "gender": payload.gender,
        "blood_group": payload.blood_group,
        "donor_type": "Regular Donor" if payload.join_bridge else "One-Time Donor",
        "eligibility_status": "eligible",
        "last_donation_date": None,
        "donations_till_date": 0.0,
        "total_calls": 0,
        "calls_to_donations_ratio": 0.0,
        "cycle_of_donations": 90,
        "user_donation_active_status": "Active"
    }
    
    h_score = calculate_health_score(mock_row)
    c_risk = calculate_churn_risk(mock_row)
    
    # Create or update donor User record
    role = "Bridge Donor" if payload.join_bridge else "Emergency Donor"
    if existing and existing.role == "Guest":
        existing.name = payload.name
        existing.role = role
        existing.role_status = True
        existing.blood_group = payload.blood_group
        existing.gender = payload.gender
        existing.latitude = lat
        existing.longitude = lon
        existing.registration_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing.donor_type = "Regular Donor" if payload.join_bridge else "One-Time Donor"
        existing.eligibility_status = "eligible"
        existing.next_eligible_date = datetime.date.today().strftime("%Y-%m-%d")
        existing.donations_till_date = 0.0
        existing.total_calls = 0
        existing.calls_to_donations_ratio = 0.0
        existing.cycle_of_donations = 90
        existing.user_donation_active_status = "Active"
        existing.preferred_channel = payload.preferred_channel
        existing.preferred_language = payload.preferred_language
        existing.health_score = h_score
        existing.churn_risk_score = c_risk
        
        new_donor = existing
    else:
        new_donor = User(
            id=user_id,
            name=payload.name,
            phone=payload.phone,
            role=role,
            role_status=True,
            blood_group=payload.blood_group,
            gender=payload.gender,
            latitude=lat,
            longitude=lon,
            registration_date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            donor_type="Regular Donor" if payload.join_bridge else "One-Time Donor",
            eligibility_status="eligible",
            next_eligible_date=datetime.date.today().strftime("%Y-%m-%d"),
            donations_till_date=0.0,
            total_calls=0,
            calls_to_donations_ratio=0.0,
            cycle_of_donations=90,
            user_donation_active_status="Active",
            preferred_channel=payload.preferred_channel,
            preferred_language=payload.preferred_language,
            health_score=h_score,
            churn_risk_score=c_risk
        )
        db.add(new_donor)
    db.commit()
    db.refresh(new_donor)
    
    assigned_bridge_msg = ""
    # If bridge donor, allocate to a compatible patient bridge with space (< 10 donors)
    if payload.join_bridge:
        from .matching import COMPATIBILITY_MAP
        from .models import Bridge, BridgeDonorLink
        
        # Find compatible patient bridges
        compatible_bridges = []
        all_bridges = db.query(Bridge).filter(Bridge.bridge_status == True).all()
        for bridge in all_bridges:
            patient = db.query(User).filter(User.id == bridge.patient_id).first()
            if not patient:
                continue
                
            # Count current bridge donors
            current_count = db.query(BridgeDonorLink).filter(BridgeDonorLink.bridge_id == bridge.id).count()
            if current_count >= 10:
                continue # Bridge is capped at 10 donors
                
            # Check compatibility: patient's required blood type accepts donor's blood type
            patient_blood = bridge.bridge_blood_group or patient.blood_group or "O Positive"
            allowed_groups = COMPATIBILITY_MAP.get(patient_blood, [])
            if payload.blood_group in allowed_groups:
                compatible_bridges.append((bridge, current_count))
                
        # Sort bridges to allot: prefer the one with the lowest donor count (greatest deficit)
        if compatible_bridges:
            compatible_bridges.sort(key=lambda x: x[1])
            selected_bridge, current_size = compatible_bridges[0]
            
            # Create Link
            new_link = BridgeDonorLink(bridge_id=selected_bridge.id, donor_id=new_donor.id)
            db.add(new_link)
            db.commit()
            
            assigned_bridge_msg = f" Matched with Patient {selected_bridge.patient_id[:8].upper()} (Current bridge size: {current_size + 1}/10)."
            
    # Log registration
    outreach.log_notification(
        f"📝 NEW DONOR REGISTERED: {payload.name} ({payload.blood_group}, {role})."
        f"{assigned_bridge_msg}"
    )
    
    return new_donor


@app.post("/api/outreach/trigger-schedule-check")
def trigger_scheduled_transfusion_check(
    patient_id: Optional[str] = Query(None),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Triggers a scheduled transfusion cycle check (simulates checking expected_next_transfusion_date).
    If a specific patient_id is provided, triggers the 3-day transfusion outreach for that patient immediately.
    """
    import datetime
    
    target_patient = None
    if patient_id:
        target_patient = db.query(User).filter(User.id == patient_id, User.role == "Patient").first()
        if not target_patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
    else:
        # Find first patient who has an active bridge and expects transfusion
        bridge = db.query(Bridge).filter(Bridge.bridge_status == True).first()
        if bridge:
            target_patient = db.query(User).filter(User.id == bridge.patient_id).first()
            
    if not target_patient:
        raise HTTPException(status_code=404, detail="No active patient found to run schedule check.")
        
    # Get associated bridge
    bridge = db.query(Bridge).filter(Bridge.patient_id == target_patient.id, Bridge.bridge_status == True).first()
    if not bridge:
        raise HTTPException(status_code=404, detail="Patient does not have an active bridge.")
        
    # Create request record
    db_request = Request(
        patient_id=target_patient.id,
        requested_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        needed_by=bridge.expected_next_transfusion_date or (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d"),
        status="pending",
        blood_units_needed=bridge.quantity_required or 1.0,
        hospital_name="Hyderabad General Hospital",
        hospital_lat=target_patient.latitude,
        hospital_lon=target_patient.longitude
    )
    db.add(db_request)
    db.commit()
    db.refresh(db_request)
    
    # Run the scheduled outreach orchestrator in background
    background_tasks.add_task(
        outreach.simulate_scheduled_transfusion_orchestration,
        target_patient.id,
        db_request.id
    )
    
    return {
        "status": "success",
        "message": f"Scheduled transfusion check triggered for Patient {target_patient.masked_name}.",
        "request_id": db_request.id,
        "patient_id": target_patient.id
    }






# ----------------- VEERU 2.0 CHATBOT -----------------

@app.post("/api/chatbot", response_model=schemas.ChatMessageResponse)
def chat_with_veeru(payload: schemas.ChatMessageRequest, db: Session = Depends(get_db)):
    """Handles general conversational chats with Veeru 2.0 (Lex + Bedrock)."""
    reply = chatbot.process_bot_message(payload.phone, payload.message, db)
    return schemas.ChatMessageResponse(reply=reply)


# ----------------- ANALYTICS & DASHBOARD -----------------

@app.get("/api/dashboard/metrics")
def get_metrics(db: Session = Depends(get_db)):
    return crud.get_dashboard_metrics(db)

@app.get("/api/debug/notifications")
def get_notification_logs(limit: int = Query(20, ge=1, le=100)):
    """Reads and returns the last N logs of notifications for UI rendering."""
    if not os.path.exists(outreach.NOTIFICATION_LOG_PATH):
        return []
    try:
        with open(outreach.NOTIFICATION_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Return last N lines
        recent_lines = [line.strip() for line in lines[-limit:]]
        # Reverse to show newest first
        recent_lines.reverse()
        return recent_lines
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}")

@app.post("/api/debug/clear-logs")
def clear_notification_logs():
    """Wipes the notification logs."""
    if os.path.exists(outreach.NOTIFICATION_LOG_PATH):
        try:
            os.remove(outreach.NOTIFICATION_LOG_PATH)
            return {"status": "success", "message": "Notification logs cleared"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to clear logs: {e}")
    return {"status": "success", "message": "No logs existed"}

# Trigger reload for gemini-2.5-flash model update
