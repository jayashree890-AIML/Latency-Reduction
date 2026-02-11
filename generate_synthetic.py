"""
Generates a synthetic telemetry dataset for the AI latency project.

Outputs:
  dataset/latency_dataset.csv

Columns:
  latency (target), jitter, packet_loss, bandwidth, signal_strength (inputs),
  status (classification), action_type, action_strength
"""

import os
import random
import numpy as np
import pandas as pd

# Output path
OUT_DIR = os.path.join(os.path.dirname(__file__))
OUT_CSV = os.path.join(OUT_DIR, "latency_dataset.csv")

# Deterministic randomness for reproducibility
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

# Number of samples per network condition
SAMPLES_PER_CLASS = 1000

# Clamp helper (prevents out-of-range values)
def clamp(x, low, high):
    return max(low, min(high, x))

# --- NETWORK CONDITION GENERATORS ---

def generate_normal():
    latency = np.random.normal(loc=30, scale=8)
    jitter = np.random.normal(loc=2, scale=1)
    packet_loss = abs(np.random.normal(loc=0.2, scale=0.4))
    bandwidth = np.random.normal(loc=40, scale=8)
    signal_strength = np.random.normal(loc=-45, scale=5)
    return latency, jitter, packet_loss, bandwidth, signal_strength

def generate_congestion():
    latency = np.random.normal(loc=140, scale=30)
    jitter = np.random.normal(loc=12, scale=6)
    packet_loss = abs(np.random.normal(loc=1.5, scale=1.0))
    bandwidth = np.random.normal(loc=18, scale=6)
    signal_strength = np.random.normal(loc=-65, scale=6)
    return latency, jitter, packet_loss, bandwidth, signal_strength

def generate_bandwidth_issue():
    latency = np.random.normal(loc=160, scale=25)
    jitter = np.random.normal(loc=10, scale=4)
    packet_loss = abs(np.random.normal(loc=1.0, scale=0.8))
    bandwidth = np.random.normal(loc=12, scale=4)
    signal_strength = np.random.normal(loc=-70, scale=5)
    return latency, jitter, packet_loss, bandwidth, signal_strength

def generate_ddos():
    latency = np.random.normal(loc=300, scale=80)
    jitter = np.random.normal(loc=40, scale=20)
    packet_loss = abs(np.random.normal(loc=5.0, scale=3.0))
    bandwidth = np.random.normal(loc=6, scale=3)
    signal_strength = np.random.normal(loc=-85, scale=6)
    return latency, jitter, packet_loss, bandwidth, signal_strength

# --- ACTION MAPPING ---
SOLUTION_TO_ACTION = {
    "Network stable": ("monitor", 0.0),
    "Switch to stronger network": ("switch_network", 0.8),
    "Optimize bandwidth allocation": ("optimize_bandwidth", 0.7),
    "Enable rate limiting on router": ("rate_limit", 0.9),
}

# --- ROW GENERATOR FUNCTION ---
def row_from_generator(gen_fn, status_label, solution_label, n):
    rows = []
    for _ in range(n):
        latency, jitter, packet_loss, bandwidth, signal_strength = gen_fn()

        latency = clamp(float(round(latency, 2)), 1.0, 5000.0)
        jitter = clamp(float(round(jitter, 2)), 0.0, 1000.0)
        packet_loss = clamp(float(round(packet_loss, 3)), 0.0, 100.0)
        bandwidth = clamp(float(round(bandwidth, 2)), 0.1, 1000.0)
        signal_strength = clamp(float(round(signal_strength, 2)), -130.0, -10.0)

        # Convert solution → AI-driven action
        action_type, base_strength = SOLUTION_TO_ACTION[solution_label]
        # Add light randomness for realism
        action_strength = max(0.0, min(1.0, base_strength + random.uniform(-0.05, 0.05)))

        # Build the dataset row
        rows.append({
            "latency": latency,
            "jitter": jitter,
            "packet_loss": packet_loss,
            "bandwidth": bandwidth,
            "signal_strength": signal_strength,
            "status": status_label,
            "action_type": action_type,
            "action_strength": action_strength
        })
    return rows

# --- MAIN DATASET CREATOR ---
def generate_dataset(samples_per_class=SAMPLES_PER_CLASS):
    rows = []
    rows += row_from_generator(generate_normal, "Normal", "Network stable", samples_per_class)
    rows += row_from_generator(generate_congestion, "Network Congestion", "Switch to stronger network", samples_per_class)
    rows += row_from_generator(generate_bandwidth_issue, "Bandwidth Issue", "Optimize bandwidth allocation", samples_per_class)
    rows += row_from_generator(generate_ddos, "DDoS Attack Detected", "Enable rate limiting on router", samples_per_class)

    df = pd.DataFrame(rows)
    df = df.sample(frac=1, random_state=RANDOM_SEED).reset_index(drop=True)
    return df

# --- RUN ---
def main():
    print("Generating synthetic dataset... (this may take a few seconds)")
    df = generate_dataset()
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"✅ Saved dataset to: {OUT_CSV}")
    print("📊 Preview:")
    print(df.head(8).to_string(index=False))

if __name__ == "__main__":
    main()
