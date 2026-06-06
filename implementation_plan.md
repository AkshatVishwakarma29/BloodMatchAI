# 🩸 ThalassemiaFree AI — Blood Warriors Hackathon Implementation Plan

## Executive Summary

**Problem**: Blood Warriors currently operates "BloodBridge" — a manual, WhatsApp-based system where 8–10 donors are grouped per patient. Coordinators manually message groups for every transfusion request. With 1,00,000+ patients needing 500–700 lifetime transfusions each, this is fundamentally unscalable.

**Solution**: Build an **autonomous, AI-powered Blood Support Network** — *"BloodBridge 2.0"* — that replaces manual coordination with an intelligent, event-driven orchestration platform deployed on AWS. The system will autonomously manage donor-patient matching, outreach, engagement, and escalation with minimal human intervention.

> [!IMPORTANT]
> This plan is now grounded in the **actual Blood Warriors dataset** (7,033 records). All ML features, problem framing, and dashboard metrics are derived from real data columns and observed patterns.

---

## Understanding Blood Warriors Today

### From Website Analysis ([bloodwarriors.in](https://www.bloodwarriors.in))
- **Core Program**: BloodBridge — each Thalassemia patient is assigned a WhatsApp group of 8–10 volunteer donors
- **Existing Assets**: Donor registry, patient registry, leaderboard (gamification exists!), blood-stock search, WhatsApp bot ("Veeru")

### 📊 Dataset Analysis — What the Data Tells Us (7,033 Records)

#### Population Breakdown
| Segment | Count | % of Total |
|---------|-------|-----------|
| Guest/Unregistered users | 2,420 | 34.4% — massive untapped funnel |
| Emergency Donors (one-time) | 2,385 | 33.9% — never re-engaged |
| Bridge Donors (active BloodBridge) | 2,061 | 29.3% — core regular donors |
| Patients | 84 | 1.2% |
| Volunteers | 83 | 1.2% |

#### 🚨 Critical Problem #1: Donor Inactivity Crisis
- **682 donors (9.7%) are flagged Inactive** out of 7,033
- **Inactive reasons**:
  - "Not donated in last 1 year": **361 donors**
  - "Very limited activity despite multiple calls": **321 donors**
- **Calls-to-donations ratio avg = 1.85** — for every donation, staff make nearly 2 calls. For inactive donors, ratios reach **23:1** (23 calls, 0 donations)
- **6,464 donors (91.9%) are marked eligible** but inactive — this is lost capacity

#### 🚨 Critical Problem #2: Bridge Coverage Gap
- Only **80 unique patient bridges** (BloodBridge groups) exist in the entire dataset
- **786 Bridge Donor relationships** serve those 80 patients = ~9.8 donors/bridge on average
- **The bridge_status=true for only 786 rows (11.2%)** — most donors are NOT in any bridge
- Huge pool of 2,385 Emergency Donors who donated once but were **never structured into a bridge**

#### 🚨 Critical Problem #3: Gender Imbalance
- **Male donors: 2,444 vs Female donors: 391** (6:1 ratio)
- **4,157 records have no gender** (Guests + incomplete profiles)
- Blood Warriors uses `bridge_gender` for matching — driven by **cultural/social preference** (families often prefer same-gender donors) and a **clinical nuance**: female patients of childbearing age should ideally avoid Kell-antigen-positive blood (more common in male donors) to prevent complications in future pregnancies (HDFN risk)
- Gender matching is **not a universal medical mandate** but is a configured preference in Blood Warriors' matching policy — the AI system must respect it as a **soft constraint, not a hard rule**

#### Blood Type Distribution (Donor Side)
| Blood Type | Count |
|-----------|-------|
| O Positive | 1,963 (29.5%) |
| B Positive | 1,481 (22.3%) |
| A Positive | 879 (13.2%) |
| AB Positive | 353 (5.3%) |
| O Negative | 120 (1.8%) — **critical shortage** |
| B Negative | 94 (1.4%) — **critical shortage** |
| AB Negative | 35 (0.5%) — **extreme rarity** |
| Unknown/Other | ~160 |

#### Patient Blood Type Requirements (Bridge Side)
| Required Type | Count |
|--------------|-------|
| O Positive | 331 patients |
| B Positive | 285 patients |
| A Positive | 78 patients |
| AB Positive | 49 patients |
| O Negative | 20 patients |

#### Transfusion Frequency Pattern
- Most bridges use **90-day cycle** (1,474 records) — every ~3 months
- Some patients need every **21–31 days** (frequency_in_days column)
- Average actual donor-patient contact frequency: **24.6 days**
- Outlier: one patient has **1,958-day cycle** — likely data anomaly to handle

#### Donation History
- **Average donations per donor: 1.5** — most donate only once
- **Max donations per donor: 12** in the dataset
- The top recurring donors are the backbone — need priority protection

#### 🚨 Critical Problem #4: Guest Funnel Leakage
- **2,420 Guest accounts** — people who started registration but never completed it
- Most have no blood group, no donation history, no contact data
- This is a **massive convertible pipeline** — AI-powered re-engagement could 2x the donor base

### Current Pain Points (Quantified)
| Pain Point | Data Evidence |
|-----------|---------------|
| Donors not converting after calls | Calls:donation ratio avg 1.85, max 23.0 |
| Inactive but eligible donors wasted | 321 donors: multiple calls, zero donations |
| No predictive scheduling | `expected_next_transfusion_date` exists but unused |
| Emergency donors never retained | 2,385 one-time donors, no bridge assignment |
| Incomplete donor profiles | 4,157/7,033 records missing gender/blood type |
| Rare blood type shortages | Only 35 AB-Negative, 94 B-Negative donors |

---

## What We're Building: 5 Pillars

```
┌─────────────────────────────────────────────────────────────────┐
│              ThalassemiaFree AI Platform                        │
├──────────────┬──────────────┬──────────────┬───────────────────┤
│  1. Smart    │  2. AI-      │  3. Agentic  │  4. Engagement   │
│  Matching    │  Powered     │  Outreach    │  & Retention     │
│  Engine      │  Dashboard   │  System      │  Engine          │
├──────────────┴──────────────┴──────────────┴───────────────────┤
│              5. Conversational AI (Amazon Lex + Bedrock)        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INTERACTION LAYER                    │
│  React.js Web App (Admin Portal + Patient/Donor Portal)     │
│  AWS Amplify / S3 + CloudFront                              │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST / WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                  BACKEND API LAYER                           │
│  FastAPI (Python) on AWS App Runner / Fargate               │
│  API Gateway + Lambda (serverless functions)                │
│  AWS Cognito (Auth — patients, donors, admins, NGOs)        │
└──────┬───────────┬──────────────┬────────────┬─────────────┘
       │           │              │            │
┌──────▼───┐ ┌────▼─────┐ ┌─────▼────┐ ┌────▼──────────────┐
│ Matching │ │Outreach  │ │Dashboard │ │ Conversational AI  │
│ Service  │ │Orchestr. │ │ Service  │ │ (Lex + Bedrock)    │
│(SageMaker│ │(Step Fn) │ │(Athena + │ │ WhatsApp/SMS/      │
│  ML)     │ │SQS/SNS   │ │Redshift) │ │  Voice Bot         │
└──────────┘ └──────────┘ └──────────┘ └───────────────────┘
       │           │              │            │
┌──────▼───────────▼──────────────▼────────────▼────────────┐
│                     DATA LAYER                              │
│  Amazon RDS Aurora (PostgreSQL) — Core transactional DB     │
│  Amazon DynamoDB — Donor sessions, real-time state          │
│  Amazon S3 — Documents, audit logs, ML training data        │
│  SageMaker Feature Store — Donor/Patient ML features        │
│  Amazon Redshift — Analytics warehouse                      │
│  OpenSearch — Search & real-time donor lookup               │
└────────────────────────────────────────────────────────────┘
```

---

## Pillar 1: Smart Matching Engine (AI/ML Core)

### The Problem with Current BloodBridge
Every patient gets a static WhatsApp group of 8–10 donors. When blood is needed:
1. Coordinator manually texts the group
2. Donors may or may not respond
3. No tracking of who donated last, who's available, who's travelling
4. Same donors get burnt out; no rotation intelligence

### Our Solution: ML-Powered Dynamic Donor Ranking

**SageMaker Ranking Model** — For every transfusion request, rank available donors by features directly available in the dataset:

| Dataset Column | ML Feature Engineering | Usage |
|---------------|----------------------|-------|
| `eligibility_status` | Binary flag | Hard filter — only eligible donors |
| `next_eligible_date` | Days until eligible | Time-to-availability score |
| `calls_to_donations_ratio` | Direct feature | Donor responsiveness score |
| `user_donation_active_status` | Binary: Active/Inactive | Exclude Inactive (unless emergency) |
| `donations_till_date` | Total count | Loyalty / experience weight |
| `last_donation_date` | Days since last donation | Recency score |
| `last_contacted_date` | Days since last contact | Engagement freshness |
| `frequency_in_days` | Bridge-specific cadence | Match to patient's expected window |
| `cycle_of_donations` | Donor's historical cycle | Predict next eligible date |
| `donor_type` | Regular/One-Time/Other | Trust tier (Regular > One-Time) |
| `blood_group` vs `bridge_blood_group` | Type compatibility matrix | Blood type match score |
| `latitude`, `longitude` | Haversine distance to hospital | Proximity score |
| `gender` vs `bridge_gender` | Gender preference match | Soft constraint |
| `inactive_trigger_comment` | NLP classification | Risk flag for churn model |

**Three ML Models on SageMaker**:

1. **Donor Ranking Model** (XGBoost/LightGBM)
   - Input: donor features + request context
   - Output: ranked list of top N donors for a given request
   - Training data: historical `outreach_events` + response outcomes

2. **Churn Prediction Model** (Logistic Regression / Random Forest)
   - Predict which Active donors are about to go Inactive
   - Key signal: `calls_to_donations_ratio` > 5 with `user_donation_active_status = Active` but `last_donation_date` > 365 days ago
   - **From data**: 321 donors match "very limited activity despite multiple calls" — use these as churn ground truth labels

3. **Guest Conversion Model** (Classification) — Phase 2
   - **2,420 Guest accounts** have incomplete profiles
   - Predict which guests are most likely to complete registration and donate
   - Deferred: guests have almost no features; show as "future roadmap" in demo

**SageMaker Feature Store** (real-time + offline):
```python
# Features ingested per donor (from dataset columns)
feature_group = FeatureGroup(name='donor-features', sagemaker_session=session)
donor_features = [
    'eligibility_status',           # 91.9% eligible in current data
    'calls_to_donations_ratio',     # avg 1.85, max 23.0
    'donations_till_date',          # avg 1.5
    'days_since_last_donation',     # derived from last_donation_date
    'days_since_last_contact',      # derived from last_contacted_date
    'donor_type_encoded',           # Regular=2, One-Time=1, Other=0
    'cycle_of_donations',           # 90 days most common
    'active_status_encoded',        # Active=1, Inactive=0
    'churn_risk_score',             # output of Model 2
    'blood_type_encoded',           # O+=1, A+=2, B+=3, etc.
]
```

**Implementation**:
- **Phase 1 (Hackathon)**: Rule-based ranking using dataset columns directly, scores pre-computed via Python script
- **Phase 2**: SageMaker Training Pipeline retrained weekly with new outreach data
- **Phase 2**: SageMaker Endpoint for real-time inference (<100ms)
- **Phase 2**: SageMaker Autopilot for automated model comparison

---

## Pillar 2: Agentic Outreach Orchestration

### Replacing Manual WhatsApp Coordination

**AWS Step Functions** orchestrates the entire outreach workflow autonomously:

```
Transfusion Request Received
          │
          ▼
[Lambda] Validate request & patient record
          │
          ▼
[Matching API] Rank top donors for this request
          │
          ▼
[Lambda] Outreach Wave 1: Contact top 3 donors via preferred channel
          │
    ┌─────▼──────┐
    │ Wait 4 hrs  │ ← EventBridge schedule
    └─────┬───────┘
          │
    [Lambda] Check responses via DynamoDB
          │
    ┌─────▼──────────────────────┐
    │ Sufficient donors confirmed? │
    └───┬────────────────────────┘
        │ No                 │ Yes
        ▼                    ▼
[Move to next         [Confirm & notify patient]
 ranked donors]
        │
   Still not enough?
   + rare blood type?
   + <48 hrs to need?
        │
        ▼
[Coordinator Alert]
  Human decides next action
  Notify Blood Bank for backup
```

**Communication Strategy: Single Channel + Sequential Escalation**

> [!IMPORTANT]
> Donors are **never** contacted on multiple channels simultaneously. The dataset's worst-case `calls_to_donations_ratio` of **23.0** is evidence that over-contacting donors destroys engagement. The AI's job is **smarter targeting, not more channels**.

**Channel Priority Ladder** (one step at a time, never simultaneous):

```
Step 1 — Contact via donor's PREFERRED CHANNEL only
         (set during registration: WhatsApp / SMS / Email)
              │
              │  No response after 4 hours
              ▼
Step 2 — Try donor's SECONDARY CHANNEL (if configured)
              │
              │  Still no response
              ▼
Step 3 — Move to the NEXT RANKED donor
         (do NOT escalate channels further for routine requests)
              │
              │  ONLY if: rare blood type (O-Neg/AB-Neg)
              │           AND fewer than 2 eligible donors found
              │           AND patient needs blood within 48 hours
              ▼
Step 4 — Coordinator alert (human makes the call decision)
         Voice/Amazon Connect — NEVER automated for first contact
```

**Available Channel Infrastructure** (used per donor preference):
- **WhatsApp**: Via **Twilio WhatsApp Sandbox** → Twilio webhook → API Gateway → Lambda → Step Functions
  - Sandbox allows up to 5 pre-registered test phone numbers — no business API approval needed
  - Setup: `twilio.com/console` → Messaging → Try it out → Send a WhatsApp message
  - Webhook URL: `POST /api/twilio/webhook` on our FastAPI backend
- **SMS**: Amazon SNS → regional telecom (fallback for no-smartphone users)
- **Email**: Amazon SES (low-urgency updates, certificates, reports)
- **Push Notification**: Via PWA (app users only, opt-in)
- **Voice/Amazon Connect**: Human-initiated escalation only — never automated for first contact
- **Language**: Amazon Translate — all messages in donor's preferred language (Hindi, Tamil, Telugu, Bengali, etc.)

**Donor Dignity Rules enforced by the AI policy layer**:

| Rule | Detail |
|------|--------|
| **Single channel default** | Contact via preferred channel only |
| **Hard eligibility gate** | Never contact a donor who is `not eligible` — regardless of urgency |
| **Frequency cap** | Max 1 outreach per donor per 7-day rolling window |
| **Quiet hours** | No messages between 10 PM – 7 AM (donor's local time) |
| **One-tap snooze** | Donor replies "Not available" → system respects it for 30 days, no follow-ups |
| **Decline is final** | If donor declines a request, no further contact for that same request |
| **Churn protection** | If `calls_to_donations_ratio` > 5, donor is flagged — escalate to coordinator review, not more messages |

**Failure Learning**: Every outreach outcome (sent → responded → donated / declined / ignored) is logged to S3 → SageMaker retrains weekly on these patterns → System self-improves **who to contact** (ranking model), not how many channels to use

---

## Pillar 3: Conversational AI ("Veeru 2.0")

### Current State
Blood Warriors already has "Veeru" — a basic WhatsApp bot. We upgrade it with memory, context, and agentic capabilities.

### Veeru 2.0 Architecture
```
Donor/Patient WhatsApp → AWS Lex → Lambda → Amazon Bedrock (Claude Haiku)
                                      │
                              ┌───────▼──────────┐
                              │  Memory Store     │
                              │  (DynamoDB)       │
                              │  - Past donations │
                              │  - Preferences    │
                              │  - Last interaction│
                              └───────────────────┘
```

**Capabilities**:
- **Donors**: Check eligibility status, confirm/decline donation requests, reschedule, update availability
- **Patients**: Check upcoming transfusion schedule, status of current request, nearest blood bank
- **Adaptive Language**: Responds in Hindi, English, or regional language based on user preference (Bedrock + Translate)
- **Contextual Memory**: Remembers past interactions — "Last time you donated on March 15. You're eligible again now!"
- **Proactive Nudges**: Sends check-ins when donors haven't engaged in 30 days

**Amazon Lex Intents**:
- `ConfirmDonation`, `DeclineDonation`, `RescheduleDonation`
- `CheckEligibility`, `UpdateAvailability`, `GetDonationHistory`
- `PatientRequestStatus`, `FindNearestBloodBank`
- `RegisterDonor`, `UpdateContactInfo`

---

## Pillar 4: Admin Dashboard & Analytics

### State-by-State Operational Intelligence

**Tech**: React.js + direct RDS queries (Phase 1) → Athena + Redshift (Phase 2)

**Dashboard Modules** (all powered by real dataset fields):

#### 🗺️ Geographic Heatmap
- Dataset shows concentration around Hyderabad (lat ~17.39, lon ~78.46)
- Expandable to all India states using `latitude`/`longitude` columns
- Color-coded by **donor-to-patient ratio** and **rare blood type coverage**
- Highlight critical shortage zones: O-Negative (only 120 donors), AB-Negative (35 donors)

#### 📊 Real-Time KPIs (Dataset-Grounded Baselines)
| Metric | Current Baseline (from data) | AI Target |
|--------|-----------------------------|-----------| 
| Calls-to-donation ratio | **1.85 avg** (max 23.0 !) | < 0.8 |
| Inactive donor rate | **9.7%** (682/7033) | < 3% |
| Donors per bridge | **~9.8** (786 rows, 80 bridges) | 12+ (smart pool) |
| Guest conversion rate | **~0%** (2,420 unconverted) | > 25% |
| Average donations per donor | **1.5** | > 4 |

#### 🩸 Donor Health Score (Composite ML Score)
Built from actual dataset columns:
```
Health Score = (
  0.30 × normalized(donations_till_date)
+ 0.25 × (1 - normalized(calls_to_donations_ratio))
+ 0.20 × normalized(recency_score)          # from last_donation_date
+ 0.15 × eligibility_score                  # 1 if eligible, 0 if not
+ 0.10 × profile_completeness               # blood_group, gender filled?
)
```

#### 🚨 Inactivity & Churn Alerts
- **321 donors**: "Very limited activity despite multiple calls" → AI generates personalized Bedrock re-engagement messages
- **361 donors**: "Not donated in last 1 year" → automated outreach campaign
- Churn risk score surfaced per donor on dashboard with recommended action

#### 📈 Trend Analytics
- Monthly donation volume by blood type (critical: O-Neg, B-Neg trends)
- One-time donor conversion rate (2,385 Emergency donors — can we convert even 10%?)
- Guest-to-donor funnel: 2,420 guests → registered → first donation
- Cycle compliance: patients' `expected_next_transfusion_date` vs actual fulfillment

**Data Pipeline**:
- **Phase 1**: Direct RDS Aurora queries → React.js charts
- **Phase 2**: S3 Data Lake → AWS Glue → Redshift → Athena → advanced analytics
- **EventBridge**: Trigger alert Lambda when `calls_to_donations_ratio` > 5.0 for any donor

---

## Pillar 5: Engagement & Retention Engine

### Solving Donor Attrition

**Gamification 2.0** (building on existing leaderboard):
- **BloodBridge Score**: Points for donations, response speed, streaks
- **Badges**: "Iron Warrior" (10 donations), "Lifeline" (saved 5 patients), State champion
- **Digital Certificate**: Auto-generated after each donation (SES + PDF Lambda)
- **Social Sharing**: One-click share to WhatsApp/Instagram

**Willingness Prediction Model** (SageMaker — Phase 2):
- Predicts donors at risk of churning (no donation in 90 days)
- Triggers personalized re-engagement campaigns via Bedrock-generated messages
- Tests different message styles per donor segment (A/B via EventBridge)

**Awareness & Screening** (new feature):
- Pre-conception screening reminder campaigns (address root cause)
- Partner hospital integration for thalassemia carrier testing referrals
- WhatsApp health literacy chatbot in regional languages

---

## AWS Infrastructure Mapping

| Component | AWS Service | Phase | Justification |
|-----------|------------|-------|---------------|
| Frontend hosting | S3 + CloudFront + Amplify | 1 | CDN for low-latency pan-India access |
| Authentication | AWS Cognito | 1 | Multi-role: donor, patient, admin, NGO partner |
| Backend API | FastAPI on App Runner | 1 | Auto-scaling, no server management |
| Serverless functions | Lambda + API Gateway | 1 | Event-driven matching, notifications |
| Outreach orchestration | AWS Step Functions | 1 | Visual workflow, retry logic, failure handling |
| Core database | RDS Aurora PostgreSQL | 1 | Relational: patients, donors, requests, blood banks |
| Real-time state | DynamoDB | 1 | Donor response tracking, session state |
| Email notifications | Amazon SES | 1 | Templated donor/patient emails |
| WhatsApp | Twilio Sandbox → API Gateway | 1 | No approval needed for hackathon |
| Event bus | Amazon EventBridge | 1 | Decouple services, schedule follow-ups |
| Conversational AI | Amazon Lex + Bedrock | 1 | WhatsApp bot with memory |
| Message queue | SQS + SNS | 2 | Reliable notification delivery, fan-out |
| Real-time streaming | Kinesis Data Streams | 2 | Event ingestion for analytics |
| ETL pipeline | AWS Glue | 2 | Nightly data warehouse loads |
| Analytics warehouse | Amazon Redshift | 2 | Historical queries for dashboard |
| Ad-hoc queries | Amazon Athena | 2 | SQL on S3 data lake |
| Search | OpenSearch | 2 | Donor location/availability search |
| ML training | Amazon SageMaker | 2 | Matching model, churn prediction |
| ML inference | SageMaker Endpoint | 2 | Real-time donor ranking |
| Feature store | SageMaker Feature Store | 2 | Online + offline donor/patient features |
| Translation | Amazon Translate | 2 | Multi-language donor outreach |
| Secrets | Secrets Manager | 1 | API keys, DB passwords |
| Monitoring | CloudWatch + X-Ray | 1 | End-to-end tracing, alarms |
| CI/CD | CodePipeline + CodeBuild | 1 | GitHub → auto-deploy |

---

## Data Models (Core Schema)

```sql
-- Donors (seeded from Dataset.csv)
donors (id, name, phone, blood_type, state, district, lat, lon,
        preferred_channel, preferred_language, cognito_id,
        eligibility_status, next_eligible_date, last_donation_date,
        last_contacted_date, donations_till_date, calls_to_donations_ratio,
        donor_type, user_donation_active_status, churn_risk_score,
        health_score, created_at)

-- Patients (seeded from bridge records in Dataset.csv)
patients (id, name, blood_type_needed, hospital_id, state, district,
          transfusion_frequency_days, next_due_date, guardian_phone,
          bridge_id, quantity_required)

-- Donation Requests
requests (id, patient_id, requested_at, needed_by, status,
          blood_units_needed, hospital_id, fulfilled_at)

-- Outreach Events
outreach_events (id, request_id, donor_id, channel, sent_at,
                 response, response_at, response_time_mins)

-- Donor Features (pre-computed for hackathon, SageMaker Feature Store in Phase 2)
donor_features (donor_id, days_since_last_donation, days_since_last_contact,
                donor_type_encoded, active_status_encoded,
                blood_type_encoded, churn_risk_score, health_score)
```

---

## Why This is Beneficial: Stakeholder Impact

### 🩸 For Patients
- **Faster blood access**: AI matches best available donor in minutes, not hours
- **Reliability**: Multi-wave escalation ensures 95%+ request fulfillment
- **Transparency**: Real-time status updates via Veeru 2.0
- **Reduced cost**: Efficient matching = less emergency procurement from blood banks (saves ₹500–2000 per unit)

### 💪 For Donors
- **No more batch broadcasts**: Only contacted when genuinely a good match
- **Respected channel preference**: WhatsApp, SMS, or Email — their choice
- **Recognition**: Gamification, certificates, social proof
- **Reduced guilt**: One-tap snooze — no awkward "I can't" responses needed

### 🏥 For Hospitals & Blood Banks
- **Predictive scheduling**: Know upcoming demand 30–60 days ahead from `next_due_date`
- **Reduced emergency calls**: Coordinated demand prevents last-minute crises
- **API integration**: Real-time blood stock sync with hospital systems (Phase 2)

### 🏛️ For Blood Warriors / NGO Coordinators
- **10x capacity**: Each coordinator can oversee thousands of patients (vs. hundreds today)
- **No manual follow-ups**: Step Functions handles all follow-up chains
- **Insights**: State dashboards reveal where to recruit more donors
- **Audit trail**: Full compliance logging for all donation activities

### 🌍 For India's Thalassemia Mission
- **Scalable to 1,00,000+ patients**: Cloud-native architecture scales elastically
- **Carrier prevention**: Awareness campaigns reduce new Thalassemia births
- **Cost reduction**: Efficient matching lowers overall cost of care
- **Data for policy**: Aggregate insights help government plan blood bank infrastructure

---

## Implementation Phases

### Phase 1: Hackathon Demo (24–36 hrs) — Realistic Scope

> [!NOTE]
> Phase 1 scope is deliberately simplified. SageMaker training, Glue ETL, Kinesis, Redshift, and OpenSearch are **deferred to Phase 2**. The demo uses Dataset.csv loaded directly into RDS and a Python-computed matching score — no SageMaker costs during hackathon.

**Data Seeding** (Dataset.csv → RDS Aurora directly):
- Load all 7,033 records from `Dataset.csv` into RDS Aurora on Day 1
- Pre-compute donor health scores and churn risk flags using a Python script
- Bridge records (80 patients, 786 donor links) populate the patient-side dashboard immediately
- `eligibility_status`, `next_eligible_date`, `calls_to_donations_ratio` columns used directly for matching logic

**Hackathon Deliverables**:
- [ ] React.js frontend — Admin Dashboard + Donor Portal + Patient Portal
- [ ] FastAPI backend with matching API (rule-based + pre-computed ML scores)
- [ ] RDS Aurora PostgreSQL seeded with all Dataset.csv records
- [ ] DynamoDB for real-time outreach state tracking
- [ ] Step Functions outreach workflow with Twilio WhatsApp Sandbox notifications
- [ ] Dashboard: India heatmap (lat/lon from dataset), KPI cards, churn alert list, blood type shortage alerts
- [ ] Veeru 2.0: Amazon Lex + Bedrock chatbot (embedded in frontend as WhatsApp-style UI)
- [ ] AWS Cognito authentication (3 roles: donor, patient, admin)
- [ ] Deployed on AWS App Runner (backend) + Amplify/S3+CloudFront (frontend)

### Phase 2: Post-Hackathon (Month 1–2)
- [ ] Real SageMaker training pipeline (Donor Ranking + Churn Prediction models)
- [ ] Production WhatsApp Business API (replace Twilio sandbox)
- [ ] Amazon Translate multi-language support
- [ ] AWS Glue + Kinesis + Redshift full analytics pipeline
- [ ] Hospital blood bank API integration
- [ ] Mobile-responsive PWA for donors
- [ ] Amazon SageMaker Feature Store with real-time feature updates
- [ ] Guest Conversion ML Model (once richer guest data is collected)

### Phase 3: Scale (Month 3–6)
- [ ] Full SageMaker Autopilot for ranking model optimization
- [ ] Amazon Connect voice escalation
- [ ] Partner NGO white-label portal
- [ ] Pre-conception screening campaign module
- [ ] Government reporting module

---

## Cost Estimate (AWS)

> Budget constraint: Stay within $30–40 limit for hackathon

| Service | Est. Hackathon Cost |
|---------|-------------------|
| RDS Aurora (t3.medium, 2 days) | ~$1.50 |
| App Runner (1 vCPU) | ~$0.50 |
| Lambda (1M invocations) | ~$0.20 |
| Bedrock (Claude Haiku, ~50K tokens) | ~$0.05 |
| S3 + CloudFront + Amplify | ~$0.10 |
| DynamoDB (on-demand) | ~$0.50 |
| Step Functions | ~$0.10 |
| Twilio WhatsApp Sandbox | Free |
| Lex (1,000 requests) | ~$0.75 |
| **Total Estimate** | **~$3.70 for demo** |

> [!NOTE]
> SageMaker endpoint **deferred to Phase 2** — this keeps hackathon cost well within the $30 soft limit. Matching scores are pre-computed via Python from Dataset.csv.

---

## ✅ Decisions Made

| Question | Decision |
|----------|----------|
| **Training data** | Use `Dataset.csv` (7,033 real records) — load directly into RDS Aurora. Pre-compute ML scores via Python script. |
| **WhatsApp integration** | **Twilio WhatsApp Sandbox** — no business API approval needed, supports 5 test numbers, free tier |
| **AWS Account** | ✅ Confirmed — hackathon credits available |
| **Team size** | 2 members — see team split below |

---

## 👥 2-Person Team Split

> **2 members, ~36-hour hackathon execution. Each member owns a full vertical.**

### Member A — Frontend + Infrastructure + Dashboard

| Task | Est. Time | AWS Services |
|------|----------|--------------|
| AWS setup: Cognito, RDS Aurora, S3, Amplify, App Runner | 2 hrs | Cognito, RDS, S3 |
| Load Dataset.csv → RDS Aurora, validate schema | 1 hr | RDS Aurora |
| Pre-compute donor health scores + churn flags (Python) | 2 hrs | Lambda |
| React.js project scaffold + routing (3 roles) | 1 hr | — |
| Admin Dashboard: KPI cards, blood type shortage alerts, churn list | 4 hrs | RDS |
| India state heatmap (Leaflet.js, lat/lon from dataset) | 3 hrs | S3 + CloudFront |
| Donor Portal: profile, eligibility status, donation history | 3 hrs | Cognito + RDS |
| Patient Portal: active request status, upcoming transfusion dates | 2 hrs | RDS |
| Cognito auth integration (login + role-based routing) | 2 hrs | Cognito |
| Deploy frontend to Amplify / S3 + CloudFront | 1 hr | Amplify |
| Demo scenario prep from Dataset.csv | 2 hrs | RDS |
| **Total** | **~23 hrs** | |

### Member B — Backend + AI/ML + Outreach + Chatbot

| Task | Est. Time | AWS Services |
|------|----------|--------------|
| FastAPI scaffold + RDS connection + REST endpoints | 2 hrs | App Runner, RDS |
| Matching API: rule-based ranking (eligibility, ratio, recency, blood type) | 3 hrs | Lambda / App Runner |
| Step Functions 3-wave escalation state machine | 3 hrs | Step Functions |
| Twilio WhatsApp Sandbox setup + webhook → FastAPI | 2 hrs | API Gateway, Lambda |
| DynamoDB: outreach state tracking (sent / responded / donated) | 1 hr | DynamoDB |
| Amazon SES: email notification templates | 1 hr | SES |
| Amazon Lex: define intents (Confirm, Decline, CheckEligibility, History) | 2 hrs | Lex |
| Amazon Bedrock: Lex fallback → Claude Haiku for contextual replies | 2 hrs | Bedrock |
| Veeru 2.0 WhatsApp-style chat UI (embedded in frontend) | 2 hrs | — |
| EventBridge: schedule eligibility re-check trigger jobs | 1 hr | EventBridge |
| End-to-end demo flow test + bug fixes | 3 hrs | All |
| **Total** | **~22 hrs** | |

### Shared Responsibilities
| Task | Who |
|------|-----|
| Architecture decisions | Both |
| Demo script & judge presentation | Both |
| AWS IAM roles + Secrets Manager | Member B sets up, Member A uses |
| Final integration testing | Both (last 3–4 hrs) |

### Recommended Execution Timeline

```
Hour 0–2   — [BOTH]  AWS setup, RDS launch, repo scaffold, env vars, Cognito pool
Hour 2–6   — [A] Data loading + dashboard skeleton
             [B] FastAPI + matching API + Step Functions skeleton
Hour 6–12  — [A] Dashboard KPIs + heatmap + donor/patient portals
             [B] Twilio sandbox + Lex intents + Bedrock connection
Hour 12–18 — [A] Cognito auth + portal polish + Amplify deploy
             [B] Full Step Functions flow + DynamoDB + SES templates
Hour 18–24 — [BOTH] Integration, Veeru 2.0 chat UI, end-to-end testing
Hour 24–36 — [BOTH] Demo polish, edge case fixes, judge presentation prep
```

---

## ⚠️ Recommendations & What to Defer

> [!IMPORTANT]
> **Defer from Phase 1** — too complex for 24–36 hrs, not needed for a compelling demo:
> - AWS Glue ETL pipelines → use direct Python script → RDS load instead
> - Amazon Kinesis Data Streams → use EventBridge + Lambda instead
> - Amazon Redshift warehouse → use direct RDS queries for demo charts
> - SageMaker training jobs → use pre-computed Python scores from Dataset.csv
> - Amazon OpenSearch → use PostgreSQL full-text search for demo
> - Amazon Connect voice → human-only, skip for demo
> - Guest Conversion ML Model → guests have almost no features; show as "future roadmap" slide

> [!TIP]
> **High-impact items for WOW factor with judges:**
> 1. Live donor ranking from real Dataset.csv data — show AI picking the best donor in real-time
> 2. Twilio WhatsApp message actually arriving on a test phone **during the demo** — extremely impressive
> 3. Churn alert dashboard showing the 682 real inactive donors with Bedrock-generated personalized re-engagement messages
> 4. Blood type shortage heatmap highlighting 35 AB-Negative donors vs 20 O-Negative patients — makes the crisis viscerally real

---

## Key Differentiators vs Current System

| Capability | Current BloodBridge | BloodBridge 2.0 (Ours) | Data Evidence |
|-----------|--------------------|-----------------------|--------------|
| Donor selection | Static WhatsApp group | AI-ranked (12 ML features) | calls_to_donation ratio avg 1.85 → target 0.8 |
| Inactive donor handling | None | Churn model + re-engagement | 682 inactive donors recoverable |
| Guest conversion | 0% | AI nurture funnel (Phase 2) | 2,420 guests untapped |
| Rare blood type alerts | None | Real-time shortage dashboard | Only 35 AB-Neg donors in system |
| Emergency donor retention | None | Structured bridge assignment | 2,385 one-time donors never re-contacted |
| Outreach | Manual coordinator message | Autonomous Step Functions | Eliminates 23:1 call:donation worst case |
| Donor dignity | Mass WhatsApp broadcasts | Single channel + Dignity Rules | Frequency cap, quiet hours, one-tap snooze |
| Language | English/Hindi only | 12+ Indian languages | Pan-India scalability |
| Donor availability | Unknown until response | ML-predicted from `next_eligible_date` | Direct dataset column |
| Failure learning | None | Self-improving via SageMaker | `inactive_trigger_comment` as training signal |
| Scale | ~80 patient bridges | ~100,000+ patients | 80 bridges in dataset → unlimited |

---

## Verification Plan

### Demo Flow for Judges (10-minute walkthrough)
1. **Admin Dashboard**: Show India heatmap with real donor/patient concentration (Hyderabad cluster from dataset), blood type shortage alerts (AB-Neg: only 35 donors!), live KPI cards
2. **Trigger a Request**: Simulate a B-Positive patient needing blood → watch AI rank top 5 donors in real-time from actual Dataset.csv records
3. **Outreach Automation**: Show Step Functions state machine executing → Twilio sends a **real WhatsApp message** to test phone on stage
4. **Veeru 2.0**: Type "Am I eligible to donate?" in chat → Lex + Bedrock responds contextually in Hindi or English with memory of past interactions
5. **Churn Intelligence**: Show 321 donors flagged as "Very limited activity despite multiple calls" with Bedrock-generated personalized re-engagement messages ready to send
6. **Analytics**: Demonstrate calls-to-donation ratio baseline (1.85) vs AI target (0.8) — show the system learning from each outreach outcome
