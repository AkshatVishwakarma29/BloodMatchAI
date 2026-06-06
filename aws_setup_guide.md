# ☁️ AWS Cloud Integration & Deployment Guide

This guide provides step-by-step setup instructions for implementing the AWS architecture of the **ThalassemiaFree AI (BloodBridge 2.0)** platform. 

It covers user authentication (Cognito), transactional databases (RDS Aurora PostgreSQL), backend deployment (App Runner), and frontend hosting (Amplify).

---

## 🔐 1. AWS Cognito User Pool Setup

Cognito acts as the Identity Provider for the application, enforcing Role-Based Access Control (RBAC) across three roles: `Admin/Coordinator`, `Donor`, and `Patient`.

### Step-by-Step Provisioning:
1. Open the **AWS Cognito Console** and click **Create user pool**.
2. **Configure sign-in experience**:
   - Select **Email** as the primary sign-in attribute.
   - Click Next.
3. **Configure security requirements**:
   - Set password policy (e.g., minimum 8 characters, numbers, symbols).
   - Select **No MFA** for the hackathon demo, or **SMS MFA / TOTP** for production.
   - Click Next.
4. **Configure sign-up experience**:
   - Keep self-registration enabled.
   - Under **Required attributes**, do not force any unless needed.
   - Click **Add custom attribute**:
     - Name: `role`
     - Type: `String`
     - Min length: `1`, Max length: `20`
     - Mutable: `True` (allows role assignment, though in production you should use Cognito Groups or API gateway claims).
5. **Configure message delivery**:
   - Choose **Send email with Cognito** for development/testing, or integrate with **Amazon SES** for production.
6. **Integrate your app**:
   - Enter a **User pool name** (e.g., `bloodbridge-user-pool`).
   - Under **Initial App Client**:
     - Select **Public client** (suitable for React SPA).
     - App client name: `bloodbridge-react-spa`.
     - Generate client secret: **No** (required for client-side JavaScript SDKs).
7. Review settings and click **Create user pool**.

### React Integration Setup:
In your React app, configure the AWS Amplify Auth SDK using your User Pool IDs:
```javascript
import { Amplify } from 'aws-amplify';

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: 'ap-south-1_xxxxxxxxx',
      userPoolClientId: 'xxxxxxxxxxxxxxxxxxxxxxxxxx'
    }
  }
});
```

---

## 🐘 2. AWS RDS Aurora PostgreSQL Setup

The core relational database stores structured registries, matching metadata, and audit logs. We use standard DDL schemas that map exactly to the columns present in the enriched dataset.

### Step-by-Step Provisioning:
1. Open the **AWS RDS Console** and click **Create database**.
2. Choose **Standard create**.
3. Engine options: **Amazon Aurora** -> **Aurora PostgreSQL-Compatible Edition**.
4. Templates: Select **Dev/Test** (or Serverless v2 for auto-scaling).
5. Settings:
   - DB cluster identifier: `bloodbridge-db-cluster`.
   - Master username: `postgres`.
   - Master password: `SecurePassword123!`.
6. Instance configuration:
   - For dev/testing, select **Serverless v2** (0.5–2 ACUs) or **Provisioned** instance class `db.t3.medium`.
7. Connectivity:
   - Deploy within your default VPC.
   - **Public Access**: Select **Yes** only for testing connections from local development apps (restrict using Security Groups). For production, set to **No** and access via an EC2 bastion host or VPC peering.
   - Create a new VPC security group: `bloodbridge-db-sg`.
8. Database port: `5432`.
9. Click **Create database**. Once active, copy the cluster **Writer Endpoint**.

### 🛠️ Schema DDL Script (SQL)
Execute the following DDL script in your database client (e.g., pgAdmin, DBeaver) to create the schema:

```sql
-- Enable UUID extension for secure random IDs
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. HOSPITALS / BLOOD BANKS
CREATE TABLE hospitals (
    hospital_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    city VARCHAR(50) NOT NULL,
    state VARCHAR(50) NOT NULL,
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6)
);

-- 2. DONORS (Seeded from Dataset_Enriched.csv)
CREATE TABLE donors (
    user_id VARCHAR(50) PRIMARY KEY,
    bridge_id VARCHAR(50),
    role VARCHAR(50) DEFAULT 'Donor',
    role_status VARCHAR(50),
    bridge_status BOOLEAN DEFAULT FALSE,
    blood_group VARCHAR(15) NOT NULL,
    gender VARCHAR(15),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    donor_type VARCHAR(50),
    registration_date DATE,
    last_contacted_date DATE,
    last_donation_date DATE,
    next_eligible_date DATE,
    donations_till_date INT DEFAULT 0,
    eligibility_status VARCHAR(50),
    cycle_of_donations INT,
    total_calls INT DEFAULT 0,
    calls_to_donations_ratio DECIMAL(5,2) DEFAULT 0.0,
    user_donation_active_status VARCHAR(20) DEFAULT 'Active',
    inactive_trigger_comment TEXT,
    health_score DECIMAL(3,2) DEFAULT 0.0,
    churn_risk_score DECIMAL(3,2) DEFAULT 0.0,
    life_credits INT DEFAULT 900,
    cognito_sub UUID UNIQUE
);

-- 3. PATIENTS (Seeded from Dataset_Enriched.csv where role is 'Patient')
CREATE TABLE patients (
    user_id VARCHAR(50) PRIMARY KEY,
    bridge_id VARCHAR(50),
    role VARCHAR(50) DEFAULT 'Patient',
    blood_group VARCHAR(15) NOT NULL,
    gender VARCHAR(15),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    bridge_blood_group VARCHAR(15),
    bridge_gender VARCHAR(15),
    quantity_required INT DEFAULT 1,
    frequency_in_days INT DEFAULT 30,
    last_transfusion_date DATE,
    expected_next_transfusion_date DATE,
    status_of_bridge VARCHAR(50),
    cognito_sub UUID UNIQUE
);

-- 4. TRANSFUSION REQUESTS
CREATE TABLE transfusion_requests (
    request_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id VARCHAR(50) REFERENCES patients(user_id),
    units_needed INT DEFAULT 1,
    needed_by DATE NOT NULL,
    hospital_id VARCHAR(50) REFERENCES hospitals(hospital_id),
    status VARCHAR(20) DEFAULT 'Pending', -- Pending, Matching, Contacting, Confirmed, Completed, Cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. MATCHING & OUTREACH LOGS (Anonymized Proxy Logs)
CREATE TABLE outreach_logs (
    log_id SERIAL PRIMARY KEY,
    request_id UUID REFERENCES transfusion_requests(request_id),
    donor_id VARCHAR(50) REFERENCES donors(user_id),
    proxy_donor_hash VARCHAR(30) NOT NULL,    -- E.g. Donor #D-A1B2C
    proxy_patient_hash VARCHAR(30) NOT NULL,  -- E.g. Fighter #F-8E2F3
    channel VARCHAR(30) DEFAULT 'WhatsApp Secure Proxy',
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'Sent',        -- Sent, Confirmed, Snoozed
    verification_token VARCHAR(20),           -- E.g. TXN-876F2
    response TEXT,
    response_at TIMESTAMP
);
```

### 📥 Seeding the Database from CSV:
To load your enriched dataset into PostgreSQL, use the command-line `copy` command or import utility:

```bash
# Connect to RDS Aurora PostgreSQL instance
psql -h bloodbridge-db-cluster.cluster-xxxxx.ap-south-1.rds.amazonaws.com -U postgres -d postgres

# 1. Load Donors
\copy donors(user_id, bridge_id, role, role_status, bridge_status, blood_group, gender, latitude, longitude, donor_type, last_contacted_date, last_donation_date, next_eligible_date, donations_till_date, eligibility_status, cycle_of_donations, total_calls, calls_to_donations_ratio, user_donation_active_status, inactive_trigger_comment, health_score, churn_risk_score) FROM 'Dataset_Enriched.csv' WITH CSV HEADER DELIMITER ',' NULL AS '';

# 2. Load Patients
\copy patients(user_id, bridge_id, role, blood_group, gender, latitude, longitude, bridge_blood_group, bridge_gender, quantity_required, frequency_in_days, last_transfusion_date, expected_next_transfusion_date, status_of_bridge) FROM 'Dataset_Enriched.csv' WITH CSV HEADER DELIMITER ',' NULL AS '';
```

---

## 🚀 3. AWS App Runner Backend Deployment

AWS App Runner provides an automated environment for running API containers (e.g., FastAPI/Uvicorn backend) without managing compute nodes or load balancers.

### Step-by-Step Deployment:
1. Push your FastAPI backend codebase to a private **GitHub repository** or upload a Docker image to **AWS ECR**.
2. Open the **AWS App Runner Console** and click **Create service**.
3. Select **Source code repository** (if deploying from GitHub) or **Container registry** (if deploying from ECR).
4. Configure the Repository Connection:
   - Link your GitHub account and select the repository and branch.
   - Deployment settings: **Automatic** (triggers a build on git push).
5. Configure Build Settings:
   - Runtime: **Python 3**.
   - Build command: `pip install -r requirements.txt`.
   - Start command: `uvicorn main:app --host 0.0.0.0 --port 8080`.
6. Configure Service Settings:
   - CPU: `1 vCPU`, Memory: `2 GB`.
   - **Environment Variables**:
     - `DATABASE_URL` = `postgresql://postgres:SecurePassword123!@bloodbridge-db-cluster.cluster-xxxxx.ap-south-1.rds.amazonaws.com:5432/postgres`
     - `TWILIO_ACCOUNT_SID` = `ACxxxxxxxxxxxxxxxx`
     - `TWILIO_AUTH_TOKEN` = `xxxxxxxxxxxxxxxxxx`
     - `TWILIO_WHATSAPP_NUMBER` = `whatsapp:+14155238886`
7. Click **Create & Deploy**.
8. Once active, copy the **Default Domain URL** (e.g., `https://xxxxxx.ap-south-1.awsapprunner.com`). Use this URL as the backend base path in your React app.

---

## 🌐 4. AWS Amplify Frontend Deployment

AWS Amplify offers global CDN hosting for React (Vite) single-page applications with continuous deployment.

### Step-by-Step Deployment:
1. Push your React app to a **GitHub repository**.
2. Open the **AWS Amplify Console** and click **New App** -> **Host web app**.
3. Connect **GitHub** and select your repository and branch (e.g., `main`).
4. Configure Build Settings:
   - Amplify will automatically detect Vite. The build script should resemble:
     ```yaml
     version: 1
     frontend:
       phases:
         preBuild:
           commands:
             - npm ci
         build:
           commands:
             - npm run build
       artifacts:
         baseDirectory: dist
         files:
           - '**/*'
       cache:
         paths:
           - node_modules/**/*
     ```
5. Click **Save and Deploy**.
6. **Configuring SPA Routing Rewrites (CRITICAL)**:
   Because the React application uses client-side routing (Single Page App), refresh actions on subpages (e.g., `/donor`, `/about`) will return a 404 error from CloudFront. Add a redirection rule:
   - In the Amplify console, navigate to **Rewrites and redirects**.
   - Click **Edit**.
   - Add the following rule:
     - Source Address: `</^[^.]+$|\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|ttf|map|json)$)([^.]+$)/>`
     - Target Address: `/index.html`
     - Type: `200 (Rewrite)`
   - Click Save.
7. Access your live application at the provided `.amplifyapp.com` link.

---

## ⚡ 5. AWS Step Functions Outreach State Machine (Member B Task)

AWS Step Functions orchestrates the sequential 3-wave donor outreach. If Wave 1 donors do not respond within a configured interval, the state machine automatically triggers Wave 2, and then Wave 3, before finally escalating to a human coordinator.

### Step-by-Step Provisioning:
1. Open the **AWS Step Functions Console** and click **Create state machine**.
2. Select **Blank template** and choose **Design your workflow visually** (standard workflow type).
3. Drag and drop the following states into the canvas:
   *   **Task State (Lambda):** `Rank Donors` — Queries `/api/requests/match-preview` to rank the top 9 compatible donors.
   *   **Choice State:** `Are Donors Available?` — If the candidate list is empty, transition immediately to the `Escalate to Coordinator` task.
   *   **Map/Loop State (Waves 1 to 3):** Iterate through waves of size 3:
       *   **Task State (Lambda):** `Dispatch Outreach Wave` — Calls Twilio WhatsApp sandbox to send messages.
       *   **Wait State:** Set duration (4 hours for production, 15 seconds for sandbox demo testing).
       *   **Task State (Lambda):** `Check Request Status` — Queries the SQLite/RDS database to see if `Request.status` became `"in_progress"` or `"fulfilled"`.
       *   **Choice State:** `Is Confirmed?` — If confirmed, exit the map state and transition to `Confirm & End`. If not confirmed and more waves remain, loop to the next wave.
   *   **Task State (Lambda):** `Escalate to Coordinator` — Alters status to `escalated` and sends an SNS alert.
4. Click **Create** and assign the necessary IAM Execution Role allowing Lambda invocation.

---

## 🤖 6. Amazon Lex & Bedrock Setup ("Veeru 2.0") (Member B Task)

This configures the conversational interface that donor and patient nodes interact with, including the LLM-powered fallback that handles general inquiries under strict privacy filters.

### Step-by-Step Provisioning:
1. Open the **Amazon Lex Console** and click **Create bot**.
2. Configuration:
   *   Select **Create a blank bot**.
   *   Bot name: `VeeruBot`.
   *   COPPA: Select **No**.
   *   Idle session timeout: `5 minutes`.
3. Create **Intents**:
   *   `ConfirmDonation`: Add sample utterances like `"Confirm"`, `"Accept"`, `"Yes, I will donate"`.
   *   `DeclineDonation`: Add sample utterances like `"Decline"`, `"Snooze"`, `"Cannot donate"`.
   *   `CheckEligibility`: Add sample utterances like `"Am I eligible"`, `"When can I donate"`, `"Check eligibility"`.
4. Configure **Fallback Intent**:
   *   Enable **Fulfillment** and select **Active** for the associated AWS Lambda function (`veeru-llm-fallback`).
5. Provision the **Fallback Lambda Function**:
   *   Create a Python Lambda function containing the AWS Bedrock client:
       ```python
       import boto3
       import json

       def lambda_handler(event, context):
           bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
           
           # Extract incoming message text and profile details from payload
           user_msg = event['inputTranscript']
           
           # Inject context & double-blind privacy guidelines in System Instruction
           system_instruction = (
               "You are Veeru 2.0, an empathetic chatbot for Blood Warriors supporting Thalassemia patients. "
               "CRITICAL: Under our double-blind system, NEVER reveal names, phone numbers, or details "
               "of patients to donors or donors to patients. If asked, explain this privacy policy."
           )
           
           body = json.dumps({
               "prompt": f"System: {system_instruction}\nUser: {user_msg}\nAssistant:",
               "max_tokens_to_sample": 200,
               "temperature": 0.5
           })
           
           response = bedrock.invoke_model(
               modelId='anthropic.claude-3-haiku-20240307-v1:0',
               contentType='application/json',
               accept='application/json',
               body=body
           )
           
           response_body = json.loads(response.get('body').read())
           reply = response_body.get('completion')
           
           return {
               "sessionState": {
                   "dialogAction": {
                       "type": "Close"
                   },
                   "intent": {
                       "name": event['sessionState']['intent']['name'],
                       "state": "Fulfilled"
                   }
               },
               "messages": [
                   {
                       "contentType": "PlainText",
                       "content": reply
                   }
               ]
           }
       ```

---

## 📞 7. Twilio Webhook Integration via API Gateway (Member B Task)

Configures the incoming webhooks so that replies to the Twilio WhatsApp Sandbox are processed by the FastAPI backend in real-time.

### Step-by-Step Provisioning:
1. Open the **Amazon API Gateway Console** and click **Create API**.
2. Select **HTTP API** (fastest and cheapest for webhooks).
3. Click **Add Integration** ➔ Choose **HTTP**.
   *   Method: `POST`.
   *   URL: Enter your App Runner URL: `https://xxxxxx.ap-south-1.awsapprunner.com/api/outreach/respond`.
4. Configure Routes:
   *   Method: `POST`.
   *   Path: `/api/twilio/webhook`.
5. Click Next, leave Stage as `$default` (with auto-deploy enabled), and click **Create**.
6. Copy the **Invoke URL** (e.g., `https://yyyyyy.execute-api.ap-south-1.amazonaws.com`).
7. Open the **Twilio Console**:
   *   Go to **Messaging** ➔ **Try it out** ➔ **Send a WhatsApp Message**.
   *   Navigate to **Sandbox Settings**.
   *   Paste the API Gateway URL in the **"When a message comes in"** box:
       `https://yyyyyy.execute-api.ap-south-1.amazonaws.com/api/twilio/webhook`
   *   Set the method dropdown to `POST`.
   *   Click Save.
