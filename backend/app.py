# backend/app.py
import os
import time
import random
import platform
import subprocess
import joblib
import numpy as np
from threading import Thread
from flask import Flask, request, jsonify
from flask_cors import CORS

# Optional network tools (if installed)
try:
    from ping3 import ping
except Exception:
    ping = None

try:
    import psutil
except Exception:
    psutil = None

app = Flask(__name__)
# be explicit about CORS so frontends on different hosts/phones can reach it
CORS(app, resources={r"/*": {"origins": "*"}})

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_PKL = os.path.join(ROOT, "model", "multi_task_model.pkl")
ENC_PKL = os.path.join(ROOT, "model", "label_encoders.pkl")

# ========== GLOBALS ==========
telemetry_data = []        # queue of simulated or pushed telemetry points (demo + external)
demo_attack_running = False

# Try to load models (if available). If not available, server still runs with heuristics.
models = None
le_status = le_action = None
try:
    models = joblib.load(MODEL_PKL)
    encs = joblib.load(ENC_PKL)
    le_status = encs.get("status")
    le_action = encs.get("action")
    print("✅ Model & encoders loaded.")
except Exception as e:
    print("⚠️ Model load failed or missing — server will use heuristics. (Error:", e, ")")

# ========== UTILITIES ==========
def detect_spike(latency, jitter, latency_threshold=200, jitter_threshold=20):
    return (latency is not None and latency > latency_threshold) or (jitter is not None and jitter > jitter_threshold)

def heuristic_status(lat, jit, pkt_loss, bw, sig):
    if lat is None:
        lat = 999.0
    if pkt_loss > 10 or lat > 800:
        return "Critical"
    if pkt_loss > 3 or lat > 250 or jit > 40 or bw < 3:
        return "Network Congestion"
    if lat > 100 or jit > 15 or bw < 8:
        return "Degraded"
    return "Normal"

SOLUTION_TEMPLATES = {
    "switch_network": [
        "Switch to a stronger network (move closer to AP / use wired).",
        "Switch device to 5GHz Wi-Fi or wired Ethernet.",
        "Disconnect and re-join the network to force a better AP.",
        "Change router channel to avoid interference.",
        "If available, use the higher-throughput SSID."
    ],
    "enable_qos": [
        "Enable QoS and prioritize real-time apps.",
        "Create QoS rule to limit background downloads.",
        "Map real-time traffic to a high-priority queue."
    ],
    "optimize_bandwidth": [
        "Limit background uploads/downloads.",
        "Pause high-bandwidth streams on other devices.",
        "Use bandwidth management tools."
    ],
    "rate_limit": [
        "Enable rate limiting on router and block suspicious IPs.",
        "Apply connection limits to stop flood-style traffic.",
        "Contact ISP for mitigation if attack is sustained."
    ],
    "monitor": [
        "No immediate action — continue monitoring.",
        "Gather longer logs before acting."
    ],
    "default": [
        "Investigate further: collect more telemetry and restart equipment if needed."
    ]
}

def pick_solution_variant(action_key, strength, telemetry):
    pool = SOLUTION_TEMPLATES.get(action_key, SOLUTION_TEMPLATES["default"])
    score = 0.0
    try:
        score += float(strength) if strength is not None else 0.0
    except:
        pass
    score += (telemetry.get("jitter", 0) / 100.0)
    score += (telemetry.get("packet_loss", 0) / 10.0)
    idx = int(abs(hash(str(round(score, 3)))) % len(pool))
    return pool[idx]

def measure_ping_stats_simple(target="8.8.8.8", count=4, timeout=1.0):
    if ping is None:
        return None, None, 100.0, []
    times = []
    lost = 0
    for _ in range(count):
        try:
            t = ping(target, timeout=timeout)
        except Exception:
            t = None
        if t is None:
            lost += 1
        else:
            times.append(t * 1000.0)
        time.sleep(0.02)
    packet_loss = (lost / count) * 100.0
    if not times:
        return None, None, packet_loss, []
    avg = sum(times) / len(times)
    jitter = (sum((x - avg) ** 2 for x in times) / len(times)) ** 0.5
    return avg, jitter, packet_loss, times

def measure_bandwidth_simple(interval=1.0):
    if psutil is None:
        return 0.0
    io1 = psutil.net_io_counters()
    time.sleep(interval)
    io2 = psutil.net_io_counters()
    bytes_sent = io2.bytes_sent - io1.bytes_sent
    bytes_recv = io2.bytes_recv - io1.bytes_recv
    mbps = ((bytes_sent + bytes_recv) * 8) / (interval * 1_000_000)
    return max(0.0, round(mbps, 3))

def get_wifi_signal_strength_simple():
    system = platform.system().lower()
    try:
        if "windows" in system:
            out = subprocess.check_output(
                ["netsh", "wlan", "show", "interfaces"],
                stderr=subprocess.DEVNULL,
                text=True
            )
            for line in out.splitlines():
                if "Signal" in line:
                    return int(line.split(":")[-1].strip().replace("%", ""))
    except Exception:
        pass
    return 0

def detect_ddos_like(telemetry):
    if telemetry.get("packet_loss", 0) > 5.0 and telemetry.get("jitter", 0) > 20:
        return True
    if telemetry.get("bandwidth", 0) < 1.0 and telemetry.get("packet_loss", 0) > 2.0:
        return True
    return False

# ========== ROUTES ==========

@app.route("/", methods=["GET"])
def index():
    return jsonify({"message": "Latency AI backend running. Use /telemetry_local and /predict."}), 200

@app.route("/telemetry_test", methods=["GET"])
def telemetry_test():
    """Quick test endpoint so frontend/devices can confirm connectivity and data shape."""
    now = int(time.time() * 1000)
    sample = {
        "collected_telemetry": {
            "latency_measured": 50.0,
            "jitter_measured": 5.0,
            "packet_loss": 0.1,
            "bandwidth": 50.0,
            "signal_strength": 80,
            "timestamp": now
        },
        "predicted_latency": 48.23,
        "status": "Normal",
        "action_type": "monitor",
        "action_strength": 0.3,
        "solution": "No immediate action — continue monitoring.",
        "alternative_solutions": SOLUTION_TEMPLATES.get("monitor", SOLUTION_TEMPLATES["default"])[:4],
        "spike": False,
        "ddos_suspected": False,
        "timestamp": now
    }
    return jsonify(sample), 200

@app.route("/predict", methods=["POST"])
def predict():
    if models is None:
        return jsonify({"error": "Model not loaded on server"}), 500
    try:
        data = request.get_json(force=True)
        jitter = float(data.get("jitter", 0.0))
        packet_loss = float(data.get("packet_loss", 0.0))
        bandwidth = float(data.get("bandwidth", 0.0))
        signal_strength = float(data.get("signal_strength", 0.0))
        X = np.array([jitter, packet_loss, bandwidth, signal_strength]).reshape(1, -1)

        pred_latency = float(models["latency"].predict(X)[0])
        pred_status_enc = int(models["status"].predict(X)[0])
        pred_action_enc = int(models["action"].predict(X)[0])
        pred_strength = float(models["strength"].predict(X)[0])

        status_text = (
            le_status.inverse_transform([pred_status_enc])[0]
            if le_status is not None
            else heuristic_status(pred_latency, jitter, packet_loss, bandwidth, signal_strength)
        )
        action_text = (
            le_action.inverse_transform([pred_action_enc])[0]
            if le_action is not None
            else "default"
        )

        telemetry = {
            "latency": pred_latency,
            "jitter": jitter,
            "packet_loss": packet_loss,
            "bandwidth": bandwidth,
            "signal_strength": signal_strength
        }
        solution_text = pick_solution_variant(action_text, pred_strength, telemetry)

        spike_flag = detect_spike(pred_latency, jitter)
        ddos_flag = detect_ddos_like(telemetry)

        alt_solutions = SOLUTION_TEMPLATES.get(action_text, SOLUTION_TEMPLATES["default"])[:3]

        return jsonify({
            "telemetry_input": telemetry,
            "predicted_latency": pred_latency,
            "status": status_text,
            "action_type": action_text,
            "action_strength": pred_strength,
            "solution": solution_text,
            "alternative_solutions": alt_solutions,
            "spike": spike_flag,
            "ddos_suspected": ddos_flag
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- NEW: endpoint to receive telemetry from external script ----------
@app.route("/telemetry", methods=["POST"])
def receive_telemetry():
    """
    This is called by telemetry_sender.py.
    It pushes a simplified telemetry point into telemetry_data.
    /telemetry_local will then pick it up and the frontend will see it.
    """
    try:
        data = request.get_json(force=True) or {}

        cpu = float(data.get("cpu", 0.0))
        ram = float(data.get("ram", 0.0))
        jitter = float(data.get("jitter", 0.0))
        packet_loss = float(data.get("packet_loss", 0.0))
        rtt = float(data.get("rtt", 0.0))  # Treat RTT as measured latency (ms)

        # Map incoming fields to the internal format used by telemetry_local
        telemetry_point = {
            "timestamp": time.time(),
            "latency": max(rtt, 0.0),                  # use rtt as latency
            "jitter": max(jitter, 0.0),
            "packet_loss": max(packet_loss, 0.0),
            "bandwidth": 10.0,                         # placeholder bandwidth
            "signal": 70                               # placeholder signal strength
        }

        # Optional: log CPU/RAM for debugging (not used in prediction yet)
        print(f"[telemetry] received from script: cpu={cpu}, ram={ram}, raw={data}")
        telemetry_data.append(telemetry_point)
        print("[telemetry] queued point; queue len:", len(telemetry_data))

        return jsonify({"message": "Telemetry received", "queued_len": len(telemetry_data)}), 200
    except Exception as e:
        print("[telemetry] error:", e)
        return jsonify({"error": str(e)}), 500

# ---------- telemetry_local: PREFER simulated telemetry_data when present ----------
@app.route("/telemetry_local", methods=["GET"])
def telemetry_local():
    try:
        # If simulated/demo or pushed points are in telemetry_data, return them first
        if len(telemetry_data) > 0:
            sim = telemetry_data.pop(0)
            # ensure values exist and are numeric
            telemetry_measured = {
                "latency_measured": float(round(sim.get("latency", 999.0), 3)),
                "jitter_measured": float(round(sim.get("jitter", 0.0), 3)),
                "packet_loss": float(round(sim.get("packet_loss", 0.0), 3)),
                "bandwidth": float(round(sim.get("bandwidth", 0.0), 3)),
                "signal_strength": float(sim.get("signal", sim.get("signal_strength", 0))),
                "timestamp": int(time.time() * 1000)
            }

            # If model exists, predict using model input; else use measured latency as predicted_latency
            if models is not None:
                X = np.array([
                    telemetry_measured["jitter_measured"],
                    telemetry_measured["packet_loss"],
                    telemetry_measured["bandwidth"],
                    telemetry_measured["signal_strength"]
                ]).reshape(1, -1)
                pred_latency = float(models["latency"].predict(X)[0])
                pred_status_enc = int(models["status"].predict(X)[0])
                pred_action_enc = int(models["action"].predict(X)[0])
                pred_strength = float(models["strength"].predict(X)[0])
                status_text = (
                    le_status.inverse_transform([pred_status_enc])[0]
                    if le_status is not None
                    else heuristic_status(
                        pred_latency,
                        telemetry_measured["jitter_measured"],
                        telemetry_measured["packet_loss"],
                        telemetry_measured["bandwidth"],
                        telemetry_measured["signal_strength"]
                    )
                )
                action_text = (
                    le_action.inverse_transform([pred_action_enc])[0]
                    if le_action is not None
                    else "default"
                )
            else:
                pred_latency = telemetry_measured["latency_measured"]
                status_text = heuristic_status(
                    pred_latency,
                    telemetry_measured["jitter_measured"],
                    telemetry_measured["packet_loss"],
                    telemetry_measured["bandwidth"],
                    telemetry_measured["signal_strength"]
                )
                action_text = "default"
                pred_strength = 0.5

            solution_text = pick_solution_variant(
                action_text,
                pred_strength if 'pred_strength' in locals() else 0.5,
                telemetry_measured
            )
            spike_flag = detect_spike(pred_latency, telemetry_measured["jitter_measured"])
            ddos_flag = detect_ddos_like(telemetry_measured)

            # debug log
            print("[telemetry_local] served queued point:", telemetry_measured,
                  "pred_latency:", pred_latency, "spike:", spike_flag, "ddos:", ddos_flag)

            return jsonify({
                "collected_telemetry": telemetry_measured,
                "predicted_latency": pred_latency,
                "status": status_text,
                "action_type": action_text,
                "action_strength": pred_strength if 'pred_strength' in locals() else 0.5,
                "solution": solution_text,
                "alternative_solutions": SOLUTION_TEMPLATES.get(action_text, SOLUTION_TEMPLATES["default"])[:4],
                "spike": spike_flag,
                "ddos_suspected": ddos_flag,
                "timestamp": telemetry_measured["timestamp"]
            }), 200

        # --- otherwise measure live telemetry from the device running backend ---
        avg_latency, jitter_ms, packet_loss_pct, _ = measure_ping_stats_simple(count=5)
        bandwidth_mbps = measure_bandwidth_simple(interval=1.0)
        signal_strength = get_wifi_signal_strength_simple()
        if avg_latency is None:
            avg_latency, jitter_ms = 999.0, 999.0

        telemetry_measured = {
            "latency_measured": float(round(avg_latency, 3)),
            "jitter_measured": float(round(jitter_ms or 0.0, 3)),
            "packet_loss": float(round(packet_loss_pct, 3)),
            "bandwidth": float(round(bandwidth_mbps, 3)),
            "signal_strength": signal_strength or 0.0,
            "timestamp": int(time.time() * 1000)
        }

        # Model input is jitter, packet_loss, bandwidth, signal_strength
        if models is not None:
            X = np.array([
                telemetry_measured["jitter_measured"],
                telemetry_measured["packet_loss"],
                telemetry_measured["bandwidth"],
                telemetry_measured["signal_strength"]
            ]).reshape(1, -1)
            pred_latency = float(models["latency"].predict(X)[0])
            pred_status_enc = int(models["status"].predict(X)[0])
            pred_action_enc = int(models["action"].predict(X)[0])
            pred_strength = float(models["strength"].predict(X)[0])
            status_text = (
                le_status.inverse_transform([pred_status_enc])[0]
                if le_status is not None
                else heuristic_status(
                    pred_latency,
                    telemetry_measured["jitter_measured"],
                    telemetry_measured["packet_loss"],
                    telemetry_measured["bandwidth"],
                    telemetry_measured["signal_strength"]
                )
            )
            action_text = (
                le_action.inverse_transform([pred_action_enc])[0]
                if le_action is not None
                else "default"
            )
        else:
            pred_latency = telemetry_measured["latency_measured"]
            status_text = heuristic_status(
                pred_latency,
                telemetry_measured["jitter_measured"],
                telemetry_measured["packet_loss"],
                telemetry_measured["bandwidth"],
                telemetry_measured["signal_strength"]
            )
            action_text = "default"
            pred_strength = 0.5

        solution_text = pick_solution_variant(
            action_text,
            pred_strength if 'pred_strength' in locals() else 0.5,
            telemetry_measured
        )
        spike_flag = detect_spike(pred_latency, telemetry_measured["jitter_measured"])
        ddos_flag = detect_ddos_like(telemetry_measured)

        print("[telemetry_local] served live telemetry:", telemetry_measured,
              "pred_latency:", pred_latency)

        return jsonify({
            "collected_telemetry": telemetry_measured,
            "predicted_latency": pred_latency,
            "status": status_text,
            "action_type": action_text,
            "action_strength": pred_strength if 'pred_strength' in locals() else 0.5,
            "solution": solution_text,
            "alternative_solutions": SOLUTION_TEMPLATES.get(action_text, SOLUTION_TEMPLATES["default"])[:4],
            "spike": spike_flag,
            "ddos_suspected": ddos_flag,
            "timestamp": telemetry_measured["timestamp"]
        }), 200

    except Exception as e:
        print("[telemetry_local] error:", e)
        return jsonify({"error": str(e)}), 500

# ========== Demo triggers: add simulated points into telemetry_data ==========
@app.route("/trigger_ddos_demo", methods=["POST"])
def trigger_ddos_demo():
    """Add several high-latency simulated points (instant attack)."""
    def simulate_ddos_points():
        print("[demo] starting ddos simulation")
        for _ in range(10):  # 10 simulated points, one per second
            telemetry_data.append({
                "timestamp": time.time(),
                "latency": random.uniform(600, 1200),
                "jitter": random.uniform(200, 600),
                "packet_loss": random.uniform(10, 30),
                "bandwidth": random.uniform(0.05, 1.0),
                "signal": random.randint(30, 80)
            })
            print("[demo] appended ddos point; queue len:", len(telemetry_data))
            time.sleep(1)
        print("[demo] finished ddos simulation")

    Thread(target=simulate_ddos_points, daemon=True).start()
    return jsonify({"message": "DDoS demo triggered (10 simulated points)."}), 200

@app.route("/trigger_ramp_attack", methods=["POST"])
def trigger_ramp_attack():
    """Add gradually worsening points (ramp simulation)."""
    def simulate_ramp_points():
        print("[demo] starting ramp simulation")
        for i in range(12):  # 12 points, gradually worse
            telemetry_data.append({
                "timestamp": time.time(),
                "latency": 100 + i * 50,
                "jitter": 20 + i * 15,
                "packet_loss": min(i * 2, 30),
                "bandwidth": max(10 - i * 0.8, 0.1),
                "signal": random.randint(30, 80)
            })
            print("[demo] appended ramp point; queue len:", len(telemetry_data))
            time.sleep(1)
        print("[demo] finished ramp simulation")

    Thread(target=simulate_ramp_points, daemon=True).start()
    return jsonify({"message": "Ramp attack demo triggered (12 simulated points)."}), 200

# Simple suggestions endpoint (used by frontend "Get Suggestions" button)
@app.route("/suggest_mitigation", methods=["POST"])
def suggest_mitigation():
    try:
        data = request.get_json(silent=True) or {}
        jitter = float(data.get("jitter", 0.0))
        packet_loss = float(data.get("packet_loss", 0.0))
        bandwidth = float(data.get("bandwidth", 0.0))
        signal_strength = float(data.get("signal_strength", 0.0))
        suggestions = []
        if packet_loss > 5.0:
            suggestions.append("Check cables and limit heavy traffic on the local LAN.")
        if jitter > 20:
            suggestions.append("Enable QoS and prioritize latency-sensitive traffic.")
        if bandwidth < 5.0:
            suggestions.append("Reduce background transfers and lower streaming quality.")
        if signal_strength and signal_strength < 30:
            suggestions.append("Move device closer to Wi-Fi access point or use wired connection.")
        if not suggestions:
            suggestions.append("No urgent actions. Continue monitoring.")
        return jsonify({"suggestions": suggestions}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Run
if __name__ == "__main__":
    print("🚀 Flask server running on http://0.0.0.0:5000")
    # Use threaded=True so background demo threads can run concurrently with request handling.
    # Bind to 0.0.0.0 so other devices on LAN can reach the server (use your machine IP in frontend).
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
