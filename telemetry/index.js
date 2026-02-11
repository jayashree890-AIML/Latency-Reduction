// TelemetryScreen.js
import React, { useState, useEffect, useRef } from "react";
import {
  View, Text, Button, ScrollView, StyleSheet,
  Dimensions, TouchableOpacity, Modal, Alert
} from "react-native";
import { LineChart } from "react-native-chart-kit";

// 👇 IMPORTANT: use the IP that your Flask backend shows in the terminal
// Example from your logs: * Running on http://10.199.28.136:5000
const BACKEND_HOST = "10.80.107.136:5000";
 // <--- CHANGE ONLY THIS LINE IF IP CHANGES

const TELEMETRY_LOCAL_URL = `http://${BACKEND_HOST}/telemetry_local`;
const SUGGEST_URL = `http://${BACKEND_HOST}/suggest_mitigation`;
const TRIGGER_DDOS = `http://${BACKEND_HOST}/trigger_ddos_demo`;
const TRIGGER_RAMP = `http://${BACKEND_HOST}/trigger_ramp_attack`;

async function postJson(url, body = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export default function TelemetryScreen() {
  const [history, setHistory] = useState([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [selectedPointIdx, setSelectedPointIdx] = useState(null);
  const [selectedPointSuggestions, setSelectedPointSuggestions] = useState(null);
  const [selectedPointLoading, setSelectedPointLoading] = useState(false);
  const [running, setRunning] = useState(true);
  const pollingRef = useRef(null);
  const [simulating, setSimulating] = useState(false);

  // Poll telemetry_local every 3s
  const fetchTelemetryOnce = async () => {
    try {
      console.log("Fetching telemetry from:", TELEMETRY_LOCAL_URL);
      const res = await fetch(TELEMETRY_LOCAL_URL);
      const d = await res.json();
      if (d && !d.error) {
        // normalize point
        const point = {
          timestamp: d.timestamp || Date.now(),
          latency:
            d.predicted_latency ??
            d.predictedLatency ??
            (d.collected_telemetry && d.collected_telemetry.latency_measured) ??
            0,
          spike: !!d.spike,
          ddos_suspected: !!d.ddos_suspected,
          status: d.status || "Unknown",
          solution: d.solution || "",
          alternative_solutions: d.alternative_solutions || [],
          collected_telemetry: d.collected_telemetry || d.telemetry_input || {}
        };
        setHistory(prev => {
          const next = [...prev, point];
          if (next.length > 120) next.shift();
          return next;
        });
      } else {
        // could log error if needed
        if (d && d.error) {
          console.warn("Telemetry error from backend:", d.error);
        }
      }
    } catch (e) {
      console.warn("Telemetry fetch failed:", e);
    }
  };

  useEffect(() => {
    fetchTelemetryOnce();
    pollingRef.current = setInterval(() => {
      if (running) fetchTelemetryOnce();
    }, 3000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [running]);

  // Open point modal
  const openPoint = (idx) => {
    setSelectedPointIdx(idx);
    setSelectedPointSuggestions(null); // reset suggestions for this point
    setModalVisible(true);
  };

  const closeModal = () => {
    setModalVisible(false);
    setSelectedPointIdx(null);
    setSelectedPointSuggestions(null);
  };

  // Fetch suggestions for a specific point's telemetry (called only when user clicks)
  const fetchSuggestionsForPoint = async (point) => {
    setSelectedPointLoading(true);
    try {
      // Use collected telemetry if available; fallback to model inputs
      const telemetry = {
        jitter: point.collected_telemetry?.jitter_measured ?? point.collected_telemetry?.jitter ?? 0,
        packet_loss: point.collected_telemetry?.packet_loss ?? 0,
        bandwidth: point.collected_telemetry?.bandwidth ?? 0,
        signal_strength: point.collected_telemetry?.signal_strength ?? point.collected_telemetry?.signal ?? 0
      };
      const res = await postJson(SUGGEST_URL, telemetry);
      if (res && res.suggestions) {
        setSelectedPointSuggestions(res.suggestions);
      } else if (res && res.error) {
        setSelectedPointSuggestions([`Error: ${res.error}`]);
      } else {
        setSelectedPointSuggestions(["No suggestions returned."]);
      }
    } catch (e) {
      setSelectedPointSuggestions([`Request failed: ${String(e)}`]);
    } finally {
      setSelectedPointLoading(false);
    }
  };

  // Demo triggers
  const triggerDemo = async (type) => {
    if (simulating) return;
    setSimulating(true);
    try {
      const url = type === "ddos" ? TRIGGER_DDOS : TRIGGER_RAMP;
      await postJson(url, {}); // backend will start background simulation
      Alert.alert("Demo", type === "ddos" ? "DDoS demo triggered" : "Ramp demo triggered");
    } catch (e) {
      Alert.alert("Error", String(e));
    }
    setSimulating(false);
  };

  // Chart data
  const chartData = {
    labels: history.map((_, i) => `${i + 1}`),
    datasets: [{ data: history.map(h => Number(h.latency) || 0) }],
  };

  const selectedPoint = selectedPointIdx !== null ? history[selectedPointIdx] : null;
  const latest = history.length ? history[history.length - 1] : null;

  return (
    <ScrollView style={styles.container}>
      <Text style={styles.title}>Telemetry Dashboard</Text>

      <View style={styles.controls}>
        <TouchableOpacity
          onPress={() => setRunning(r => !r)}
          style={[styles.controlBtn, running ? styles.btnActive : styles.btnIdle]}
        >
          <Text style={styles.controlText}>{running ? "Pause" : "Play"}</Text>
        </TouchableOpacity>

        <TouchableOpacity onPress={() => triggerDemo("ddos")} style={[styles.controlBtn, styles.btnDemo]}>
          <Text style={styles.controlText}>Demo: Instant Attack</Text>
        </TouchableOpacity>

        <TouchableOpacity onPress={() => triggerDemo("ramp")} style={[styles.controlBtn, styles.btnDemo]}>
          <Text style={styles.controlText}>Demo: Ramp Attack</Text>
        </TouchableOpacity>
      </View>

      {latest && latest.ddos_suspected && (
        <View style={styles.ddosBanner}>
          <Text style={styles.ddosText}>⚠️ DDoS Suspected — Investigate</Text>
        </View>
      )}

      <View style={styles.chartContainer}>
        <Text style={styles.subtitle}>Predicted Latency (ms)</Text>
        {history.length > 0 ? (
          <LineChart
            data={chartData}
            width={Dimensions.get("window").width - 20}
            height={200}
            chartConfig={{
              backgroundGradientFrom: "#0b0b0c",
              backgroundGradientTo: "#0b0b0c",
              decimalPlaces: 2,
              color: (opacity = 1) => `rgba(0,255,234,${opacity})`,
              labelColor: (opacity = 1) => `rgba(200,200,200,${opacity})`,
            }}
            bezier
            style={{ borderRadius: 8 }}
          />
        ) : (
          <Text style={styles.small}>Waiting for telemetry...</Text>
        )}
      </View>

      <ScrollView horizontal style={styles.pointsRow} contentContainerStyle={{ paddingHorizontal: 8 }}>
        {history.map((p, i) => {
          const cls = p.ddos_suspected
            ? styles.pointDdos
            : p.spike
            ? styles.pointSpike
            : styles.pointNormal;
          return (
            <TouchableOpacity key={i} onPress={() => openPoint(i)} style={[styles.pointButton, cls]}>
              <Text style={styles.pointText}>{i + 1}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      <View style={styles.summary}>
        <Text style={styles.smallBold}>Latest</Text>
        {latest ? (
          <>
            <Text style={styles.small}>
              Measured Latency: {latest.collected_telemetry?.latency_measured ?? "-"} ms
            </Text>
            <Text style={styles.small}>
              Predicted Latency: {Number(latest.latency ?? 0).toFixed(2)} ms
            </Text>
            <Text style={styles.small}>Status: {latest.status}</Text>
            <Text style={styles.small}>Solution: {latest.solution}</Text>

            <View style={{ marginTop: 8 }}>
              <Button
                title="Get Suggestions for Latest"
                onPress={() => {
                  if (!latest) return;
                  setSelectedPointIdx(history.length - 1);
                  setModalVisible(true);
                  setSelectedPointSuggestions(null);
                  fetchSuggestionsForPoint(latest);
                }}
              />
            </View>
          </>
        ) : (
          <Text style={styles.small}>No data yet</Text>
        )}
      </View>

      {/* Modal for point details */}
      <Modal visible={modalVisible} animationType="slide" onRequestClose={closeModal}>
        <ScrollView style={{ padding: 16, backgroundColor: "#0b0b0c", flex: 1 }}>
          <Text style={{ fontSize: 18, color: "#fff", fontWeight: "700" }}>
            Point details (#{selectedPointIdx !== null ? selectedPointIdx + 1 : "-"})
          </Text>
          <View style={{ height: 8 }} />

          {selectedPoint ? (
            <View>
              <View
                style={[
                  styles.header,
                  selectedPoint.ddos_suspected
                    ? styles.ddosHeader
                    : selectedPoint.spike
                    ? styles.spikeHeader
                    : styles.normalHeader
                ]}
              >
                <Text style={{ color: "#fff", fontWeight: "800" }}>
                  {selectedPoint.ddos_suspected
                    ? "🚨 DDoS ALERT"
                    : selectedPoint.spike
                    ? "⚠️ Spike / Congestion"
                    : "✅ Normal"}
                </Text>
                <Text style={{ color: "#fff", opacity: 0.9 }}>{selectedPoint.status}</Text>
              </View>

              <Text style={styles.smallBold}>Timestamp</Text>
              <Text style={styles.small}>{new Date(selectedPoint.timestamp).toLocaleString()}</Text>

              <Text style={styles.smallBold}>Measured Telemetry</Text>
              <Text style={styles.small}>
                Latency: {selectedPoint.collected_telemetry?.latency_measured ?? "-"} ms
              </Text>
              <Text style={styles.small}>
                Jitter: {selectedPoint.collected_telemetry?.jitter_measured ?? "-"} ms
              </Text>
              <Text style={styles.small}>
                Packet Loss: {selectedPoint.collected_telemetry?.packet_loss ?? "-"} %
              </Text>
              <Text style={styles.small}>
                Bandwidth: {selectedPoint.collected_telemetry?.bandwidth ?? "-"} Mbps
              </Text>
              <Text style={styles.small}>
                Signal:{" "}
                {selectedPoint.collected_telemetry?.signal_strength ??
                  selectedPoint.collected_telemetry?.signal ??
                  "-"}
              </Text>

              <Text style={styles.smallBold}>Model</Text>
              <Text style={styles.small}>
                Predicted Latency: {Number(selectedPoint.latency).toFixed(2)} ms
              </Text>
              <Text style={styles.small}>Status (model): {selectedPoint.status}</Text>
              <Text style={styles.small}>Chosen Solution: {selectedPoint.solution}</Text>

              <View style={{ height: 10 }} />

              <Text style={styles.smallBold}>Alternative Solutions</Text>
              {selectedPoint.alternative_solutions &&
                selectedPoint.alternative_solutions.map((s, i) => (
                  <Text key={i} style={styles.small}>
                    • {s}
                  </Text>
                ))}

              <View style={{ height: 10 }} />
              <Button
                title={
                  selectedPointLoading
                    ? "Getting Suggestions..."
                    : selectedPointSuggestions
                    ? "Refresh Suggestions"
                    : "Get Suggestions"
                }
                onPress={() => fetchSuggestionsForPoint(selectedPoint)}
                disabled={selectedPointLoading}
              />

              <View style={{ height: 12 }} />
              {selectedPointSuggestions && (
                <>
                  <Text style={styles.smallBold}>Suggested Actions</Text>
                  {selectedPointSuggestions.map((s, i) => (
                    <Text key={i} style={styles.small}>
                      • {s}
                    </Text>
                  ))}
                </>
              )}

              <View style={{ height: 12 }} />
              <Button title="Close" onPress={closeModal} />
            </View>
          ) : (
            <Text style={styles.small}>No point selected.</Text>
          )}
        </ScrollView>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 10, backgroundColor: "#0b0b0c" },
  title: { fontSize: 22, color: "#fff", fontWeight: "700" },
  controls: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 10,
    marginBottom: 10
  },
  controlBtn: {
    padding: 10,
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 120
  },
  controlText: { color: "#fff", fontWeight: "700" },
  btnActive: { backgroundColor: "#ff6b6b" },
  btnIdle: { backgroundColor: "#2b7a78" },
  btnDemo: { backgroundColor: "#007acc" },
  ddosBanner: {
    padding: 12,
    borderRadius: 8,
    marginBottom: 10,
    backgroundColor: "#ff3b3b"
  },
  ddosText: { color: "#fff", fontSize: 16, fontWeight: "800", textAlign: "center" },
  chartContainer: { marginTop: 8 },
  subtitle: { color: "#fff", marginBottom: 8 },
  pointsRow: { marginTop: 10, height: 46 },
  pointButton: {
    width: 38,
    height: 38,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    marginHorizontal: 6
  },
  pointText: { color: "#fff", fontWeight: "700" },
  pointNormal: { backgroundColor: "#2b7a78" },
  pointSpike: { backgroundColor: "#ff8b2b" },
  pointDdos: { backgroundColor: "#ff3b3b" },
  summary: { marginTop: 12 },
  small: { color: "#ddd", fontSize: 13, marginTop: 4 },
  smallBold: { color: "#fff", fontSize: 13, fontWeight: "700", marginTop: 6 },
  header: { padding: 8, borderRadius: 6, marginVertical: 6 },
  ddosHeader: { backgroundColor: "#b00020" },
  spikeHeader: { backgroundColor: "#ff8b2b" },
  normalHeader: { backgroundColor: "#2b7a78" }
});

