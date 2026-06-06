import math
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
import joblib
from sqlalchemy.orm import Session
from .models import User, Bridge
from .database import SessionLocal

# Blood compatibility map: key is Patient blood group, value is list of compatible Donor blood groups
COMPATIBILITY_MAP = {
    "O Negative": ["O Negative"],
    "O Positive": ["O Positive", "O Negative"],
    "A Negative": ["A Negative", "O Negative"],
    "A Positive": ["A Positive", "A Negative", "O Positive", "O Negative"],
    "B Negative": ["B Negative", "O Negative"],
    "B Positive": ["B Positive", "B Negative", "O Positive", "O Negative"],
    "AB Negative": ["AB Negative", "A Negative", "B Negative", "O Negative"],
    "AB Positive": ["AB Positive", "AB Negative", "A Positive", "A Negative", "B Positive", "B Negative", "O Positive", "O Negative"]
}

# Load models setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHURN_MODEL_PATH = os.path.join(SCRIPT_DIR, "churn_model.joblib")
RESPONSIVENESS_MODEL_PATH = os.path.join(SCRIPT_DIR, "responsiveness_model.joblib")

_churn_model = None
_responsiveness_model = None

def get_ml_models():
    global _churn_model, _responsiveness_model
    if _churn_model is None or _responsiveness_model is None:
        try:
            if os.path.exists(CHURN_MODEL_PATH) and os.path.exists(RESPONSIVENESS_MODEL_PATH):
                _churn_model = joblib.load(CHURN_MODEL_PATH)
                _responsiveness_model = joblib.load(RESPONSIVENESS_MODEL_PATH)
                print("Successfully loaded local ML models in matching!")
        except Exception as e:
            print(f"Error loading local ML models in matching: {e}")
    return _churn_model, _responsiveness_model

def extract_donor_features(donor: User):
    # 1. Gender encoding
    gender_encoded = 0
    if donor.gender:
        g_str = donor.gender.strip().lower()
        if g_str == "male":
            gender_encoded = 1
        elif g_str == "female":
            gender_encoded = 2
            
    # 2. Blood group encoding
    bg_list = ["O Positive", "O Negative", "A Positive", "A Negative", "B Positive", "B Negative", "AB Positive", "AB Negative"]
    bg_map = {bg: idx + 1 for idx, bg in enumerate(bg_list)}
    blood_group_encoded = bg_map.get(donor.blood_group, 0)
    
    # 3. Donor Type encoding
    donor_type_encoded = 0
    dt = donor.role or donor.donor_type
    if dt:
        dt_str = str(dt).strip().lower()
        if "regular" in dt_str:
            donor_type_encoded = 2
        elif "one-time" in dt_str or "one time" in dt_str:
            donor_type_encoded = 1
            
    # 4. Eligibility status
    eligibility_encoded = 1 if donor.eligibility_status == "eligible" else 0
    
    # 5. Recency calculation
    recency_days = 9999.0
    if donor.last_donation_date:
        try:
            ld_dt = datetime.strptime(str(donor.last_donation_date).split()[0], "%Y-%m-%d")
            current_dt = datetime(2025, 8, 31)
            days = (current_dt - ld_dt).days
            recency_days = float(max(0, days))
        except Exception:
            pass
            
    # 6. Basic numeric features
    donations = float(donor.donations_till_date) if donor.donations_till_date is not None else 0.0
    total_calls = int(donor.total_calls) if donor.total_calls is not None else 0
    calls_ratio = float(donor.calls_to_donations_ratio) if donor.calls_to_donations_ratio is not None else 0.0
    cycle = int(donor.cycle_of_donations) if donor.cycle_of_donations is not None else 90
    
    return [
        gender_encoded,
        blood_group_encoded,
        donor_type_encoded,
        eligibility_encoded,
        recency_days,
        donations,
        total_calls,
        calls_ratio,
        cycle
    ]

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) in kilometers.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 0.0
        
    # convert decimal degrees to radians 
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371 # Radius of earth in kilometers.
    return c * r

def get_days_since_date(date_str: Optional[str]) -> float:
    """Calculate days since a date string (YYYY-MM-DD)."""
    if not date_str:
        return 999.0  # Large default meaning a long time ago
    try:
        dt = datetime.strptime(date_str.split()[0], "%Y-%m-%d")
        current_dt = datetime(2025, 8, 31)  # Anchored local date for dataset consistency
        diff = (current_dt - dt).days
        return float(max(0, diff))
    except Exception:
        return 999.0

def rank_donors(
    db: Session,
    blood_group: str,
    patient_lat: float,
    patient_lon: float,
    gender_preference: Optional[str] = None,
    limit: int = 10,
    force_eligible_only: bool = True
) -> List[Dict[str, Any]]:
    """
    Ranks compatible donors based on proximity, responsiveness (local ML predicted), and preferences.
    """
    compatible_groups = COMPATIBILITY_MAP.get(blood_group, [blood_group])
    
    # Query database for compatible active donors (Bridge Donors and Emergency Donors)
    query = db.query(User).filter(
        User.blood_group.in_(compatible_groups),
        User.role.in_(["Bridge Donor", "Emergency Donor"]),
        User.user_donation_active_status == "Active"
    )
    
    if force_eligible_only:
        query = query.filter(User.eligibility_status == "eligible")
        
    donors = query.all()
    ranked_donors = []
    
    for donor in donors:
        # 1. Proximity Score (Weight: 0.30)
        dist = haversine_distance(patient_lat, patient_lon, donor.latitude, donor.longitude)
        # Score decreases as distance increases. Score is 1 at 0km, 0.5 at 10km, 0.09 at 100km
        proximity_score = 10.0 / (10.0 + dist) if dist > 0 else 1.0
        
        # 2. Responsiveness/Call-to-Donations Score (Weight: 0.25)
        ratio = donor.calls_to_donations_ratio
        if ratio is None or ratio < 0:
            responsiveness_score = 0.5  # Neutral default
        else:
            # Lower ratio is better. 1.0 ratio -> score 0.9. 10+ ratio -> score 0.0
            responsiveness_score = max(0.0, 1.0 - (ratio / 10.0))
            
        # 3. Rotation/Recency Score (Weight: 0.20)
        # We want to prefer donors who have NOT donated in a long time (to prevent burn out)
        days_since_donation = get_days_since_date(donor.last_donation_date)
        # Max out at 1 year (365 days)
        rotation_score = min(days_since_donation / 365.0, 1.0)
        
        # 4. Gender preference match (Weight: 0.15)
        gender_score = 0.0
        if gender_preference:
            if donor.gender == gender_preference:
                gender_score = 1.0
        else:
            gender_score = 1.0  # Full score if no preference
            
        # 5. Experience/Loyalty Score (Weight: 0.10)
        donations = donor.donations_till_date or 0.0
        experience_score = min(donations / 10.0, 1.0)
        
        # Try local ML prediction for responsiveness
        churn_m, resp_m = get_ml_models()
        ml_responsiveness = None
        if resp_m is not None:
            try:
                features = [extract_donor_features(donor)]
                ml_responsiveness = float(resp_m.predict(features)[0])
            except Exception as e:
                print(f"Error predicting responsiveness in matching: {e}")

        # Compute match score
        if ml_responsiveness is not None:
            # ML scoring mode: combines ML responsiveness + Proximity + Gender Pref
            match_score = (
                0.30 * proximity_score +
                0.55 * ml_responsiveness +
                0.15 * gender_score
            )
        else:
            # Heuristic fallback
            match_score = (
                0.30 * proximity_score +
                0.25 * responsiveness_score +
                0.20 * rotation_score +
                0.15 * gender_score +
                0.10 * experience_score
            )
        
        ranked_donors.append({
            "donor_id": donor.id,
            "name": donor.name,
            "phone": donor.phone,
            "blood_group": donor.blood_group,
            "gender": donor.gender,
            "distance_km": round(dist, 2),
            "calls_to_donations_ratio": donor.calls_to_donations_ratio,
            "donations_till_date": donor.donations_till_date,
            "eligibility_status": donor.eligibility_status,
            "match_score": round(match_score, 4),
            "preferred_channel": donor.preferred_channel,
            "preferred_language": donor.preferred_language,
            "health_score": donor.health_score,
            "churn_risk_score": donor.churn_risk_score
        })
        
    # Sort by score descending, then by distance ascending
    ranked_donors.sort(key=lambda x: (-x["match_score"], x["distance_km"]))
    
    return ranked_donors[:limit]
