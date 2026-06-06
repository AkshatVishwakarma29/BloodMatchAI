from pydantic import BaseModel, Field
from typing import Optional, List

class UserBase(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    role: str
    role_status: bool = True
    blood_group: Optional[str] = None
    gender: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    registration_date: Optional[str] = None
    donor_type: Optional[str] = None
    last_contacted_date: Optional[str] = None
    last_donation_date: Optional[str] = None
    next_eligible_date: Optional[str] = None
    donations_till_date: Optional[float] = None
    eligibility_status: Optional[str] = None
    cycle_of_donations: Optional[int] = None
    total_calls: Optional[int] = None
    calls_to_donations_ratio: Optional[float] = None
    user_donation_active_status: Optional[str] = None
    inactive_trigger_comment: Optional[str] = None
    preferred_channel: str = "WhatsApp"
    preferred_language: str = "English"

class UserCreate(UserBase):
    id: str

class UserResponse(UserBase):
    id: str
    health_score: Optional[float] = None
    churn_risk_score: Optional[float] = None

    class Config:
        from_attributes = True

class BridgeBase(BaseModel):
    patient_id: str
    bridge_status: bool = True
    bridge_gender: Optional[str] = None
    bridge_blood_group: Optional[str] = None
    quantity_required: Optional[float] = 1.0
    last_transfusion_date: Optional[str] = None
    expected_next_transfusion_date: Optional[str] = None
    frequency_in_days: Optional[int] = 90
    status_of_bridge: bool = True

class BridgeCreate(BridgeBase):
    id: str

class BridgeResponse(BridgeBase):
    id: str
    patient: Optional[UserResponse] = None

    class Config:
        from_attributes = True

class RequestCreate(BaseModel):
    patient_id: str
    blood_units_needed: float = 1.0
    hospital_name: str
    hospital_lat: Optional[float] = None
    hospital_lon: Optional[float] = None
    needed_by: str

class OutreachEventResponse(BaseModel):
    id: int
    request_id: int
    donor_id: str
    channel: str
    wave_number: int
    sent_at: str
    response: str
    response_at: Optional[str] = None
    response_time_mins: Optional[float] = None
    donor: Optional[UserResponse] = None

    class Config:
        from_attributes = True

class RequestResponse(BaseModel):
    id: int
    patient_id: str
    requested_at: str
    needed_by: str
    status: str
    blood_units_needed: float
    hospital_name: Optional[str] = None
    hospital_lat: Optional[float] = None
    hospital_lon: Optional[float] = None
    fulfilled_at: Optional[str] = None
    patient: Optional[UserResponse] = None
    outreach_events: List[OutreachEventResponse] = []

    class Config:
        from_attributes = True

class ResponseSubmit(BaseModel):
    phone: str
    message: str

class ChatMessageRequest(BaseModel):
    phone: str
    message: str

class ChatMessageResponse(BaseModel):
    reply: str
