import re
import json
from datetime import datetime, timedelta
from typing import Tuple, Optional, List, Dict, Any
from sqlalchemy.orm import Session
from .config import settings
from .models import User, OutreachEvent, Request, ChatHistory, ChatSession
from .matching import haversine_distance

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

# ----------------- SESSION MEMORY HELPERS -----------------

def get_chat_history(phone: str, db: Session, limit: int = 8) -> str:
    """Retrieves the last N messages for the user's phone, ordered chronologically."""
    history = db.query(ChatHistory).filter(ChatHistory.phone == phone).order_by(ChatHistory.id.desc()).limit(limit).all()
    history.reverse()
    history_text = ""
    for h in history:
        history_text += f"{h.sender.capitalize()}: {h.message}\n"
    return history_text

def save_chat_message(phone: str, sender: str, message: str, db: Session):
    """Saves a message into the chat history table."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    h = ChatHistory(phone=phone, sender=sender, message=message, timestamp=timestamp)
    db.add(h)
    db.commit()

# ----------------- REGISTRATION SLOT NORMALIZATIONS -----------------

def normalize_blood_group(bg: str) -> Optional[str]:
    bg_clean = bg.strip().upper().replace(" ", "")
    mapping = {
        "O+": "O Positive", "OPOS": "O Positive", "OPOSITIVE": "O Positive",
        "O-": "O Negative", "ONEG": "O Negative", "ONEGATIVE": "O Negative",
        "A+": "A Positive", "APOS": "A Positive", "APOSITIVE": "A Positive",
        "A-": "A Negative", "ANEG": "A Negative", "ANEGATIVE": "A Negative",
        "B+": "B Positive", "BPOS": "B Positive", "BPOSITIVE": "B Positive",
        "B-": "B Negative", "BNEG": "B Negative", "BNEGATIVE": "B Negative",
        "AB+": "AB Positive", "ABPOS": "AB Positive", "ABPOSITIVE": "AB Positive",
        "AB-": "AB Negative", "ABNEG": "AB Negative", "ABNEGATIVE": "AB Negative"
    }
    for key, val in mapping.items():
        if bg_clean == key:
            return val
    for val in mapping.values():
        if bg_clean == val.upper().replace(" ", ""):
            return val
    return None

def normalize_gender(gender: str) -> Optional[str]:
    g = gender.strip().lower()
    if g in ["m", "male"]:
        return "Male"
    if g in ["f", "female"]:
        return "Female"
    if g in ["o", "other"]:
        return "Other"
    return None

def normalize_channel(chan: str) -> Optional[str]:
    c = chan.strip().lower()
    if c in ["whatsapp", "wa"]:
        return "WhatsApp"
    if c in ["sms", "text"]:
        return "SMS"
    if c in ["email", "mail"]:
        return "Email"
    return None

def normalize_lang(lang: str) -> Optional[str]:
    l = lang.strip().lower()
    if l in ["english", "eng", "en"]:
        return "English"
    if l in ["hindi", "hin", "hi"]:
        return "Hindi"
    if l in ["telugu", "tel", "te"]:
        return "Telugu"
    if l in ["tamil", "tam", "ta"]:
        return "Tamil"
    return None

# ----------------- REGISTRATION FLOW STATE MACHINE -----------------

def complete_registration(phone: str, data: dict, db: Session) -> str:
    from .main import register_donor
    from .schemas import DonorRegister
    
    payload = DonorRegister(
        name=data["name"],
        phone=phone,
        blood_group=data["blood_group"],
        gender=data["gender"],
        preferred_channel=data["preferred_channel"],
        preferred_language=data["preferred_language"],
        join_bridge=data["join_bridge"]
    )
    
    try:
        new_user = register_donor(payload, db)
        role_desc = "Regular Bridge Donor" if new_user.role == "Bridge Donor" else "Emergency General Donor"
        return (
            f"🎉 Registration Successful! You have been successfully registered as a **{role_desc}**.\n"
            f"• Anonymized pseudoynm: **{new_user.masked_name}**\n"
            f"• Match Group choice: **{'Joined Patient Bridge' if data['join_bridge'] else 'Emergency standby'}**\n"
            f"You can now check your eligibility status by sending 'ELIGIBILITY' or check history with 'HISTORY'. Thank you for joining the Blood Warriors network! ❤️"
        )
    except Exception as e:
        print(f"Error registering user via bot: {e}")
        return "Sorry, I encountered an issue completing your registration. Please try again or contact a coordinator."

def handle_registration_slot(session: ChatSession, text: str, user_phone: str, db: Session) -> str:
    data = json.loads(session.temp_data or "{}")
    step = session.step
    
    if step == 'reg_name':
        # Name input
        name = text.strip().title()
        if len(name) < 2:
            return "Please provide a valid Full Name."
        data["name"] = name
        session.temp_data = json.dumps(data)
        session.step = 'reg_blood'
        db.commit()
        return f"Nice to meet you, {name}! What is your Blood Group? (e.g. O+, A-, B Positive, AB Negative)"
        
    elif step == 'reg_blood':
        bg = normalize_blood_group(text)
        if not bg:
            return "Invalid blood group format. Please specify (e.g., O Positive, A Negative, B+, AB- etc.)."
        data["blood_group"] = bg
        session.temp_data = json.dumps(data)
        session.step = 'reg_gender'
        db.commit()
        return f"Understood, {bg}. What is your Gender? (Male / Female / Other)"
        
    elif step == 'reg_gender':
        gender = normalize_gender(text)
        if not gender:
            return "Invalid gender. Please reply with Male, Female, or Other."
        data["gender"] = gender
        session.temp_data = json.dumps(data)
        session.step = 'reg_channel'
        db.commit()
        return "What is your preferred channel for transfusion alerts? (WhatsApp / SMS / Email)"
        
    elif step == 'reg_channel':
        channel = normalize_channel(text)
        if not channel:
            return "Invalid channel option. Please reply with WhatsApp, SMS, or Email."
        data["preferred_channel"] = channel
        session.temp_data = json.dumps(data)
        session.step = 'reg_lang'
        db.commit()
        return "What is your preferred language for messages? (English / Hindi / Telugu / Tamil)"
        
    elif step == 'reg_lang':
        lang = normalize_lang(text)
        if not lang:
            return "Invalid language. Please choose from English, Hindi, Telugu, or Tamil."
        data["preferred_language"] = lang
        session.temp_data = json.dumps(data)
        session.step = 'reg_bridge'
        db.commit()
        return "Would you like to join a patient bridge to support a specific patient? (Yes / No)\nReply Yes to be assigned to a matched child needing rotating transfusions, or No to notify you only for regional emergencies."
        
    elif step == 'reg_bridge':
        ans = text.strip().lower()
        if ans in ["yes", "y", "ha", "haan"]:
            data["join_bridge"] = True
        elif ans in ["no", "n", "nahi", "na"]:
            data["join_bridge"] = False
        else:
            return "Please reply with Yes or No."
            
        reply = complete_registration(user_phone, data, db)
        db.delete(session)
        db.commit()
        return reply
        
    return "Error: Unknown registration state. Type 'cancel' to restart."

# ----------------- CORE CHATBOT ENGINE -----------------

def query_llm(prompt: str, system_instruction: str) -> Optional[str]:
    """Queries AWS Bedrock (Claude 3.5 Sonnet/Haiku) as the primary engine, with fallbacks to Gemini and OpenAI."""
    # 1. Try AWS Bedrock using boto3
    try:
        import boto3
        import os
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        bedrock = boto3.client(service_name='bedrock-runtime', region_name=region)
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 250,
            "temperature": 0.5,
            "system": system_instruction,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        })
        
        # Candidate model IDs in order of preference
        models = [
            'anthropic.claude-3-5-sonnet-20241022-v2:0',
            'us.anthropic.claude-3-5-sonnet-20241022-v2:0',
            'anthropic.claude-3-5-sonnet-20240620-v1:0',
            'us.anthropic.claude-3-5-sonnet-20240620-v1:0',
            'anthropic.claude-3-5-haiku-20241022-v1:0',
            'us.anthropic.claude-3-5-haiku-20241022-v1:0',
            'anthropic.claude-3-opus-20240229-v1:0',
            'us.anthropic.claude-3-opus-20240229-v1:0'
        ]
        
        for model_id in models:
            try:
                print(f"[CHATBOT] Trying Bedrock model: {model_id}")
                response = bedrock.invoke_model(
                    modelId=model_id,
                    contentType='application/json',
                    accept='application/json',
                    body=body
                )
                response_body = json.loads(response.get('body').read())
                content_list = response_body.get('content', [])
                if content_list and len(content_list) > 0:
                    result = content_list[0].get('text', '').strip()
                    if result:
                        print(f"[CHATBOT] Bedrock invocation succeeded with model: {model_id}")
                        return result
            except Exception as e:
                print(f"[LLM] Bedrock model {model_id} failed: {e}")
    except Exception as e:
        print(f"[LLM] AWS Bedrock client initialization failed: {e}")

    # 2. Fallback to Gemini
    if HAS_GEMINI and settings.GEMINI_API_KEY:
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                system_instruction=system_instruction
            )
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[LLM] Gemini generation failed: {e}")

    # 3. Fallback to OpenAI
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
    Analyzes message intents, executes DB transactions for confirms/declines/rescheduling,
    and falls back to Generative LLM with profile memory and session histories.
    """
    clean_text = text.strip().lower()
    
    # 1. Find or create user
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        user_id = f"guest_{hash(phone) & 0xffffffff:x}"
        user = User(
            id=user_id,
            name="New Guest",
            phone=phone,
            role="Guest",
            role_status=True,
            user_donation_active_status="Active",
            registration_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            eligibility_status="eligible",
            next_eligible_date=datetime.today().strftime("%Y-%m-%d"),
            preferred_channel="WhatsApp",
            preferred_language="English"
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Save incoming user message in history
    save_chat_message(phone, 'user', text, db)

    # 2. Check for active slot-filling session
    session = db.query(ChatSession).filter(ChatSession.phone == phone).first()
    if session:
        if clean_text in ["cancel", "stop", "abort"]:
            db.delete(session)
            db.commit()
            reply = "Registration cancelled. Let me know if you want to start again!"
            save_chat_message(phone, 'bot', reply, db)
            return reply
        
        reply = handle_registration_slot(session, text, phone, db)
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # 3. Check for starting registration intent
    if any(k in clean_text for k in ["register", "become a donor", "join as donor", "sign up"]):
        if phone == "+91 0000000000":
            # Clean up any stale sessions for the demo user
            stale_sess = db.query(ChatSession).filter(ChatSession.phone == phone).first()
            if stale_sess:
                db.delete(stale_sess)
                db.commit()
            new_session = ChatSession(phone=phone, step='reg_name', temp_data='{}')
            db.add(new_session)
            db.commit()
            reply = "Let's register you as a voluntary blood donor! Let's start with your details.\nWhat is your Full Name? (Type 'cancel' at any time to abort)"
            save_chat_message(phone, 'bot', reply, db)
            return reply
        elif user.role != "Guest":
            reply = f"You are already registered as a {user.role}! If you want to check your eligibility, send 'ELIGIBILITY'. To check donation history, send 'HISTORY'."
            save_chat_message(phone, 'bot', reply, db)
            return reply
        else:
            new_session = ChatSession(phone=phone, step='reg_name', temp_data='{}')
            db.add(new_session)
            db.commit()
            reply = "Let's register you as a voluntary blood donor! Let's start with your details.\nWhat is your Full Name? (Type 'cancel' at any time to abort)"
            save_chat_message(phone, 'bot', reply, db)
            return reply

    # 4. Check for privacy questions (identity masking filters)
    privacy_keywords = [
        "who am i donating to", "who is the patient", "patient name", "receiver name", 
        "who got my blood", "patient phone", "patient contact", "who needs my blood", 
        "receiver contact", "donor name", "who is my donor", "who donated", "donor contact",
        "who received my blood", "who received the blood", "whose request", "who is the donor",
        "who provided", "donor details", "patient details", "donor info", "patient info"
    ]
    if any(k in clean_text for k in privacy_keywords):
        if user.role == "Patient":
            reply = (
                "🛡️ **BloodBridge Privacy Protection:**\n"
                "To protect donor privacy and prevent any commercialization of blood donation, "
                "BloodBridge operates on a strict double-blind anonymity system. "
                "We do not share the donor's identity, phone number, or personal details. "
                "Your transfusion request is managed completely autonomously. "
                "Thank you for being a part of this noble network!"
            )
        else:
            reply = (
                "🛡️ **BloodBridge Privacy Protection:**\n"
                "To protect patient privacy and ensure this noble cause remains purely altruistic, "
                "BloodBridge operates on a strict double-blind anonymity system. "
                "We do not share the patient's identity, phone number, or personal details. "
                "When you confirm a donation, you are provided with a secure verification code "
                "to present at the hospital. Thank you for your lifesaving support!"
            )
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # 5. Check for keywords/intents in message
    
    # 5. Check for keywords/intents in message
    lang = user.preferred_language or "English"
    if lang not in ["English", "Hindi", "Telugu", "Tamil"]:
        lang = "English"

    # A. Confirmation flow: CONFIRM
    if "confirm" in clean_text:
        pending_outreach = db.query(OutreachEvent).filter(
            OutreachEvent.donor_id == user.id,
            OutreachEvent.response == "pending"
        ).order_by(OutreachEvent.id.desc()).first()
        
        if pending_outreach:
            pending_outreach.response = "confirmed"
            pending_outreach.response_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            sent_dt = datetime.strptime(pending_outreach.sent_at, "%Y-%m-%d %H:%M:%S")
            now_dt = datetime.now()
            pending_outreach.response_time_mins = float(round((now_dt - sent_dt).total_seconds() / 60.0, 1))
            
            token = f"BB-{(hash(f'{pending_outreach.request_id}-{pending_outreach.donor_id}-{now_dt.timestamp()}') & 0xffffff):06X}"
            pending_outreach.verification_token = token
            
            req = db.query(Request).filter(Request.id == pending_outreach.request_id).first()
            if req:
                req.status = "in_progress"
            
            db.commit()
            
            if lang == "Hindi":
                reply = (
                    f"धन्यवाद {user.name}! ❤️ आपने अपने रक्तदान की पुष्टि की है। "
                    f"मरीज और दाता की गोपनीयता की रक्षा के लिए, आपका सुरक्षित सत्यापन कोड **{token}** है। "
                    f"कृपया रक्तदान करते समय इसे अस्पताल के ब्लड बैंक में दिखाएं। "
                    f"यह पूरी तरह से अज्ञात है। जीवन बचाने के लिए धन्यवाद!"
                )
            elif lang == "Telugu":
                reply = (
                    f"ధన్యవాదాలు {user.name}! ❤️ మీరు రక్తం దానం చేయడానికి అంగీకరించారు. "
                    f"రోగి మరియు దాత గోప్యతను కాపాడటానికి, మీ సురక్షిత కోడ్ **{token}**. "
                    f"దయచేసి రక్తదానం చేసేటప్పుడు ఆసుపత్రి బ్లడ్ బ్యాంక్‌లో ఈ కోడ్‌ను చూపించండి. "
                    f"ఈ లావాదేవీ పూర్తిగా అనామకమైనది. సహాయం చేసినందుకు ధన్యవాదాలు!"
                )
            elif lang == "Tamil":
                reply = (
                    f"நன்றி {user.name}! ❤️ உங்கள் இரத்த தானத்தை உறுதிப்படுத்தியுள்ளீர்கள். "
                    f"நோயாளி மற்றும் கொடையாளரின் தனியுரிமையைப் பாதுகாக்க, உங்கள் பாதுகாப்பான குறியீடு **{token}** ஆகும். "
                    f"இரத்த தானம் செய்யும் போது மருத்துவமனை இரத்த வங்கியில் இதைச் சமர்ப்பிக்கவும். "
                    f"இந்த பரிவர்த்தனை முற்றிலும் அநாமதேயமானது. உங்கள் ஆதரவுக்கு நன்றி!"
                )
            else:
                reply = (
                    f"Thank you {user.name}! ❤️ You have confirmed your donation intent. "
                    f"To protect patient and donor privacy, your secure donation verification code is **{token}**. "
                    f"Please present this code at the hospital blood bank when donating. "
                    f"The transaction is fully anonymous. Thank you for your lifesaving support!"
                )
        else:
            if lang == "Hindi":
                reply = "आपके पास कोई लंबित रक्तदान अनुरोध नहीं है। संपर्क करने के लिए धन्यवाद!"
            elif lang == "Telugu":
                reply = "మీకు ఎటువంటి పెండింగ్ విరాళం అభ్యర్థనలు లేవు. సంప్రదించినందుకు ధన్యవాదాలు!"
            elif lang == "Tamil":
                reply = "உங்களுக்கு நிலுவையில் உள்ள இரத்த தான கோரிக்கைகள் எதுவும் இல்லை. தொடர்பு கொண்டதற்கு நன்றி!"
            else:
                reply = "You do not have any pending donation requests. Thank you for checking in!"
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # B. Decline flow: DECLINE
    if "decline" in clean_text:
        pending_outreach = db.query(OutreachEvent).filter(
            OutreachEvent.donor_id == user.id,
            OutreachEvent.response == "pending"
        ).order_by(OutreachEvent.id.desc()).first()
        
        if pending_outreach:
            pending_outreach.response = "declined"
            pending_outreach.response_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            now_dt = datetime.now()
            user.next_eligible_date = (now_dt + timedelta(days=30)).strftime("%Y-%m-%d")
            user.eligibility_status = "not eligible"
            user.last_contacted_date = now_dt.strftime("%Y-%m-%d")
            db.commit()
            
            if lang == "Hindi":
                reply = f"समझा, {user.name}। हमने आपकी स्थिति अपडेट कर दी है और अगले 30 दिनों के लिए अनुरोधों को रोक दिया है। अपना ख्याल रखें!"
            elif lang == "Telugu":
                reply = f"అర్థమైంది, {user.name}. మేము మీ స్థితిని నవీకరించాము మరియు తదుపరి 30 రోజుల వరకు అభ్యర్థనలను నిలిపివేస్తున్నాము. జాగ్రత్తగా ఉండండి!"
            elif lang == "Tamil":
                reply = f"புரிந்து கொள்ளப்பட்டது, {user.name}. உங்கள் நிலையை நாங்கள் புதுப்பித்துள்ளோம், அடுத்த 30 நாட்களுக்கு கோரிக்கைகளை நிறுத்தி வைப்போம். உடலை கவனித்துக் கொள்ளுங்கள்!"
            else:
                reply = f"Understood, {user.name}. We have updated your status and will snooze requests for the next 30 days. Take care!"
        else:
            if lang == "Hindi":
                reply = "कोई लंबित अनुरोध नहीं मिला। यदि आप रक्तदान से ब्रेक लेना चाहते हैं, तो कृपया पोर्टल में अपनी उपलब्धता अपडेट करें। धन्यवाद!"
            elif lang == "Telugu":
                reply = "పెండింగ్ అభ్యర్థనలు ఏవీ కనుగొనబడలేదు. మీరు విరాళాల నుండి విరామం తీసుకోవాలనుకుంటే, దయచేసి పోర్టల్‌లో మీ లభ్యతను అప్‌డేట్ చేయండి. ధన్యవాదాలు!"
            elif lang == "Tamil":
                reply = "நிலுவையில் உள்ள கோரிக்கைகள் எதுவும் இல்லை. நீங்கள் தற்காலிகமாக ஓய்வெடுக்க விரும்பினால், போர்ட்டலில் உங்கள் இருப்பைப் புதுப்பிக்கவும். நன்றி!"
            else:
                reply = "No pending requests found. If you wish to take a break from donations, please update your availability in the portal. Thank you!"
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # C. Reschedule flow: RESCHEDULE
    if any(k in clean_text for k in ["reschedule", "change date", "postpone"]):
        # Find latest confirmed outreach event for this user
        confirmed_outreach = db.query(OutreachEvent).filter(
            OutreachEvent.donor_id == user.id,
            OutreachEvent.response == "confirmed"
        ).order_by(OutreachEvent.id.desc()).first()
        
        if confirmed_outreach:
            req = db.query(Request).filter(Request.id == confirmed_outreach.request_id).first()
            if req:
                # Postpone by 7 days default
                current_need_by = datetime.strptime(req.needed_by.split()[0], "%Y-%m-%d")
                new_need_by = (current_need_by + timedelta(days=7)).strftime("%Y-%m-%d")
                req.needed_by = new_need_by
                db.commit()
                if lang == "Hindi":
                    reply = f"बिल्कुल, हमने आपके निर्धारित रक्तदान अनुरोध (ID: {req.id}) को 7 दिनों के लिए टाल दिया है। नई तिथि **{new_need_by}** है। हम मरीज और NGO समन्वयक को सूचित कर देंगे। धन्यवाद!"
                elif lang == "Telugu":
                    reply = f"ఖచ్చితంగా, మేము మీ షెడ్యూల్ చేసిన విరాళం అభ్యర్థనను (ID: {req.id}) 7 రోజులు వాయిదా వేసాము. కొత్త తేదీ **{new_need_by}**. మేము రోగి మరియు NGO సమన్వయకర్తకు తెలియజేస్తాము. ధన్యవాదాలు!"
                elif lang == "Tamil":
                    reply = f"நிச்சயமாக, உங்கள் இரத்த தான கோரிக்கையை (ID: {req.id}) 7 நாட்கள் ஒத்திவைத்துள்ளோம். புதிய தேதி **{new_need_by}**. நாங்கள் நோயாளி மற்றும் NGO ஒருங்கிணைப்பாளருக்கு அறிவிப்போம். நன்றி!"
                else:
                    reply = f"Sure, we have postponed your scheduled donation request (ID: {req.id}) by 7 days. The new expected date is **{new_need_by}**. We will update the patient and NGO coordinator. Thank you!"
            else:
                if lang == "Hindi":
                    reply = "आपके पुष्टि किए गए दान से जुड़ा कोई सक्रिय अनुरोध नहीं मिला। कृपया समन्वयक से संपर्क करें।"
                elif lang == "Telugu":
                    reply = "మీరు నిర్ధారించిన విరాళానికి లింక్ చేయబడిన సక్రియ అభ్యర్థన కనుగొనబడలేదు. దయచేసి సమన్వయకర్తను సంప్రదించండి।"
                elif lang == "Tamil":
                    reply = "உறுதிப்படுத்தப்பட்ட தானத்துடன் இணைக்கப்பட்ட எந்தவொரு கோரிக்கையையும் கண்டறிய முடியவில்லை. தயவுசெய்து ஒருங்கிணைப்பாளரைத் தொடர்பு கொள்ளவும்।"
                else:
                    reply = "Could not find an active request linked to your confirmed donation. Please contact the coordinator."
        else:
            if lang == "Hindi":
                reply = "आपके पास स्थगित करने के लिए कोई सक्रिय पुष्टि किया गया रक्तदान अनुरोध नहीं है। पंजीकरण या उपलब्धता अपडेट करने के लिए HELP टाइप करें।"
            elif lang == "Telugu":
                reply = "మీకు వాయిదా వేయడానికి ఎటువంటి సక్రియ నిర్ధారించబడిన విరాళం అభ్యర్థనలు లేవు. రిజిస్టర్ లేదా లభ్యతను అప్‌డేట్ చేయడానికి HELP అని టైప్ చేయండి।"
            elif lang == "Tamil":
                reply = "உங்களிடம் ஒத்திவைக்க உறுதிப்படுத்தப்பட்ட இரத்த தான கோரிக்கைகள் எதுவும் இல்லை. பதிவு செய்ய அல்லது உங்கள் இருப்பைப் புதுப்பிக்க HELP என டைப் செய்யவும்।"
            else:
                reply = "You do not have any active confirmed donation requests to reschedule. If you want to register or update availability, type HELP."
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # D. Availability snooze: SNOOZE
    if "snooze" in clean_text:
        # Check for duration input (e.g. snooze 15 days)
        days = 30
        match = re.search(r"snooze\s+(\d+)", clean_text)
        if match:
            days = int(match.group(1))
            
        now_dt = datetime.now()
        user.next_eligible_date = (now_dt + timedelta(days=days)).strftime("%Y-%m-%d")
        user.eligibility_status = "not eligible"
        db.commit()
        if lang == "Hindi":
            reply = f"समझा, {user.name}। हमने आपकी उपलब्धता को 'not eligible' पर अपडेट कर दिया है और अगले **{days} दिनों** के लिए सभी अनुरोधों को रोक दिया है। अपना ख्याल रखें!"
        elif lang == "Telugu":
            reply = f"అర్థమైంది, {user.name}. మేము మీ లభ్యతను నిలిపివేసి, తదుపరి **{days} రోజుల** వరకు అన్ని అభ్యర్థనలను ఆపివేసాము. జాగ్రత్తగా ఉండండి!"
        elif lang == "Tamil":
            reply = f"புரிந்து கொள்ளப்பட்டது, {user.name}. உங்கள் இருப்பை தற்காலிகமாக நிறுத்தி, அடுத்த **{days} நாட்களுக்கு** அனைத்து கோரிக்கைகளையும் ஒத்திவைத்துள்ளோம். உடலை கவனித்துக் கொள்ளுங்கள்!"
        else:
            reply = f"Understood, {user.name}. We have updated your availability status to not eligible and snoozed all requests for the next **{days} days**. Take care!"
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # E. Find Nearest Blood Bank
    if any(k in clean_text for k in ["blood bank", "nearest bank", "where to donate", "center"]):
        # Major blood banks in Hyderabad
        banks = [
            {"name": "Aarohi Blood Center (Madhapur)", "lat": 17.43, "lon": 78.38},
            {"name": "NTR Trust Blood Bank (Banjara Hills)", "lat": 17.42, "lon": 78.43},
            {"name": "Gandhi Hospital Blood Bank (Secunderabad)", "lat": 17.42, "lon": 78.50},
            {"name": "Red Cross Blood Bank (Adikmet)", "lat": 17.40, "lon": 78.48},
            {"name": "Chiranjeevi Blood Bank (Jubilee Hills)", "lat": 17.43, "lon": 78.44}
        ]
        
        ulat = user.latitude or 17.39
        ulon = user.longitude or 78.46
        
        bank_distances = []
        for b in banks:
            dist = haversine_distance(ulat, ulon, b["lat"], b["lon"])
            bank_distances.append((b["name"], dist))
            
        bank_distances.sort(key=lambda x: x[1])
        
        if lang == "Hindi":
            reply = "🏥 **निकटतम संगत रक्त केंद्र:**\n"
            for name, dist in bank_distances[:3]:
                reply += f"• **{name}**: {dist:.1f} किमी दूर\n"
            reply += "कृपया रक्तदान करते समय अपना अज्ञात टोकन `BB-XXXXXX` प्रस्तुत करें।"
        elif lang == "Telugu":
            reply = "🏥 **సమీపంలోని సరిపోయే బ్లడ్ బ్యాంకులు:**\n"
            for name, dist in bank_distances[:3]:
                reply += f"• **{name}**: {dist:.1f} కి.మీ దూరంలో ఉంది\n"
            reply += "దయచేసి రక్తదానం చేసేటప్పుడు మీ అనామక టోకెన్ `BB-XXXXXX` ను చూపించండి।"
        elif lang == "Tamil":
            reply = "🏥 **அருகிலுள்ள இணக்கமான இரத்த வங்கிகள்:**\n"
            for name, dist in bank_distances[:3]:
                reply += f"• **{name}**: {dist:.1f} கி.மீ தொலைவில் உள்ளது\n"
            reply += "இரத்த தானம் செய்யும் போது உங்கள் அநாமதேய குறியீடு `BB-XXXXXX` ஐச் சமர்ப்பிக்கவும்।"
        else:
            reply = "🏥 **Nearest Compatible Blood Centers:**\n"
            for name, dist in bank_distances[:3]:
                reply += f"• **{name}**: {dist:.1f} km away\n"
            reply += "Please present your anonymous token `BB-XXXXXX` when donating."
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # F. Eligibility check
    if any(k in clean_text for k in ["eligib", "avail", "can i donate"]):
        if user.role == "Patient":
            if lang == "Hindi":
                reply = "एक पंजीकृत रोगी के रूप में, आपको ब्लड ब्रिज सहायता मिल रही है। यदि आप अपने निर्धारित रक्त आधान की तिथियों की जांच करना चाहते हैं, तो STATUS का उत्तर दें।"
            elif lang == "Telugu":
                reply = "నమోదిత రోగిగా, మీరు బ్లడ్ బ్రిడ్జ్ మద్దతును పొందుతున్నారు. మీ తదుపరి రక్తదాన తేదీలను తనిఖీ చేయాలనుకుంటే, STATUS అని రిప్లై ఇవ్వండి।"
            elif lang == "Tamil":
                reply = "பதிவுசெய்யப்பட்ட நோயாளியாக, நீங்கள் இரத்த தான ஆதரவைப் பெறுகிறீர்கள். உங்கள் இரத்த தான தேதிகளைச் சரிபார்க்க விரும்பினால், STATUS எனப் பதிலளிக்கவும்।"
            else:
                reply = "As a registered Patient, you are receiving blood bridge support. If you want to check your scheduled transfusion dates, reply with STATUS."
        elif user.role == "Guest":
            if lang == "Hindi":
                reply = "आप वर्तमान में एक अतिथि के रूप में लॉग इन हैं। एक स्वैच्छिक रक्तदाता के रूप में पंजीकरण करने और अपनी पात्रता सत्यापित करने के लिए 'REGISTER' भेजें!"
            elif lang == "Telugu":
                reply = "మీరు ప్రస్తుతం అతిథిగా సైన్ ఇన్ చేసారు. స్వచ్ఛంద రక్తదాతగా నమోదు చేసుకోవడానికి మరియు మీ అర్హతను ధృవీకరించడానికి 'REGISTER' పంపండి!"
            elif lang == "Tamil":
                reply = "நீங்கள் தற்போது விருந்தினராக உள்நுழைந்துள்ளீர்கள். தானாக முன்வந்து இரத்த தானம் செய்ய பதிவு செய்ய மற்றும் உங்கள் தகுதியை சரிபார்க்க 'REGISTER' அனுப்பவும்!"
            else:
                reply = "You are currently signed in as a Guest. Send 'REGISTER' to sign up as a voluntary blood donor and verify your eligibility!"
        elif user.eligibility_status == "eligible":
            if lang == "Hindi":
                reply = f"नमस्ते {user.name}, आप वर्तमान में दान करने के लिए पात्र (ELIGIBLE) हैं! 🩸 आपका रक्त समूह {user.blood_group or 'अभी पंजीकृत नहीं है'} है। जब कोई अनुरोध आपसे मेल खाएगा, तो हम आपसे आपके पसंदीदा माध्यम ({user.preferred_channel}) पर संपर्क करेंगे।"
            elif lang == "Telugu":
                reply = f"హలో {user.name}, మీరు ప్రస్తుతం రక్తం దానం చేయడానికి అర్హులు! 🩸 మీ రక్త సమూహం {user.blood_group or 'ఇంకా నమోదు కాలేదు'}. అభ్యర్థన సరిపోలినప్పుడు, మేము మీ ప్రాధాన్యత ఛానెల్ ({user.preferred_channel}) ద్వారా మిమ్మల్ని సంప్రదిస్తాము।"
            elif lang == "Tamil":
                reply = f"வணக்கம் {user.name}, நீங்கள் தற்போது இரத்தம் தானம் செய்ய தகுதியுடையவர்! 🩸 உங்கள் இரத்த வகை {user.blood_group or 'இன்னும் பதிவு செய்யப்படவில்லை'}. பொருத்தமான கோரிக்கை வரும்போது, உங்கள் விருப்பமான ஊடகம் ({user.preferred_channel}) மூலம் உங்களைத் தொடர்புகொள்வோம்।"
            else:
                reply = f"Hi {user.name}, you are currently ELIGIBLE to donate! 🩸 Your blood group is {user.blood_group or 'not registered yet'}. When a transfusion request matches you, we will contact you via your preferred channel ({user.preferred_channel})."
        else:
            next_date = user.next_eligible_date or "unknown"
            if lang == "Hindi":
                reply = f"नमस्ते {user.name}, आप वर्तमान में दान करने के लिए पात्र नहीं हैं। आपकी अगली पात्रता तिथि {next_date} है। आपके धैर्य और मदद करने की इच्छा के लिए धन्यवाद!"
            elif lang == "Telugu":
                reply = f"హలో {user.name}, మీరు ప్రస్తుతం దానం చేయడానికి అర్హులు కారు. మీ తదుపరి అర్హత తేదీ {next_date}. మీ సహనానికి మరియు సహాయం చేయడానికి ముందుకు వచ్చినందుకు ధన్యవాదాలు!"
            elif lang == "Tamil":
                reply = f"வணக்கம் {user.name}, நீங்கள் தற்போது இரத்தம் தானம் செய்ய தகுதியற்றவர். உங்கள் அடுத்த தகுதித் தேதி {next_date} ஆகும். உங்கள் பொறுமைக்கும் உதவ முன்வந்ததற்கும் நன்றி!"
            else:
                reply = f"Hi {user.name}, you are currently not eligible to donate. Your next eligible date is {next_date}. Thank you for your patience and willingness to help!"
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # G. Show history
    if any(k in clean_text for k in ["history", "stat", "donat"]):
        if user.role == "Patient":
            reqs = db.query(Request).filter(Request.patient_id == user.id).all()
            if not reqs:
                if lang == "Hindi":
                    reply = "आपने अभी तक कोई रक्त अनुरोध नहीं किया है।"
                elif lang == "Telugu":
                    reply = "మీరు ఇంకా ఎటువంటి రక్త అభ్యర్థనలు చేయలేదు."
                elif lang == "Tamil":
                    reply = "நீங்கள் இன்னும் எந்த இரத்தக் கோரிக்கையையும் செய்யவில்லை."
                else:
                    reply = "You haven't made any blood requests yet."
            else:
                if lang == "Hindi":
                    reply = f"नमस्ते {user.name}, हमारे नेटवर्क में आपके {len(reqs)} अनुरोध हैं। नवीनतम अनुरोध स्थिति: {reqs[-1].status}।"
                elif lang == "Telugu":
                    reply = f"హలో {user.name}, మా నెట్‌వర్క్‌లో మీకు {len(reqs)} అభ్యర్థనలు ఉన్నాయి. తాజా అభ్యర్థన స్థితి: {reqs[-1].status}."
                elif lang == "Tamil":
                    reply = f"வணக்கம் {user.name}, எங்கள் நெட்வொர்க்கில் உங்களுக்கு {len(reqs)} கோரிக்கைகள் உள்ளன. சமீபத்திய கோரிக்கையின் நிலை: {reqs[-1].status}."
                else:
                    reply = f"Hi {user.name}, you have {len(reqs)} requests in our network. Latest request status: {reqs[-1].status}."
        elif user.role == "Guest":
            if lang == "Hindi":
                reply = "आप एक अतिथि उपयोगकर्ता हैं। आप 'REGISTER' भेजकर अपना दाता पंजीकरण शुरू कर सकते हैं।"
            elif lang == "Telugu":
                reply = "మీరు అతిథి వినియోగదారు. మీరు 'REGISTER' పంపడం ద్వారా మీ దాత నమోదును ప్రారంభించవచ్చు."
            elif lang == "Tamil":
                reply = "நீங்கள் ஒரு விருந்தினராக உள்நுழைந்துள்ளீர்கள். 'REGISTER' அனுப்புவதன் மூலம் உங்கள் பதிவைத் தொடங்கலாம்."
            else:
                reply = "You are a Guest user. You can start your donor registration by sending 'REGISTER'."
        else:
            donations = int(user.donations_till_date) if user.donations_till_date is not None else 0
            last_d = user.last_donation_date or "never"
            if lang == "Hindi":
                reply = f"🌟 **दाता प्रोफ़ाइल — {user.name}**\n- रक्त समूह: {user.blood_group or 'अज्ञात'}\n- कुल दान: {donations}\n- अंतिम दान: {last_d}\n- स्वास्थ्य स्कोर: {user.health_score or 0.0}\nब्लड वारियर बनने के लिए धन्यवाद! 🩸"
            elif lang == "Telugu":
                reply = f"🌟 **దాత ప్రొఫైల్ — {user.name}**\n-రక్త సమూహం: {user.blood_group or 'తెలియదు'}\n- మొత్తం విరాళాలు: {donations}\n- చివరి విరాళం: {last_d}\n- ఆరోగ్య స్కోరు: {user.health_score or 0.0}\nబ్లడ్ వారియర్ అయినందుకు ధన్యవాదాలు! 🩸"
            elif lang == "Tamil":
                reply = f"🌟 **கொடையாளர் சுயவிவரம் — {user.name}**\n- இரத்த வகை: {user.blood_group or 'தெரியவில்லை'}\n- மொத்த தானங்கள்: {donations}\n- கடைசி தானம்: {last_d}\n- சுகாதார மதிப்பெண்: {user.health_score or 0.0}\nஇரத்த வாரியராக இருப்பதற்கு நன்றி! 🩸"
            else:
                reply = f"🌟 **Donor Profile — {user.name}**\n- Blood Group: {user.blood_group or 'Unknown'}\n- Total Donations: {donations}\n- Last Donation: {last_d}\n- Health Score: {user.health_score or 0.0}\nThank you for being a Blood Warrior! 🩸"
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # H. Request status
    if "status" in clean_text:
        latest_req = None
        if user.role == "Patient":
            latest_req = db.query(Request).filter(Request.patient_id == user.id).order_by(Request.id.desc()).first()
        else:
            latest_req = db.query(Request).order_by(Request.id.desc()).first()
            
        if not latest_req:
            if lang == "Hindi":
                reply = "सिस्टम में अभी कोई सक्रिय अनुरोध नहीं है।"
            elif lang == "Telugu":
                reply = "సిస్టమ్‌లో ప్రస్తుతం ఎటువంటి సక్రియ అభ్యర్థనలు లేవు."
            elif lang == "Tamil":
                reply = "சிஸ்டத்தில் தற்போது செயலில் உள்ள கோரிக்கைகள் எதுவும் இல்லை."
            else:
                reply = "There are no active requests in the system right now."
        else:
            if lang == "Hindi":
                reply = f"अनुरोध ID {latest_req.id} की स्थिति: **{latest_req.status.upper()}**। आवश्यकता तिथि: {latest_req.needed_by}।"
            elif lang == "Telugu":
                reply = f"అభ్యర్థన ID {latest_req.id} స్థితి: **{latest_req.status.upper()}**. చివరి తేదీ: {latest_req.needed_by}."
            elif lang == "Tamil":
                reply = f"கோரிக்கை ID {latest_req.id} நிலை: **{latest_req.status.upper()}**. தேவைப்படும் தேதி: {latest_req.needed_by}."
            else:
                reply = f"Request ID {latest_req.id} status is: **{latest_req.status.upper()}**. Needed by: {latest_req.needed_by}."
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # I. Help command
    if "help" in clean_text:
        if lang == "Hindi":
            reply = (
                "🤖 **वीरू 2.0 कमांड:**\n"
                "• **ELIGIBILITY**: जांचें कि क्या आप रक्तदान कर सकते हैं\n"
                "• **HISTORY**: अपने दान के आंकड़े देखें\n"
                "• **STATUS**: वर्तमान अनुरोध की स्थिति जांचें\n"
                "• **CONFIRM**: लंबित रक्तदान अनुरोध स्वीकार करें\n"
                "• **DECLINE**: वर्तमान अनुरोध को 30 दिनों के लिए टालें\n"
                "• **RESCHEDULE**: एक पुष्ट अनुरोध को 7 दिनों के लिए स्थगित करें\n"
                "• **SNOOZE [दिन]**: अलर्ट को अस्थायी रूप से रोकें (जैसे, snooze 15)\n"
                "• **BLOOD BANK**: निकटतम संगत केंद्र खोजें\n"
                "• **REGISTER**: दाता पंजीकरण शुरू करें"
            )
        elif lang == "Telugu":
            reply = (
                "🤖 **వీరు 2.0 కమాండ్లు:**\n"
                "• **ELIGIBILITY**: మీరు రక్తం దానం చేయవచ్చో లేదో తనిఖీ చేయండి\n"
                "• **HISTORY**: మీ విరాళాల గణాంకాలను చూడండి\n"
                "• **STATUS**: ప్రస్తుత అభ్యర్థన స్థితిని తనిఖీ చేయండి\n"
                "• **CONFIRM**: పెండింగ్ విరాళం అభ్యర్థనను ఆమోదించండి\n"
                "• **DECLINE**: ప్రస్తుత అభ్యర్థనను 30 రోజులు నిలిపివేయండి\n"
                "• **RESCHEDULE**: నిర్ధారించబడిన అభ్యర్థనను 7 రోజులు వాయిదా వేయండి\n"
                "• **SNOOZE [రోజులు]**: హెచ్చరికలను తాత్కాలికంగా ఆపివేయండి (ఉదా. snooze 15)\n"
                "• **BLOOD BANK**: సమీపంలోని రక్త కేంద్రాలను కనుగొనండి\n"
                "• **REGISTER**: దాత నమోదును ప్రారంభించండి"
            )
        elif lang == "Tamil":
            reply = (
                "🤖 **வீரு 2.0 கட்டளைகள்:**\n"
                "• **ELIGIBILITY**: நீங்கள் இரத்தம் தானம் செய்ய முடியுமா என்று சரிபார்க்கவும்\n"
                "• **HISTORY**: உங்கள் தான புள்ளிவிவரங்களைக் காண்க\n"
                "• **STATUS**: தற்போதைய கோரிக்கையின் நிலையைச் சரிபார்க்கவும்\n"
                "• **CONFIRM**: நிலுவையில் உள்ள இரத்த தான கோரிக்கையை ஏற்கவும்\n"
                "• **DECLINE**: தற்போதைய கோரிக்கையை 30 நாட்களுக்கு ஒத்திவைக்கவும்\n"
                "• **RESCHEDULE**: உறுதிப்படுத்தப்பட்ட கோரிக்கையை 7 நாட்களுக்கு ஒத்திவைக்கவும்\n"
                "• **SNOOZE [நாட்கள்]**: தற்காலிகமாக விழிப்பூட்டல்களை நிறுத்தவும் (எ.கா. snooze 15)\n"
                "• **BLOOD BANK**: அருகிலுள்ள இரத்த வங்கிகளைக் கண்டறியவும்\n"
                "• **REGISTER**: இரத்த தான பதிவு செய்ய தொடங்கவும்"
            )
        else:
            reply = (
                "🤖 **Veeru 2.0 Commands:**\n"
                "• **ELIGIBILITY**: Check if you can donate blood\n"
                "• **HISTORY**: View your donation stats\n"
                "• **STATUS**: Check the status of the current request\n"
                "• **CONFIRM**: Accept a pending donation request\n"
                "• **DECLINE**: Snooze current request for 30 days\n"
                "• **RESCHEDULE**: Postpone a confirmed request by 7 days\n"
                "• **SNOOZE [days]**: Temporarily pause alerts (e.g., snooze 15)\n"
                "• **BLOOD BANK**: Find the nearest compatible centers\n"
                "• **REGISTER**: Start donor slot-filling registration"
            )
        save_chat_message(phone, 'bot', reply, db)
        return reply

    # 6. LLM Fallback with memory
    history_context = get_chat_history(phone, db, limit=8)
    
    system_instruction = (
        "You are Veeru 2.0, an intelligent, empathetic conversational AI chatbot for Blood Warriors, "
        "an NGO supporting Thalassemia patients in India. Keep your answers concise, engaging, and friendly. "
        "Help the user based on their profile and constraints. Never say you are an AI assistant unless asked. "
        "Always sound like a dedicated, supportive coordinator. Keep answers under 3-4 sentences. "
        "Always adapt to and write in the user's preferred language, or detected conversational language (English, Hindi, Telugu, Tamil). "
        "CRITICAL PRIVACY DIRECTIVE: To prevent transactional pressure, BloodBridge operates on a strict double-blind anonymity system. "
        "Never reveal any identifying info (names, phone numbers, location details) of a patient to a donor, or a donor to a patient. "
        "If asked about the other party's identity or contact details, explain this privacy policy politely and firmly."
    )
    
    user_context = (
        f"Conversation History:\n{history_context}\n"
        f"User Profile Details:\n"
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
        f"Latest User message: \"{text}\""
    )
    
    llm_response = query_llm(user_context, system_instruction)
    if llm_response:
        reply = llm_response
    else:
        # Basic Greeting Fallback
        reply = (
            f"Hello {user.name}! I am Veeru 2.0, your Blood Warriors assistant. "
            f"How can I help you today? You can check your 'ELIGIBILITY', view donation 'HISTORY', or check request 'STATUS'."
        )
        
    save_chat_message(phone, 'bot', reply, db)
    return reply
