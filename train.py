# model/train.py
import os
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, classification_report

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_CSV = os.path.join(ROOT, "dataset", "latency_dataset.csv")
MODEL_PKL = os.path.join(ROOT, "model", "multi_task_model.pkl")
ENC_PKL = os.path.join(ROOT, "model", "label_encoders.pkl")

df = pd.read_csv(DATA_CSV)

# Inputs: the 4 features (we let model predict latency)
X = df[["jitter", "packet_loss", "bandwidth", "signal_strength"]]

# Targets
y_latency = df["latency"]
y_status = df["status"]
y_action = df["action_type"]
y_strength = df["action_strength"]

# Encode categorical outputs
le_status = LabelEncoder().fit(y_status)
le_action = LabelEncoder().fit(y_action)
y_status_enc = le_status.transform(y_status)
y_action_enc = le_action.transform(y_action)

# Train/test split
X_train, X_test, y_lat_train, y_lat_test, y_stat_train, y_stat_test, y_act_train, y_act_test, y_str_train, y_str_test = train_test_split(
    X, y_latency, y_status_enc, y_action_enc, y_strength, test_size=0.2, random_state=42
)

# Models
lat_model = RandomForestRegressor(n_estimators=150, random_state=42)
stat_model = RandomForestClassifier(n_estimators=150, random_state=42)
act_model = RandomForestClassifier(n_estimators=150, random_state=42)
str_model = RandomForestRegressor(n_estimators=150, random_state=42)

print("Training latency regressor...")
lat_model.fit(X_train, y_lat_train)
lat_pred = lat_model.predict(X_test)
print("Latency RMSE:", np.sqrt(mean_squared_error(y_lat_test, lat_pred)))

print("Training status classifier...")
stat_model.fit(X_train, y_stat_train)
stat_pred = stat_model.predict(X_test)
print(classification_report(y_stat_test, stat_pred, target_names=le_status.classes_))

print("Training action classifier...")
act_model.fit(X_train, y_act_train)
act_pred = act_model.predict(X_test)
print(classification_report(y_act_test, act_pred, target_names=le_action.classes_))

print("Training strength regressor...")
str_model.fit(X_train, y_str_train)
str_pred = str_model.predict(X_test)
print("Strength RMSE:", np.sqrt(mean_squared_error(y_str_test, str_pred)))

# Save models and encoders
os.makedirs(os.path.join(ROOT, "model"), exist_ok=True)
joblib.dump({
    "latency": lat_model,
    "status": stat_model,
    "action": act_model,
    "strength": str_model
}, MODEL_PKL)

joblib.dump({
    "status": le_status,
    "action": le_action
}, ENC_PKL)

print("Saved models to", MODEL_PKL)
print("Saved encoders to", ENC_PKL)
