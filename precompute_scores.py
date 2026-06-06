import csv
from datetime import datetime

# Path definitions
INPUT_PATH = "given/Dataset.csv"
OUTPUT_PATH = "given/Dataset_Enriched.csv"
CURRENT_DATE = datetime(2026, 6, 6)

def parse_date(date_str):
    if not date_str or date_str.strip() == "":
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None

def main():
    print(f"Reading {INPUT_PATH}...")
    
    with open(INPUT_PATH, mode="r", encoding="utf-8") as infile:
        reader = list(csv.DictReader(infile))
        
    fieldnames = list(reader[0].keys())
    # Add new fields if they don't exist
    if "health_score" not in fieldnames:
        fieldnames.append("health_score")
    if "churn_risk_score" not in fieldnames:
        fieldnames.append("churn_risk_score")
        
    print(f"Loaded {len(reader)} rows. Starting scoring...")
    
    processed = 0
    for row in reader:
        # Check if donor role
        role = row.get("role", "").lower()
        is_donor = "donor" in role
        
        if not is_donor:
            row["health_score"] = "0.00"
            row["churn_risk_score"] = "0.00"
            continue
            
        # 1. Normalized donations till date (capped at 10 for normalization)
        try:
            donations = float(row.get("donations_till_date") or 0)
        except ValueError:
            donations = 0.0
        norm_donations = min(donations / 10.0, 1.0)
        
        # 2. Calls-to-donations ratio score (lower is better, penalty for high ratios)
        try:
            calls_ratio = float(row.get("calls_to_donations_ratio") or 0)
        except ValueError:
            calls_ratio = 0.0
        calls_ratio_score = max(0.0, 1.0 - (calls_ratio / 10.0))
        
        # 3. Recency score (decays over time since last donation)
        last_don_date = parse_date(row.get("last_donation_date"))
        if last_don_date:
            days_since = (CURRENT_DATE - last_don_date).days
            # Half-life of 90 days
            recency_score = 1.0 / (1.0 + max(0, days_since) / 90.0)
        else:
            days_since = 9999
            recency_score = 0.0
            
        # 4. Eligibility status
        elig_status = row.get("eligibility_status", "").lower()
        eligibility_score = 1.0 if (elig_status == "eligible" or elig_status == "true") else 0.0
        
        # 5. Profile completeness
        bg = row.get("blood_group", "").strip()
        gender = row.get("gender", "").strip()
        profile_completeness = 0.0
        if bg:
            profile_completeness += 0.5
        if gender:
            profile_completeness += 0.5
            
        # Calculate composite Health Score
        health_score = (
            0.30 * norm_donations +
            0.25 * calls_ratio_score +
            0.20 * recency_score +
            0.15 * eligibility_score +
            0.10 * profile_completeness
        )
        
        # Calculate Churn Risk Score
        active_status = row.get("user_donation_active_status", "").lower()
        comment = row.get("inactive_trigger_comment", "").lower()
        
        if active_status == "inactive":
            churn_risk_score = 1.0
        else:
            churn_risk = 0.0
            # Higher call ratio implies lower response/higher annoyance
            if calls_ratio > 5.0:
                churn_risk += 0.3
            # Inactive comments trigger flags
            if comment and any(w in comment for w in ("no response", "not active", "calls", "snooze", "refuse")):
                churn_risk += 0.3
            # Not donated in 1 year
            if days_since > 365:
                churn_risk += 0.4
            churn_risk_score = min(churn_risk, 0.95)
            
        row["health_score"] = f"{health_score:.2f}"
        row["churn_risk_score"] = f"{churn_risk_score:.2f}"
        processed += 1
        
    print(f"Processed {processed} donors. Writing to {OUTPUT_PATH}...")
    
    with open(OUTPUT_PATH, mode="w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reader)
        
    print("Pre-computation completed successfully!")

if __name__ == "__main__":
    main()
