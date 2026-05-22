from twilio.rest import Client
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
import pandas as pd
import numpy as np

# ── Twilio Setup ─────────────────────────────────────────────────────────────
from dotenv import load_dotenv
import os

load_dotenv()

TWILIO_SID   = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_FROM  = os.getenv("TWILIO_FROM")
registered_phone = {"number": None, "name": None}
leak_history     = []

def send_sms(to_number, message):
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=message, from_=TWILIO_FROM, to=to_number)
        print(f"SMS sent to {to_number}")
    except Exception as e:
        print(f"SMS failed: {e}")

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)
from flask import send_from_directory

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_file(filename):
    return send_from_directory('.', filename)
# ════════════════════════════════════════════════════════════════════════════
#  SIMULATION MODEL — Gasket Leak only
#  1. Smooth baseline generated from real no-leak CSV RMS levels
#  2. Gasket leak disturbance injected at t=8s to t=30s
#  3. Detection: smoothed flow > BL_MEAN + 2.15*BL_STD → Leak Detected
# ════════════════════════════════════════════════════════════════════════════

N = 300
T = np.linspace(0, 38, N)
np.random.seed(42)

CSV_FILES = {
    "no_leak":     "noleak.csv",
    "gasket_leak": "gasketleak.csv",
}

# ── Step 1: Load CSVs ─────────────────────────────────────────────────────────
print("Loading real CSV data for disturbance calibration...")
real_rms = {}
for key, fname in CSV_FILES.items():
    try:
        df  = pd.read_csv(fname)
        ws  = len(df) // N
        rms = [float(np.sqrt((df["Value"].iloc[i*ws:(i+1)*ws]**2).mean()))
               for i in range(N)]
        real_rms[key] = {
            "mean": float(np.mean(rms)),
            "std":  float(np.std(rms)),
            "min":  float(np.min(rms)),
            "max":  float(np.max(rms)),
        }
        print(f"  {key}: mean_rms={real_rms[key]['mean']:.2f}")
    except FileNotFoundError:
        print(f"  WARNING: {fname} not found — using fallback values")
        real_rms[key] = {
            "mean": {"no_leak": 2948, "gasket_leak": 4323}[key],
            "std": 330, "min": 2300, "max": 5500
        }

# ── Step 2: Smooth baseline ───────────────────────────────────────────────────
NL_MEAN = real_rms["no_leak"]["mean"]
NL_STD  = real_rms["no_leak"]["std"]

tank_pressure = NL_MEAN * np.exp(-0.006 * T)
pipe_wave     = NL_STD * 0.55 * np.sin(2 * np.pi * 0.08 * T + 0.5)
harmonic      = NL_STD * 0.18 * np.sin(2 * np.pi * 0.25 * T + 1.2)
sensor_noise  = np.random.normal(0, NL_STD * 0.07, N)

BASELINE = tank_pressure + pipe_wave + harmonic + sensor_noise

BL_MEAN = float(BASELINE.mean())
BL_STD  = float(BASELINE.std())
HIGH_TH = round(BL_MEAN + 2.15 * BL_STD, 2)
LOW_TH  = round(BL_MEAN - 2.0  * BL_STD, 2)

print(f"Baseline: mean={BL_MEAN:.2f}, std={BL_STD:.2f}")
print(f"Thresholds — Leak: {HIGH_TH:.2f} | Low: {LOW_TH:.2f}")

# ── Step 3: Gasket leak flow (t=8s to t=30s) ─────────────────────────────────
GASKET_FLOW = BASELINE.copy()
GAS_DIFF    = real_rms["gasket_leak"]["mean"] - real_rms["no_leak"]["mean"]
mask_g      = (T >= 8) & (T <= 30)
ramp_g      = np.zeros(N)
ramp_g[mask_g] = np.linspace(0, 1, mask_g.sum()) ** 0.4

turbulence_g = GAS_DIFF * 1.8 * np.abs(np.sin(2 * np.pi * 0.9 * T)) \
             + NL_STD * 0.9 * np.abs(np.random.normal(0, 1, N))

GASKET_FLOW += turbulence_g * ramp_g

print(f"Gasket max flow = {GASKET_FLOW.max():.2f}")

# ── Status tag helper ─────────────────────────────────────────────────────────
def tag_status(val):
    if val > HIGH_TH: return "Leak Detected"
    if val < LOW_TH:  return "Low Usage"
    return "Normal"

# ── Step 4: Build endpoint payloads ──────────────────────────────────────────
def make_windows(flow_array):
    pressure_array = flow_array \
                   + np.random.normal(0, NL_STD * 0.45, N) \
                   + NL_STD * 0.2 * np.sin(2 * np.pi * 3.5 * T)

    kernel   = 7
    pad      = kernel // 2
    padded   = np.pad(flow_array, pad, mode='edge')
    smoothed = np.convolve(padded, np.ones(kernel) / kernel, mode='valid')
    smoothed = smoothed[:N]

    return [{
        "time":     round(float(T[i]), 3),
        "pressure": round(float(pressure_array[i]), 2),
        "flow":     round(float(smoothed[i]), 2),
        "status":   tag_status(smoothed[i]),
    } for i in range(N)]

WINDOWS = {
    "gasket_leak": make_windows(GASKET_FLOW),
}

for key in WINDOWS:
    lk = sum(1 for w in WINDOWS[key] if w["status"] == "Leak Detected")
    print(f"  {key}: {lk}/{N} windows = Leak Detected")

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return "AquaTrack simulation backend running!"

@app.route("/get-flow")
def get_flow():
    key = request.args.get("file", "gasket_leak")
    if key not in WINDOWS:
        return jsonify({"error": "unknown key"}), 400
    return jsonify({
        "data":    WINDOWS[key],
        "high_th": HIGH_TH,
        "low_th":  LOW_TH,
        "bl_mean": round(BL_MEAN, 2),
        "label":   "Gasket Leak"
    })

@app.route("/get-comparison")
def get_comparison():
    return jsonify({
        "times":      [round(float(T[i]), 3) for i in range(N)],
        "baseline":   [round(float(BASELINE[i]), 2) for i in range(N)],
        "leak_flow":  [round(float(GASKET_FLOW[i]), 2) for i in range(N)],
        "leak_label": "Gasket Leak",
        "high_th":    HIGH_TH,
    })

@app.route("/get-summary")
def get_summary():
    return jsonify({
        "bl_mean":      round(BL_MEAN, 2),
        "bl_std":       round(BL_STD, 2),
        "high_th":      HIGH_TH,
        "low_th":       LOW_TH,
        "gas_diff":     round(float(real_rms["gasket_leak"]["mean"] - real_rms["no_leak"]["mean"]), 2),
        "gas_leak_pct": round(sum(1 for w in WINDOWS["gasket_leak"] if w["status"] == "Leak Detected") / N * 100, 1),
    })

@app.route("/register", methods=["POST"])
def register():
    data     = request.get_json()
    username = data.get("username", "").strip()
    phone    = data.get("phone", "").strip()
    print(f"Received phone: '{phone}'")
    if not username or not phone:
        return jsonify({"error": "Missing fields"}), 400
    registered_phone["number"] = phone
    registered_phone["name"]   = username
    send_sms(phone, f"Hi {username}! You are now registered on AquaTrack. You will receive leak alerts on this number.")
    return jsonify({"success": True, "message": f"Registered {username}"})

@app.route("/contact-sms", methods=["POST"])
def contact_sms():
    data    = request.get_json()
    name    = data.get("name", "")
    phone   = data.get("phone", "")
    message = data.get("message", "")
    if not name or not phone or not message:
        return jsonify({"error": "Missing fields"}), 400
    send_sms(phone, f"AquaTrack Contact: Hi {name}, we received your message: '{message}'. We'll get back to you soon!")
    return jsonify({"success": True})

@app.route("/alert-leak", methods=["POST"])
def alert_leak():
    data = request.get_json()
    t    = data.get("time", "--")
    flow = data.get("flow", "--")
    leak_history.append({
        "time":      t,
        "flow":      flow,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "type":      "Leak Detected"
    })
    if registered_phone["number"]:
        send_sms(registered_phone["number"],
                 f"AquaTrack ALERT: Leak Detected at t={t}s! Flow Activity={flow}. Check your pipeline immediately.")
        return jsonify({"success": True})
    return jsonify({"error": "No registered phone"}), 400

@app.route("/alert-repaired", methods=["POST"])
def alert_repaired():
    """Called when flow returns to normal after a leak — leak is repaired."""
    data = request.get_json()
    t    = data.get("time", "--")
    if registered_phone["number"]:
        send_sms(registered_phone["number"],
                 f"AquaTrack: Pipeline back to NORMAL at t={t}s. Leak appears to be repaired. No further action needed.")
        print(f"Repair SMS sent at t={t}s")
        return jsonify({"success": True})
    return jsonify({"error": "No registered phone"}), 400

@app.route("/get-account")
def get_account():
    return jsonify({
        "name":         registered_phone.get("name", ""),
        "phone":        registered_phone.get("number", ""),
        "leak_history": leak_history
    })

@app.route("/signout", methods=["POST"])
def signout():
    registered_phone["number"] = None
    registered_phone["name"]   = None
    leak_history.clear()
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(debug=True)