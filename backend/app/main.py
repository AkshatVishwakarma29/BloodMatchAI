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
