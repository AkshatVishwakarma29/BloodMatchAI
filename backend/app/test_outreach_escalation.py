import os
import sys
import asyncio
import shutil

# Add backend directory to path so app can be imported
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.append(backend_dir)

# Force the environment database URL to be a test database
os.environ["DATABASE_URL"] = "sqlite:///./test_bloodbridge.db"

# Remove test database if it exists
if os.path.exists("test_bloodbridge.db"):
    try:
        os.remove("test_bloodbridge.db")
    except Exception as e:
        print(f"Error removing old test DB: {e}")

from app.database import engine, Base, SessionLocal
from app.models import User, Bridge, BridgeDonorLink, Request, OutreachEvent
from app.schemas import DonorRegister
from app.main import register_donor
from app.outreach import simulate_scheduled_transfusion_orchestration, NOTIFICATION_LOG_PATH

# Create all tables on the clean test database
Base.metadata.create_all(bind=engine)

def clear_notification_log():
    if os.path.exists(NOTIFICATION_LOG_PATH):
        try:
            os.remove(NOTIFICATION_LOG_PATH)
        except Exception:
            pass

def print_log_contents():
    print("\n--- NOTIFICATION LOG OUTPUT ---")
    if os.path.exists(NOTIFICATION_LOG_PATH):
        with open(NOTIFICATION_LOG_PATH, "r", encoding="utf-8") as f:
            print(f.read())
    else:
        print("[No notification log found]")
    print("--------------------------------\n")

async def test_registration_and_outreach():
    db = SessionLocal()
    clear_notification_log()
    
    print("====== 1. SETTING UP TEST PATIENT AND BRIDGE ======")
    # Create a patient
    patient = User(
        id="test_patient_1",
        name="Thalassemia Fighter",
        phone="+91 7777777777",
        role="Patient",
        blood_group="O Positive",
        gender="Female",
        latitude=17.39,
        longitude=78.46,
        eligibility_status="not eligible",
        user_donation_active_status="Active"
    )
    db.add(patient)
    db.commit()
    
    # Create patient's active bridge
    bridge = Bridge(
        id="test_bridge_1",
        patient_id=patient.id,
        bridge_status=True,
        bridge_blood_group="O Positive",
        bridge_gender="Female",
        quantity_required=1.0,
        frequency_in_days=30,
        expected_next_transfusion_date="2026-06-10"
    )
    db.add(bridge)
    db.commit()
    print(f"Patient {patient.name} registered with bridge {bridge.id}")
    
    print("\n====== 2. REGISTERING BRIDGE DONORS & CHECKING 10-DONOR CAP ======")
    # Register 10 compatible bridge donors
    for i in range(1, 11):
        reg = DonorRegister(
            name=f"Bridge Donor {i}",
            phone=f"+91 90000000{i:02d}",
            blood_group="O Positive",
            gender="Female" if i % 2 == 0 else "Male",
            preferred_channel="WhatsApp",
            preferred_language="English",
            join_bridge=True
        )
        register_donor(reg, db)
    
    # Check bridge donor links count
    links_count = db.query(BridgeDonorLink).filter(BridgeDonorLink.bridge_id == bridge.id).count()
    print(f"Registered 10 compatible bridge donors. Bridge size: {links_count}/10")
    assert links_count == 10, f"Expected 10 bridge links, got {links_count}"
    
    # Register an 11th compatible bridge donor
    reg_11 = DonorRegister(
        name="Bridge Donor 11",
        phone="+91 9000000011",
        blood_group="O Positive",
        gender="Female",
        preferred_channel="WhatsApp",
        preferred_language="English",
        join_bridge=True
    )
    donor_11 = register_donor(reg_11, db)
    
    # Check bridge donor links count again (must still be 10)
    links_count = db.query(BridgeDonorLink).filter(BridgeDonorLink.bridge_id == bridge.id).count()
    print(f"Registered 11th compatible bridge donor. Bridge size (should stay capped at 10): {links_count}/10")
    assert links_count == 10, f"Expected bridge links count capped at 10, got {links_count}"
    
    # Verify that Donor 11 is not linked to this bridge
    is_linked = db.query(BridgeDonorLink).filter(
        BridgeDonorLink.bridge_id == bridge.id,
        BridgeDonorLink.donor_id == donor_11.id
    ).first()
    assert is_linked is None, "11th donor should not be linked to the capped bridge."
    print("Verified: Donor 11 is not in the bridge (Cap enforced successfully!).")
    
    print("\n====== 3. REGISTERING EMERGENCY DONORS ======")
    # Register an emergency donor (join_bridge = False)
    reg_emergency = DonorRegister(
        name="Emergency Donor 1",
        phone="+91 9999999999",
        blood_group="O Positive",
        gender="Female",
        preferred_channel="SMS",
        preferred_language="Hindi",
        join_bridge=False
    )
    donor_em = register_donor(reg_emergency, db)
    assert donor_em.role == "Emergency Donor", f"Expected role 'Emergency Donor', got {donor_em.role}"
    
    # Verify they are not linked to bridge
    is_linked_em = db.query(BridgeDonorLink).filter(BridgeDonorLink.donor_id == donor_em.id).first()
    assert is_linked_em is None, "Emergency donor should not be in any bridge"
    print(f"Registered: {donor_em.name} as {donor_em.role}. Verified not assigned to any bridge.")
    
    # Register 15 more emergency donors for Stage 2 wave checks
    for i in range(2, 17):
        reg = DonorRegister(
            name=f"Emergency Donor {i}",
            phone=f"+91 99999999{i:02d}",
            blood_group="O Positive",
            gender="Male",
            preferred_channel="WhatsApp",
            preferred_language="English",
            join_bridge=False
        )
        register_donor(reg, db)
        
    print(f"Registered 15 additional emergency donors for global pool tests.")
    
    print("\n====== 4. RUNNING SCHEDULED TRANSFUSION OUTREACH AND ESCALATION ======")
    # Create request
    req = Request(
        patient_id=patient.id,
        requested_at="2026-06-07 00:00:00",
        needed_by="2026-06-10",
        status="pending",
        blood_units_needed=1.0,
        hospital_name="Hyderabad General Hospital",
        hospital_lat=17.39,
        hospital_lon=78.46
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    print(f"Transfusion request created. ID: {req.id}")
    
    # Run the scheduled transfusion orchestration
    # Note: DEMO_WAVE_DELAY is 15 seconds. Let's run it.
    print("Starting scheduled transfusion orchestration...")
    print("It will wait 15 seconds for Stage 1 (Bridge), then 15 seconds for Stage 2 Wave 1, then 15 seconds for Wave 2.")
    print("Please wait...")
    
    await simulate_scheduled_transfusion_orchestration(patient.id, req.id)
    
    print("\n====== 5. VERIFYING ESCALATION OUTCOME ======")
    # Refresh request and check outreach events
    db.refresh(req)
    print(f"Final Request Status: {req.status}")
    assert req.status == "escalated", f"Expected request status to be 'escalated', got {req.status}"
    
    # Count events by wave number
    events_bridge = db.query(OutreachEvent).filter(OutreachEvent.request_id == req.id, OutreachEvent.wave_number == 1).all()
    events_wave_1 = db.query(OutreachEvent).filter(OutreachEvent.request_id == req.id, OutreachEvent.wave_number == 2).all()
    events_wave_2 = db.query(OutreachEvent).filter(OutreachEvent.request_id == req.id, OutreachEvent.wave_number == 3).all()
    
    print(f"Stage 1 (Bridge Wave) alerts sent: {len(events_bridge)}")
    print(f"Stage 2 Wave 1 (Top 10 global) alerts sent: {len(events_wave_1)}")
    print(f"Stage 2 Wave 2 (Next 15 global) alerts sent: {len(events_wave_2)}")
    
    assert len(events_bridge) == 10, f"Expected 10 bridge alerts, got {len(events_bridge)}"
    assert len(events_wave_1) == 10, f"Expected 10 emergency wave 1 alerts, got {len(events_wave_1)}"
    # Global pool compatible: donor_11 (O Positive, regular) + 16 emergency donors = 17 compatible global donors.
    # Top 10 go to wave 1. The remaining 7 should go to wave 2.
    assert len(events_wave_2) == 7, f"Expected 7 emergency wave 2 alerts, got {len(events_wave_2)}"
    
    print("All assertions passed!")
    
    print_log_contents()
    
    # Clean up test DB file at the end
    db.close()
    
if __name__ == "__main__":
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass
    # Since windows encoding issue was mentioned, we run using event loop
    asyncio.run(test_registration_and_outreach())
