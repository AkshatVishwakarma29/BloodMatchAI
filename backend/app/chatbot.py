import re
from datetime import datetime, timedelta
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from .config import settings
from .models import User, OutreachEvent, Request

# Optional Generative AI integrations
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

def query_llm(prompt: str, system_instruction: str) -> Optional[str]:
    """Tries to query Gemini or OpenAI based on available keys in config."""
    # 1. Try Gemini first (highly likely on Google workspace setup)
    if HAS_GEMINI and settings.GEMINI_API_KEY:
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=system_instruction
            )
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[LLM] Gemini generation failed: {e}")

    # 2. Fall back to OpenAI
    if HAS_OPENAI and settings.OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=250,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[LLM] OpenAI generation failed: {e}")
            
    return None

def process_bot_message(phone: str, text: str, db: Session) -> str:
    """
    Core conversational logic for Veeru 2.0 WhatsApp Bot.
    Analyzes message intents, executes DB transactions for confirms/declines,
    and falls back to Generative LLM with profile memory.
    """
    clean_text = text.strip().lower()
    
    # 1. Find user by phone number
    user = db.query(User).filter(User.phone == phone).first()
    
    # If user not found, create a new Guest user
    if not user:
        user_id = f"guest_{hash(phone) & 0xffffffff:x}"
        user = User(
            id=user_id,
            name="New Guest",
            phone=phone,
            role="Guest",
            role_status=True,
            user_donation_active_status="Active",
            registration_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # 2. Check for keywords/intents in message
    
    # A. Confirmation flow: CONFIRM
    if "confirm" in clean_text:
        # Find latest pending outreach event for this donor
        pending_outreach = db.query(OutreachEvent).filter(
            OutreachEvent.donor_id == user.id,
            OutreachEvent.response == "pending"
        ).order_by(OutreachEvent.id.desc()).first()
        
        if pending_outreach:
            # Update outreach event
            pending_outreach.response = "confirmed"
            pending_outreach.response_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Calculate response time
            sent_dt = datetime.strptime(pending_outreach.sent_at, "%Y-%m-%d %H:%M:%S")
            now_dt = datetime.now()
            pending_outreach.response_time_mins = float(round((now_dt - sent_dt).total_seconds() / 60.0, 1))
            
            # Update corresponding request status to fulfilled
            req = db.query(Request).filter(Request.id == pending_outreach.request_id).first()
            if req:
                req.status = "fulfilled"
                req.fulfilled_at = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                
            # Update donor record
            user.last_donation_date = now_dt.strftime("%Y-%m-%d")
            # Donor is not eligible for the next 90 days
            user.next_eligible_date = (now_dt + timedelta(days=90)).strftime("%Y-%m-%d")
            user.eligibility_status = "not eligible"
            if user.donations_till_date is None:
                user.donations_till_date = 1.0
            else:
                user.donations_till_date += 1.0
            
            db.commit()
            
            return f"Thank you {user.name}! ❤️ You have confirmed your donation. We have notified the patient and hospital. Your support is saving a life today!"
        else:
            return "You do not have any pending donation requests. Thank you for checking in!"

    # B. Decline flow: DECLINE
    if "decline" in clean_text:
        pending_outreach = db.query(OutreachEvent).filter(
            OutreachEvent.donor_id == user.id,
            OutreachEvent.response == "pending"
        ).order_by(OutreachEvent.id.desc()).first()
        
        if pending_outreach:
            # Update outreach event
            pending_outreach.response = "declined"
            pending_outreach.response_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Snooze donor: set next eligibility date to 30 days from now (dignity rules)
            now_dt = datetime.now()
            user.next_eligible_date = (now_dt + timedelta(days=30)).strftime("%Y-%m-%d")
            user.eligibility_status = "not eligible"
            user.last_contacted_date = now_dt.strftime("%Y-%m-%d")
            db.commit()
            
            return f"Understood, {user.name}. We have updated your status and will snooze requests for the next 30 days. Take care!"
        else:
            return "No pending requests found. If you wish to take a break from donations, please update your availability in the portal. Thank you!"

    # C. Eligibility check
    if any(k in clean_text for k in ["eligib", "avail", "can i donate"]):
        if user.role == "Patient":
            return "As a registered Patient, you are receiving blood bridge support. If you want to check your scheduled transfusion dates, reply with STATUS."
            
        if user.eligibility_status == "eligible":
            return f"Hi {user.name}, you are currently ELIGIBLE to donate! 🩸 Your blood group is {user.blood_group or 'not registered yet'}. When a transfusion request matches you, we will contact you via your preferred channel ({user.preferred_channel})."
        else:
            next_date = user.next_eligible_date or "unknown"
            return f"Hi {user.name}, you are currently not eligible to donate. Your next eligible date is {next_date}. Thank you for your patience and willingness to help!"

    # D. Show history
    if any(k in clean_text for k in ["history", "stat", "donat"]):
        if user.role == "Patient":
            # Show patient's request history
            reqs = db.query(Request).filter(Request.patient_id == user.id).all()
            if not reqs:
                return "You haven't made any blood requests yet."
            return f"Hi {user.name}, you have {len(reqs)} requests in our network. Latest status: {reqs[-1].status}."
        
        donations = int(user.donations_till_date) if user.donations_till_date is not None else 0
        last_d = user.last_donation_date or "never"
        return f"🌟 Donor Profile — {user.name}\n- Blood Group: {user.blood_group or 'Unknown'}\n- Total Donations: {donations}\n- Last Donation: {last_d}\n- Health Score: {user.health_score or 0.0}\nThank you for being a Blood Warrior! 🩸"

    # E. Patient request status
    if "status" in clean_text:
        # Find latest request
        latest_req = db.query(Request).order_by(Request.id.desc()).first() # For demo, get global latest or filter by user
        if user.role == "Patient":
            latest_req = db.query(Request).filter(Request.patient_id == user.id).order_by(Request.id.desc()).first()
            
        if not latest_req:
            return "There are no active requests in the system right now."
            
        return f"Request ID {latest_req.id} status is: {latest_req.status.upper()}. Needed by: {latest_req.needed_by}."

    # F. Help command
    if "help" in clean_text:
        return (
            "🤖 Veeru 2.0 Commands:\n"
            "- 'ELIGIBILITY': Check if you can donate blood\n"
            "- 'HISTORY': View your donation stats\n"
            "- 'STATUS': Check the status of current request\n"
            "- 'CONFIRM': Accept a pending donation request\n"
            "- 'DECLINE': Snooze current request for 30 days"
        )

    # 3. LLM Fallback (if keys are available)
    # Contextual prompt for LLM containing user details
    system_instruction = (
        "You are Veeru 2.0, an intelligent, empathetic conversational AI chatbot for Blood Warriors, "
        "an NGO supporting Thalassemia patients in India. Keep your answers concise, engaging, and friendly. "
        "Help the user based on their profile and constraints. Never say you are an AI assistant unless asked. "
        "Always sound like a dedicated, supportive coordinator. Keep answers under 3-4 sentences."
    )
    
    user_context = (
        f"User Details:\n"
        f"- Name: {user.name}\n"
        f"- Role: {user.role}\n"
        f"- Blood Group: {user.blood_group or 'Unknown'}\n"
        f"- Gender: {user.gender or 'Unknown'}\n"
        f"- Eligibility Status: {user.eligibility_status or 'Unknown'}\n"
        f"- Next Eligible Date: {user.next_eligible_date or 'Unknown'}\n"
        f"- Total Donations: {user.donations_till_date or 0}\n"
        f"- Last Donation Date: {user.last_donation_date or 'Never'}\n"
        f"- Preferred Channel: {user.preferred_channel}\n"
        f"- Preferred Language: {user.preferred_language}\n"
        f"User message: \"{text}\""
    )
    
    llm_response = query_llm(user_context, system_instruction)
    if llm_response:
        return llm_response
        
    # 4. Fallback to basic greeting
    return (
        f"Hello {user.name}! I am Veeru 2.0, your Blood Warriors assistant. "
        f"How can I help you today? You can check your 'ELIGIBILITY', view donation 'HISTORY', or check request 'STATUS'."
    )
