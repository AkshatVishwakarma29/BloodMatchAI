from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)  # maps to user_id
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    role = Column(String, index=True)  # 'Guest', 'Emergency Donor', 'Bridge Donor', 'Patient', 'Volunteer'
    role_status = Column(Boolean, default=True)
    blood_group = Column(String, nullable=True, index=True)
    gender = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    registration_date = Column(String, nullable=True)
    donor_type = Column(String, nullable=True)  # 'Regular Donor', 'One-Time Donor', etc.
    last_contacted_date = Column(String, nullable=True)
    last_donation_date = Column(String, nullable=True)
    next_eligible_date = Column(String, nullable=True)
    donations_till_date = Column(Float, nullable=True)  # float in CSV sometimes, cast to float or handle
    eligibility_status = Column(String, nullable=True, index=True)  # 'eligible', 'not eligible'
    cycle_of_donations = Column(Integer, nullable=True)
    total_calls = Column(Integer, nullable=True)
    calls_to_donations_ratio = Column(Float, nullable=True)
    user_donation_active_status = Column(String, nullable=True, index=True)  # 'Active', 'Inactive'
    inactive_trigger_comment = Column(String, nullable=True)
    
    # Custom attributes for simulation
    preferred_channel = Column(String, default="WhatsApp")  # 'WhatsApp', 'SMS', 'Email'
    preferred_language = Column(String, default="English")  # 'English', 'Hindi', 'Telugu', 'Tamil', etc.
    health_score = Column(Float, nullable=True)
    churn_risk_score = Column(Float, nullable=True)
    
    # Relationships
    bridges = relationship("Bridge", back_populates="patient", foreign_keys="Bridge.patient_id")
    donation_requests = relationship("Request", back_populates="patient", foreign_keys="Request.patient_id")
    outreach_events = relationship("OutreachEvent", back_populates="donor")

    @property
    def masked_name(self) -> str:
        if not self.name:
            return "Anonymous"
        parts = self.name.split()
        masked_parts = []
        for part in parts:
            if len(part) > 1:
                masked_parts.append(part[0] + "*" * (len(part) - 1))
            else:
                masked_parts.append(part)
        return " ".join(masked_parts)

    @property
    def masked_phone(self) -> str:
        if not self.phone:
            return "Unknown"
        if len(self.phone) > 6:
            # e.g., +91 9876543210 -> +91 98******10
            return self.phone[:7] + "*" * (len(self.phone) - 10) + self.phone[-3:]
        return "****"


class Bridge(Base):
    __tablename__ = "bridges"
    
    id = Column(String, primary_key=True, index=True)  # maps to bridge_id
    patient_id = Column(String, ForeignKey("users.id"), index=True)
    bridge_status = Column(Boolean, default=True)
    bridge_gender = Column(String, nullable=True)
    bridge_blood_group = Column(String, nullable=True)
    quantity_required = Column(Float, nullable=True)
    last_transfusion_date = Column(String, nullable=True)
    expected_next_transfusion_date = Column(String, nullable=True)
    frequency_in_days = Column(Integer, nullable=True)
    status_of_bridge = Column(Boolean, default=True)
    
    # Relationships
    patient = relationship("User", back_populates="bridges", foreign_keys=[patient_id])
    donors = relationship("BridgeDonorLink", back_populates="bridge")

class BridgeDonorLink(Base):
    __tablename__ = "bridge_donors"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    bridge_id = Column(String, ForeignKey("bridges.id"), index=True)
    donor_id = Column(String, ForeignKey("users.id"), index=True)
    
    # Relationships
    bridge = relationship("Bridge", back_populates="donors")
    donor = relationship("User")

class Request(Base):
    __tablename__ = "requests"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    patient_id = Column(String, ForeignKey("users.id"), index=True)
    requested_at = Column(String, index=True)
    needed_by = Column(String)
    status = Column(String, default="pending")  # 'pending', 'in_progress', 'fulfilled', 'cancelled'
    blood_units_needed = Column(Float, default=1.0)
    hospital_name = Column(String, nullable=True)
    hospital_lat = Column(Float, nullable=True)
    hospital_lon = Column(Float, nullable=True)
    fulfilled_at = Column(String, nullable=True)
    
    # Relationships
    patient = relationship("User", back_populates="donation_requests", foreign_keys=[patient_id])
    outreach_events = relationship("OutreachEvent", back_populates="request")

class OutreachEvent(Base):
    __tablename__ = "outreach_events"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("requests.id"), index=True)
    donor_id = Column(String, ForeignKey("users.id"), index=True)
    channel = Column(String)  # 'WhatsApp', 'SMS', 'Email'
    wave_number = Column(Integer)  # 1, 2, 3
    sent_at = Column(String)
    response = Column(String, default="pending")  # 'pending', 'confirmed', 'declined', 'ignored'
    response_at = Column(String, nullable=True)
    response_time_mins = Column(Float, nullable=True)
    verification_token = Column(String, unique=True, nullable=True, index=True)
    
    # Relationships
    request = relationship("Request", back_populates="outreach_events")
    donor = relationship("User", back_populates="outreach_events")
