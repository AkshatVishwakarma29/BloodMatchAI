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

    # 2. Check for privacy questions (identity masking filters)
    privacy_keywords = [
        "who am i donating to", "who is the patient", "patient name", "receiver name", 
        "who got my blood", "patient phone", "patient contact", "who needs my blood", 
        "receiver contact", "donor name", "who is my donor", "who donated", "donor contact",
        "who received my blood", "who received the blood", "whose request", "who is the donor",
        "who provided", "donor details", "patient details", "donor info", "patient info"
    ]
    if any(k in clean_text for k in privacy_keywords):
        if user.role == "Patient":
            return (
                "🛡️ **BloodBridge Privacy Protection:**\n"
                "To protect donor privacy and prevent any commercialization of blood donation, "
                "BloodBridge operates on a strict double-blind anonymity system. "
                "We do not share the donor's identity, phone number, or personal details. "
                "Your transfusion request is managed completely autonomously. "
                "Thank you for being a part of this noble network!"
            )
        else:
            return (
                "🛡️ **BloodBridge Privacy Protection:**\n"
                "To protect patient privacy and ensure this noble cause remains purely altruistic, "
                "BloodBridge operates on a strict double-blind anonymity system. "
                "We do not share the patient's identity, phone number, or personal details. "
                "When you confirm a donation, you are provided with a secure verification code "
                "to present at the hospital. Thank you for your lifesaving support!"
            )

    # 3. Check for keywords/intents in message
    
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
            
            # Generate a secure verification token for double-blind confirmation
            token = f"BB-{(hash(f'{pending_outreach.request_id}-{pending_outreach.donor_id}-{now_dt.timestamp()}') & 0xffffff):06X}"
            pending_outreach.verification_token = token
            
            # Update corresponding request status to in_progress (intent confirmed)
            req = db.query(Request).filter(Request.id == pending_outreach.request_id).first()
            if req:
                req.status = "in_progress"
            
            db.commit()
            
            return (
                f"Thank you {user.name}! ❤️ You have confirmed your donation intent. "
                f"To protect patient and donor privacy, your secure donation verification code is **{token}**. "
                f"Please present this code at the hospital blood bank when donating. "
                f"The transaction is fully anonymous. Thank you for your lifesaving support!"
            )
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
        "Always sound like a dedicated, supportive coordinator. Keep answers under 3-4 sentences. "
        "CRITICAL PRIVACY DIRECTIVE: To prevent transactional greediness, BloodBridge operates on a strict double-blind anonymity system. "
        "Never reveal any identifying info (names, phone numbers, location details) of a patient to a donor, or a donor to a patient. "
        "If asked about the other party's identity or contact details, explain this privacy policy politely and firmly."
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
