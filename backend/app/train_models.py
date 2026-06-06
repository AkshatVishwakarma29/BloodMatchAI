import os
import pandas as pd
import numpy as np
import joblib
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.preprocessing import LabelEncoder

# Anchored current date to align with dataset timestamps (August 2025)
CURRENT_DATE = datetime(2025, 8, 31)

def parse_date(date_str):
    if pd.isna(date_str) or not isinstance(date_str, str) or date_str.strip() == "":
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None

def main():
    # Setup paths relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(os.path.dirname(script_dir))
    csv_path = os.path.join(base_dir, "Dataset.csv")
    
    print(f"Loading dataset from: {csv_path}")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Could not find Dataset.csv at {csv_path}")
        
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows. Filtering for donors to train models...")
    
    # Filter for donors (role contains "Donor")
    df_donors = df[df["role"].str.contains("Donor", na=False, case=False)].copy()
    print(f"Found {len(df_donors)} donors.")
    
    # ----------------- FEATURE ENGINEERING -----------------
    
    # 1. Gender encoding (Male = 1, Female = 2, Missing/Other = 0)
    def encode_gender(g):
        if pd.isna(g):
            return 0
        g_str = str(g).strip().lower()
        if g_str == "male":
            return 1
        elif g_str == "female":
            return 2
        return 0
    df_donors["gender_encoded"] = df_donors["gender"].apply(encode_gender)
    
    # 2. Blood group encoding (categorical maps to numeric)
    bg_list = ["O Positive", "O Negative", "A Positive", "A Negative", "B Positive", "B Negative", "AB Positive", "AB Negative"]
    bg_map = {bg: idx + 1 for idx, bg in enumerate(bg_list)}
    df_donors["blood_group_encoded"] = df_donors["blood_group"].map(bg_map).fillna(0).astype(int)
    
    # 3. Donor Type encoding (Regular = 2, One-Time = 1, Other = 0)
    def encode_donor_type(dt):
        if pd.isna(dt):
            return 0
        dt_str = str(dt).strip().lower()
        if "regular" in dt_str:
            return 2
        elif "one-time" in dt_str or "one time" in dt_str:
            return 1
        return 0
    df_donors["donor_type_encoded"] = df_donors["donor_type"].apply(encode_donor_type)
    
    # 4. Eligibility status encoding (eligible = 1, not eligible = 0)
    df_donors["eligibility_encoded"] = df_donors["eligibility_status"].apply(
        lambda e: 1 if str(e).strip().lower() == "eligible" else 0
    )
    
    # 5. Recency calculation (days since last donation)
    def get_recency_days(last_don_date):
        dt = parse_date(last_don_date)
        if dt:
            days = (CURRENT_DATE - dt).days
            return max(0, days)
        return 9999.0  # Large value representing no recent donations
    df_donors["recency_days"] = df_donors["last_donation_date"].apply(get_recency_days)
    
    # 6. Basic numeric features
    df_donors["donations_till_date"] = pd.to_numeric(df_donors["donations_till_date"], errors="coerce").fillna(0.0)
    df_donors["total_calls"] = pd.to_numeric(df_donors["total_calls"], errors="coerce").fillna(0).astype(int)
    df_donors["calls_to_donations_ratio"] = pd.to_numeric(df_donors["calls_to_donations_ratio"], errors="coerce").fillna(0.0)
    df_donors["cycle_of_donations"] = pd.to_numeric(df_donors["cycle_of_donations"], errors="coerce").fillna(90.0)
    
    # ----------------- TARGET ENGINEERING -----------------
    
    # Target 1: Churn Status (1 if Inactive, 0 if Active)
    df_donors["is_churned"] = df_donors["user_donation_active_status"].apply(
        lambda status: 1 if str(status).strip().lower() == "inactive" else 0
    )
    
    # Target 2: Composite Health/Responsiveness Score (0.0 to 1.0)
    # Replicates our business logic for training regression labels:
    # 0.3*norm_donations + 0.25*calls_ratio_score + 0.2*recency_score + 0.15*eligibility_score + 0.1*profile
    norm_donations = (df_donors["donations_till_date"] / 10.0).clip(0.0, 1.0)
    calls_ratio_score = (1.0 - (df_donors["calls_to_donations_ratio"] / 10.0)).clip(0.0, 1.0)
    recency_score = (1.0 - (df_donors["recency_days"] / 730.0)).clip(0.0, 1.0)
    eligibility_score = df_donors["eligibility_encoded"]
    
    # profile completeness (has gender and blood group)
    profile_score = (df_donors["gender"].notna().astype(float) * 0.5) + (df_donors["blood_group"].notna().astype(float) * 0.5)
    
    df_donors["responsiveness_score_target"] = (
        0.30 * norm_donations +
        0.25 * calls_ratio_score +
        0.20 * recency_score +
        0.15 * eligibility_score +
        0.10 * profile_score
    )
    
    # Define features for training
    feature_cols = [
        "gender_encoded",
        "blood_group_encoded",
        "donor_type_encoded",
        "eligibility_encoded",
        "recency_days",
        "donations_till_date",
        "total_calls",
        "calls_to_donations_ratio",
        "cycle_of_donations"
    ]
    
    X = df_donors[feature_cols].copy()
    
    # 1. Train Churn Model
    y_churn = df_donors["is_churned"]
    print("Training Churn RandomForest Classifier...")
    churn_model = RandomForestClassifier(n_estimators=50, max_depth=8, random_state=42)
    churn_model.fit(X.values, y_churn)
    
    # 2. Train Responsiveness Model
    y_resp = df_donors["responsiveness_score_target"]
    print("Training Responsiveness RandomForest Regressor...")
    responsiveness_model = RandomForestRegressor(n_estimators=50, max_depth=8, random_state=42)
    responsiveness_model.fit(X.values, y_resp)
    
    # Save models
    churn_path = os.path.join(script_dir, "churn_model.joblib")
    responsiveness_path = os.path.join(script_dir, "responsiveness_model.joblib")
    
    print(f"Saving churn model to {churn_path}")
    joblib.dump(churn_model, churn_path)
    
    print(f"Saving responsiveness model to {responsiveness_path}")
    joblib.dump(responsiveness_model, responsiveness_path)
    
    print("Models successfully trained and saved!")

if __name__ == "__main__":
    main()
