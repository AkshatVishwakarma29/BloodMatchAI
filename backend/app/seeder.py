import os
import pandas as pd
import numpy as np
import hashlib
from datetime import datetime
from sqlalchemy.orm import Session
from .database import engine, SessionLocal, Base
from .models import User, Bridge, BridgeDonorLink

# Lists of Indian names for deterministic generation
MALE_NAMES = [
    "Aarav", "Aditya", "Arjun", "Amit", "Alok", "Anil", "Abhishek", "Bhavesh", "Deepak",
    "Dinesh", "Gaurav", "Hari", "Ishan", "Jay", "Karan", "Kunal", "Manish", "Nikhil",
    "Pranav", "Rahul", "Rajesh", "Rohan", "Sanjay", "Siddharth", "Sunil", "Tushar",
    "Umesh", "Varun", "Vijay", "Vivek", "Yash"
]

FEMALE_NAMES = [
    "Aadhya", "Ananya", "Avani", "Asha", "Anjali", "Bhavna", "Divya", "Deepika", "Ekta",
    "Geeta", "Ira", "Jyoti", "Kavita", "Kiran", "Lata", "Meera", "Neha", "Nisha",
    "Pooja", "Priya", "Ritu", "Riya", "Saanvi", "Shalini", "Sneha", "Sunita",
    "Tanvi", "Uma", "Vidya", "Yamini", "Zoya"
]

LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Patel", "Reddy", "Rao", "Kumar", "Singh", "Joshi",
    "Mehta", "Nair", "Pillai", "Iyer", "Sen", "Das", "Mukherjee", "Bose", "Chatterjee",
    "Roy", "Choudhury", "Mishra", "Pandey", "Yadav", "Dubey", "Shukla", "Deshmukh",
    "Kulkarni", "Joshi", "Bhatt", "Chawla", "Gill"
]

REGIONAL_LANGUAGES = ["Hindi", "Telugu", "Tamil", "Bengali", "Marathi", "Kannada", "Malayalam", "Gujarati"]
CHANNELS = ["WhatsApp", "SMS", "Email"]

def get_deterministic_int(string_seed: str, max_val: int) -> int:
    """Returns a deterministic integer between 0 and max_val-1 using SHA-256."""
    h = hashlib.sha256(string_seed.encode('utf-8')).hexdigest()
    return int(h, 16) % max_val

def generate_mock_name(user_id: str, gender: str) -> str:
    seed_str = user_id + "_name"
    last_idx = get_deterministic_int(seed_str + "_last", len(LAST_NAMES))
    last_name = LAST_NAMES[last_idx]
    
    if gender == "Male":
        first_idx = get_deterministic_int(seed_str + "_first", len(MALE_NAMES))
        first_name = MALE_NAMES[first_idx]
    elif gender == "Female":
        first_idx = get_deterministic_int(seed_str + "_first", len(FEMALE_NAMES))
        first_name = FEMALE_NAMES[first_idx]
    else:
        # Mix first names
        all_first = MALE_NAMES + FEMALE_NAMES
        first_idx = get_deterministic_int(seed_str + "_first", len(all_first))
        first_name = all_first[first_idx]
        
    return f"{first_name} {last_name}"

def generate_mock_phone(user_id: str) -> str:
    seed_str = user_id + "_phone"
    digits = []
    # Deterministic 8 digits
    for i in range(8):
        digit = get_deterministic_int(seed_str + f"_d{i}", 10)
        digits.append(str(digit))
    # Starting with Indian mobile prefixes (e.g. 98, 97, 96, 95, 91, 88, 77)
    prefixes = ["98", "97", "96", "99", "88", "77", "95"]
    prefix_idx = get_deterministic_int(seed_str + "_pref", len(prefixes))
    prefix = prefixes[prefix_idx]
    return f"+91 {prefix}{''.join(digits)}"

def clean_value(val):
    if pd.isna(val) or val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return val

def clean_float(val):
    cleaned = clean_value(val)
    if cleaned is None:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def clean_int(val):
    cleaned = clean_value(val)
    if cleaned is None:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None

def calculate_health_score(row) -> float:
    """
    Computes a donor health score between 0.0 and 1.0 based on columns.
    Health Score = 0.3 * donations_till_date + 0.25 * (1 - ratio) + 0.2 * recency + 0.15 * eligibility + 0.1 * profile
    """
    # 1. Donations score (normalized, capped at 10 donations)
    donations = clean_float(row.get('donations_till_date')) or 0.0
    donations_score = min(donations / 10.0, 1.0)
    
    # 2. Call-to-donations ratio score
    ratio = clean_float(row.get('calls_to_donations_ratio'))
    if ratio is None:
        ratio_score = 0.5  # Neutral default
    else:
        # Lower ratio is better (1.0 means 1 call for 1 donation, 23.0 means 23 calls for 0 donations)
        # We clamp ratio to [0.5, 10.0] and invert
        ratio_score = max(0.0, 1.0 - (min(ratio, 10.0) / 10.0))
        
    # 3. Recency score (days since last donation)
    last_donation = clean_value(row.get('last_donation_date'))
    if not last_donation:
        recency_score = 0.0
    else:
        try:
            ld_dt = datetime.strptime(str(last_donation).split()[0], "%Y-%m-%d")
            # Assume local current date is around August 2025 (matching dates in the dataset)
            current_dt = datetime(2025, 8, 31)
            days = (current_dt - ld_dt).days
            if days <= 0:
                recency_score = 1.0
            else:
                # Closer to last donation -> higher recency score, but need rotation.
                # Actually, standard donation cycle is 90 days. Ideal recency is 90+ days.
                # So if days > 90, higher score is good. Let's make a simple curve:
                # if donor is eligible (days > 90), score decreases the longer they haven't donated.
                recency_score = max(0.0, 1.0 - (days / 730.0)) # decays over 2 years
        except Exception:
            recency_score = 0.5
            
    # 4. Eligibility score
    eligibility = clean_value(row.get('eligibility_status'))
    eligibility_score = 1.0 if eligibility == 'eligible' else 0.0
    
    # 5. Profile completeness (has gender and blood group)
    gender = clean_value(row.get('gender'))
    bg = clean_value(row.get('blood_group'))
    profile_score = 0.0
    if gender: profile_score += 0.5
    if bg: profile_score += 0.5
    
    # Combined score
    h_score = (
        0.30 * donations_score +
        0.25 * ratio_score +
        0.20 * recency_score +
        0.15 * eligibility_score +
        0.10 * profile_score
    )
    return float(round(h_score, 2))

def calculate_churn_risk(row) -> float:
    """
    Computes a churn risk score between 0.0 and 1.0.
    """
    active_status = clean_value(row.get('user_donation_active_status'))
    ratio = clean_float(row.get('calls_to_donations_ratio')) or 0.0
    total_calls = clean_int(row.get('total_calls')) or 0
    donations = clean_float(row.get('donations_till_date')) or 0.0
    
    if active_status == "Inactive":
        return 1.0
        
    risk = 0.0
    # High call-to-donation ratio indicates donor burnout
    if ratio > 5.0:
        risk += 0.4
    if ratio > 15.0:
        risk += 0.3
        
    # High calls but 0 donations
    if total_calls > 3 and donations == 0:
        risk += 0.5
        
    # Recency check
    last_donation = clean_value(row.get('last_donation_date'))
    if last_donation:
        try:
            ld_dt = datetime.strptime(str(last_donation).split()[0], "%Y-%m-%d")
            current_dt = datetime(2025, 8, 31)
            days = (current_dt - ld_dt).days
            if days > 365:
                risk += 0.3
        except Exception:
            pass
    else:
        # Registered but never donated despite calls
        if total_calls > 0:
            risk += 0.2

    return float(round(min(risk, 1.0), 2))

def seed_database(csv_path: str):
    print(f"Creating database tables...")
    Base.metadata.create_all(bind=engine)
    
    print(f"Reading dataset from {csv_path}...")
    df = pd.read_csv(csv_path)
    print(f"Total rows in CSV: {len(df)}")
    
    db: Session = SessionLocal()
    
    try:
        # To avoid primary key violations, we aggregate users by user_id
        # We group by user_id and select the row with the most complete donor information
        print("Grouping users by user_id...")
        users_to_create = {}
        
        # Sort so that roles with more details (Bridge Donor, Patient, Emergency Donor) come last, overwriting less descriptive rows
        role_priority = {
            'Guest': 1,
            'Volunteer': 2,
            'Emergency Donor': 3,
            'Bridge Donor': 4,
            'Patient': 5
        }
        df['role_priority'] = df['role'].map(role_priority).fillna(0)
        df_sorted = df.sort_values(by='role_priority', ascending=True)
        
        for idx, row in df_sorted.iterrows():
            u_id = clean_value(row['user_id'])
            if not u_id:
                continue
                
            role = clean_value(row['role'])
            gender = clean_value(row['gender'])
            bg = clean_value(row['blood_group'])
            
            # Deterministic mock demographics
            name = generate_mock_name(u_id, gender)
            phone = generate_mock_phone(u_id)
            pref_lang = REGIONAL_LANGUAGES[get_deterministic_int(u_id + "_lang", len(REGIONAL_LANGUAGES))]
            pref_chan = CHANNELS[get_deterministic_int(u_id + "_chan", len(CHANNELS))]
            
            h_score = calculate_health_score(row)
            c_risk = calculate_churn_risk(row)
            
            users_to_create[u_id] = {
                "id": u_id,
                "name": name,
                "phone": phone,
                "role": role,
                "role_status": bool(row.get('role_status', True)),
                "blood_group": bg,
                "gender": gender,
                "latitude": clean_float(row.get('latitude')),
                "longitude": clean_float(row.get('longitude')),
                "registration_date": clean_value(row.get('registration_date')),
                "donor_type": clean_value(row.get('donor_type')),
                "last_contacted_date": clean_value(row.get('last_contacted_date')),
                "last_donation_date": clean_value(row.get('last_donation_date')),
                "next_eligible_date": clean_value(row.get('next_eligible_date')),
                "donations_till_date": clean_float(row.get('donations_till_date')),
                "eligibility_status": clean_value(row.get('eligibility_status')),
                "cycle_of_donations": clean_int(row.get('cycle_of_donations')),
                "total_calls": clean_int(row.get('total_calls')),
                "calls_to_donations_ratio": clean_float(row.get('calls_to_donations_ratio')),
                "user_donation_active_status": clean_value(row.get('user_donation_active_status')),
                "inactive_trigger_comment": clean_value(row.get('inactive_trigger_comment')),
                "preferred_channel": pref_chan,
                "preferred_language": pref_lang,
                "health_score": h_score,
                "churn_risk_score": c_risk
            }
            
        print(f"Unique users to insert: {len(users_to_create)}")
        
        # Save users
        user_objects = []
        for u_id, u_data in users_to_create.items():
            user_objects.append(User(**u_data))
        
        db.bulk_save_objects(user_objects)
        db.commit()
        print("Users successfully seeded.")
        
        # Now seed bridges
        # A bridge belongs to a patient. We look for rows with role='Patient' and a valid bridge_id
        print("Seeding bridges...")
        bridges_to_create = {}
        patient_rows = df[df['role'] == 'Patient']
        
        for idx, row in patient_rows.iterrows():
            b_id = clean_value(row['bridge_id'])
            u_id = clean_value(row['user_id'])
            if not b_id or not u_id:
                continue
                
            bridges_to_create[b_id] = {
                "id": b_id,
                "patient_id": u_id,
                "bridge_status": bool(row.get('bridge_status', True)),
                "bridge_gender": clean_value(row.get('bridge_gender')),
                "bridge_blood_group": clean_value(row.get('bridge_blood_group')),
                "quantity_required": clean_float(row.get('quantity_required')),
                "last_transfusion_date": clean_value(row.get('last_transfusion_date')),
                "expected_next_transfusion_date": clean_value(row.get('expected_next_transfusion_date')),
                "frequency_in_days": clean_int(row.get('frequency_in_days')),
                "status_of_bridge": bool(row.get('status_of_bridge', True))
            }
            
        # If there are other bridges in the dataset that do not have a role='Patient' row,
        # we can seed them by finding any row with that bridge_id and mocking a patient user if necessary
        all_bridge_ids = df['bridge_id'].dropna().unique()
        for b_id in all_bridge_ids:
            if b_id not in bridges_to_create:
                # Find any row with this bridge_id
                bridge_rows = df[df['bridge_id'] == b_id]
                first_row = bridge_rows.iloc[0]
                
                # Create a mock patient for this bridge
                mock_patient_id = f"mock_patient_{b_id[:10]}"
                mock_patient_name = f"Patient {generate_mock_name(b_id, 'Male')}"
                mock_patient_phone = generate_mock_phone(b_id + "_pat")
                
                # Check if mock patient already exists
                existing_pat = db.query(User).filter(User.id == mock_patient_id).first()
                if not existing_pat:
                    mock_pat = User(
                        id=mock_patient_id,
                        name=mock_patient_name,
                        phone=mock_patient_phone,
                        role="Patient",
                        blood_group=clean_value(first_row.get('bridge_blood_group')) or "O Positive",
                        gender="Male",
                        latitude=clean_float(first_row.get('latitude')) or 17.392,
                        longitude=clean_float(first_row.get('longitude')) or 78.460,
                        registration_date="2020-01-01 00:00:00",
                        user_donation_active_status="Active"
                    )
                    db.add(mock_pat)
                    db.commit()
                
                bridges_to_create[b_id] = {
                    "id": b_id,
                    "patient_id": mock_patient_id,
                    "bridge_status": bool(first_row.get('bridge_status', True)),
                    "bridge_gender": clean_value(first_row.get('bridge_gender')),
                    "bridge_blood_group": clean_value(first_row.get('bridge_blood_group')),
                    "quantity_required": clean_float(first_row.get('quantity_required')) or 1.0,
                    "last_transfusion_date": clean_value(first_row.get('last_transfusion_date')),
                    "expected_next_transfusion_date": clean_value(first_row.get('expected_next_transfusion_date')),
                    "frequency_in_days": clean_int(first_row.get('frequency_in_days')) or 90,
                    "status_of_bridge": bool(first_row.get('status_of_bridge', True))
                }
                
        print(f"Total bridges to insert: {len(bridges_to_create)}")
        bridge_objects = []
        for b_id, b_data in bridges_to_create.items():
            bridge_objects.append(Bridge(**b_data))
            
        db.bulk_save_objects(bridge_objects)
        db.commit()
        print("Bridges successfully seeded.")
        
        # Link Bridge Donors to Bridges
        # Rows where role='Bridge Donor' (or Volunteer with a bridge_id)
        print("Linking donors to bridges...")
        donor_rows = df[(df['role'] == 'Bridge Donor') & (df['bridge_id'].notna())]
        
        links_to_create = []
        seen_links = set()
        
        for idx, row in donor_rows.iterrows():
            b_id = clean_value(row['bridge_id'])
            u_id = clean_value(row['user_id'])
            if not b_id or not u_id:
                continue
                
            link_key = (b_id, u_id)
            if link_key not in seen_links:
                seen_links.add(link_key)
                links_to_create.append(
                    BridgeDonorLink(bridge_id=b_id, donor_id=u_id)
                )
                
        print(f"Total bridge-donor relationships to create: {len(links_to_create)}")
        db.bulk_save_objects(links_to_create)
        db.commit()
        print("Bridge-donor links successfully seeded.")
        
        # Verify seeding counts
        users_count = db.query(User).count()
        bridges_count = db.query(Bridge).count()
        links_count = db.query(BridgeDonorLink).count()
        
        print(f"\nSeeding Verification:")
        print(f"- Total Users: {users_count}")
        print(f"- Total Bridges: {bridges_count}")
        print(f"- Total Bridge-Donor Links: {links_count}")
        print(f"  Guest users: {db.query(User).filter(User.role == 'Guest').count()}")
        print(f"  Emergency donors: {db.query(User).filter(User.role == 'Emergency Donor').count()}")
        print(f"  Bridge donors: {db.query(User).filter(User.role == 'Bridge Donor').count()}")
        print(f"  Patients: {db.query(User).filter(User.role == 'Patient').count()}")
        print(f"  Volunteers: {db.query(User).filter(User.role == 'Volunteer').count()}")
        
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    # CSV is located at root
    csv_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Dataset.csv")
    seed_database(csv_file)
