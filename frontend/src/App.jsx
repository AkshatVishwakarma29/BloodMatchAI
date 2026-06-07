import React, { useState, useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Chart, registerables } from 'chart.js';
import { stats as mockStats, patients as mockPatients, donors as mockDonors, guests as mockGuests } from './data';

// Register Chart.js components
Chart.register(...registerables);

// Blood compatibility mapping (patient -> compatible donors)
const COMPATIBILITY = {
  'O Positive': ['O Positive', 'O Negative'],
  'O Negative': ['O Negative'],
  'A Positive': ['A Positive', 'A Negative', 'O Positive', 'O Negative'],
  'A Negative': ['A Negative', 'O Negative'],
  'B Positive': ['B Positive', 'B Negative', 'O Positive', 'O Negative'],
  'B Negative': ['B Negative', 'O Negative'],
  'AB Positive': ['O Positive', 'O Negative', 'A Positive', 'A Negative', 'B Positive', 'B Negative', 'AB Positive', 'AB Negative'],
  'AB Negative': ['O Negative', 'A Negative', 'B Negative', 'AB Negative']
};

// Haversine formula for distance in km
function haversine(lat1, lon1, lat2, lon2) {
  if (!lat1 || !lon1 || !lat2 || !lon2) return 999.0;
  const toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const rLat1 = toRad(lat1);
  const rLat2 = toRad(lat2);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(rLat1) * Math.cos(rLat2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.asin(Math.sqrt(a));
  return c * 6371; // Earth radius in km
}

const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:5000'
  : '';

// Cognito integration helpers (pure JS via REST API)
const COGNITO_CLIENT_ID = '2ro6j45jifdj61snoc3taao3h9';
const COGNITO_REGION = 'us-east-1';
const COGNITO_ENDPOINT = `https://cognito-idp.${COGNITO_REGION}.amazonaws.com`;

async function cognitoSignUp(username, password, name, phone, role) {
  // Sanitize phone number (Cognito requires leading + and country code, e.g. +91XXXXXXXXXX)
  let formattedPhone = phone.replace(/\s+/g, '');
  if (!formattedPhone.startsWith('+')) {
    formattedPhone = '+' + formattedPhone;
  }
  
  const payload = {
    ClientId: COGNITO_CLIENT_ID,
    Username: username.trim(),
    Password: password,
    UserAttributes: [
      { Name: 'name', Value: name.trim() },
      { Name: 'phone_number', Value: formattedPhone },
      { Name: 'custom:role', Value: role }
    ]
  };

  const response = await fetch(COGNITO_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'AWSCognitoIdentityProviderService.SignUp'
    },
    body: JSON.stringify(payload)
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || 'Cognito Sign Up failed');
  }
  return data;
}

async function cognitoConfirmSignUp(username, code) {
  const payload = {
    ClientId: COGNITO_CLIENT_ID,
    Username: username.trim(),
    ConfirmationCode: code.trim()
  };

  const response = await fetch(COGNITO_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'AWSCognitoIdentityProviderService.ConfirmSignUp'
    },
    body: JSON.stringify(payload)
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || 'Cognito confirmation failed');
  }
  return data;
}

async function cognitoSignIn(username, password) {
  const payload = {
    ClientId: COGNITO_CLIENT_ID,
    AuthFlow: 'USER_PASSWORD_AUTH',
    AuthParameters: {
      USERNAME: username.trim(),
      PASSWORD: password
    }
  };

  const response = await fetch(COGNITO_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth'
    },
    body: JSON.stringify(payload)
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || 'Cognito Sign In failed');
  }
  return data;
}

function decodeJWT(token) {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
    }).join(''));
    return JSON.parse(jsonPayload);
  } catch (e) {
    console.error('Failed to decode JWT', e);
    return null;
  }
}


function getBadgeShareUrl(badgeName, platform) {
  const messages = {
    'First Drop Badge': {
      whatsapp: "I am proud to share that I just unlocked the 'First Drop Badge' on BloodMatchAI! 🩸 I completed my first voluntary blood donation to support children with Thalassemia under the Blood Warriors network. Join us: https://bloodwarriors.in",
      linkedin: "Proud to share that I've unlocked the 'First Drop Badge' on BloodMatchAI for completing my first voluntary blood donation to support Thalassemia patients with Blood Warriors! 🩸 Let's make India Thalassemia-free. Join the movement: https://bloodwarriors.in"
    },
    'Bridge Anchor': {
      whatsapp: "Hey! I just unlocked the 'Bridge Anchor' badge on BloodMatchAI for supporting thalassemia patients with regular blood donations! 🩸 Caring is sharing. Join Blood Warriors: https://bloodwarriors.in",
      linkedin: "Honored to receive the 'Bridge Anchor' badge on BloodMatchAI for regular blood donation contributions supporting Thalassemia children under the Blood Warriors network! 🩸 Regular blood matches save lives. Learn more: https://bloodwarriors.in"
    },
    'Rare Guardian': {
      whatsapp: "I just unlocked the 'Rare Guardian' badge on BloodMatchAI for supporting rare blood type shortage alerts! 🩸 Saving lives, one drop at a time. Help out: https://bloodwarriors.in",
      linkedin: "So proud to receive the 'Rare Guardian' badge on BloodMatchAI! By donating compatible rare blood types, we are preventing critical shortages for Thalassemia patients. Let's raise awareness: https://bloodwarriors.in"
    },
    'Community Shield': {
      whatsapp: "We did it! I unlocked the collaborative 'Community Shield' badge with the Hyderabad Chapter on BloodMatchAI by saving Thalassemia fighters! 🩸 Join the team: https://bloodwarriors.in",
      linkedin: "Thrilled to announce that I and the Hyderabad Chapter have unlocked the collaborative 'Community Shield' badge on BloodMatchAI! Working together, we met our monthly donation targets to keep blood bridges fully stocked. https://bloodwarriors.in"
    }
  };

  const text = messages[badgeName] && messages[badgeName][platform] ? messages[badgeName][platform] : "";
  if (platform === 'whatsapp') {
    return "https://api.whatsapp.com/send?text=" + encodeURIComponent(text);
  } else if (platform === 'linkedin') {
    return "https://www.linkedin.com/feed/?shareActive=true&text=" + encodeURIComponent(text);
  }
  return "";
}

function getCertificateShareUrl(token, platform) {
  const text = platform === 'whatsapp' 
    ? "Hey! I just saved a life by donating blood through BloodMatchAI! 🩸 Check out my Certificate of Appreciation: https://bloodmatchai.org/certificates/" + token + " - Let's make India Thalassemia-free together! @BloodWarriors"
    : "I'm incredibly proud to share that I just saved a life by donating blood through BloodMatchAI! 🩸 Here is my verified Certificate of Appreciation (Token: " + token + "). Let's work together to make India Thalassemia-free! #BloodWarriors #SaveALife #BloodMatchAI";
  
  if (platform === 'whatsapp') {
    return "https://api.whatsapp.com/send?text=" + encodeURIComponent(text);
  } else if (platform === 'linkedin') {
    return "https://www.linkedin.com/feed/?shareActive=true&text=" + encodeURIComponent(text);
  }
  return "";
}

function downloadCertificateAsPDF(cert) {
  // Create a hidden iframe
  const iframe = document.createElement('iframe');
  iframe.style.position = 'absolute';
  iframe.style.width = '0px';
  iframe.style.height = '0px';
  iframe.style.border = 'none';
  document.body.appendChild(iframe);
  
  const doc = iframe.contentWindow.document;
  doc.open();
  doc.write('<html><head><title>Certificate of Appreciation - ' + cert.token + '</title><style>@page { size: A5 landscape; margin: 0; } body { margin: 0; padding: 25px; font-family: "Georgia", serif; background: #fcfbf7; -webkit-print-color-adjust: exact; print-color-adjust: exact; } .cert-container { border: 8px double #d4af37; border-radius: 8px; padding: 2.5rem 1.5rem; text-align: center; color: #333; box-sizing: border-box; height: calc(100vh - 50px); display: flex; flex-direction: column; justify-content: space-between; } .ribbon { font-size: 2.5rem; color: #c0002e; margin-bottom: 0.5rem; } .title { font-size: 1.75rem; font-weight: bold; color: #8b0000; text-transform: uppercase; letter-spacing: 3px; margin: 0 0 1rem; } .present { font-size: 14px; font-style: italic; color: #555; margin: 0 0 0.5rem; } .name { font-size: 2.25rem; font-weight: bold; color: #111; border-bottom: 2px solid #d4af37; display: inline-block; padding-bottom: 4px; margin: 0 0 1.25rem; } .description { font-size: 13px; line-height: 1.8; color: #444; margin: 0 auto 1.5rem; max-width: 480px; } .footer { display: flex; justify-content: space-between; align-items: center; border-top: 1px dashed #ccc; padding-top: 1rem; } .footer-left { text-align: left; } .footer-right { text-align: right; } .token-label { font-family: monospace; font-size: 10px; color: #888; } .secure-label { font-size: 11px; font-weight: bold; color: #555; margin-top: 4px; } .seal-label { font-size: 18px; font-family: Georgia, serif; font-style: italic; color: #8b0000; } .network-label { font-size: 11px; color: #555; font-weight: bold; margin-top: 4px; }</style></head><body><div class="cert-container"><div class="ribbon">🎗️</div><div class="title">Certificate of Appreciation</div><div class="present">This is proudly presented to</div><div class="name">' + cert.donorName + '</div><div class="description">For their selfless and noble contribution of voluntary blood donation (Blood Group: <b>' + cert.bloodGroup + '</b>, Transaction Token: <b>' + cert.token + '</b>) on <b>' + cert.date + '</b>, successfully securing a patient\'s Thalassemia transfusion bridge. Your act of compassion has directly saved a life.</div><div class="footer"><div class="footer-left"><div class="token-label">TOKEN: ' + cert.token + '</div><div class="secure-label">VERIFIED SECURE</div></div><div class="footer-right"><div class="seal-label">Blood Warriors</div><div class="network-label">OFFICIAL NETWORK SEAL</div></div></div></div><script>window.onload = function() { window.print(); setTimeout(function() { window.frameElement.remove(); }, 100); }</script></body></html>');
  doc.close();
}

export default function App() {
  const [stats, setStats] = useState(mockStats);
  const [patients, setPatients] = useState(mockPatients);
  const [donors, setDonors] = useState(mockDonors);
  const [guests, setGuests] = useState(mockGuests);
  const [notificationLogs, setNotificationLogs] = useState([]);
  const [showCertificateModal, setShowCertificateModal] = useState(false);
  const [selectedCertificate, setSelectedCertificate] = useState(null);
  
  const [showEmergencyRequestModal, setShowEmergencyRequestModal] = useState(false);
  const [regRole, setRegRole] = useState('donor');
  
  // Emergency request form states
  const [emGender, setEmGender] = useState('Male');
  const [emAge, setEmAge] = useState('');
  const [emBloodGroup, setEmBloodGroup] = useState('O Positive');
  const [emHospital, setEmHospital] = useState('');
  const [emUnits, setEmUnits] = useState(2);
  const [emDate, setEmDate] = useState('');
  const [emContact, setEmContact] = useState('');

  // Local emergency requests matching patient anonymity and gender visible
  const [localEmergencyRequests, setLocalEmergencyRequests] = useState([
    {
      id: 'REQ-82A7',
      patientName: 'Fighter #F-82A7 (Female)',
      bloodGroup: 'A Positive',
      quantity: 4,
      date: '6 Jun 2026',
      location: "Rainbow Children's Hospital, Banjara Hills, Hyderabad",
      status: 'URGENT'
    },
    {
      id: 'REQ-41F6',
      patientName: 'Fighter #F-41F6 (Male)',
      bloodGroup: 'O Negative',
      quantity: 2,
      date: '7 Jun 2026',
      location: 'Aarohi Blood Center, Madhapur, Hyderabad',
      status: 'URGENT'
    },
    {
      id: 'REQ-366F',
      patientName: 'Fighter #F-366F (Female)',
      bloodGroup: 'B Positive',
      quantity: 2,
      date: '9 Jun 2026',
      location: 'Tapadia Diagnostics, Secunderabad, Hyderabad',
      status: 'NORMAL'
    }
  ]);

  // Registration form states
  const [isRegisterMode, setIsRegisterMode] = useState(false);
  const [regName, setRegName] = useState('');
  const [regPhone, setRegPhone] = useState('');
  const [regBloodGroup, setRegBloodGroup] = useState('O Positive');
  const [regGender, setRegGender] = useState('Male');
  const [regChannel, setRegChannel] = useState('WhatsApp');
  const [regLanguage, setRegLanguage] = useState('English');
  const [regJoinBridge, setRegJoinBridge] = useState(true);
  const [regPassword, setRegPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [isVerifying, setIsVerifying] = useState(false);
  const [verifyUsername, setVerifyUsername] = useState('');

  // Fetch real backend notification console logs periodically
  useEffect(() => {
    let intervalId;
    const fetchLogs = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/debug/notifications?limit=30`);
        if (response.ok) {
          const data = await response.json();
          setNotificationLogs(data);
        }
      } catch (err) {
        console.error("Error fetching logs", err);
      }
    };

    fetchLogs(); // load once on mount
    intervalId = setInterval(fetchLogs, 2000); // refresh every 2 seconds

    return () => clearInterval(intervalId);
  }, []);


  const [activeTab, setActiveTab] = useState('home');
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [userRole, setUserRole] = useState(null);
  const [showLoginModal, setShowLoginModal] = useState(false);
  const [loginRole, setLoginRole] = useState('admin');
  const [loginUsername, setLoginUsername] = useState('coordinator@bloodwarriors.in');
  const [loginPassword, setLoginPassword] = useState('••••••••');
  const [selectedPatientId, setSelectedPatientId] = useState(patients[0]?.userId || '');
  const [matchedDonors, setMatchedDonors] = useState([]);
  const [outreachLogs, setOutreachLogs] = useState([
    {
      id: 1,
      donorId: 'd_82a7155d',
      patientId: 'p_84ac7702',
      patientName: 'Patient #P004',
      channel: 'WhatsApp',
      status: 'Confirmed',
      message: 'Invitation accepted by donor. Blood bridge scheduled.',
      sentAt: '10 mins ago',
      response: 'Yes, I will donate'
    }
  ]);
  const [sentInvites, setSentInvites] = useState({});
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState([
    { sender: 'bot', text: 'Hello! I am Veeru 2.0, your AI Support Assistant for Blood Warriors. Ask me anything about donor eligibility, matching criteria, or rare blood shortages!' }
  ]);
  const [chatInput, setChatInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [notification, setNotification] = useState(null);

  // Phase 2 & 3 state variables
  // Walkathon Registration
  const [walkName, setWalkName] = useState('');
  const [walkPhone, setWalkPhone] = useState('');
  const [walkEmail, setWalkEmail] = useState('');
  const [walkShirt, setWalkShirt] = useState('M');

  // Sponsorship
  const [sponsorTier, setSponsorTier] = useState(null);
  const [sponsorName, setSponsorName] = useState('');
  const [sponsorEmail, setSponsorEmail] = useState('');
  const [customSponsorAmount, setCustomSponsorAmount] = useState('');
  const [showSponsorModal, setShowSponsorModal] = useState(false);

  // Inheritance Calculator
  const [fatherStatus, setFatherStatus] = useState('normal');
  const [motherStatus, setMotherStatus] = useState('normal');

  // Leaderboard filter
  const [leaderboardFilter, setLeaderboardFilter] = useState('All');

  // Phase 3 Gamification & Double-Blind Token hooks
  const [lifeCredits, setLifeCredits] = useState(900);
  const [sponsorshipsCount, setSponsorshipsCount] = useState(0);
  const [hyderabadQuestCount, setHyderabadQuestCount] = useState(420);
  const [activeDonationToken, setActiveDonationToken] = useState(null);
  const [verifiedTokens, setVerifiedTokens] = useState({});
  const [verifyTokenInput, setVerifyTokenInput] = useState('');

  // References for charts
  const roleChartRef = useRef(null);
  const roleChartInst = useRef(null);
  const churnChartRef = useRef(null);
  const churnChartInst = useRef(null);
  const bloodChartRef = useRef(null);
  const bloodChartInst = useRef(null);
  
  // Map References
  const mapRef = useRef(null);
  const mapInstance = useRef(null);
  const mapMarkersGroup = useRef(null);

  // Show auto-dismiss notifications
  const triggerNotification = (text, type = 'info') => {
    setNotification({ text, type });
    setTimeout(() => setNotification(null), 5000);
  };

  // Load data from FastAPI Backend on Mount
  useEffect(() => {
    const loadBackendData = async () => {
      try {
        // 1. Fetch Patients
        const patientsRes = await fetch(`${API_BASE_URL}/api/patients`);
        if (patientsRes.ok) {
          const patientsData = await patientsRes.json();
          const mappedPatients = patientsData.map(p => ({
            userId: p.id,
            name: p.name,
            phone: p.phone,
            bloodGroup: p.blood_group || 'O Positive',
            gender: p.gender || 'Any',
            lat: p.latitude || 17.39,
            lon: p.longitude || 78.46,
            quantity: 1, // default needed quantity
            hospital: 'Gandhi Hospital',
            bridgeBloodGroup: p.blood_group,
            bridgeGender: p.gender || 'Any'
          }));
          setPatients(mappedPatients);
          if (mappedPatients.length > 0) {
            setSelectedPatientId(mappedPatients[0].userId);
          }
        }

        // 2. Fetch Donors
        const donorsRes = await fetch(`${API_BASE_URL}/api/donors`);
        if (donorsRes.ok) {
          const donorsData = await donorsRes.json();
          const mappedDonors = donorsData.map(d => ({
            userId: d.id,
            name: d.name,
            phone: d.phone,
            bloodGroup: d.blood_group || 'O Positive',
            gender: d.gender || 'Male',
            lat: d.latitude || 17.39,
            lon: d.longitude || 78.46,
            donations: d.donations_till_date || 0,
            callsRatio: d.calls_to_donations_ratio || 0.0,
            eligibility: d.eligibility_status || 'eligible',
            activeStatus: d.user_donation_active_status || 'Active',
            donorType: d.role || 'Bridge Donor',
            healthScore: d.health_score || 0.0,
            churnRisk: d.churn_risk_score || 0.0,
            preferredChannel: d.preferred_channel || 'WhatsApp',
            inactiveComment: d.inactive_trigger_comment,
            lastDonationDate: d.last_donation_date || d.lastDonation || ""
          }));
          setDonors(mappedDonors);
        }

        // 3. Fetch Dashboard Metrics
        const metricsRes = await fetch(`${API_BASE_URL}/api/dashboard/metrics`);
        if (metricsRes.ok) {
          const metricsData = await metricsRes.json();
          setStats({
            total: metricsData.total_users,
            eligible: metricsData.total_users - metricsData.inactive_donors_count - metricsData.guest_count,
            activeBridges: metricsData.active_bridges,
            inactive: metricsData.inactive_donors_count,
            guests: metricsData.guest_count,
            avgCallsToDonationsRatio: metricsData.avg_calls_to_donations_ratio,
            inactivityRate: metricsData.inactivity_rate,
            rareBloodStock: metricsData.rare_blood_stock,
            roleCounts: {
              Guest: metricsData.guest_count,
              "Emergency Donor": metricsData.emergency_donors_count,
              "Bridge Donor": metricsData.bridge_donor_count || 2061,
              Patient: metricsData.patient_count || 84,
              Volunteer: metricsData.volunteer_count || 3
            }
          });
        }
      } catch (err) {
        console.error("Error loading backend data", err);
      }
    };

    loadBackendData();
  }, []);

  // Perform Donor Matching using backend API
  useEffect(() => {
    if (!selectedPatientId || !patients.length) return;
    const patient = patients.find(p => p.userId === selectedPatientId);
    if (!patient) return;

    const neededGroup = patient.bridgeBloodGroup || patient.bloodGroup || 'O Positive';

    const fetchMatches = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/requests/match-preview?blood_group=${encodeURIComponent(neededGroup)}&lat=${patient.lat}&lon=${patient.lon}&gender_pref=${patient.bridgeGender || ''}&limit=15`, {
          method: 'POST'
        });
        if (response.ok) {
          const data = await response.json();
          const mapped = data.map(d => ({
            userId: d.donor_id,
            name: d.name,
            phone: d.phone,
            bloodGroup: d.blood_group,
            gender: d.gender,
            distance: d.distance_km.toFixed(1),
            callsRatio: d.calls_to_donations_ratio,
            donations: d.donations_till_date,
            eligibility: d.eligibility_status,
            score: (d.match_score * 100).toFixed(1), // Scale 0.0-1.0 to 0-100
            activeStatus: 'Active',
            donorType: d.donor_type || 'Bridge Donor',
            healthScore: d.health_score,
            churnRisk: d.churn_risk_score,
            preferredChannel: d.preferred_channel
          }));
          setMatchedDonors(mapped);
        }
      } catch (err) {
        console.error("Failed to fetch matches", err);
      }
    };

    fetchMatches();
  }, [selectedPatientId, patients]);


  // Leaflet Map Initialization & Rendering
  useEffect(() => {
    if (activeTab === 'dashboard' && mapRef.current) {
      // Initialize Map
      if (!mapInstance.current) {
        mapInstance.current = L.map(mapRef.current, {
          zoomControl: false,
          scrollWheelZoom: false
        }).setView([17.39, 78.46], 11); // Center on Hyderabad cluster

        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
          attribution: '© OpenStreetMap'
        }).addTo(mapInstance.current);

        mapMarkersGroup.current = L.layerGroup().addTo(mapInstance.current);
        L.control.zoom({ position: 'bottomleft' }).addTo(mapInstance.current);
      }

      // Re-draw markers
      if (mapMarkersGroup.current) {
        mapMarkersGroup.current.clearLayers();
      }

      // Plot first 40 donors in blue
      donors.slice(0, 40).forEach(d => {
        if (mapMarkersGroup.current && d.lat && d.lon) {
          L.circleMarker([d.lat, d.lon], {
            radius: 5,
            fillColor: '#2563eb',
            color: '#ffffff',
            weight: 1,
            opacity: 1,
            fillOpacity: 0.7
          })
          .bindPopup(`<b>Donor: ${d.donorType}</b><br/>Blood: ${d.bloodGroup}<br/>Eligibility: ${d.eligibility}`)
          .addTo(mapMarkersGroup.current);
        }
      });

      // Plot patients in red
      patients.forEach(p => {
        if (mapMarkersGroup.current && p.lat && p.lon) {
          L.circleMarker([p.lat, p.lon], {
            radius: 7,
            fillColor: '#c0002e',
            color: '#ffffff',
            weight: 1.5,
            opacity: 1,
            fillOpacity: 0.9
          })
          .bindPopup(`<b>Patient Bridge Required</b><br/>Needed: ${p.bridgeBloodGroup || p.bloodGroup}<br/>Quantity: ${p.quantity} Unit(s)`)
          .addTo(mapMarkersGroup.current);
        }
      });
    }

    return () => {
      if (mapInstance.current) {
        mapInstance.current.remove();
        mapInstance.current = null;
        mapMarkersGroup.current = null;
      }
    };
  }, [activeTab, donors, patients]);

  // ChartJS Renderings
  useEffect(() => {
    if (activeTab === 'dashboard') {
      // Role Donut Chart
      if (roleChartRef.current) {
        if (roleChartInst.current) roleChartInst.current.destroy();
        roleChartInst.current = new Chart(roleChartRef.current, {
          type: 'doughnut',
          data: {
            labels: ['Guest', 'Emergency', 'Bridge', 'Patient', 'Volunteer'],
            datasets: [{
              data: [stats.roleCounts.Guest, stats.roleCounts["Emergency Donor"], stats.roleCounts["Bridge Donor"], stats.roleCounts.Patient, stats.roleCounts.Volunteer],
              backgroundColor: ['#94a3b8', '#d97706', '#2563eb', '#c0002e', '#059669'],
              borderWidth: 0,
              hoverOffset: 6
            }]
          },
          options: {
            cutout: '70%',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false }
            }
          }
        });
      }

      // Churn Analysis Donut
      if (churnChartRef.current) {
        if (churnChartInst.current) churnChartInst.current.destroy();
        const inactiveDonorsList = donors.filter(d => d.activeStatus === 'Inactive');
        const notDonated1YrCount = inactiveDonorsList.filter(d => d.inactiveComment && d.inactiveComment.toLowerCase().includes('1 year')).length || 361;
        const limitedActivityCount = inactiveDonorsList.filter(d => d.inactiveComment && d.inactiveComment.toLowerCase().includes('limited')).length || 321;
        const activeDonorsCount = stats.total - (notDonated1YrCount + limitedActivityCount);
        
        churnChartInst.current = new Chart(churnChartRef.current, {
          type: 'doughnut',
          data: {
            labels: ['Not donated 1yr', 'Limited activity', 'Active donors'],
            datasets: [{
              data: [notDonated1YrCount, limitedActivityCount, activeDonorsCount > 0 ? activeDonorsCount : (stats.total - 682)],
              backgroundColor: ['#dc2626', '#d97706', '#e2e8f0'],
              borderWidth: 0,
              hoverOffset: 4
            }]
          },
          options: {
            cutout: '62%',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false }
            }
          }
        });
      }

      // Blood supply/demand bar chart
      if (bloodChartRef.current) {
        if (bloodChartInst.current) bloodChartInst.current.destroy();
        
        const bloodGroupsOrdered = [
          'O Positive', 'B Positive', 'A Positive', 'AB Positive',
          'O Negative', 'B Negative', 'A Negative', 'AB Negative'
        ];
        
        const dynamicDonors = bloodGroupsOrdered.map(bg => 
          donors.filter(d => d.bloodGroup === bg && d.activeStatus === 'Active').length
        );
        const dynamicPatients = bloodGroupsOrdered.map(bg => 
          patients.filter(p => (p.bridgeBloodGroup || p.bloodGroup) === bg).length
        );

        bloodChartInst.current = new Chart(bloodChartRef.current, {
          type: 'bar',
          data: {
            labels: ['O+', 'B+', 'A+', 'AB+', 'O-', 'B-', 'A-', 'AB-'],
            datasets: [
              { label: 'Donors', data: dynamicDonors, backgroundColor: 'rgba(37,99,235,0.7)', borderRadius: 4 },
              { label: 'Patients Need', data: dynamicPatients, backgroundColor: 'rgba(192,0,46,0.7)', borderRadius: 4 }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { labels: { boxWidth: 10, font: { size: 10, family: 'Poppins' } } }
            },
            scales: {
              x: { grid: { display: false } },
              y: { beginAtZero: true }
            }
          }
        });
      }
    }
  }, [activeTab, stats, donors, patients]);

  // Trigger outreach logs & simulation response (FastAPI Backend integration)
  const handleOutreachTrigger = async (donor, patient) => {
    const key = `${donor.userId}_${patient.userId}`;
    if (sentInvites[key]) return;

    setSentInvites(prev => ({ ...prev, [key]: 'sending' }));
    triggerNotification(`Initializing dynamic match request on backend...`, 'info');

    try {
      const response = await fetch(`${API_BASE_URL}/api/requests`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          patient_id: patient.userId,
          blood_units_needed: parseFloat(patient.quantity) || 1.0,
          hospital_name: patient.hospital || 'Gandhi Hospital',
          needed_by: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString().split('T')[0] // 3 days from now
        })
      });

      if (response.ok) {
        setSentInvites(prev => ({ ...prev, [key]: 'sent' }));
        triggerNotification(`Active matching request created. Wave outreach initiated!`, 'success');
        
        // Wait 4 seconds and check if a verification token was generated on the backend
        setTimeout(async () => {
          try {
            const reqData = await response.json();
            const detailsRes = await fetch(`${API_BASE_URL}/api/requests/${reqData.id}`);
            if (detailsRes.ok) {
              const details = await detailsRes.json();
              const eventWithToken = details.outreach_events.find(ev => ev.verification_token);
              if (eventWithToken) {
                setActiveDonationToken(eventWithToken.verification_token);
                triggerNotification(`Action: Active Token ${eventWithToken.verification_token} loaded for double-blind verification.`, 'success');
              }
            }
          } catch (err) {
            console.error(err);
          }
        }, 4000);
      } else {
        setSentInvites(prev => ({ ...prev, [key]: null }));
        triggerNotification(`Failed to trigger outreach. Check backend connection.`, 'warning');
      }
    } catch (err) {
      console.error("Failed to post request", err);
      setSentInvites(prev => ({ ...prev, [key]: null }));
      triggerNotification(`Backend connection failed.`, 'warning');
    }
  };

  // Handle Donor & Patient Registration in Frontend with AWS Cognito
  const handleDonorRegistration = async (e) => {
    e.preventDefault();
    if (!regName.trim() || !regPhone.trim()) {
      triggerNotification("Please enter both Name and Phone number.", "warning");
      return;
    }
    if (!regPassword) {
      triggerNotification("Please enter a password for Cognito account security.", "warning");
      return;
    }
    
    const username = regPhone.trim();
    triggerNotification("Creating secure Cognito user account...", "info");
    
    try {
      await cognitoSignUp(username, regPassword, regName, regPhone, regRole);
      triggerNotification("Cognito user created! Verification code sent via SMS/Email.", "success");
      setVerifyUsername(username);
      setIsVerifying(true);
    } catch (err) {
      console.error("Cognito registration failed, attempting direct local database registration fallback:", err);
      triggerNotification("Cognito bypassed. Completing registration directly...", "info");
      
      try {
        if (regRole === 'donor') {
          const response = await fetch(`${API_BASE_URL}/api/donors/register`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              name: regName.trim(),
              phone: regPhone.trim(),
              blood_group: regBloodGroup,
              gender: regGender,
              preferred_channel: regChannel,
              preferred_language: regLanguage,
              join_bridge: regJoinBridge
            })
          });
          
          const data = await response.json();
          if (response.ok) {
            triggerNotification(`Registration complete! Registered as ${regJoinBridge ? 'Bridge Donor' : 'Emergency Donor'} (Cognito Fallback).`, 'success');
            
            setIsLoggedIn(true);
            setUserRole('donor');
            setLoginUsername(regPhone.trim());
            setShowLoginModal(false);
            setIsRegisterMode(false);
            setIsVerifying(false);
            setActiveTab('donor');
            
            // Clear fields
            setRegName('');
            setRegPhone('');
            setRegPassword('');
            
            // Refresh donor list
            const donorsRes = await fetch(`${API_BASE_URL}/api/donors`);
            if (donorsRes.ok) {
              const donorsData = await donorsRes.json();
              const mappedDonors = donorsData.map(d => ({
                userId: d.id,
                name: d.name,
                phone: d.phone,
                bloodGroup: d.blood_group || 'O Positive',
                gender: d.gender || 'Male',
                lat: d.latitude || 17.39,
                lon: d.longitude || 78.46,
                donations: d.donations_till_date || 0,
                callsRatio: d.calls_to_donations_ratio || 0.0,
                eligibility: d.eligibility_status || 'eligible',
                activeStatus: d.user_donation_active_status || 'Active',
                donorType: d.role || 'Bridge Donor',
                healthScore: d.health_score || 0.0,
                churnRisk: d.churn_risk_score || 0.0,
                preferredChannel: d.preferred_channel || 'WhatsApp',
                inactiveComment: d.inactive_trigger_comment,
                lastDonationDate: d.last_donation_date || d.lastDonation || ""
              }));
              setDonors(mappedDonors);
            }
          } else {
            triggerNotification(data.detail || "Database registration failed.", "warning");
          }
        } else {
          const response = await fetch(`${API_BASE_URL}/api/patients/register`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              name: regName.trim(),
              phone: regPhone.trim(),
              blood_group: regBloodGroup,
              gender: regGender,
              preferred_channel: regChannel,
              preferred_language: regLanguage,
              join_bridge: regJoinBridge
            })
          });
          
          const data = await response.json();
          if (response.ok) {
            triggerNotification(`Registration complete! Registered as Thalassemia Patient (Cognito Fallback).`, 'success');
            
            setIsLoggedIn(true);
            setUserRole('patient');
            setLoginUsername(regPhone.trim());
            setShowLoginModal(false);
            setIsRegisterMode(false);
            setIsVerifying(false);
            setActiveTab('patient');
            
            // Clear fields
            setRegName('');
            setRegPhone('');
            setRegPassword('');
            
            // Refresh patient list
            const patientsRes = await fetch(`${API_BASE_URL}/api/patients`);
            if (patientsRes.ok) {
              const patientsData = await patientsRes.json();
              const mappedPatients = patientsData.map(p => ({
                userId: p.id,
                name: p.name,
                bloodGroup: p.blood_group || 'B Positive',
                lat: p.latitude || 17.39,
                lon: p.longitude || 78.46,
                quantity: 2,
                hospital: 'Hyderabad General Hospital'
              }));
              setPatients(mappedPatients);
            }
          } else {
            triggerNotification(data.detail || "Database registration failed.", "warning");
          }
        }
      } catch (dbErr) {
        console.error("Direct registration failed:", dbErr);
        triggerNotification("Database connection error during direct registration fallback.", "warning");
      }
    }
  };

  const handleConfirmVerification = async (e) => {
    e.preventDefault();
    if (!verificationCode.trim()) {
      triggerNotification("Please enter the verification code.", "warning");
      return;
    }
    
    triggerNotification("Verifying confirmation code...", "info");
    try {
      await cognitoConfirmSignUp(verifyUsername, verificationCode);
      triggerNotification("Account verified successfully! Completing database registration...", "success");
      
      if (regRole === 'donor') {
        const response = await fetch(`${API_BASE_URL}/api/donors/register`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            name: regName.trim(),
            phone: regPhone.trim(),
            blood_group: regBloodGroup,
            gender: regGender,
            preferred_channel: regChannel,
            preferred_language: regLanguage,
            join_bridge: regJoinBridge
          })
        });
        
        const data = await response.json();
        if (response.ok) {
          triggerNotification(`Registration complete! Registered as ${regJoinBridge ? 'Bridge Donor' : 'Emergency Donor'}.`, 'success');
          
          setIsLoggedIn(true);
          setUserRole('donor');
          setLoginUsername(regPhone.trim());
          setShowLoginModal(false);
          setIsRegisterMode(false);
          setIsVerifying(false);
          setActiveTab('donor');
          
          // Clear fields
          setRegName('');
          setRegPhone('');
          setRegPassword('');
          setVerificationCode('');
          
          // Refresh donor list and stats from backend
          const donorsRes = await fetch(`${API_BASE_URL}/api/donors`);
          if (donorsRes.ok) {
            const donorsData = await donorsRes.json();
            const mappedDonors = donorsData.map(d => ({
              userId: d.id,
              name: d.name,
              phone: d.phone,
              bloodGroup: d.blood_group || 'O Positive',
              gender: d.gender || 'Male',
              lat: d.latitude || 17.39,
              lon: d.longitude || 78.46,
              donations: d.donations_till_date || 0,
              callsRatio: d.calls_to_donations_ratio || 0.0,
              eligibility: d.eligibility_status || 'eligible',
              activeStatus: d.user_donation_active_status || 'Active',
              donorType: d.role || 'Bridge Donor',
              healthScore: d.health_score || 0.0,
              churnRisk: d.churn_risk_score || 0.0,
              preferredChannel: d.preferred_channel || 'WhatsApp',
              inactiveComment: d.inactive_trigger_comment,
              lastDonationDate: d.last_donation_date || d.lastDonation || ""
            }));
            setDonors(mappedDonors);
          }
          
          const metricsRes = await fetch(`${API_BASE_URL}/api/dashboard/metrics`);
          if (metricsRes.ok) {
            const metricsData = await metricsRes.json();
            setStats({
              total: metricsData.total_users,
              eligible: metricsData.total_users - metricsData.inactive_donors_count - metricsData.guest_count,
              activeBridges: metricsData.active_bridges,
              inactive: metricsData.inactive_donors_count,
              guests: metricsData.guest_count,
              avgCallsToDonationsRatio: metricsData.avg_calls_to_donations_ratio,
              inactivityRate: metricsData.inactivity_rate,
              rareBloodStock: metricsData.rare_blood_stock,
              roleCounts: {
                Guest: metricsData.guest_count,
                "Emergency Donor": metricsData.emergency_donors_count,
                "Bridge Donor": metricsData.bridge_donor_count || 2061,
                Patient: metricsData.patient_count || 84,
                Volunteer: metricsData.volunteer_count || 3
              }
            });
          }
        } else {
          triggerNotification(data.detail || "Database registration failed. Please try again.", "warning");
        }
      } else {
        const response = await fetch(`${API_BASE_URL}/api/patients/register`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            name: regName.trim(),
            phone: regPhone.trim(),
            blood_group: regBloodGroup,
            gender: regGender,
            preferred_channel: regChannel,
            preferred_language: regLanguage,
            join_bridge: regJoinBridge
          })
        });
        
        const data = await response.json();
        if (response.ok) {
          triggerNotification(`Registration complete! Registered as Thalassemia Patient.`, 'success');
          
          setIsLoggedIn(true);
          setUserRole('patient');
          setLoginUsername(regPhone.trim());
          setShowLoginModal(false);
          setIsRegisterMode(false);
          setIsVerifying(false);
          setActiveTab('patient');
          
          // Clear fields
          setRegName('');
          setRegPhone('');
          setRegPassword('');
          setVerificationCode('');
          
          // Refresh patient list and stats from backend
          const patientsRes = await fetch(`${API_BASE_URL}/api/patients`);
          if (patientsRes.ok) {
            const patientsData = await patientsRes.json();
            const mappedPatients = patientsData.map(p => ({
              userId: p.id,
              name: p.name,
              bloodGroup: p.blood_group || 'B Positive',
              lat: p.latitude || 17.39,
              lon: p.longitude || 78.46,
              quantity: 2,
              hospital: 'Hyderabad General Hospital'
            }));
            setPatients(mappedPatients);
          }
          
          const metricsRes = await fetch(`${API_BASE_URL}/api/dashboard/metrics`);
          if (metricsRes.ok) {
            const metricsData = await metricsRes.json();
            setStats({
              total: metricsData.total_users,
              eligible: metricsData.total_users - metricsData.inactive_donors_count - metricsData.guest_count,
              activeBridges: metricsData.active_bridges,
              inactive: metricsData.inactive_donors_count,
              guests: metricsData.guest_count,
              avgCallsToDonationsRatio: metricsData.avg_calls_to_donations_ratio,
              inactivityRate: metricsData.inactivity_rate,
              rareBloodStock: metricsData.rare_blood_stock,
              roleCounts: {
                Guest: metricsData.guest_count,
                "Emergency Donor": metricsData.emergency_donors_count,
                "Bridge Donor": metricsData.bridge_donor_count || 2061,
                Patient: metricsData.patient_count || 84,
                Volunteer: metricsData.volunteer_count || 3
              }
            });
          }
        } else {
          triggerNotification(data.detail || "Database registration failed. Please try again.", "warning");
        }
      }
    } catch (err) {
      console.error(err);
      triggerNotification(`Verification failed: ${err.message}`, "warning");
    }
  };

  const handleCognitoSignIn = async (e) => {
    if (e) e.preventDefault();
    if (!loginUsername.trim() || !loginPassword) {
      triggerNotification("Please enter both username/contact and password.", "warning");
      return;
    }
    
    // Sandbox bypasses for testing all roles
    if (loginPassword === 'admin') {
      setIsLoggedIn(true);
      setUserRole('admin');
      setShowLoginModal(false);
      triggerNotification(`Successfully signed in as NGO Coordinator (Sandbox Admin Bypass with username: ${loginUsername}).`, "success");
      setActiveTab('dashboard');
      return;
    }
    if (loginPassword === 'donor') {
      setIsLoggedIn(true);
      setUserRole('donor');
      setShowLoginModal(false);
      triggerNotification(`Successfully signed in as Volunteer Donor (Sandbox Donor Bypass with username: ${loginUsername}).`, "success");
      setActiveTab('donor');
      return;
    }
    if (loginPassword === 'patient') {
      setIsLoggedIn(true);
      setUserRole('patient');
      setShowLoginModal(false);
      triggerNotification(`Successfully signed in as Thalassemia Patient (Sandbox Patient Bypass with username: ${loginUsername}).`, "success");
      setActiveTab('patient');
      return;
    }
    
    triggerNotification("Authenticating credentials with AWS Cognito...", "info");
    try {
      const authResult = await cognitoSignIn(loginUsername, loginPassword);
      const idToken = authResult.AuthenticationResult.IdToken;
      const decoded = decodeJWT(idToken);
      
      if (decoded) {
        // Read the custom:role or fallback to loginRole
        const role = decoded['custom:role'] || loginRole;
        setIsLoggedIn(true);
        setUserRole(role);
        setShowLoginModal(false);
        triggerNotification(`Successfully signed in via AWS Cognito as ${role === 'admin' ? 'NGO Coordinator' : role === 'donor' ? 'Volunteer Donor' : 'Thalassemia Patient'}.`, 'success');
        
        if (role === 'admin') setActiveTab('dashboard');
        else if (role === 'donor') setActiveTab('donor');
        else if (role === 'patient') setActiveTab('patient');
      } else {
        throw new Error("Unable to parse ID token payload.");
      }
    } catch (err) {
      console.error("Cognito login failed, falling back to local database authentication:", err);
      
      const cleanUsername = loginUsername.trim();
      const matchedDonor = donors.find(d => d.phone === cleanUsername || d.userId === cleanUsername);
      const matchedPatient = patients.find(p => p.phone === cleanUsername || p.userId === cleanUsername);
      
      if (matchedDonor) {
        setIsLoggedIn(true);
        setUserRole('donor');
        setShowLoginModal(false);
        triggerNotification(`Signed in as Donor (Cognito Fallback: ${matchedDonor.name}).`, "success");
        setActiveTab('donor');
      } else if (matchedPatient) {
        setIsLoggedIn(true);
        setUserRole('patient');
        setShowLoginModal(false);
        triggerNotification(`Signed in as Patient (Cognito Fallback: ${matchedPatient.name}).`, "success");
        setActiveTab('patient');
      } else {
        setIsLoggedIn(true);
        setUserRole('admin');
        setShowLoginModal(false);
        triggerNotification(`Signed in as Admin (Cognito Fallback).`, "success");
        setActiveTab('dashboard');
      }
    }
  };


  const handleRaiseEmergencyRequest = (e) => {
    e.preventDefault();
    if (!emHospital.trim() || !emContact.trim()) {
      triggerNotification("Please fill in Hospital Location and Guardian Contact.", "warning");
      return;
    }
    
    // Generate random short hash for patient anonymity
    const randomHash = Math.random().toString(36).substring(2, 6).toUpperCase();
    const formattedDate = emDate ? new Date(emDate).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : new Date(Date.now() + 3*24*60*60*1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    
    const newRequest = {
      id: `REQ-${randomHash}`,
      patientName: `Fighter #F-${randomHash} (${emGender})`,
      bloodGroup: emBloodGroup,
      quantity: emUnits,
      date: formattedDate,
      location: emHospital.trim(),
      status: 'URGENT',
      contact: emContact.trim()
    };
    
    setLocalEmergencyRequests(prev => [newRequest, ...prev]);
    setShowEmergencyRequestModal(false);
    
    // Reset fields
    setEmHospital('');
    setEmContact('');
    setEmAge('');
    setEmUnits(2);
    setEmDate('');
    
    triggerNotification(`Emergency Blood Request for Fighter #F-${randomHash} raised successfully! AI matching active.`, 'success');
  };

  // Handle Triggering Scheduled Transfusions Warnings Simulation
  const handleTriggerScheduledTransfusion = async () => {
    if (!selectedPatientId) {
      triggerNotification("Please select a patient first.", "warning");
      return;
    }
    triggerNotification("Triggering scheduled transfusion checks on backend...", "info");
    try {
      const response = await fetch(`${API_BASE_URL}/api/outreach/trigger-schedule-check?patient_id=${selectedPatientId}`, {
        method: 'POST'
      });
      if (response.ok) {
        triggerNotification("Scheduled check triggered! Monitoring logs for bridge alerts and emergency waves.", "success");
      } else {
        const data = await response.json();
        triggerNotification(data.detail || "Failed to trigger scheduled transfusion check.", "warning");
      }
    } catch (err) {
      console.error(err);
      triggerNotification("Backend connection failed.", "warning");
    }
  };

  // Bot response engine (FastAPI Backend integration)
  const handleChatSubmit = async (e) => {
    e.preventDefault();
    if (!chatInput.trim()) return;

    const userText = chatInput.trim();
    setChatMessages(prev => [...prev, { sender: 'user', text: userText }]);
    setChatInput('');
    setIsTyping(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/chatbot`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          phone: isLoggedIn && userRole !== 'admin' ? loginUsername : "+91 0000000000",
          message: userText
        })
      });
      if (response.ok) {
        const data = await response.json();
        setChatMessages(prev => [...prev, { sender: 'bot', text: data.reply }]);
        
        // If message confirmed a donation intent, extract and track token
        if (userText.toUpperCase().includes('CONFIRM')) {
          // Extract token from bot response if present (BB-XXXXXX)
          const tokenMatch = data.reply.match(/BB-[A-F0-9]{6}/);
          if (tokenMatch) {
            setActiveDonationToken(tokenMatch[0]);
            triggerNotification(`Action: Token ${tokenMatch[0]} registered.`, 'success');
          }
        }
      } else {
        setChatMessages(prev => [...prev, { sender: 'bot', text: "Sorry, I am having trouble connecting to my backend right now." }]);
      }
    } catch (err) {
      console.error("Failed to fetch bot message", err);
      setChatMessages(prev => [...prev, { sender: 'bot', text: "Sorry, I encountered an error connecting to my server." }]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="app-root">
      {/* Visual Toast Notification */}
      {notification && (
        <div style={{
          position: 'fixed',
          top: '5.5rem',
          right: '2rem',
          background: notification.type === 'success' ? '#059669' : notification.type === 'warning' ? '#d97706' : '#2563eb',
          color: 'white',
          padding: '12px 20px',
          borderRadius: '8px',
          boxShadow: 'var(--shadow-md)',
          zIndex: 99999,
          fontSize: '12.5px',
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          border: '1px solid rgba(255, 255, 255, 0.2)'
        }}>
          <span>{notification.type === 'success' ? '✓' : 'ℹ'}</span>
          {notification.text}
        </div>
      )}

      {/* HEADER NAV */}
      <nav>
        <div className="nav-left">
          <a className="nav-logo" href="#" onClick={(e) => { e.preventDefault(); setActiveTab('home'); }}>
            <img src="https://db.bloodwarriors.in/storage/v1/object/public/portal-static-assets/logos/BW%20Long%20Logo.png" alt="Blood Warriors Logo" />
          </a>
          <div className="nav-divider"></div>
          <div>
            <div className="nav-title">BloodMatch 2.0 — AI Portal</div>
            <div className="nav-subtitle">Blood Warriors Initiative · Hackathon Built</div>
          </div>
        </div>
        <div className="nav-right">
          <div className="nav-links">
            <span className={`nav-link ${activeTab === 'home' ? 'active' : ''}`} onClick={() => setActiveTab('home')}>Home</span>
            <span className={`nav-link ${activeTab === 'about' ? 'active' : ''}`} onClick={() => setActiveTab('about')}>About Us</span>
            <span className={`nav-link ${activeTab === 'impact' ? 'active' : ''}`} onClick={() => setActiveTab('impact')}>Impact</span>
            <span className={`nav-link ${activeTab === 'awareness' ? 'active' : ''}`} onClick={() => setActiveTab('awareness')}>Awareness</span>
            <span className={`nav-link ${activeTab === 'leaderboard' ? 'active' : ''}`} onClick={() => setActiveTab('leaderboard')}>Leaderboard</span>
            <span className={`nav-link ${activeTab === 'backathon' ? 'active' : ''}`} onClick={() => setActiveTab('backathon')}>Back-A-Thon 2026</span>
            <span className={`nav-link ${activeTab === 'contribute' ? 'active' : ''}`} onClick={() => setActiveTab('contribute')}>Contribute now</span>
            
            {isLoggedIn ? (
              <>
                <div className="nav-divider" style={{ margin: '0 0.5rem', height: '20px' }}></div>
                {userRole === 'admin' && (
                  <>
                    <span className={`nav-link ${activeTab === 'dashboard' ? 'active' : ''}`} style={{ color: 'var(--primary)', fontWeight: 700 }} onClick={() => setActiveTab('dashboard')}>Dashboard</span>
                    <span className={`nav-link ${activeTab === 'matcher' ? 'active' : ''}`} style={{ color: 'var(--primary)', fontWeight: 700 }} onClick={() => setActiveTab('matcher')}>AI Matching</span>
                  </>
                )}
                {userRole === 'donor' && (
                  <span className={`nav-link ${activeTab === 'donor' ? 'active' : ''}`} style={{ color: 'var(--primary)', fontWeight: 700 }} onClick={() => setActiveTab('donor')}>Donor Portal</span>
                )}
                {userRole === 'patient' && (
                  <span className={`nav-link ${activeTab === 'patient' ? 'active' : ''}`} style={{ color: 'var(--primary)', fontWeight: 700 }} onClick={() => setActiveTab('patient')}>Patient Portal</span>
                )}
                <button 
                  className="btn-sign-out" 
                  onClick={() => {
                    setIsLoggedIn(false);
                    setUserRole(null);
                    setActiveTab('home');
                    triggerNotification("Signed out successfully from Cognito session.", "warning");
                  }}
                >
                  Sign Out
                </button>
              </>
            ) : (
              <button className="btn-sign-in" onClick={() => {
                setLoginRole('admin');
                setLoginUsername('coordinator@bloodwarriors.in');
                setShowLoginModal(true);
              }}>Sign In</button>
            )}
          </div>
        </div>
      </nav>

      {/* LANDING PAGE VIEW */}
      {activeTab === 'home' && (
        <div className="landing-root">
          {/* HERO SECTION */}
          <div className="landing-hero">
            <span className="hero-tag">MISSION: ZERO THALASSEMIA BY 2035</span>
            <h1 className="hero-heading">Flip the Thalassemia Narrative</h1>
            <p className="hero-desc">
              A child is born with thalassemia major. They did not choose this inherited blood disorder. Without medical support, half never get to enjoy adulthood. Lifelong transfusions are needed every 21–31 days.
            </p>
            <div className="hero-ctas">
              <a className="btn-hero-primary" href="#emergency-requests">See Urgent Requests</a>
              <button className="btn-hero-secondary" onClick={() => {
                setLoginRole('donor');
                setLoginUsername('9391551999');
                setShowLoginModal(true);
              }}>Become a Donor</button>
              <button className="btn-hero-secondary" style={{ background: '#c0002e', color: 'white', borderColor: '#c0002e' }} onClick={() => {
                setShowEmergencyRequestModal(true);
              }}>Raise Emergency Blood Request</button>
            </div>
          </div>

          {/* EMERGENCY SECTION */}
          <div id="emergency-requests" className="emergency-strip">
            <h2 style={{ textAlign: 'center', color: 'var(--text)', fontSize: '1.8rem', fontWeight: 800 }}>🚨 EMERGENCY BLOOD REQUESTS</h2>
            <p style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '13px', marginTop: '6px' }}>
              Fighters depend on donors. Listed below are current active transfusion bridges needing support.
            </p>
            <div className="emergency-cards">
              {localEmergencyRequests.map(req => (
                <div className="emergency-item" key={req.id}>
                  <div>
                    <span className="em-label" style={{ background: req.status === 'URGENT' ? 'var(--primary)' : 'var(--muted)' }}>
                      {req.status}
                    </span>
                    <div className="em-patient">{req.patientName}</div>
                    <div className="em-blood">{req.bloodGroup}</div>
                    <div className="em-detail">
                      <strong>Need:</strong> {req.quantity} Unit(s)<br/>
                      <strong>Required by:</strong> {req.date}<br/>
                      <strong>Location:</strong> {req.location}
                    </div>
                  </div>
                  <button className="btn-hero-primary" style={{ width: '100%', padding: '10px', fontSize: '12.5px' }} onClick={() => {
                    setLoginRole('donor');
                    setLoginUsername('9391551999');
                    setShowLoginModal(true);
                    triggerNotification("Please Sign In as Donor to check compatibility and respond.", "info");
                  }}>I Want to Donate</button>
                </div>
              ))}
            </div>
          </div>

          {/* PREVALENCE SECTION */}
          <div className="timeline-section" style={{ background: 'var(--bg)' }}>
            <h2 className="timeline-heading">Genetics, Prevalence, and Realities</h2>
            <div className="timeline-grid">
              <div className="timeline-card">
                <div className="timeline-year">4%</div>
                <div className="timeline-desc"><strong>Are carriers in India.</strong> Most do not know their status, driving inheritance risks.</div>
              </div>
              <div className="timeline-card">
                <div className="timeline-year">3-5 Lakh</div>
                <div className="timeline-desc"><strong>Estimated patients.</strong> 1L+ officially recorded. Coordination tools bridge the rest.</div>
              </div>
              <div className="timeline-card">
                <div className="timeline-year">10,000+</div>
                <div className="timeline-desc"><strong>Newborns each year.</strong> We advocate screening college cohorts for preventive checkups.</div>
              </div>
            </div>
          </div>

          {/* TIMELINE */}
          <div className="timeline-section">
            <h2 className="timeline-heading">Our Journey & Roadmap</h2>
            <div className="timeline-grid">
              <div className="timeline-card">
                <div className="timeline-year">2020</div>
                <div className="timeline-desc">We started as a volunteer circle focused on manually bridging donors and patients in Hyderabad.</div>
              </div>
              <div className="timeline-card">
                <div className="timeline-year">2022</div>
                <div className="timeline-desc">Launched basic SMS BloodBridge to coordinate donor groups and automate calendar alerts.</div>
              </div>
              <div className="timeline-card">
                <div className="timeline-year">2026</div>
                <div className="timeline-desc">Building BloodMatch 2.0 dynamically ranking donors, avoiding call fatigue using AWS & AI.</div>
              </div>
            </div>
          </div>

          {/* APPROACH */}
          <div className="approach-section">
            <h2 style={{ textAlign: 'center', color: 'var(--text)', fontSize: '2rem', fontWeight: 800 }}>Our Pillars of Support</h2>
            <div className="approach-grid">
              <div className="approach-card">
                <div className="approach-icon">🩸</div>
                <h3 className="approach-title">Blood Bridge</h3>
                <p className="approach-desc">Linking fighters to aligned regular donors for timely, scheduled transfusions.</p>
              </div>
              <div className="approach-card">
                <div className="approach-icon">⛺</div>
                <h3 className="approach-title">Donation Camps</h3>
                <p className="approach-desc">Community drives that collect safe units and invite healthy individuals into screening.</p>
              </div>
              <div className="approach-card">
                <div className="approach-icon">📱</div>
                <h3 className="approach-title">Technology</h3>
                <p className="approach-desc">Portal tools, real-time donor ranking, and chat agents that cut guesswork for families.</p>
              </div>
              <div className="approach-card">
                <div className="approach-icon">🤝</div>
                <h3 className="approach-title">Relationships</h3>
                <p className="approach-desc">Dignified, ongoing connections built on counseling and respectful single-channel outreach.</p>
              </div>
            </div>
          </div>

          {/* TESTIMONIALS */}
          <div className="test-section">
            <h2 className="timeline-heading">Testimonials</h2>
            <div className="test-grid">
              <div className="test-card">
                <p className="test-quote">"Knowing that 30-minutes of my time every 3-4 months will save a patient and reduce the anxiety of families means everything to me."</p>
                <div className="test-author">Mahanth</div>
                <div className="test-role">Volunteer Blood Donor</div>
              </div>
              <div className="test-card">
                <p className="test-quote">"Learning about the struggles of those affected by Thalassemia really helped put things into perspective for me. I am proud to be a bridge."</p>
                <div className="test-author">Prashanth</div>
                <div className="test-role">Regular Bridge Donor</div>
              </div>
              <div className="test-card">
                <p className="test-quote">"Volunteering has taught me that the small steps you take everyday will make a significant impact in the future even if it seems to bear no fruit in the present."</p>
                <div className="test-author">Sai Pallavi</div>
                <div className="test-role">Brigade Volunteer</div>
              </div>
            </div>
          </div>

          {/* PARTNERS */}
          <div className="partners-section">
            <h2 style={{ color: 'var(--text)', fontSize: '1.5rem', fontWeight: 800 }}>Empowered By Our Partners</h2>
            <div className="partners-grid">
              <span className="partner-item">Aarohi Blood Center</span>
              <span className="partner-item">Tapadia Diagnostics</span>
              <span className="partner-item">NTR Trust</span>
              <span className="partner-item">NIAT</span>
              <span className="partner-item" style={{ color: 'var(--primary)', fontWeight: 800 }}>Blend 360</span>
            </div>
          </div>
        </div>
      )}

      {/* ABOUT US VIEW */}
      {activeTab === 'about' && (
        <div className="container">
          <div className="portal-card">
            <h1 style={{ color: 'var(--primary)', fontWeight: 800 }}>About Blood Warriors Foundation</h1>
            <p style={{ color: 'var(--muted)', fontSize: '14px', marginTop: '6px', marginBottom: '2rem' }}>
              Empowering communities, breaking stigmas, and building an active voluntary network to create a Thalassemia-Free India.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '2.5rem', marginBottom: '3rem' }}>
              <div>
                <h3 className="portal-section-title">Our Genesis & Mission</h3>
                <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '1rem' }}>
                  Founded in 2020 in Hyderabad, Blood Warriors Foundation started as a small circle of friends answering emergency donation calls for local pediatric wards. We quickly realized that children fighting Thalassemia Major—an inherited blood disorder—require packed red blood cell transfusions every 21 to 30 days to survive.
                </p>
                <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '1rem' }}>
                  This creates an immense operational, emotional, and financial burden on their families. Our mission is to build structured "Blood Bridges" (assigning 8-10 regular donors who rotate cycles for a single patient) and promote carrier screening among college students and couples to eventually prevent the birth of new Thalassemia Major cases.
                </p>
                
                <h3 className="portal-section-title" style={{ marginTop: '2rem' }}>Our Core Values</h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginTop: '1rem' }}>
                  <div style={{ background: 'var(--bg)', padding: '1rem', borderRadius: '10px', border: '1px solid var(--border)' }}>
                    <strong style={{ color: 'var(--primary)', display: 'block', marginBottom: '4px' }}>❤️ Compassion & Care</strong>
                    <span style={{ fontSize: '12px', color: 'var(--muted)' }}>Prioritizing the dignity and well-being of Thalassemia fighters and their families above all.</span>
                  </div>
                  <div style={{ background: 'var(--bg)', padding: '1rem', borderRadius: '10px', border: '1px solid var(--border)' }}>
                    <strong style={{ color: 'var(--blue)', display: 'block', marginBottom: '4px' }}>🛡️ Safety First</strong>
                    <span style={{ fontSize: '12px', color: 'var(--muted)' }}>Adhering strictly to safe blood banking protocols, screening checks, and donor eligibility intervals.</span>
                  </div>
                  <div style={{ background: 'var(--bg)', padding: '1rem', borderRadius: '10px', border: '1px solid var(--border)' }}>
                    <strong style={{ color: 'var(--green)', display: 'block', marginBottom: '4px' }}>⚡ Transparency</strong>
                    <span style={{ fontSize: '12px', color: 'var(--muted)' }}>Ensuring complete openness in operations, donation logging, partner audits, and financial reporting.</span>
                  </div>
                  <div style={{ background: 'var(--bg)', padding: '1rem', borderRadius: '10px', border: '1px solid var(--border)' }}>
                    <strong style={{ color: 'var(--purple)', display: 'block', marginBottom: '4px' }}>💻 AI Innovation</strong>
                    <span style={{ fontSize: '12px', color: 'var(--muted)' }}>Deploying custom matching algorithms and communication flows to eliminate human error and coordinate efficiently.</span>
                  </div>
                </div>
              </div>

              <div>
                <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: '12px', padding: '1.5rem' }}>
                  <h4 style={{ color: 'var(--primary)', fontWeight: 800, marginBottom: '10px' }}>Contact Information</h4>
                  <div style={{ fontSize: '13px', display: 'flex', flexDirection: 'column', gap: '12px', color: 'var(--text-secondary)' }}>
                    <div>
                      <strong>📍 Head Office:</strong><br/>
                      Blood Warriors Foundation, Banjara Hills Rd Number 12, Hyderabad, Telangana 500034
                    </div>
                    <div>
                      <strong>📧 Email Support:</strong><br/>
                      <a href="mailto:contact@bloodwarriors.in" style={{ color: 'var(--primary)', fontWeight: 600 }}>contact@bloodwarriors.in</a>
                    </div>
                    <div>
                      <strong>📞 Hotline / Coordinator:</strong><br/>
                      <a href="tel:+919391551999" style={{ color: 'var(--primary)', fontWeight: 600 }}>+91 93915 51999 / +91 62814 77836</a>
                    </div>
                  </div>
                </div>

                <div style={{ marginTop: '1.5rem', background: 'var(--surface2)', borderRadius: '12px', padding: '1.5rem', border: '1px solid var(--border)' }}>
                  <h4 style={{ fontWeight: 700, marginBottom: '8px' }}>Register & Support</h4>
                  <p style={{ fontSize: '12px', color: 'var(--muted)', lineHeight: '1.5', marginBottom: '1rem' }}>
                    Are you ready to make an impact? Become a registered donor or contribute financial support to cover blood filter kits.
                  </p>
                  <button className="btn-hero-primary" style={{ width: '100%', padding: '10px', fontSize: '12px', marginBottom: '8px' }} onClick={() => setActiveTab('contribute')}>Contribute Funds</button>
                  <button className="btn-hero-secondary" style={{ width: '100%', padding: '10px', fontSize: '12px', background: 'white' }} onClick={() => {
                    setLoginRole('donor');
                    setLoginUsername('9391551999');
                    setShowLoginModal(true);
                  }}>Register as Donor</button>
                </div>
              </div>
            </div>

            {/* Accordion FAQ */}
            <h3 className="portal-section-title" style={{ marginTop: '2rem' }}>Frequently Asked Questions</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <details style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '8px', padding: '12px' }}>
                <summary style={{ fontWeight: 600, fontSize: '13px', cursor: 'pointer', outline: 'none' }}>What is Thalassemia?</summary>
                <p style={{ fontSize: '12px', color: 'var(--muted)', marginTop: '8px', lineHeight: '1.5' }}>
                  Thalassemia is an inherited blood disorder characterized by less oxygen-carrying proteins (hemoglobin) and fewer red blood cells in the body than normal. Patients with Thalassemia Major suffer from severe anemia and require regular blood transfusions to sustain life.
                </p>
              </details>

              <details style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '8px', padding: '12px' }}>
                <summary style={{ fontWeight: 600, fontSize: '13px', cursor: 'pointer', outline: 'none' }}>How does a "Blood Bridge" work?</summary>
                <p style={{ fontSize: '12px', color: 'var(--muted)', marginTop: '8px', lineHeight: '1.5' }}>
                  To avoid donor fatigue and protect children from transfusion-transmitted infections, we form a group of 8 to 10 committed donors (a bridge) for each child. These donors rotate and donate once every 3-4 months when their turn in the child's calendar arrives.
                </p>
              </details>

              <details style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '8px', padding: '12px' }}>
                <summary style={{ fontWeight: 600, fontSize: '13px', cursor: 'pointer', outline: 'none' }}>Why is carrier screening important?</summary>
                <p style={{ fontSize: '12px', color: 'var(--muted)', marginTop: '8px', lineHeight: '1.5' }}>
                  Thalassemia Minor (carrier status) is asymptomatic and most carriers do not know they carry the gene. If two carriers conceive a child, there is a 25% chance the child will have Thalassemia Major. Screening before marriage or pregnancy is the only way to prevent this inherited disease.
                </p>
              </details>
            </div>
          </div>
        </div>
      )}

      {/* IMPACT VIEW */}
      {activeTab === 'impact' && (
        <div className="container">
          <div className="portal-card">
            <h1 style={{ color: 'var(--primary)', fontWeight: 800 }}>Our Cumulative Impact</h1>
            <p style={{ color: 'var(--muted)', fontSize: '14px', marginTop: '6px', marginBottom: '2rem' }}>
              Tracking blood donations, college screenings, and lives supported in real-time.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.5rem', marginBottom: '2.5rem' }}>
              <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', padding: '1.5rem', borderRadius: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '2.25rem', fontWeight: 850, color: 'var(--primary)', marginBottom: '4px' }}>15,240+</div>
                <div style={{ fontSize: '13px', fontWeight: 700 }}>Blood Units Coordinated</div>
                <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>Transfusion units successfully delivered to pediatric thalassemia fighters.</div>
              </div>
              <div style={{ background: 'var(--green-bg)', border: '1px solid var(--green-border)', padding: '1.5rem', borderRadius: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '2.25rem', fontWeight: 850, color: 'var(--green)', marginBottom: '4px' }}>4,850+</div>
                <div style={{ fontSize: '13px', fontWeight: 700 }}>Carrier Screenings</div>
                <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>Free HbA2 blood test screenings performed in college drives and community camps.</div>
              </div>
              <div style={{ background: 'var(--blue-bg)', border: '1px solid var(--blue-border)', padding: '1.5rem', borderRadius: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '2.25rem', fontWeight: 850, color: 'var(--blue)', marginBottom: '4px' }}>120+</div>
                <div style={{ fontSize: '13px', fontWeight: 700 }}>Active Child Bridges</div>
                <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>Children registered with a dedicated group of rotating active blood donors.</div>
              </div>
              <div style={{ background: '#f5f3ff', border: '1px solid #ddd6fe', padding: '1.5rem', borderRadius: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '2.25rem', fontWeight: 850, color: 'var(--purple)', marginBottom: '4px' }}>3,200+</div>
                <div style={{ fontSize: '13px', fontWeight: 700 }}>Registered Donors</div>
                <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '4px' }}>Active emergency and bridge volunteers stored securely in our database.</div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '2rem', marginBottom: '2rem' }}>
              <div>
                <h3 className="portal-section-title">Recent Awareness & Screening Camps (2026)</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Institution / Camp Location</th>
                        <th>Screenings</th>
                        <th>Carriers Identified</th>
                        <th>Blood Units Collected</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td><b>12 May 2026</b></td>
                        <td>Osmania University Campus, Hyderabad</td>
                        <td>420</td>
                        <td>18 (4.2%)</td>
                        <td>84 Units</td>
                      </tr>
                      <tr>
                        <td><b>28 Apr 2026</b></td>
                        <td>JNTU College of Engineering, Kukatpally</td>
                        <td>380</td>
                        <td>15 (3.9%)</td>
                        <td>65 Units</td>
                      </tr>
                      <tr>
                        <td><b>15 Mar 2026</b></td>
                        <td>Gachibowli Community Health Camp</td>
                        <td>250</td>
                        <td>9 (3.6%)</td>
                        <td>42 Units</td>
                      </tr>
                      <tr>
                        <td><b>12 Feb 2026</b></td>
                        <td>Vignan Institute of Tech, Deshmukhi</td>
                        <td>510</td>
                        <td>22 (4.3%)</td>
                        <td>110 Units</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              <div>
                <h3 className="portal-section-title">Verified Official Audit Documents</h3>
                <p style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '1rem', lineHeight: '1.4' }}>
                  For compliance, transparency, and public review, we provide access to our yearly auditor disclosures.
                </p>

                <div className="cert-card" style={{ background: 'var(--surface2)', borderColor: 'var(--border)', marginTop: '0' }}>
                  <div className="cert-icon">📂</div>
                  <div style={{ flex: 1 }}>
                    <div className="cert-title" style={{ color: 'var(--text)' }}>Annual Report 2023-24</div>
                    <div className="cert-desc" style={{ color: 'var(--muted)' }}>Summary of activities, bridges, and prevention milestones.</div>
                    <button className="btn-cert-download" style={{ background: 'var(--primary)' }} onClick={() => triggerNotification('Downloading Annual Report 2023-24 PDF (Audit verified)...', 'success')}>Download PDF</button>
                  </div>
                </div>

                <div className="cert-card" style={{ background: 'var(--surface2)', borderColor: 'var(--border)', marginTop: '12px' }}>
                  <div className="cert-icon">📊</div>
                  <div style={{ flex: 1 }}>
                    <div className="cert-title" style={{ color: 'var(--text)' }}>Financial Statements 2022-23</div>
                    <div className="cert-desc" style={{ color: 'var(--muted)' }}>Income disclosures, 80G tax reports, and filter expenses.</div>
                    <button className="btn-cert-download" style={{ background: 'var(--primary)' }} onClick={() => triggerNotification('Downloading Financial Statements 2022-23 PDF...', 'success')}>Download PDF</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* AWARENESS VIEW */}
      {activeTab === 'awareness' && (
        <div className="container">
          <div className="portal-card">
            <h1 style={{ color: 'var(--primary)', fontWeight: 800 }}>Thalassemia Education & Genetics</h1>
            <p style={{ color: 'var(--muted)', fontSize: '14px', marginTop: '6px', marginBottom: '2rem' }}>
              Understanding the difference between Thalassemia Minor (carrier) and Thalassemia Major, and screening to build a Thalassemia-free future.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginBottom: '3rem' }}>
              <div style={{ background: 'white', border: '1px solid var(--border)', borderRadius: '12px', padding: '1.5rem' }}>
                <h3 style={{ color: 'var(--green)', fontWeight: 700, marginBottom: '8px', fontSize: '15px' }}>🟢 Thalassemia Minor (Carrier)</h3>
                <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.5', marginBottom: '10px' }}>
                  A person who inherits the Thalassemia gene from only one parent has <strong>Thalassemia Minor</strong>. 
                </p>
                <ul style={{ fontSize: '12px', color: 'var(--muted)', paddingLeft: '1.25rem', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <li>Usually asymptomatic and has normal life expectancy.</li>
                  <li>May show mild anemia (often misdiagnosed as iron deficiency).</li>
                  <li>Does NOT require regular blood transfusions or special medical care.</li>
                  <li><strong>Important:</strong> Can pass the thalassemia gene to their children.</li>
                </ul>
              </div>

              <div style={{ background: 'white', border: '1px solid var(--red-border)', borderRadius: '12px', padding: '1.5rem' }}>
                <h3 style={{ color: 'var(--primary)', fontWeight: 700, marginBottom: '8px', fontSize: '15px' }}>🔴 Thalassemia Major (Patient)</h3>
                <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.5', marginBottom: '10px' }}>
                  A person who inherits the gene from both parents develops <strong>Thalassemia Major</strong>.
                </p>
                <ul style={{ fontSize: '12px', color: 'var(--muted)', paddingLeft: '1.25rem', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <li>Severe, life-threatening anemia starting in infancy.</li>
                  <li>Requires lifelong blood transfusions every 21 to 30 days.</li>
                  <li>Requires daily iron chelation therapy to remove excess iron accumulation.</li>
                  <li>Can be prevented through carrier screening of couples prior to pregnancy.</li>
                </ul>
              </div>
            </div>

            {/* Inheritance Calculator */}
            <div style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: '16px', padding: '2rem' }}>
              <h2 style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--text)', textAlign: 'center', marginBottom: '8px' }}>🧬 Thalassemia Inheritance Calculator</h2>
              <p style={{ fontSize: '13px', color: 'var(--muted)', textAlign: 'center', maxWidth: '600px', margin: '0 auto 2rem', lineHeight: '1.5' }}>
                Select the carrier status of both parents to calculate the mathematical genetic probability outcomes for their biological children.
              </p>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', maxWidth: '700px', margin: '0 auto 2rem' }}>
                <div>
                  <label className="auth-input-label" style={{ display: 'block', marginBottom: '6px' }}>Father's Carrier Status</label>
                  <select 
                    className="match-selector" 
                    value={fatherStatus}
                    onChange={(e) => setFatherStatus(e.target.value)}
                  >
                    <option value="normal">Normal (Non-carrier)</option>
                    <option value="carrier">Carrier (Thalassemia Minor)</option>
                    <option value="patient">Patient (Thalassemia Major)</option>
                  </select>
                </div>
                <div>
                  <label className="auth-input-label" style={{ display: 'block', marginBottom: '6px' }}>Mother's Carrier Status</label>
                  <select 
                    className="match-selector" 
                    value={motherStatus}
                    onChange={(e) => setMotherStatus(e.target.value)}
                  >
                    <option value="normal">Normal (Non-carrier)</option>
                    <option value="carrier">Carrier (Thalassemia Minor)</option>
                    <option value="patient">Patient (Thalassemia Major)</option>
                  </select>
                </div>
              </div>

              {/* Calculator Output Calculation */}
              {(() => {
                let normal = 0, carrier = 0, major = 0;
                let outcomeText = "";
                let alertColor = "var(--green)";
                let alertBg = "var(--green-bg)";
                let alertBorder = "var(--green-border)";

                if (fatherStatus === 'normal' && motherStatus === 'normal') {
                  normal = 100;
                  outcomeText = "Normal Status: All children will inherit normal hemoglobin genes. 0% chance of Thalassemia carrier/major status.";
                } else if (
                  (fatherStatus === 'normal' && motherStatus === 'carrier') ||
                  (fatherStatus === 'carrier' && motherStatus === 'normal')
                ) {
                  normal = 50;
                  carrier = 50;
                  outcomeText = "Carrier Status: There is a 50% chance the child will be a Thalassemia Minor carrier (healthy, asymptomatic) and a 50% chance of being completely Normal. 0% chance of Thalassemia Major.";
                  alertColor = "var(--blue)";
                  alertBg = "var(--blue-bg)";
                  alertBorder = "var(--blue-border)";
                } else if (fatherStatus === 'carrier' && motherStatus === 'carrier') {
                  normal = 25;
                  carrier = 50;
                  major = 25;
                  outcomeText = "HIGH RISK: Since both parents are Thalassemia Minor carriers, there is a 25% chance of Thalassemia Major (lifelong transfusions needed), a 50% chance of Thalassemia Minor carrier, and a 25% chance of being Normal. Pre-natal diagnostics or genetic counseling is highly recommended.";
                  alertColor = "var(--primary)";
                  alertBg = "var(--red-bg)";
                  alertBorder = "var(--red-border)";
                } else if (
                  (fatherStatus === 'patient' && motherStatus === 'normal') ||
                  (fatherStatus === 'normal' && motherStatus === 'patient')
                ) {
                  carrier = 100;
                  outcomeText = "Carrier Status: All children will inherit one Thalassemia gene and be Thalassemia Minor carriers (healthy, asymptomatic). 0% chance of Thalassemia Major.";
                  alertColor = "var(--blue)";
                  alertBg = "var(--blue-bg)";
                  alertBorder = "var(--blue-border)";
                } else if (
                  (fatherStatus === 'patient' && motherStatus === 'carrier') ||
                  (fatherStatus === 'carrier' && motherStatus === 'patient')
                ) {
                  carrier = 50;
                  major = 50;
                  outcomeText = "VERY HIGH RISK: There is a 50% chance the child will have Thalassemia Major (severe anemia) and a 50% chance of Thalassemia Minor carrier. Immediate pre-pregnancy medical guidance is critical.";
                  alertColor = "var(--primary)";
                  alertBg = "var(--red-bg)";
                  alertBorder = "var(--red-border)";
                } else if (fatherStatus === 'patient' && motherStatus === 'patient') {
                  major = 100;
                  outcomeText = "CRITICAL RISK: Both parents are Thalassemia Major patients. 100% chance of children inheriting Thalassemia Major. Consult specialized medical experts.";
                  alertColor = "var(--primary)";
                  alertBg = "var(--red-bg)";
                  alertBorder = "var(--red-border)";
                }

                return (
                  <div style={{ maxWidth: '700px', margin: '0 auto' }}>
                    <div style={{
                      background: alertBg,
                      border: `1px solid ${alertBorder}`,
                      color: alertColor,
                      padding: '16px 20px',
                      borderRadius: '12px',
                      fontSize: '13px',
                      fontWeight: 600,
                      lineHeight: '1.5',
                      marginBottom: '2rem',
                      textAlign: 'center'
                    }}>
                      {outcomeText}
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', fontWeight: 700, marginBottom: '6px' }}>
                          <span>Normal Child (Non-Carrier)</span>
                          <span style={{ color: 'var(--green)' }}>{normal}%</span>
                        </div>
                        <div className="prog-track" style={{ height: '12px' }}><div className="prog-fill" style={{ width: `${normal}%`, background: 'var(--green)', transition: 'width 0.3s ease' }}></div></div>
                      </div>

                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', fontWeight: 700, marginBottom: '6px' }}>
                          <span>Carrier Child (Thalassemia Minor)</span>
                          <span style={{ color: 'var(--blue)' }}>{carrier}%</span>
                        </div>
                        <div className="prog-track" style={{ height: '12px' }}><div className="prog-fill" style={{ width: `${carrier}%`, background: 'var(--blue)', transition: 'width 0.3s ease' }}></div></div>
                      </div>

                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', fontWeight: 700, marginBottom: '6px' }}>
                          <span>Patient Child (Thalassemia Major)</span>
                          <span style={{ color: 'var(--primary)' }}>{major}%</span>
                        </div>
                        <div className="prog-track" style={{ height: '12px' }}><div className="prog-fill" style={{ width: `${major}%`, background: 'var(--primary)', transition: 'width 0.3s ease' }}></div></div>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* LEADERBOARD VIEW */}
      {activeTab === 'leaderboard' && (
        <div className="container">
          <div className="portal-card">
            <h1 style={{ color: 'var(--primary)', fontWeight: 800 }}>Our Voluntary Blood Donor Heroes</h1>
            <p style={{ color: 'var(--muted)', fontSize: '14px', marginTop: '6px', marginBottom: '2rem' }}>
              Recognizing top active voluntary donors who keep the Thalassemia transfusion bridges alive in Hyderabad.
            </p>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
              <div className="match-label">Active Leaderboard Rankings</div>
              <div style={{ display: 'flex', gap: '8px' }}>
                {['All', 'O Negative', 'B Positive', 'A Positive', 'O Positive'].map(grp => (
                  <button 
                    key={grp}
                    style={{
                      border: '1px solid var(--border)',
                      background: leaderboardFilter === grp ? 'var(--primary-light)' : 'white',
                      color: leaderboardFilter === grp ? 'var(--primary)' : 'var(--text-secondary)',
                      fontSize: '11.5px',
                      fontWeight: 700,
                      padding: '4px 12px',
                      borderRadius: '6px',
                      cursor: 'pointer'
                    }}
                    onClick={() => setLeaderboardFilter(grp)}
                  >
                    {grp}
                  </button>
                ))}
              </div>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: '80px', textAlign: 'center' }}>Rank</th>
                    <th>Donor Name (Privacy Masked)</th>
                    <th>Blood Group</th>
                    <th>General Location</th>
                    <th>Lifetime Donations</th>
                    <th>Bridge Status</th>
                    <th>Badge / Title</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { rank: 1, name: "Mahanth K.", blood: "B Positive", location: "Madhapur, Hyd", count: 24, badge: "🎖 Grand Lifesaver", status: "Active" },
                    { rank: 2, name: "Prashanth R.", blood: "A Positive", location: "Secunderabad, Hyd", count: 19, badge: "🎗 Bridge Champion", status: "Active" },
                    { rank: 3, name: "Sai Pallavi P.", blood: "O Positive", location: "Banjara Hills, Hyd", count: 15, badge: "⭐ Volunteer Star", status: "Active" },
                    { rank: 4, name: "Apurva S.", blood: "O Negative", location: "Gachibowli, Hyd", count: 12, badge: "🩸 Rare Type Hero", status: "Active" },
                    { rank: 5, name: "Venkatesh B.", blood: "O Positive", location: "Kondapur, Hyd", count: 10, badge: "🎗 Bridge Champion", status: "Active" },
                    { rank: 6, name: "Rithika M.", blood: "B Positive", location: "Begumpet, Hyd", count: 8, badge: "⭐ Volunteer Star", status: "Active" },
                    { rank: 7, name: "Kiran Kumar A.", blood: "AB Negative", location: "Madhapur, Hyd", count: 7, badge: "🩸 Rare Type Hero", status: "Active" },
                    { rank: 8, name: "Nitya N.", blood: "A Negative", location: "Jubilee Hills, Hyd", count: 6, badge: "⭐ Volunteer Star", status: "Active" }
                  ]
                  .filter(d => leaderboardFilter === 'All' || d.blood === leaderboardFilter)
                  .map((d, idx) => (
                    <tr key={idx} style={{ background: d.rank <= 3 ? 'var(--bg)' : 'white' }}>
                      <td style={{ textAlign: 'center', fontWeight: 800, color: d.rank === 1 ? '#eab308' : d.rank === 2 ? '#94a3b8' : d.rank === 3 ? '#b45309' : 'var(--muted)' }}>
                        #{d.rank}
                      </td>
                      <td><b>{d.name}</b></td>
                      <td><span className="bg-pill" style={{ display: 'inline-block' }}>{d.blood}</span></td>
                      <td>{d.location}</td>
                      <td><b>{d.count} Donations</b></td>
                      <td><span style={{ color: 'var(--green)', fontWeight: 700 }}>● {d.status}</span></td>
                      <td><span style={{ fontWeight: 650, color: 'var(--text-secondary)' }}>{d.badge}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="opp-box" style={{ marginTop: '1.5rem' }}>
              <div className="opp-title">🎁 Donor Recognition Campaign</div>
              <div className="opp-text">
                Every voluntary donor who completes 5+ donations is awarded a certificate, printed badge, and entered into our quarterly volunteer honors ledger. Thank you for your support!
              </div>
            </div>
          </div>
        </div>
      )}

      {/* BACK-A-THON VIEW */}
      {activeTab === 'backathon' && (
        <div className="container">
          <div className="portal-card">
            <h1 style={{ color: 'var(--primary)', fontWeight: 800 }}>Back-A-Thon 2026 - Walk for Thalassemia</h1>
            <p style={{ color: 'var(--muted)', fontSize: '14px', marginTop: '6px', marginBottom: '2rem' }}>
              Join our annual public awareness walkathon, pledge support, and make India Thalassemia-free.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '2.5rem' }}>
              <div>
                <h3 className="portal-section-title">Event Logistics</h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
                  <div style={{ background: 'var(--bg)', padding: '1rem', borderRadius: '10px', border: '1px solid var(--border)' }}>
                    <strong>📅 Date</strong>
                    <div style={{ fontSize: '13px', marginTop: '4px', fontWeight: 600 }}>15 November 2026</div>
                  </div>
                  <div style={{ background: 'var(--bg)', padding: '1rem', borderRadius: '10px', border: '1px solid var(--border)' }}>
                    <strong>⏰ Time</strong>
                    <div style={{ fontSize: '13px', marginTop: '4px', fontWeight: 600 }}>6:00 AM — 9:30 AM</div>
                  </div>
                  <div style={{ background: 'var(--bg)', padding: '1rem', borderRadius: '10px', border: '1px solid var(--border)', gridColumn: 'span 2' }}>
                    <strong>📍 Starting Point</strong>
                    <div style={{ fontSize: '13px', marginTop: '4px', fontWeight: 600 }}>Necklace Road, PV Ghat, Hyderabad, Telangana</div>
                  </div>
                </div>

                <h3 className="portal-section-title">Rules & Guidelines</h3>
                <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.5', marginBottom: '8px' }}>
                  1. Participants are requested to report by 5:45 AM for T-shirt distribution.
                </p>
                <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.5', marginBottom: '8px' }}>
                  2. Free breakfast and hydration support stations are located at every 1.5 km of the 5 km route.
                </p>
                <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.5', marginBottom: '8px' }}>
                  3. All registrants will receive a verified awareness kit, certificates, and wristbands.
                </p>
              </div>

              <div>
                <div style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: '14px', padding: '1.75rem' }}>
                  <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '1rem', color: 'var(--text)' }}>🎟️ Free Walkathon Registration</h3>
                  <form onSubmit={(e) => {
                    e.preventDefault();
                    if (!walkName.trim() || !walkPhone.trim()) {
                      triggerNotification("Please fill in Name and Phone Number.", "warning");
                      return;
                    }
                    triggerNotification(`Successfully registered ${walkName} for Back-A-Thon 2026. Code: BW2026-WK${Math.floor(1000 + Math.random() * 9000)}`, "success");
                    setWalkName('');
                    setWalkPhone('');
                    setWalkEmail('');
                  }}>
                    <div className="auth-input-group">
                      <label className="auth-input-label">FullName</label>
                      <input 
                        type="text" 
                        className="auth-input" 
                        value={walkName}
                        onChange={(e) => setWalkName(e.target.value)}
                        placeholder="Enter your name" 
                        required 
                      />
                    </div>
                    <div className="auth-input-group">
                      <label className="auth-input-label">Mobile Number</label>
                      <input 
                        type="tel" 
                        className="auth-input" 
                        value={walkPhone}
                        onChange={(e) => setWalkPhone(e.target.value)}
                        placeholder="Enter phone number" 
                        required 
                      />
                    </div>
                    <div className="auth-input-group">
                      <label className="auth-input-label">Email Address (Optional)</label>
                      <input 
                        type="email" 
                        className="auth-input" 
                        value={walkEmail}
                        onChange={(e) => setWalkEmail(e.target.value)}
                        placeholder="Enter email address" 
                      />
                    </div>
                    <div className="auth-input-group">
                      <label className="auth-input-label">T-Shirt Size</label>
                      <select 
                        className="match-selector" 
                        value={walkShirt}
                        onChange={(e) => setWalkShirt(e.target.value)}
                      >
                        <option value="S">Small (S)</option>
                        <option value="M">Medium (M)</option>
                        <option value="L">Large (L)</option>
                        <option value="XL">Extra Large (XL)</option>
                      </select>
                    </div>

                    <button type="submit" className="btn-login" style={{ marginTop: '1rem' }}>Register Free Ticket</button>
                  </form>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* CONTRIBUTE VIEW */}
      {activeTab === 'contribute' && (
        <div className="container">
          <div className="portal-card">
            <h1 style={{ color: 'var(--primary)', fontWeight: 800 }}>Support Thalassemia Children</h1>
            <p style={{ color: 'var(--muted)', fontSize: '14px', marginTop: '6px', marginBottom: '2rem' }}>
              Your financial contributions directly fund leucodepletion blood filters, iron chelation therapies, and pre-marital carrier testing drives.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem', marginBottom: '2.5rem' }}>
              <div style={{ border: '1px solid var(--border)', padding: '1.75rem', borderRadius: '12px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', background: 'white' }}>
                <div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--primary)', marginBottom: '8px' }}>₹1,000 / month</div>
                  <strong style={{ display: 'block', fontSize: '13.5px', marginBottom: '8px' }}>Leucodepletion Blood Filters</strong>
                  <p style={{ fontSize: '12px', color: 'var(--muted)', lineHeight: '1.5' }}>
                    Sponsors one filter set. Filters remove white blood cells from donated units, preventing recurrent transfusion reactions and antibody formations in children.
                  </p>
                </div>
                <button className="btn-hero-primary" style={{ width: '100%', marginTop: '1.5rem', padding: '10px' }} onClick={() => {
                  setSponsorTier({ name: "Blood Filters Sponsorship", amt: "₹1,000" });
                  setShowSponsorModal(true);
                }}>Sponsor Now</button>
              </div>

              <div style={{ border: '1px solid var(--primary)', padding: '1.75rem', borderRadius: '12px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', background: 'white', position: 'relative' }}>
                <span className="em-label" style={{ position: 'absolute', top: '10px', right: '10px', background: 'var(--primary)' }}>POPULAR</span>
                <div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--primary)', marginBottom: '8px' }}>₹3,000 / month</div>
                  <strong style={{ display: 'block', fontSize: '13.5px', marginBottom: '8px' }}>Daily Iron Chelation Meds</strong>
                  <p style={{ fontSize: '12px', color: 'var(--muted)', lineHeight: '1.5' }}>
                    Sponsors chelation therapy. Repeated blood transfusions cause dangerous iron overload in the liver and heart. Chelation drugs help clear this toxic build-up.
                  </p>
                </div>
                <button className="btn-hero-primary" style={{ width: '100%', marginTop: '1.5rem', padding: '10px' }} onClick={() => {
                  setSponsorTier({ name: "Iron Chelation Sponsorship", amt: "₹3,000" });
                  setShowSponsorModal(true);
                }}>Sponsor Now</button>
              </div>

              <div style={{ border: '1px solid var(--border)', padding: '1.75rem', borderRadius: '12px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', background: 'white' }}>
                <div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--primary)', marginBottom: '8px' }}>₹5,000 / month</div>
                  <strong style={{ display: 'block', fontSize: '13.5px', marginBottom: '8px' }}>Complete Medical Support</strong>
                  <p style={{ fontSize: '12px', color: 'var(--muted)', lineHeight: '1.5' }}>
                    Sponsors full medical care. Includes blood filters, chelation medicine, monthly blood counts, liver function profiles, and specialist pediatrician consulting.
                  </p>
                </div>
                <button className="btn-hero-primary" style={{ width: '100%', marginTop: '1.5rem', padding: '10px' }} onClick={() => {
                  setSponsorTier({ name: "Complete Medical Support", amt: "₹5,000" });
                  setShowSponsorModal(true);
                }}>Sponsor Now</button>
              </div>
            </div>

            {/* Custom contribution card */}
            <div style={{ background: 'var(--surface2)', padding: '1.5rem', borderRadius: '12px', border: '1px solid var(--border)', maxWidth: '600px', margin: '0 auto' }}>
              <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '6px', textAlign: 'center' }}>Custom Support Contribution</h3>
              <p style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center', marginBottom: '1rem' }}>Enter a custom amount to support screening and camp expenses.</p>
              <div style={{ display: 'flex', gap: '10px' }}>
                <input 
                  type="number" 
                  className="auth-input" 
                  placeholder="Enter amount (₹)" 
                  value={customSponsorAmount}
                  onChange={(e) => setCustomSponsorAmount(e.target.value)}
                />
                <button className="btn-hero-primary" style={{ padding: '8px 24px', fontSize: '12px', whiteSpace: 'nowrap' }} onClick={() => {
                  if (!customSponsorAmount || parseFloat(customSponsorAmount) <= 0) {
                    triggerNotification("Please enter a valid amount.", "warning");
                    return;
                  }
                  setSponsorTier({ name: "Custom Contribution", amt: `₹${customSponsorAmount}` });
                  setShowSponsorModal(true);
                }}>Contribute</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SPONSORSHIP CHECKOUT MODAL */}
      {showSponsorModal && sponsorTier && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ width: '400px' }}>
            <button className="modal-close" onClick={() => setShowSponsorModal(false)}>×</button>
            <div className="auth-title">Complete Your Sponsorship</div>
            <div className="auth-sub">Thank you for supporting our mission</div>
            
            <div style={{
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              padding: '12px 14px',
              fontSize: '13px',
              fontWeight: 600,
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: '1.5rem'
            }}>
              <span>Selected support:</span>
              <span style={{ color: 'var(--primary)' }}>{sponsorTier.name} ({sponsorTier.amt})</span>
            </div>

            <div className="auth-input-group">
              <label className="auth-input-label">Sponsor / Donor Name</label>
              <input 
                type="text" 
                className="auth-input" 
                value={sponsorName}
                onChange={(e) => setSponsorName(e.target.value)}
                placeholder="Enter your name" 
                required
              />
            </div>
            
            <div className="auth-input-group">
              <label className="auth-input-label">Email Address</label>
              <input 
                type="email" 
                className="auth-input" 
                value={sponsorEmail}
                onChange={(e) => setSponsorEmail(e.target.value)}
                placeholder="Enter email address" 
                required
              />
            </div>

            <button 
              className="btn-login"
              onClick={() => {
                if (!sponsorName.trim() || !sponsorEmail.trim()) {
                  triggerNotification("Please enter both Name and Email.", "warning");
                  return;
                }
                setShowSponsorModal(false);
                triggerNotification(`Heartfelt thanks! Simulating successful 80G gateway approval for ${sponsorTier.amt}. Receipt sent.`, 'success');
                setSponsorName('');
                setSponsorEmail('');
                setCustomSponsorAmount('');
              }}
            >
              Simulate Secure Payment
            </button>
          </div>
        </div>
      )}

      {/* ADMIN DASHBOARD VIEW */}
      {activeTab === 'dashboard' && (
        <>
          <div className="page-header">
            <div className="page-header-left">
              <h1>Operational Intelligence Dashboard</h1>
              <p>Real-time analytics powered by Blood Warriors dataset · {stats.total.toLocaleString()} records · Hyderabad cluster</p>
            </div>
            <div className="header-stats">
              <div className="hstat">
                <div className="hstat-val">{stats.total.toLocaleString()}</div>
                <div className="hstat-lbl">Total Records</div>
              </div>
              <div className="hstat">
                <div className="hstat-val" style={{ color: 'var(--green)' }}>{stats.eligible.toLocaleString()}</div>
                <div className="hstat-lbl">Eligible Donors</div>
              </div>
              <div className="hstat">
                <div className="hstat-val" style={{ color: 'var(--amber)' }}>{stats.activeBridges}</div>
                <div className="hstat-lbl">Active Bridges</div>
              </div>
              <div className="hstat">
                <div className="hstat-val" style={{ color: 'var(--primary)' }}>{stats.inactive}</div>
                <div className="hstat-lbl">Inactive Donors</div>
              </div>
            </div>
          </div>

          <div className="alert">
            <span style={{ fontSize: '18px' }}>🚨</span>
            <div className="alert-text">
              <strong>Critical Shortage Alert:</strong> Only <strong>{stats.rareBloodStock?.AB_Negative !== undefined ? stats.rareBloodStock.AB_Negative : '32'} AB-Negative</strong> and <strong>{stats.rareBloodStock?.O_Negative !== undefined ? stats.rareBloodStock.O_Negative : '117'} O-Negative</strong> donors are registered for 28 patients needing these rare types. Calls-to-donation worst case is <strong>23 calls → 0 donations</strong>. AI scheduling avoids donor burnout.
            </div>
            <div className="alert-badge">⚠ Action Required</div>
          </div>

          {/* SECURE TOKEN VERIFICATION GATEWAY */}
          <div style={{
            margin: '1.25rem 2rem 0',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: '12px',
            padding: '1.25rem 1.5rem',
            boxShadow: 'var(--shadow-sm)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '1rem'
          }}>
            <div>
              <h4 style={{ color: 'var(--text)', fontWeight: 700, fontSize: '13.5px' }}>🏥 Double-Blind Hospital Donation Verification</h4>
              <p style={{ color: 'var(--muted)', fontSize: '11.5px', marginTop: '3px' }}>
                Enter the transactional token presented by the donor at the blood bank to verify their donation cycle anonymously.
              </p>
            </div>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
              <input 
                type="text" 
                className="auth-input" 
                placeholder="Enter Token (e.g. TXN-876F2)" 
                style={{ width: '220px', textTransform: 'uppercase', height: '38px', margin: 0 }}
                value={verifyTokenInput}
                onChange={(e) => setVerifyTokenInput(e.target.value)}
              />
              <button 
                className="btn-hero-primary" 
                style={{ padding: '0 20px', fontSize: '12.5px', whiteSpace: 'nowrap', height: '38px', cursor: 'pointer' }}
                onClick={async () => {
                  if (!verifyTokenInput.trim()) {
                    triggerNotification("Please enter a verification token.", "warning");
                    return;
                  }
                  const token = verifyTokenInput.trim().toUpperCase();
                  triggerNotification(`Contacting backend verification ledger...`, 'info');
                  
                  try {
                    const response = await fetch(`${API_BASE_URL}/api/outreach/verify-token`, {
                      method: 'POST',
                      headers: {
                        'Content-Type': 'application/json'
                      },
                      body: JSON.stringify({ token })
                    });
                    const data = await response.json();
                    
                    if (response.ok) {
                      setVerifiedTokens(prev => ({ ...prev, [token]: true }));
                      setLifeCredits(prev => prev + 100);
                      setHyderabadQuestCount(prev => prev + 1);
                      triggerNotification(data.message, 'success');
                      setVerifyTokenInput('');
                      
                      // Refresh dashboard stats, donors and patients
                      const metricsRes = await fetch(`${API_BASE_URL}/api/dashboard/metrics`);
                      if (metricsRes.ok) {
                        const metricsData = await metricsRes.json();
                        setStats({
                          total: metricsData.total_users,
                          eligible: metricsData.total_users - metricsData.inactive_donors_count - metricsData.guest_count,
                          activeBridges: metricsData.active_bridges,
                          inactive: metricsData.inactive_donors_count,
                          guests: metricsData.guest_count,
                          avgCallsToDonationsRatio: metricsData.avg_calls_to_donations_ratio,
                          inactivityRate: metricsData.inactivity_rate,
                          rareBloodStock: metricsData.rare_blood_stock,
                          roleCounts: {
                            Guest: metricsData.guest_count,
                            "Emergency Donor": metricsData.emergency_donors_count,
                            "Bridge Donor": metricsData.bridge_donor_count || 2061,
                            Patient: metricsData.patient_count || 84,
                            Volunteer: metricsData.volunteer_count || 3
                          }
                        });
                      }

                      // Fetch updated Donors list to refresh map & leaderboard UI
                      const donorsRes = await fetch(`${API_BASE_URL}/api/donors`);
                      if (donorsRes.ok) {
                        const donorsData = await donorsRes.json();
                        const mappedDonors = donorsData.map(d => ({
                          userId: d.id,
                          name: d.name,
                          phone: d.phone,
                          bloodGroup: d.blood_group || 'O Positive',
                          gender: d.gender || 'Male',
                          lat: d.latitude || 17.39,
                          lon: d.longitude || 78.46,
                          donations: d.donations_till_date || 0,
                          callsRatio: d.calls_to_donations_ratio || 0.0,
                          eligibility: d.eligibility_status || 'eligible',
                          activeStatus: d.user_donation_active_status || 'Active',
                          donorType: d.role || 'Bridge Donor',
                          healthScore: d.health_score || 0.0,
                          churnRisk: d.churn_risk_score || 0.0,
                          preferredChannel: d.preferred_channel || 'WhatsApp',
                          inactiveComment: d.inactive_trigger_comment,
                          lastDonationDate: d.last_donation_date || d.lastDonation || ""
                        }));
                        setDonors(mappedDonors);
                      }
                    } else {
                      triggerNotification(data.detail || 'Invalid token verification request.', 'warning');
                    }
                  } catch (err) {
                    console.error("Token verification failed", err);
                    triggerNotification("Server connection error during verification.", "warning");
                  }
                }}
              >
                Verify Donation
              </button>
            </div>
          </div>

          <div className="container">
            {/* KPI Summary */}
            <div className="section-label">Key Performance Indicators — Baseline vs AI Target</div>
            <div className="kpi-grid">
              <div className="kpi-card c-red">
                <div className="kpi-top">
                  <div className="kpi-icon-wrap">📞</div>
                  <span className="kpi-badge badge-red">▲ Worst: 23.0</span>
                </div>
                <div className="kpi-val">{stats.avgCallsToDonationsRatio !== undefined ? stats.avgCallsToDonationsRatio : '1.85'}</div>
                <div className="kpi-label">Calls-to-Donation Ratio</div>
                <div className="kpi-meta">Avg. calls per successful donation</div>
                <div className="kpi-target">🎯 AI Target: &lt; 0.8 · Smarter ranking, not more calls</div>
              </div>
              <div className="kpi-card c-amber">
                <div className="kpi-top">
                  <div className="kpi-icon-wrap">😴</div>
                  <span className="kpi-badge badge-red">{stats.inactivityRate !== undefined ? stats.inactivityRate : '9.7'}% of total</span>
                </div>
                <div className="kpi-val">{stats.inactive}</div>
                <div className="kpi-label">Inactive Donors</div>
                <div className="kpi-meta">361 not donated 1yr · 321 no response</div>
                <div className="kpi-target">🎯 AI Target: &lt; 3% · Churn prediction model</div>
              </div>
              <div className="kpi-card c-green">
                <div className="kpi-top">
                  <div className="kpi-icon-wrap">✅</div>
                  <span className="kpi-badge badge-green">Ready now</span>
                </div>
                <div className="kpi-val">{stats.eligible.toLocaleString()}</div>
                <div className="kpi-label">Eligible Active Donors</div>
                <div className="kpi-meta">1,718 Bridge · 1,587 Emergency</div>
                <div className="kpi-target">🎯 Target: 12+ donors per patient bridge</div>
              </div>
              <div className="kpi-card c-blue">
                <div className="kpi-top">
                  <div className="kpi-icon-wrap">🔗</div>
                  <span className="kpi-badge badge-red">Only 11.2%</span>
                </div>
                <div className="kpi-val">{stats.activeBridges}</div>
                <div className="kpi-label">Patient Bridges</div>
                <div className="kpi-meta">786 bridge-donor links · 9.8 donors/bridge</div>
                <div className="kpi-target">🎯 Target: 1,00,000+ patients via BloodMatch 2.0</div>
              </div>
              <div className="kpi-card c-purple">
                <div className="kpi-top">
                  <div className="kpi-icon-wrap">👤</div>
                  <span className="kpi-badge badge-amber">34.4%</span>
                </div>
                <div className="kpi-val">{stats.guests.toLocaleString()}</div>
                <div className="kpi-label">Unconverted Guests</div>
                <div className="kpi-meta">No blood group · incomplete profile</div>
                <div className="kpi-target">🎯 Target: &gt; 25% conversion via AI nurturing</div>
              </div>
            </div>

            {/* Maps & Stats */}
            <div className="section-label">Geographic & Population Intelligence</div>
            <div className="row-2">
              <div className="card">
                <div className="card-title">🩸 Hyderabad Donor & Patient Distribution Map</div>
                <div className="card-sub">Red markers represent Thalassemia Patients. Blue circles display local volunteer donor clusters.</div>
                <div className="map-container-wrap" ref={mapRef}></div>
              </div>

              <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
                <div className="card-title">Donor Population Breakdown</div>
                <div className="card-sub">Role distribution across all 7,033 records</div>
                <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: '1.25rem', alignItems: 'center', flex: 1 }}>
                  <div style={{ height: '140px', position: 'relative' }}>
                    <canvas ref={roleChartRef}></canvas>
                  </div>
                  <div>
                    <div className="prog-row">
                      <div className="prog-label">Guest</div>
                      <div className="prog-track">
                        <div 
                          className="prog-fill" 
                          style={{ 
                            width: `${stats.total > 0 ? (stats.roleCounts.Guest / stats.total * 100).toFixed(1) : '34.4'}%`, 
                            background: '#94a3b8' 
                          }}
                        ></div>
                      </div>
                      <div className="prog-count">{(stats.roleCounts.Guest || 2420).toLocaleString()}</div>
                    </div>
                    <div className="prog-row">
                      <div className="prog-label">Emergency</div>
                      <div className="prog-track">
                        <div 
                          className="prog-fill" 
                          style={{ 
                            width: `${stats.total > 0 ? (stats.roleCounts["Emergency Donor"] / stats.total * 100).toFixed(1) : '33.9'}%`, 
                            background: '#d97706' 
                          }}
                        ></div>
                      </div>
                      <div className="prog-count">{(stats.roleCounts["Emergency Donor"] || 2385).toLocaleString()}</div>
                    </div>
                    <div className="prog-row">
                      <div className="prog-label">Bridge</div>
                      <div className="prog-track">
                        <div 
                          className="prog-fill" 
                          style={{ 
                            width: `${stats.total > 0 ? (stats.roleCounts["Bridge Donor"] / stats.total * 100).toFixed(1) : '29.3'}%`, 
                            background: '#2563eb' 
                          }}
                        ></div>
                      </div>
                      <div className="prog-count">{(stats.roleCounts["Bridge Donor"] || 2061).toLocaleString()}</div>
                    </div>
                    <div className="prog-row">
                      <div className="prog-label">Patient</div>
                      <div className="prog-track">
                        <div 
                          className="prog-fill" 
                          style={{ 
                            width: `${stats.total > 0 ? (stats.roleCounts.Patient / stats.total * 100).toFixed(1) : '1.2'}%`, 
                            background: '#c0002e' 
                          }}
                        ></div>
                      </div>
                      <div className="prog-count">{(stats.roleCounts.Patient || 84).toLocaleString()}</div>
                    </div>
                  </div>
                </div>
                <div className="opp-box">
                  <div className="opp-title">💡 AI Opportunity</div>
                  <div className="opp-text">2,385 Emergency donors donated once and were never re-engaged. Converting just 10% adds 238 bridge donors immediately.</div>
                </div>
              </div>
            </div>

            {/* Supply/Demand & Churn re-engagement */}
            <div className="section-label">Inventory & Churn Risks</div>
            <div className="row-2">
              <div className="card">
                <div className="card-title">🩸 Blood Type: Supply vs Demand</div>
                <div className="card-sub">Total active donor registry counts vs patients needing bridge transfusion</div>
                <div style={{ height: '200px' }}>
                  <canvas ref={bloodChartRef}></canvas>
                </div>
              </div>

              <div className="card">
                <div className="card-title">⚠️ Churn Risk — Re-engagement Queue</div>
                <div className="card-sub">Active donors flagged for inactivity. Bedrock drafts automated re-engagement triggers.</div>
                <div className="churn-list-container">
                  {donors.filter(d => d.activeStatus === 'Inactive').slice(0, 4).map(d => {
                    const bgShort = d.bloodGroup.replace(' Positive', '+').replace(' Negative', '-');
                    const isRed = bgShort.includes('-');
                    return (
                      <div className="churn-item" key={d.userId}>
                        <div className="churn-avatar" style={isRed ? { background: 'var(--red-bg)', color: 'var(--red)' } : { background: 'var(--amber-bg)', color: 'var(--amber)' }}>{bgShort}</div>
                        <div className="churn-info">
                          <div className="churn-name">{d.donorType} — {d.bloodGroup}</div>
                          <div className="churn-reason">Inactivity: {d.inactiveComment || 'No donation in last 12 months'}</div>
                          <button 
                            className="btn-reengage" 
                            onClick={() => triggerNotification(`Bedrock generated re-engagement message: "Hi! We noticed you haven't donated recently. A child with Thalassemia needs ${bgShort} blood soon. Reply YES to check availability."`, 'success')}
                          >
                            Re-engage
                          </button>
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <div className="churn-ratio">{d.callsRatio ? `${d.callsRatio.toFixed(1)}:1` : '1.8:1'}</div>
                          <div className="churn-lbl">call ratio</div>
                        </div>
                      </div>
                    );
                  })}
                  {donors.filter(d => d.activeStatus === 'Inactive').length === 0 && (
                    <div style={{ color: 'var(--muted)', fontSize: '12px', padding: '10px 0' }}>No inactive donors currently flagged.</div>
                  )}
                </div>
              </div>
            </div>

            {/* Footer Summary */}
            <div className="section-label">System Performance</div>
            <div className="footer-stats">
              <div className="fstat">
                <div className="fstat-val">
                  {donors.filter(d => d.donorType === 'Bridge Donor' && d.eligibility === 'eligible' && d.activeStatus === 'Active').length.toLocaleString()}
                </div>
                <div className="fstat-lbl">Bridge Donors — Eligible & Active</div>
              </div>
              <div className="fstat">
                <div className="fstat-val">
                  {donors.filter(d => d.donorType === 'Emergency Donor' && d.eligibility === 'eligible' && d.activeStatus === 'Active').length.toLocaleString()}
                </div>
                <div className="fstat-lbl">Emergency Donors — Ready to Engage</div>
              </div>
              <div className="fstat" style={{ color: 'var(--green)' }}>
                <div className="fstat-val">1.5 → 4+</div>
                <div className="fstat-lbl">Avg Donations (Current → Target)</div>
              </div>
              <div className="fstat" style={{ color: 'var(--amber)' }}>
                <div className="fstat-val">24.6 days</div>
                <div className="fstat-lbl">Avg Contact Frequency</div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* AI MATCHING VIEW */}
      {activeTab === 'matcher' && (
        <div className="container">
          <div className="portal-card">
            <h1>🤖 AI Donor Ranking & Outreach Simulator</h1>
            <p style={{ color: 'var(--muted)', fontSize: '13px', marginTop: '4px', marginBottom: '1.5rem' }}>
              Select a patient record to calculate real compatible donor rankings from Dataset.csv based on distance, calls ratio, and gender preference.
            </p>

            <div className="portal-grid">
              {/* Left Column: Matcher Control & List */}
              <div>
                <div className="match-selector-wrap" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <label className="match-label" style={{ display: 'block', marginBottom: '2px' }}>Select Patient Transfusion Request</label>
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <select 
                      className="match-selector" 
                      value={selectedPatientId} 
                      onChange={(e) => setSelectedPatientId(e.target.value)}
                      style={{ flex: 1, margin: 0 }}
                    >
                      {patients.map(p => (
                        <option key={p.userId} value={p.userId}>
                          Patient {p.userId.substring(0, 8)} ({p.bridgeBloodGroup || p.bloodGroup}) - Needs {p.quantity} Unit(s)
                        </option>
                      ))}
                    </select>
                    <button 
                      className="btn-hero-primary"
                      onClick={handleTriggerScheduledTransfusion}
                      style={{ padding: '0 15px', height: '38px', fontSize: '11.5px', whiteSpace: 'nowrap', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', background: '#d97706', borderColor: '#d97706' }}
                    >
                      ⏰ Simulate Scheduled Transfusion Check
                    </button>
                  </div>
                </div>

                {/* Patient Detail Summary */}
                {patients.find(p => p.userId === selectedPatientId) && (
                  <div className="match-request">
                    <div className="match-req-badge">🚨 Active Request Details</div>
                    <div className="match-req-title">
                      Patient #{selectedPatientId.substring(0, 8).toUpperCase()} — Needs {patients.find(p => p.userId === selectedPatientId).bridgeBloodGroup || patients.find(p => p.userId === selectedPatientId).bloodGroup}
                    </div>
                    <div className="match-req-sub">
                      Quantity: {patients.find(p => p.userId === selectedPatientId).quantity} Unit(s) | Hospital: {patients.find(p => p.userId === selectedPatientId).hospital}<br/>
                      Preferred Gender Match: <b>{patients.find(p => p.userId === selectedPatientId).bridgeGender || 'Any'}</b> | Location: Hyderabad ({patients.find(p => p.userId === selectedPatientId).lat}, {patients.find(p => p.userId === selectedPatientId).lon})
                    </div>
                  </div>
                )}

                <div className="match-label">AI-Ranked Compatible Donors</div>
                <div className="match-list-container">
                  {matchedDonors.length === 0 ? (
                    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)', fontSize: '13px' }}>
                      No compatible active donors found in this area.
                    </div>
                  ) : (
                    matchedDonors.map((d, index) => {
                      const key = `${d.userId}_${selectedPatientId}`;
                      const inviteStatus = sentInvites[key];
                      
                      return (
                        <div key={d.userId} className={`match-donor rank-${index < 3 ? index + 1 : '3'}`}>
                          <div className="rank-num">#{index + 1}</div>
                          <div className="bg-pill">{d.bloodGroup}</div>
                          <div className="donor-info">
                            <div className="donor-name">{d.donorType} (ID: {d.userId.substring(0,8)})</div>
                            <div className="donor-sub">
                              {d.donations} donations | Call Ratio: {d.callsRatio} | <b>{d.distance} km</b> away<br/>
                              Gender: {d.gender} | Eligibility: <b>{d.eligibility}</b>
                            </div>
                            {inviteStatus === 'sending' ? (
                              <button className="btn-outreach sent" disabled>Sending WhatsApp SMS...</button>
                            ) : inviteStatus === 'sent' ? (
                              <button className="btn-outreach sent" disabled>✓ Outreach Complete</button>
                            ) : (
                              <button 
                                className="btn-outreach" 
                                onClick={() => handleOutreachTrigger(d, patients.find(p => p.userId === selectedPatientId))}
                              >
                                Send WhatsApp Invite
                              </button>
                            )}
                          </div>
                          <div className="score-wrap">
                            <div className="score-num">{d.score}</div>
                            <div className="score-bar"><div className="score-fill" style={{ width: `${d.score}%`, background: index === 0 ? 'var(--green)' : index === 1 ? 'var(--blue)' : 'var(--purple)' }}></div></div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* Right Column: Outreach Log Simulator */}
              <div>
                <div className="portal-section-title">Outreach Log & Reply Simulator</div>
                <p style={{ fontSize: '11.5px', color: 'var(--muted)', marginBottom: '1rem', lineHeight: '1.4' }}>
                  Every outreach event communicates only via preferred channels to avoid donor fatigue. Under sandbox rules, the coordinator triggers the message and receives callbacks from test donor nodes in 3 seconds.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '480px', overflowY: 'auto', paddingRight: '4px' }}>
                  {notificationLogs.length === 0 ? (
                    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)', fontSize: '12.5px' }}>
                      No outreach events logged yet. Trigger an invite to see real-time orchestrations.
                    </div>
                  ) : (
                    notificationLogs.map((logLine, idx) => {
                      const match = logLine.match(/^\[(.*?)\] (.*)$/);
                      const timestamp = match ? match[1] : '';
                      const message = match ? match[2] : logLine;
                      
                      const isCrisis = message.includes('CRISIS') || message.includes('🚨') || message.includes('⚠️') || message.includes('ESCALATION');
                      const isSuccess = message.includes('SUCCESS') || message.includes('✅') || message.includes('VERIFIED') || message.includes('Confirmed');
                      const isWave = message.includes('🌊') || message.includes('Wave');

                      return (
                        <div key={idx} style={{
                          background: isCrisis ? 'rgba(239, 68, 68, 0.08)' : isSuccess ? 'rgba(16, 185, 129, 0.08)' : isWave ? 'rgba(59, 130, 246, 0.08)' : 'var(--surface2)',
                          border: `1px solid ${isCrisis ? 'rgba(239, 68, 68, 0.2)' : isSuccess ? 'rgba(16, 185, 129, 0.2)' : isWave ? 'rgba(59, 130, 246, 0.2)' : 'var(--border)'}`,
                          borderRadius: '10px',
                          padding: '12px 14px',
                          fontSize: '12px',
                          boxShadow: 'var(--shadow-sm)',
                          color: isCrisis ? '#b91c1c' : isSuccess ? '#047857' : isWave ? '#1d4ed8' : 'var(--text)'
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--muted)', marginBottom: '4px', fontWeight: 600 }}>
                            <span>{isCrisis ? '🚨 SYSTEM ALERT' : isSuccess ? '✅ TRANSACTION' : isWave ? '🌊 WAVE OUTREACH' : 'LOG'}</span>
                            <span>{timestamp.split(' ')[1] || timestamp}</span>
                          </div>
                          <div style={{ fontWeight: 600, lineHeight: '1.45', wordBreak: 'break-word' }}>
                            {message}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* DONOR PORTAL VIEW */}
      {activeTab === 'donor' && (
        <div className="container">
          <div className="portal-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.5rem' }}>
              <div>
                <h1 style={{ color: 'var(--primary)', fontWeight: 800 }}>💪 Donor Lifeline & Impact Dashboard</h1>
                <p style={{ color: 'var(--muted)', fontSize: '13px', marginTop: '4px' }}>
                  Welcome back, Lifeline Volunteer. Track your achievements, spend Life-Credits on pay-it-forward redemptions, and present secure verification tokens.
                </p>
              </div>
              <div style={{ display: 'flex', gap: '1.25rem', background: 'var(--surface2)', padding: '12px 20px', borderRadius: '12px', border: '1px solid var(--border)' }}>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '10px', color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase' }}>Available Life-Credits</div>
                  <div style={{ fontSize: '1.35rem', fontWeight: 850, color: 'var(--primary)' }}>{lifeCredits} Credits</div>
                </div>
                <div style={{ width: '1px', background: 'var(--border)' }}></div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '10px', color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase' }}>Sponsorships Funded</div>
                  <div style={{ fontSize: '1.35rem', fontWeight: 850, color: 'var(--green)' }}>{sponsorshipsCount} Packages</div>
                </div>
              </div>
            </div>

            {/* Gamification Panel: XP Levels and Quests */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '1.5rem', marginBottom: '2rem' }}>
              <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '14px', padding: '1.5rem' }}>
                <h3 className="portal-section-title" style={{ borderLeftColor: 'var(--blue)' }}>Chapter Collaborative Quest</h3>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>
                    🎯 <b>Hyderabad Chapter Quest:</b> Save 500 Lives this month!
                  </span>
                  <span style={{ fontSize: '12.5px', fontWeight: 750, color: 'var(--blue)' }}>
                    {hyderabadQuestCount} / 500 Saved
                  </span>
                </div>
                <div className="prog-track" style={{ height: '14px', marginBottom: '12px' }}>
                  <div 
                    className="prog-fill" 
                    style={{ 
                      width: `${Math.min(100, (hyderabadQuestCount / 500) * 100)}%`, 
                      background: 'var(--blue)', 
                      transition: 'width 0.5s ease-out' 
                    }}
                  ></div>
                </div>
                <p style={{ fontSize: '11px', color: 'var(--muted)', lineHeight: '1.4' }}>
                  <b>Quest Status:</b> Collaborative goal. If the monthly chapter quest target of 500 lives saved is met, all participating donors receive the shared <b>"Community Shield"</b> badge. This shifts focus from individual ego-driven ranks to collaborative community impact.
                </p>
              </div>

              <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '14px', padding: '1.5rem', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <span style={{ fontSize: '11.5px', fontWeight: 700, color: 'var(--muted)' }}>LEVEL PROGRESSION</span>
                  <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--primary)' }}>Level 3 Lifesaver</span>
                </div>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>750 XP</div>
                <div className="prog-track" style={{ height: '10px', marginBottom: '6px' }}>
                  <div className="prog-fill" style={{ width: '75%', background: 'var(--primary)' }}></div>
                </div>
                <div style={{ fontSize: '10px', color: 'var(--muted)', textAlign: 'right' }}>250 XP until Level 4</div>
              </div>
            </div>

            {/* Profile Grid */}
            <div className="portal-grid" style={{ marginBottom: '2rem' }}>
              {/* Profile Details */}
              <div>
                {(() => {
                  const currentDonor = donors.find(d => d.phone === loginUsername || d.userId === loginUsername) || {
                    name: "Rahul Sharma",
                    bloodGroup: "B Positive",
                    userId: "donor_82a7155d",
                    donations: 9,
                    lastDonationDate: "2025-08-17",
                    eligibility: "eligible",
                    preferredChannel: "WhatsApp"
                  };
                  return (
                    <>
                      <div className="portal-section-title">My Donor Profile (Masked & Protected)</div>
                      <div className="profile-field">
                        <span className="profile-field-lbl">My Real Name (Verification)</span>
                        <span className="profile-field-val" style={{ fontWeight: 'bold' }}>{currentDonor.name}</span>
                      </div>
                      <div className="profile-field">
                        <span className="profile-field-lbl">Blood Group</span>
                        <span className="profile-field-val" style={{ color: 'var(--primary)', fontWeight: 'bold' }}>{currentDonor.bloodGroup}</span>
                      </div>
                      <div className="profile-field">
                        <span className="profile-field-lbl">Donor Anonymity Code</span>
                        <span className="profile-field-val">Donor #{currentDonor.userId.substring(0, 8).toUpperCase()}</span>
                      </div>
                      <div className="profile-field">
                        <span className="profile-field-lbl">Total Donations</span>
                        <span className="profile-field-val">{currentDonor.donations} Lifetime Donation{currentDonor.donations !== 1 ? 's' : ''}</span>
                      </div>
                      <div className="profile-field">
                        <span className="profile-field-lbl">Last Donation Date</span>
                        <span className="profile-field-val">{currentDonor.lastDonationDate || '2025-08-17'}</span>
                      </div>
                      <div className="profile-field">
                        <span className="profile-field-lbl">Eligibility Status</span>
                        <span className="profile-field-val" style={{ color: currentDonor.eligibility === 'eligible' ? 'var(--green)' : 'var(--amber)', fontWeight: 'bold' }}>
                          {currentDonor.eligibility === 'eligible' ? 'Eligible to Donate Now' : 'Snoozed / Temporarily Ineligible'}
                        </span>
                      </div>
                    </>
                  );
                })()}

                <div style={{ marginTop: '1.5rem', display: 'flex', gap: '10px' }}>
                  <button className="btn-outreach" style={{ padding: '8px 16px', fontSize: '12px' }} onClick={() => triggerNotification('Status updated: You are now marked as AVAILABLE for active bridges in Hyderabad.', 'success')}>Update Availability</button>
                  <button className="btn-reengage" style={{ padding: '8px 16px', fontSize: '12px', border: '1px solid var(--border)' }} onClick={() => triggerNotification('Snooze scheduled. You will not receive donation requests for the next 30 days.', 'warning')}>Snooze Requests (30d)</button>
                </div>
              </div>

              {/* Secure Token & QR Card */}
              <div>
                <div className="portal-section-title">🏥 Secure Token & QR Verification</div>
                <p style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '1rem', lineHeight: '1.4' }}>
                  To maintain double-blind anonymity and prevent direct recipient-donor transactional pressure, present this secure transactional token at the hospital blood bank. 
                </p>

                {activeDonationToken ? (
                  <div style={{
                    background: 'white',
                    border: '1px solid var(--primary-mid)',
                    borderRadius: '12px',
                    padding: '1.25rem',
                    textAlign: 'center',
                    boxShadow: 'var(--shadow-sm)'
                  }}>
                    <div style={{ fontSize: '11px', color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', marginBottom: '4px' }}>Active Transactional Token</div>
                    <div style={{ fontSize: '1.75rem', fontWeight: 900, color: 'var(--primary)', letterSpacing: '2px', marginBottom: '12px' }}>{activeDonationToken}</div>
                    
                    {/* Visual QR Code Simulator */}
                    <div style={{
                      width: '120px',
                      height: '120px',
                      margin: '0 auto 12px',
                      background: 'var(--surface2)',
                      border: '6px solid white',
                      borderRadius: '8px',
                      display: 'flex',
                      flexWrap: 'wrap',
                      padding: '4px',
                      boxShadow: 'inset 0 0 10px rgba(0,0,0,0.1)'
                    }}>
                      {[...Array(64)].map((_, i) => (
                        <div 
                          key={i} 
                          style={{
                            width: '12.5%', 
                            height: '12.5%', 
                            background: (i * 7 + 13) % 5 === 0 || (i < 8 && i % 3 === 0) || (i > 56 && i % 2 === 0) ? '#0f172a' : 'transparent'
                          }}
                        ></div>
                      ))}
                    </div>
                    
                    <p style={{ fontSize: '10.5px', color: 'var(--muted)', lineHeight: '1.4' }}>
                      Ask hospital staff to verify this code `<b>{activeDonationToken}</b>` in their Coordinator portal to confirm your donation anonymously.
                    </p>
                  </div>
                ) : (
                  <div style={{
                    background: 'var(--surface2)',
                    border: '1px dotted var(--border)',
                    borderRadius: '12px',
                    padding: '2rem 1.5rem',
                    textAlign: 'center',
                    color: 'var(--muted)'
                  }}>
                    <span style={{ fontSize: '2rem', display: 'block', marginBottom: '8px' }}>🎟️</span>
                    <strong style={{ fontSize: '13px', display: 'block', color: 'var(--text-secondary)' }}>No Active Token</strong>
                    <span style={{ fontSize: '11.5px', display: 'block', marginTop: '4px', lineHeight: '1.4' }}>
                      Once the coordinator assigns you to an urgent request and outreach is confirmed, your secure QR token will generate here.
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Virtual Impact Tokens (Pay-It-Forward Redemptions) */}
            <div style={{ background: '#f8fafc', border: '1px solid var(--border)', borderRadius: '16px', padding: '1.75rem', marginBottom: '2rem' }}>
              <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '4px' }}>🎁 Pay-It-Forward Redemption Center</h3>
              <p style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '1.25rem', lineHeight: '1.4' }}>
                Life-Credits cannot be exchanged for money to prevent commercialization of blood donation. Instead, spend your credits to fund life-saving medical care and screenings for underprivileged families:
              </p>
              
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
                <div style={{ background: 'white', border: '1px solid var(--border)', borderRadius: '12px', padding: '1.25rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Rural Family Carrier Screening</strong>
                      <span className="bg-pill" style={{ background: 'var(--green-bg)', color: 'var(--green)', fontSize: '10px' }}>200 Credits</span>
                    </div>
                    <p style={{ fontSize: '11.5px', color: 'var(--muted)', lineHeight: '1.4' }}>
                      Sponsor a free Thalassemia carrier screening (HbA2 test) for an underprivileged rural family to prevent genetic inheritance risks.
                    </p>
                  </div>
                  <button 
                    className="btn-cert-download" 
                    style={{ background: 'var(--green)', width: '100%', marginTop: '1rem', padding: '8px', fontSize: '11.5px' }}
                    onClick={() => {
                      if (lifeCredits < 200) {
                        triggerNotification("Insufficient Life-Credits. Complete active bridges to earn more!", "warning");
                        return;
                      }
                      setLifeCredits(prev => prev - 200);
                      setSponsorshipsCount(prev => prev + 1);
                      triggerNotification("Redemption Success! Sponsoring 1 Rural Thalassemia Carrier screening drive.", "success");
                    }}
                  >
                    Redeem Screening (200c)
                  </button>
                </div>

                <div style={{ background: 'white', border: '1px solid var(--border)', borderRadius: '12px', padding: '1.25rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Pediatric Diagnostics Package</strong>
                      <span className="bg-pill" style={{ background: 'var(--green-bg)', color: 'var(--green)', fontSize: '10px' }}>500 Credits</span>
                    </div>
                    <p style={{ fontSize: '11.5px', color: 'var(--muted)', lineHeight: '1.4' }}>
                      Fund a diagnostics blood package (including full blood count, serum ferritin, and liver panels) for a pediatric patient.
                    </p>
                  </div>
                  <button 
                    className="btn-cert-download" 
                    style={{ background: 'var(--green)', width: '100%', marginTop: '1rem', padding: '8px', fontSize: '11.5px' }}
                    onClick={() => {
                      if (lifeCredits < 500) {
                        triggerNotification("Insufficient Life-Credits. Complete active bridges to earn more!", "warning");
                        return;
                      }
                      setLifeCredits(prev => prev - 500);
                      setSponsorshipsCount(prev => prev + 1);
                      triggerNotification("Redemption Success! Funding 1 pediatric diagnostics support package.", "success");
                    }}
                  >
                    Redeem Care Package (500c)
                  </button>
                </div>
              </div>
            </div>

            {/* Achievements and Badges */}
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1.5rem' }}>
              <div className="portal-section-title">My Earned Milestone Badges & Awareness Sharing</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', marginTop: '1rem', marginBottom: '2rem' }}>
                <div style={{ background: 'var(--green-bg)', border: '1px solid var(--green-border)', borderRadius: '12px', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ fontSize: '28px' }}>🔓</span>
                    <div>
                      <strong style={{ fontSize: '12.5px', color: '#065f46', display: 'block' }}>First Drop Badge</strong>
                      <span style={{ fontSize: '11px', color: '#047857' }}>Completed first voluntary donation in Hyderabad.</span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '6px', borderTop: '1px solid rgba(0,0,0,0.05)', paddingTop: '8px' }}>
                    <a 
                      href={getBadgeShareUrl('First Drop Badge', 'whatsapp')}
                      target="_blank" 
                      rel="noopener noreferrer" 
                      style={{ fontSize: '10px', padding: '4px 8px', background: '#25D366', color: 'white', borderRadius: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                    >
                      💬 WhatsApp
                    </a>
                    <a 
                      href={getBadgeShareUrl('First Drop Badge', 'linkedin')}
                      target="_blank" 
                      rel="noopener noreferrer" 
                      style={{ fontSize: '10px', padding: '4px 8px', background: '#0077B5', color: 'white', borderRadius: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                    >
                      🔗 LinkedIn
                    </a>
                  </div>
                </div>

                <div style={{ background: 'var(--green-bg)', border: '1px solid var(--green-border)', borderRadius: '12px', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ fontSize: '28px' }}>🔓</span>
                    <div>
                      <strong style={{ fontSize: '12.5px', color: '#065f46', display: 'block' }}>Bridge Anchor</strong>
                      <span style={{ fontSize: '11px', color: '#047857' }}>Supported a thalassemia child for multiple cycles.</span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '6px', borderTop: '1px solid rgba(0,0,0,0.05)', paddingTop: '8px' }}>
                    <a 
                      href={getBadgeShareUrl('Bridge Anchor', 'whatsapp')}
                      target="_blank" 
                      rel="noopener noreferrer" 
                      style={{ fontSize: '10px', padding: '4px 8px', background: '#25D366', color: 'white', borderRadius: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                    >
                      💬 WhatsApp
                    </a>
                    <a 
                      href={getBadgeShareUrl('Bridge Anchor', 'linkedin')}
                      target="_blank" 
                      rel="noopener noreferrer" 
                      style={{ fontSize: '10px', padding: '4px 8px', background: '#0077B5', color: 'white', borderRadius: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                    >
                      🔗 LinkedIn
                    </a>
                  </div>
                </div>

                <div style={{ background: 'var(--green-bg)', border: '1px solid var(--green-border)', borderRadius: '12px', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ fontSize: '28px' }}>🔓</span>
                    <div>
                      <strong style={{ fontSize: '12.5px', color: '#065f46', display: 'block' }}>Rare Guardian</strong>
                      <span style={{ fontSize: '11px', color: '#047857' }}>Supported rare blood type shortage alerts.</span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '6px', borderTop: '1px solid rgba(0,0,0,0.05)', paddingTop: '8px' }}>
                    <a 
                      href={getBadgeShareUrl('Rare Guardian', 'whatsapp')}
                      target="_blank" 
                      rel="noopener noreferrer" 
                      style={{ fontSize: '10px', padding: '4px 8px', background: '#25D366', color: 'white', borderRadius: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                    >
                      💬 WhatsApp
                    </a>
                    <a 
                      href={getBadgeShareUrl('Rare Guardian', 'linkedin')}
                      target="_blank" 
                      rel="noopener noreferrer" 
                      style={{ fontSize: '10px', padding: '4px 8px', background: '#0077B5', color: 'white', borderRadius: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                    >
                      🔗 LinkedIn
                    </a>
                  </div>
                </div>

                {hyderabadQuestCount >= 421 ? (
                  <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '12px', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span style={{ fontSize: '28px' }}>🛡️</span>
                      <div>
                        <strong style={{ fontSize: '12.5px', color: '#1e40af', display: 'block' }}>Community Shield</strong>
                        <span style={{ fontSize: '11px', color: '#1d4ed8' }}>Collaborated in Chapter's monthly quest targets!</span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '6px', borderTop: '1px solid rgba(0,0,0,0.05)', paddingTop: '8px' }}>
                      <a 
                        href={getBadgeShareUrl('Community Shield', 'whatsapp')}
                        target="_blank" 
                        rel="noopener noreferrer" 
                        style={{ fontSize: '10px', padding: '4px 8px', background: '#25D366', color: 'white', borderRadius: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                      >
                        💬 WhatsApp
                      </a>
                      <a 
                        href={getBadgeShareUrl('Community Shield', 'linkedin')}
                        target="_blank" 
                        rel="noopener noreferrer" 
                        style={{ fontSize: '10px', padding: '4px 8px', background: '#0077B5', color: 'white', borderRadius: '4px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}
                      >
                        🔗 LinkedIn
                      </a>
                    </div>
                  </div>
                ) : (
                  <div style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: '12px', padding: '1rem', display: 'flex', alignItems: 'center', gap: '12px', opacity: 0.65 }}>
                    <span style={{ fontSize: '28px', filter: 'grayscale(1)' }}>🔒</span>
                    <div>
                      <strong style={{ fontSize: '12.5px', color: 'var(--muted)', display: 'block' }}>Community Shield</strong>
                      <span style={{ fontSize: '11px', color: 'var(--muted)' }}>Locked: Complete the monthly Hyderabad Chapter Quest.</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Donation Certificates Section */}
              {(() => {
                const currentDonor = donors.find(d => d.phone === loginUsername || d.userId === loginUsername) || {
                  name: "Rahul Sharma",
                  bloodGroup: "B Positive",
                  userId: "donor_82a7155d",
                  donations: 9,
                  lastDonationDate: "2025-08-17"
                };
                
                // Construct dynamic list of certificates
                const certs = [];
                if (currentDonor.donations > 0) {
                  certs.push({
                    id: `CERT-${currentDonor.userId.substring(0, 6).toUpperCase()}-1`,
                    date: currentDonor.lastDonationDate || "2025-08-17",
                    bloodGroup: currentDonor.bloodGroup,
                    token: "BB-D82A71",
                    donorName: currentDonor.name
                  });
                }
                // If they have multiple donations, seed a couple of historical ones for aesthetic richness
                if (currentDonor.donations > 1) {
                  certs.push({
                    id: `CERT-${currentDonor.userId.substring(0, 6).toUpperCase()}-2`,
                    date: "2025-05-15",
                    bloodGroup: currentDonor.bloodGroup,
                    token: "BB-A41B92",
                    donorName: currentDonor.name
                  });
                  certs.push({
                    id: `CERT-${currentDonor.userId.substring(0, 6).toUpperCase()}-3`,
                    date: "2025-02-10",
                    bloodGroup: currentDonor.bloodGroup,
                    token: "BB-F71D38",
                    donorName: currentDonor.name
                  });
                }

                return (
                  <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1.5rem', marginTop: '1.5rem' }}>
                    <div className="portal-section-title">My Donation Certificates (Awareness Center)</div>
                    <p style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '1rem', lineHeight: '1.4' }}>
                      Each successful blood donation logs a digital Certificate of Appreciation. Download your certificate or share it directly to your social media to inspire others to donate!
                    </p>
                    {certs.length > 0 ? (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
                        {certs.map(cert => (
                          <div key={cert.id} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '12px', padding: '1.25rem', boxShadow: 'var(--shadow-sm)', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                <span style={{ fontSize: '10px', background: 'var(--primary-light)', color: 'var(--primary)', padding: '2px 8px', borderRadius: '4px', fontWeight: 700 }}>{cert.id}</span>
                                <span style={{ fontSize: '11px', color: 'var(--muted)', fontWeight: 600 }}>{cert.date}</span>
                              </div>
                              <h4 style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--text)', marginBottom: '4px' }}>📜 Certificate of Appreciation</h4>
                              <p style={{ fontSize: '11px', color: 'var(--muted)', lineHeight: '1.4', marginBottom: '1rem' }}>
                                Awarded to <b>{cert.donorName}</b> for saving a life by donating <b>{cert.bloodGroup}</b> blood (Token: {cert.token}).
                              </p>
                            </div>
                            <div style={{ display: 'flex', gap: '10px' }}>
                              <button 
                                className="btn-cert-download" 
                                style={{ flex: 1, padding: '8px', fontSize: '11.5px', background: 'var(--primary)', borderColor: 'var(--primary)', cursor: 'pointer' }}
                                onClick={() => {
                                  setSelectedCertificate(cert);
                                  setShowCertificateModal(true);
                                }}
                              >
                                View / Download
                              </button>
                              <a 
                                href={getCertificateShareUrl(cert.token, 'whatsapp')}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="btn-reengage"
                                style={{ padding: '8px 12px', fontSize: '11.5px', border: '1px solid var(--border)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
                              >
                                💬 Share Story
                              </a>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div style={{ background: 'var(--surface2)', padding: '1.5rem', borderRadius: '8px', textAlign: 'center', color: 'var(--muted)', fontSize: '12px' }}>
                        No donation certificates found yet. Complete a scheduled bridge donation to generate one!
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* PATIENT PORTAL VIEW */}
      {activeTab === 'patient' && (
        <div className="container">
          <div className="portal-card">
            <h1>🩸 Patient Transfusion Calendar & Network</h1>
            <p style={{ color: 'var(--muted)', fontSize: '13px', marginTop: '4px', marginBottom: '2rem' }}>
              Manage upcoming blood transfusion dates and view assigned anonymous Bridge Donors. Contact is mediated through the secure NGO proxy line.
            </p>

            <div className="portal-grid">
              {/* Next transfusion */}
              <div>
                <div className="portal-section-title">My Transfusion Calendar</div>
                <div className="profile-field">
                  <span className="profile-field-lbl">Required Blood Group</span>
                  <span className="profile-field-val" style={{ color: 'var(--primary)', fontSize: '14px' }}>B Positive</span>
                </div>
                <div className="profile-field">
                  <span className="profile-field-lbl">Transfusion Frequency</span>
                  <span className="profile-field-val">Every 21 Days</span>
                </div>
                <div className="profile-field">
                  <span className="profile-field-lbl">Last Transfusion Date</span>
                  <span className="profile-field-val">2026-05-18</span>
                </div>
                <div className="profile-field">
                  <span className="profile-field-lbl">Expected Next Date</span>
                  <span className="profile-field-val" style={{ color: 'var(--primary)' }}>2026-06-08 (In 2 days)</span>
                </div>
                <div className="profile-field">
                  <span className="profile-field-lbl">Quantity Required</span>
                  <span className="profile-field-val">2 Units (Red Blood Cells)</span>
                </div>
                <div className="profile-field">
                  <span className="profile-field-lbl">Assigned Hospital</span>
                  <span className="profile-field-val">Hyderabad General Hospital</span>
                </div>

                <div style={{ marginTop: '1.5rem' }}>
                  <button className="btn-outreach" style={{ background: 'var(--red)', padding: '10px 20px', fontSize: '12px' }} onClick={() => triggerNotification('Emergency alert generated. NGO Coordinator and proxy backup bridges notified immediately.', 'success')}>🚨 Request Emergency Backup</button>
                </div>
              </div>

              {/* Assigned Bridge Donors */}
              <div>
                <div className="portal-section-title">Assigned Bridge Donors (Double-Blind Protected)</div>
                <p style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '10px', lineHeight: '1.4' }}>
                  To prevent direct transactional requests or conflicts of interest, all donor identities are anonymized and communications are routed securely.
                </p>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Donor Pseudonym</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Preferred Contact</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td><b>Donor #D-82A71</b></td>
                        <td>Regular Bridge</td>
                        <td><span style={{ color: 'var(--green)', fontWeight: 600 }}>Active / Eligible</span></td>
                        <td>NGO Proxy Hotline</td>
                      </tr>
                      <tr>
                        <td><b>Donor #D-41F6A</b></td>
                        <td>Regular Bridge</td>
                        <td><span style={{ color: 'var(--green)', fontWeight: 600 }}>Active / Eligible</span></td>
                        <td>NGO Proxy Hotline</td>
                      </tr>
                      <tr>
                        <td><b>Donor #D-366F1</b></td>
                        <td>Emergency Backup</td>
                        <td><span style={{ color: 'var(--amber)', fontWeight: 600 }}>Ineligible (Cycle Lock)</span></td>
                        <td>NGO Proxy Hotline</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* FOOTER */}
      <footer>
        <div className="footer-inner">
          <div className="footer-copy">© Blood Warriors 2026 · BloodMatch 2.0</div>
          <div className="footer-links">
            <a href="https://www.bloodwarriors.in" target="_blank" rel="noreferrer">bloodwarriors.in</a>
            <a href="https://www.bloodwarriors.in/about" target="_blank" rel="noreferrer">About</a>
            <a href="https://www.bloodwarriors.in/leaderboard" target="_blank" rel="noreferrer">Leaderboard</a>
          </div>
        </div>
      </footer>

      {/* CHATBOT TRIGGER FAB */}
      <div className="fab" onClick={() => setIsChatOpen(!isChatOpen)} aria-label="Open Chat with Veeru">
        <svg stroke="#fff" fill="#fff" strokeWidth="0" viewBox="0 0 448 512" height="26" width="26" xmlns="http://www.w3.org/2000/svg">
          <path d="M380.9 97.1C339 55.1 283.2 32 223.9 32c-122.4 0-222 99.6-222 222 0 39.1 10.2 77.3 29.6 111L0 480l117.7-30.9c32.4 17.7 68.9 27 106.1 27h.1c122.3 0 224.1-99.6 224.1-222 0-59.3-25.2-115-67.1-157zm-157 341.6c-33.2 0-65.7-8.9-94-25.7l-6.7-4-69.8 18.3L72 359.2l-4.4-7c-18.5-29.4-28.2-63.3-28.2-98.2 0-101.7 82.8-184.5 184.6-184.5 49.3 0 95.6 19.2 130.4 54.1 34.8 34.9 56.2 81.2 56.1 130.5 0 101.8-84.9 184.6-186.6 184.6zm101.2-138.2c-5.5-2.8-32.8-16.2-37.9-18-5.1-1.9-8.8-2.8-12.5 2.8-3.7 5.6-14.3 18-17.6 21.8-3.2 3.7-6.5 4.2-12 1.4-32.6-16.3-54-29.1-75.5-66-5.7-9.8 5.7-9.1 16.3-30.3 1.8-3.7.9-6.9-.5-9.7-1.4-2.8-12.5-30.1-17.1-41.2-4.5-10.8-9.1-9.3-12.5-9.5-3.2-.2-6.9-.2-10.6-.2-3.7 0-9.7 1.4-14.8 6.9-5.1 5.6-19.4 19-19.4 46.3 0 27.3 19.9 53.7 22.6 57.4 2.8 3.7 39.1 59.7 94.8 83.8 35.2 15.2 49 16.5 66.6 13.9 10.7-1.6 32.8-13.4 37.4-26.4 4.6-13 4.6-24.1 3.2-26.4-1.3-2.5-5-3.9-10.5-6.6z"/>
        </svg>
      </div>

      {/* VEERU CHAT DRAWER */}
      <div className={`chat-panel ${isChatOpen ? '' : 'closed'}`}>
        <div className="chat-header">
          <div className="chat-bot-avatar">🤖</div>
          <div className="chat-header-info">
            <div className="chat-bot-name">Veeru 2.0</div>
            <div className="chat-bot-status"><span style={{ width: '6px', height: '6px', background: '#4ade80', borderRadius: '50%' }}></span>Support Agent</div>
          </div>
          <button className="chat-close-btn" onClick={() => setIsChatOpen(false)}>×</button>
        </div>

        <div className="chat-messages">
          {chatMessages.map((m, i) => (
            <div key={i} className={`chat-msg ${m.sender}`}>
              {m.text}
            </div>
          ))}
          {isTyping && <div className="chat-msg typing">Veeru is typing...</div>}
        </div>

        <form className="chat-input-area" onSubmit={handleChatSubmit}>
          <input 
            type="text" 
            className="chat-input" 
            placeholder="Type a message..." 
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
          />
          <button type="submit" className="chat-send-btn">
            <svg stroke="currentColor" fill="none" strokeWidth="2" viewBox="0 0 24 24" height="16" width="16" xmlns="http://www.w3.org/2000/svg">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </form>
      </div>

      {/* SIGN IN / REGISTER MODAL */}
      {showLoginModal && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ width: '450px', maxHeight: '90vh', overflowY: 'auto' }}>
            <button className="modal-close" onClick={() => { setShowLoginModal(false); setIsRegisterMode(false); }}>×</button>
            
            <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: '1.25rem', paddingBottom: '0.5rem' }}>
              <button 
                style={{
                  flex: 1,
                  background: 'none',
                  border: 'none',
                  fontSize: '14px',
                  fontWeight: 700,
                  color: !isRegisterMode ? 'var(--primary)' : 'var(--muted)',
                  borderBottom: !isRegisterMode ? '2px solid var(--primary)' : 'none',
                  padding: '8px',
                  cursor: 'pointer'
                }}
                onClick={() => setIsRegisterMode(false)}
              >
                Sign In
              </button>
              <button 
                style={{
                  flex: 1,
                  background: 'none',
                  border: 'none',
                  fontSize: '14px',
                  fontWeight: 700,
                  color: isRegisterMode ? 'var(--primary)' : 'var(--muted)',
                  borderBottom: isRegisterMode ? '2px solid var(--primary)' : 'none',
                  padding: '8px',
                  cursor: 'pointer'
                }}
                onClick={() => setIsRegisterMode(true)}
              >
                Register
              </button>
            </div>

            {!isRegisterMode ? (
              <>
                <div className="auth-title" style={{ marginTop: '0' }}>Sign In to BloodMatch</div>
                <div className="auth-sub">Select your account type to proceed</div>
                
                <div className="role-select-grid">
                  <button 
                    className={`role-btn ${loginRole === 'admin' ? 'active' : ''}`}
                    onClick={() => {
                      setLoginRole('admin');
                      setLoginUsername('coordinator@bloodwarriors.in');
                    }}
                  >
                    <span className="role-icon">🧑‍💼</span>
                    <span>NGO Coordinator / Admin</span>
                  </button>
                  <button 
                    className={`role-btn ${loginRole === 'donor' ? 'active' : ''}`}
                    onClick={() => {
                      setLoginRole('donor');
                      setLoginUsername('9391551999');
                    }}
                  >
                    <span className="role-icon">🩸</span>
                    <span>Volunteer Blood Donor</span>
                  </button>
                  <button 
                    className={`role-btn ${loginRole === 'patient' ? 'active' : ''}`}
                    onClick={() => {
                      setLoginRole('patient');
                      setLoginUsername('guardian_phone');
                    }}
                  >
                    <span className="role-icon">👤</span>
                    <span>Thalassemia Patient Portal</span>
                  </button>
                </div>

                <div className="auth-input-group">
                  <label className="auth-input-label">Username / Registered Contact</label>
                  <input 
                    type="text" 
                    className="auth-input" 
                    placeholder="Enter email or mobile number" 
                    value={loginUsername}
                    onChange={(e) => setLoginUsername(e.target.value)}
                  />
                </div>
                
                <div className="auth-input-group">
                  <label className="auth-input-label">Password</label>
                  <input 
                    type="password" 
                    className="auth-input" 
                    placeholder="••••••••" 
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                  />
                </div>

                <button 
                  className="btn-login"
                  onClick={handleCognitoSignIn}
                >
                  Sign In (Cognito Live Auth)
                </button>
                <div style={{ textAlign: 'center', marginTop: '1rem', fontSize: '12px' }}>
                  <a href="#" style={{ color: 'var(--primary)', fontWeight: 600 }} onClick={(e) => { e.preventDefault(); setIsRegisterMode(true); }}>
                    Don't have an account? Register Now
                  </a>
                </div>
              </>
            ) : isVerifying ? (
              <form onSubmit={handleConfirmVerification}>
                <div className="auth-title" style={{ marginTop: '0' }}>Verify Account</div>
                <div className="auth-sub">Enter the confirmation code sent to your contact:</div>

                <div className="auth-input-group">
                  <label className="auth-input-label">Verification Code</label>
                  <input 
                    type="text" 
                    className="auth-input" 
                    placeholder="e.g. 123456" 
                    value={verificationCode}
                    onChange={(e) => setVerificationCode(e.target.value)}
                    required
                  />
                </div>

                <button type="submit" className="btn-login" style={{ marginTop: '1.25rem' }}>
                  Confirm Verification Code
                </button>

                <div style={{ textAlign: 'center', marginTop: '1rem', fontSize: '12px' }}>
                  <a href="#" style={{ color: 'var(--primary)', fontWeight: 600 }} onClick={(e) => { e.preventDefault(); setIsVerifying(false); }}>
                    Back to Registration
                  </a>
                </div>
              </form>
            ) : (
              <form onSubmit={handleDonorRegistration}>
                <div className="auth-title" style={{ marginTop: '0' }}>Register to BloodMatch</div>
                <div className="auth-sub">Choose your role and enter your details to register</div>

                <div className="role-select-grid" style={{ marginBottom: '1rem', display: 'flex', gap: '10px' }}>
                  <button 
                    type="button"
                    className={`role-btn ${regRole === 'donor' ? 'active' : ''}`}
                    onClick={() => setRegRole('donor')}
                    style={{ flex: 1, padding: '10px', fontSize: '12.5px', justifyContent: 'center' }}
                  >
                    <span className="role-icon">🩸</span>
                    <span>Volunteer Donor</span>
                  </button>
                  <button 
                    type="button"
                    className={`role-btn ${regRole === 'patient' ? 'active' : ''}`}
                    onClick={() => setRegRole('patient')}
                    style={{ flex: 1, padding: '10px', fontSize: '12.5px', justifyContent: 'center' }}
                  >
                    <span className="role-icon">👤</span>
                    <span>Thalassemia Patient</span>
                  </button>
                </div>

                <div className="auth-input-group">
                  <label className="auth-input-label">Full Name</label>
                  <input 
                    type="text" 
                    className="auth-input" 
                    placeholder="e.g. Rahul Sharma" 
                    value={regName}
                    onChange={(e) => setRegName(e.target.value)}
                    required
                  />
                </div>

                <div className="auth-input-group">
                  <label className="auth-input-label">Mobile Number (with +91)</label>
                  <input 
                    type="text" 
                    className="auth-input" 
                    placeholder="e.g. +91 9876543210" 
                    value={regPhone}
                    onChange={(e) => setRegPhone(e.target.value)}
                    required
                  />
                </div>

                <div className="auth-input-group">
                  <label className="auth-input-label">Password</label>
                  <input 
                    type="password" 
                    className="auth-input" 
                    placeholder="Set secure password" 
                    value={regPassword}
                    onChange={(e) => setRegPassword(e.target.value)}
                    required
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                  <div className="auth-input-group">
                    <label className="auth-input-label">Blood Group</label>
                    <select 
                      className="match-selector" 
                      value={regBloodGroup}
                      onChange={(e) => setRegBloodGroup(e.target.value)}
                    >
                      <option value="O Positive">O Positive (O+)</option>
                      <option value="O Negative">O Negative (O-)</option>
                      <option value="A Positive">A Positive (A+)</option>
                      <option value="A Negative">A Negative (A-)</option>
                      <option value="B Positive">B Positive (B+)</option>
                      <option value="B Negative">B Negative (B-)</option>
                      <option value="AB Positive">AB Positive (AB+)</option>
                      <option value="AB Negative">AB Negative (AB-)</option>
                    </select>
                  </div>

                  <div className="auth-input-group">
                    <label className="auth-input-label">Gender</label>
                    <select 
                      className="match-selector" 
                      value={regGender}
                      onChange={(e) => setRegGender(e.target.value)}
                    >
                      <option value="Male">Male</option>
                      <option value="Female">Female</option>
                      <option value="Other">Other</option>
                    </select>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                  <div className="auth-input-group">
                    <label className="auth-input-label">Preferred Channel</label>
                    <select 
                      className="match-selector" 
                      value={regChannel}
                      onChange={(e) => setRegChannel(e.target.value)}
                    >
                      <option value="WhatsApp">WhatsApp</option>
                      <option value="SMS">SMS</option>
                      <option value="Email">Email</option>
                    </select>
                  </div>

                  <div className="auth-input-group">
                    <label className="auth-input-label">Preferred Language</label>
                    <select 
                      className="match-selector" 
                      value={regLanguage}
                      onChange={(e) => setRegLanguage(e.target.value)}
                    >
                      <option value="English">English</option>
                      <option value="Hindi">Hindi</option>
                      <option value="Telugu">Telugu</option>
                      <option value="Tamil">Tamil</option>
                    </select>
                  </div>
                </div>

                <div className="auth-input-group" style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '10px', background: 'var(--surface2)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border)' }}>
                  <input 
                    type="checkbox" 
                    id="joinBridgeCheck"
                    checked={regJoinBridge}
                    onChange={(e) => setRegJoinBridge(e.target.checked)}
                    style={{ width: '18px', height: '18px', cursor: 'pointer' }}
                  />
                  {regRole === 'donor' ? (
                    <label htmlFor="joinBridgeCheck" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', cursor: 'pointer' }}>
                      Join a Patient Bridge? (Yes / No)
                      <span style={{ display: 'block', fontSize: '10px', color: 'var(--muted)', fontWeight: 'normal', marginTop: '2px' }}>
                        Allocates you to a matched child needing rotating transfusions. If No, you will be notified only during emergencies.
                      </span>
                    </label>
                  ) : (
                    <label htmlFor="joinBridgeCheck" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', cursor: 'pointer' }}>
                      Create Dedicated Blood Bridge? (Yes / No)
                      <span style={{ display: 'block', fontSize: '10px', color: 'var(--muted)', fontWeight: 'normal', marginTop: '2px' }}>
                        Sets up a rotating group of 8-10 regular donors to support your regular transfusion cycle.
                      </span>
                    </label>
                  )}
                </div>

                <button type="submit" className="btn-login" style={{ marginTop: '1.25rem' }}>
                  Register and Sign In
                </button>
                
                <div style={{ textAlign: 'center', marginTop: '1rem', fontSize: '12px' }}>
                  <a href="#" style={{ color: 'var(--primary)', fontWeight: 600 }} onClick={(e) => { e.preventDefault(); setIsRegisterMode(false); }}>
                    Already have an account? Sign In
                  </a>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* DONATION CERTIFICATE VIEWER MODAL */}
      {showCertificateModal && selectedCertificate && (
        <div className="modal-overlay" style={{ zIndex: 2000 }}>
          <div className="modal-content" style={{ width: '600px', padding: '2rem', background: '#fcfbf7', border: '8px double #d4af37', borderRadius: '8px', boxShadow: '0 10px 30px rgba(0,0,0,0.25)', position: 'relative' }}>
            <button className="modal-close" style={{ color: '#888', right: '15px', top: '15px' }} onClick={() => { setShowCertificateModal(false); setSelectedCertificate(null); }}>×</button>
            
            <div style={{ textAlign: 'center', fontFamily: "'Georgia', serif", color: '#333' }}>
              <div style={{ fontSize: '2.5rem', color: '#c0002e', fontWeight: 'bold', letterSpacing: '2px', marginBottom: '0.5rem' }}>🎗️</div>
              <h2 style={{ fontSize: '1.75rem', fontWeight: 'bold', color: '#8b0000', textTransform: 'uppercase', letterSpacing: '3px', margin: '0 0 1.5rem' }}>Certificate of Appreciation</h2>
              
              <p style={{ fontSize: '14px', fontStyle: 'italic', color: '#555', margin: '0 0 1rem' }}>This is proudly presented to</p>
              <h1 style={{ fontSize: '2.25rem', fontWeight: 'bold', color: '#111', borderBottom: '2px solid #d4af37', display: 'inline-block', paddingBottom: '4px', margin: '0 0 1.5rem', minWidth: '300px' }}>
                {selectedCertificate.donorName}
              </h1>
              
              <p style={{ fontSize: '13px', lineHeight: '1.8', color: '#444', margin: '0 auto 2rem', maxWidth: '480px' }}>
                For their selfless and noble contribution of voluntary blood donation (Blood Group: <b>{selectedCertificate.bloodGroup}</b>, Transaction Token: <b>{selectedCertificate.token}</b>) on <b>{selectedCertificate.date}</b>, successfully securing a patient's Thalassemia transfusion bridge. Your act of compassion has directly saved a life.
              </p>
              
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '3rem', borderTop: '1px dashed #ccc', paddingTop: '1.5rem', paddingLeft: '1rem', paddingRight: '1rem' }}>
                <div>
                  <div style={{ fontFamily: 'monospace', fontSize: '10px', color: '#888' }}>TOKEN: {selectedCertificate.token}</div>
                  <div style={{ fontSize: '11px', fontWeight: 'bold', color: '#555', marginTop: '4px' }}>VERIFIED SECURE</div>
                </div>
                <div>
                  <div style={{ fontSize: '18px', fontFamily: "'Zapfino', cursive, serif", color: '#8b0000', fontStyle: 'italic' }}>Blood Warriors</div>
                  <div style={{ fontSize: '11px', color: '#555', fontWeight: 'bold', marginTop: '4px' }}>OFFICIAL NETWORK SEAL</div>
                </div>
              </div>
            </div>
            
            <div style={{ display: 'flex', gap: '10px', marginTop: '2.5rem', borderTop: '1px solid #eee', paddingTop: '1.25rem' }}>
              <button 
                className="btn-cert-download"
                style={{ flex: 1, padding: '10px', background: 'var(--primary)', borderColor: 'var(--primary)', cursor: 'pointer' }}
                onClick={() => {
                  downloadCertificateAsPDF(selectedCertificate);
                  triggerNotification("Generating PDF print layout for Certificate of Appreciation...", "success");
                }}
              >
                📥 Download PDF
              </button>
              
              <a 
                href={getCertificateShareUrl(selectedCertificate.token, 'whatsapp')}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-hero-primary"
                style={{ background: '#25D366', borderColor: '#25D366', color: 'white', textDecoration: 'none', padding: '10px 16px', borderRadius: '8px', fontSize: '12px', fontWeight: 'bold', display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}
              >
                💬 WhatsApp Story
              </a>
              
              <a 
                href={getCertificateShareUrl(selectedCertificate.token, 'linkedin')}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-hero-primary"
                style={{ background: '#0077B5', borderColor: '#0077B5', color: 'white', textDecoration: 'none', padding: '10px 16px', borderRadius: '8px', fontSize: '12px', fontWeight: 'bold', display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}
              >
                🔗 LinkedIn Share
              </a>
            </div>
          </div>
        </div>
      )}

      {/* EMERGENCY REQUEST MODAL */}
      {showEmergencyRequestModal && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ width: '450px', maxHeight: '90vh', overflowY: 'auto' }}>
            <button className="modal-close" onClick={() => setShowEmergencyRequestModal(false)}>×</button>
            <div className="auth-title" style={{ marginTop: '0' }}>Raise Emergency Request</div>
            <div className="auth-sub">Alert nearby compatible donors instantly</div>

            <form onSubmit={handleRaiseEmergencyRequest}>
              <div className="auth-input-group">
                <label className="auth-input-label">Patient Gender</label>
                <select 
                  className="match-selector" 
                  value={emGender}
                  onChange={(e) => setEmGender(e.target.value)}
                >
                  <option value="Male">Male</option>
                  <option value="Female">Female</option>
                  <option value="Other">Other</option>
                </select>
              </div>

              <div className="auth-input-group">
                <label className="auth-input-label">Patient Age (Years)</label>
                <input 
                  type="number" 
                  className="auth-input" 
                  placeholder="e.g. 8" 
                  value={emAge}
                  onChange={(e) => setEmAge(e.target.value)}
                  required
                />
              </div>

              <div className="auth-input-group">
                <label className="auth-input-label">Required Blood Group</label>
                <select 
                  className="match-selector" 
                  value={emBloodGroup}
                  onChange={(e) => setEmBloodGroup(e.target.value)}
                >
                  <option value="O Positive">O Positive (O+)</option>
                  <option value="O Negative">O Negative (O-)</option>
                  <option value="A Positive">A Positive (A+)</option>
                  <option value="A Negative">A Negative (A-)</option>
                  <option value="B Positive">B Positive (B+)</option>
                  <option value="B Negative">B Negative (B-)</option>
                  <option value="AB Positive">AB Positive (AB+)</option>
                  <option value="AB Negative">AB Negative (AB-)</option>
                </select>
              </div>

              <div className="auth-input-group">
                <label className="auth-input-label">Hospital Location & Address</label>
                <input 
                  type="text" 
                  className="auth-input" 
                  placeholder="e.g. Rainbow Children's Hospital, Banjara Hills" 
                  value={emHospital}
                  onChange={(e) => setEmHospital(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div className="auth-input-group">
                  <label className="auth-input-label">Units Needed</label>
                  <input 
                    type="number" 
                    className="auth-input" 
                    min="1" 
                    max="10" 
                    value={emUnits}
                    onChange={(e) => setEmUnits(parseInt(e.target.value) || 2)}
                    required
                  />
                </div>
                <div className="auth-input-group">
                  <label className="auth-input-label">Required By Date</label>
                  <input 
                    type="date" 
                    className="auth-input" 
                    value={emDate}
                    onChange={(e) => setEmDate(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="auth-input-group">
                <label className="auth-input-label">Guardian Contact Number</label>
                <input 
                  type="tel" 
                  className="auth-input" 
                  placeholder="e.g. +91 9876543210" 
                  value={emContact}
                  onChange={(e) => setEmContact(e.target.value)}
                  required
                />
              </div>

              <button type="submit" className="btn-login" style={{ marginTop: '1rem', background: '#c0002e' }}>
                Submit Emergency Request
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
