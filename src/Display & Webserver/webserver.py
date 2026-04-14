"""
PTT Web Server v8.4 – with Real-time Waveforms
Fixed Syntax + Full Dashboard
"""

from pyngrok import ngrok
import json, os, time, socket
from flask import Flask, jsonify, render_template_string, make_response

app = Flask(__name__)
VITALS_FILE = "vitals_state.json"

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Biomedical Monitor</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;400;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg:#080b10; --surface:#0d1117; --border:#1c2230; --green:#39d353; 
    --red:#ff5555; --amber:#e3b341; --blue:#79c0ff; --purple:#d2a8ff; 
    --cyan:#00ffff; --text:#c9d1d9; --muted:#8b949e;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:'Exo 2',sans-serif;min-height:100vh;}
  header{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;
    padding:14px 20px;border-bottom:1px solid var(--border);background:rgba(13,17,23,.95);}
  .logo{font-family:'Share Tech Mono';font-size:13px;letter-spacing:3px;color:var(--green);}
  #conn-badge{font-family:monospace;font-size:11px;padding:4px 12px;border-radius:20px;
    border:1px solid #4a5568;color:#4a5568;transition:all .3s;}
  #conn-badge.live{color:var(--green);border-color:var(--green);}

  .vitals-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px;}
  .vital-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;
    padding:14px 16px;position:relative;}
  .vital-label{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:6px;}
  .vital-value{font-family:'Share Tech Mono';font-size:38px;line-height:1;color:var(--accent,var(--green));}
  .vital-value.small{font-size:28px;}
  .vital-unit{font-size:10px;color:var(--muted);margin-top:4px;}

  .battery-panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;
    padding:12px 16px;margin-bottom:14px;display:flex;align-items:center;gap:12px;}
  .battery-cell{flex:1;text-align:center;}
  .battery-cell .bc-label{font-size:8.5px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);}
  .battery-cell .bc-value{font-family:'Share Tech Mono';font-size:16px;color:var(--cyan);}

  .panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-bottom:14px;}
  .panel-title{font-size:9px;letter-spacing:2.5px;text-transform:uppercase;color:var(--muted);margin-bottom:12px;}
  .metrics-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;}
  .metric-cell{background:rgba(0,0,0,.3);border:1px solid var(--border);border-radius:6px;padding:8px 10px;}
  .metric-cell .mc-label{font-size:8.5px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);}
  .metric-cell .mc-value{font-family:'Share Tech Mono';font-size:15px;color:var(--text);}

  #alerts-box{background:var(--surface);border:1px solid var(--border);border-radius:10px;
    padding:12px 16px;margin-bottom:14px;font-family:monospace;font-size:12px;min-height:40px;}
  #alerts-box.ok{color:var(--green);}
  #alerts-box.warn{color:var(--red);background:rgba(255,85,85,.06);}

  .wave-container{background:var(--surface);border:1px solid var(--border);border-radius:10px;
    padding:12px;margin-bottom:14px;}
  .wave-title{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:8px;}
  canvas{width:100% !important;height:160px !important;}
</style>
</head>
<body>
<header>
  <div class="logo">PTT // Biomedical Monitor</div>
  <div id="conn-badge">● OFFLINE</div>
</header>

<main style="padding:18px 16px;max-width:860px;margin:0 auto;">
  <div id="last-update" style="font-size:10px;color:var(--muted);text-align:right;margin-bottom:12px;">last update: —</div>

  <div class="vitals-grid">
    <div class="vital-card" style="--accent:var(--green)">
      <div class="vital-label">HEART RATE</div>
      <div class="vital-value" id="v-hr">---</div>
      <div class="vital-unit">bpm</div>
    </div>
    <div class="vital-card" style="--accent:#ff7b72">
      <div class="vital-label">BLOOD PRESSURE</div>
      <div class="vital-value small" id="v-bp">---/---</div>
      <div class="vital-unit">mmHg (estimated)</div>
    </div>
    <div class="vital-card" style="--accent:var(--blue)">
      <div class="vital-label">PULSE WAVE VELOCITY</div>
      <div class="vital-value" id="v-pwv">---</div>
      <div class="vital-unit">m/s</div>
    </div>
    <div class="vital-card" style="--accent:var(--purple)">
      <div class="vital-label">AVERAGE PTT</div>
      <div class="vital-value" id="v-ptt">---</div>
      <div class="vital-unit">ms</div>
    </div>
  </div>

  <div class="battery-panel">
    <div style="font-size:24px;">🔋</div>
    <div style="flex:1;display:flex;">
      <div class="battery-cell"><div class="bc-label">VOLTAGE</div><div class="bc-value" id="b-v">-- V</div></div>
      <div class="battery-cell"><div class="bc-label">CURRENT</div><div class="bc-value" id="b-i">-- mA</div></div>
      <div class="battery-cell"><div class="bc-label">POWER</div><div class="bc-value" id="b-p">-- mW</div></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-title">ECG MORPHOLOGY & HRV — 10s WINDOW</div>
    <div class="metrics-grid">
      <div class="metric-cell"><div class="mc-label">SDNN</div><div class="mc-value" id="m-sdnn">—</div></div>
      <div class="metric-cell"><div class="mc-label">RMSSD</div><div class="mc-value" id="m-rmssd">—</div></div>
      <div class="metric-cell"><div class="mc-label">pNN50</div><div class="mc-value" id="m-pnn50">—</div></div>
      <div class="metric-cell"><div class="mc-label">RHYTHM</div><div class="mc-value" id="m-reg">—</div></div>
      <div class="metric-cell"><div class="mc-label">QRS</div><div class="mc-value" id="m-qrs">—</div></div>
      <div class="metric-cell"><div class="mc-label">PR</div><div class="mc-value" id="m-pr">—</div></div>
      <div class="metric-cell"><div class="mc-label">QTc</div><div class="mc-value" id="m-qtc">—</div></div>
      <div class="metric-cell"><div class="mc-label">ST OFF</div><div class="mc-value" id="m-st">—</div></div>
    </div>
  </div>

  <div id="alerts-box" class="ok">✓ No clinical flags detected.</div>

  <!-- Waveforms -->
  <div class="wave-container">
    <div class="wave-title">ECG — Live</div>
    <canvas id="chart-ecg"></canvas>
  </div>
  <div class="wave-container">
    <div class="wave-title">APW1 — Foot Detection</div>
    <canvas id="chart-apw1"></canvas>
  </div>
  <div class="wave-container">
    <div class="wave-title">APW2 — Trough Detection</div>
    <canvas id="chart-apw2"></canvas>
  </div>
</main>

<script>
const $ = id => document.getElementById(id);
let chartECG, chartAPW1, chartAPW2;

function createChart(canvasId, color) {
  const ctx = $(canvasId).getContext('2d');
  return new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{ data: [], borderColor: color, borderWidth: 2.5, tension: 0.25, pointRadius: 0 }] },
    options: { 
      animation: false, 
      scales: { x: { display: false }, y: { display: true, grid: { color: '#1c2230' } } },
      plugins: { legend: { display: false } },
      maintainAspectRatio: false
    }
  });
}

chartECG = createChart('chart-ecg', '#39d353');
chartAPW1 = createChart('chart-apw1', '#e3b341');
chartAPW2 = createChart('chart-apw2', '#d2a8ff');

async function poll() {
  try {
    const r = await fetch('/api/vitals');
    if (!r.ok) throw new Error();
    const d = await r.json();

    // Connection status
    const badge = $('conn-badge');
    badge.textContent = d.connected ? '● LIVE' : '● OFFLINE';
    badge.className = d.connected ? 'live' : '';

    // Vitals
    $('v-hr').textContent = d.hr ?? '---';
    $('v-bp').textContent = d.bp ?? '---/---';
    $('v-pwv').textContent = d.pwv ?? '---';
    $('v-ptt').textContent = d.ptt ?? '---';

    // Battery
    $('b-v').textContent = d.v_bus != null ? d.v_bus.toFixed(2) + ' V' : '-- V';
    $('b-i').textContent = d.i_ma != null ? d.i_ma.toFixed(1) + ' mA' : '-- mA';
    $('b-p').textContent = d.p_mw != null ? d.p_mw.toFixed(1) + ' mW' : '-- mW';

    // Morphology
    $('m-sdnn').textContent = d.sdnn ? d.sdnn + ' ms' : '—';
    $('m-rmssd').textContent = d.rmssd ? d.rmssd + ' ms' : '—';
    $('m-pnn50').textContent = d.pnn50 ? d.pnn50 + ' %' : '—';
    $('m-reg').textContent = d.reg ?? '—';
    $('m-qrs').textContent = d.qrs ? d.qrs + ' ms' : '—';
    $('m-pr').textContent = d.pr ? d.pr + ' ms' : '—';
    $('m-qtc').textContent = d.qtc ? d.qtc + ' ms' : '—';
    $('m-st').textContent = d.st ?? '—';

    // Alerts
    const ab = $('alerts-box');
    if (d.alerts && d.alerts.length > 0) {
      ab.textContent = d.alerts.join(' | ');
      ab.className = 'warn';
    } else {
      ab.textContent = '✓ No clinical flags detected.';
      ab.className = 'ok';
    }

    // Waveforms
    if (d.wave_ecg && d.wave_ecg.length > 0) {
      chartECG.data.labels = Array.from({length: d.wave_ecg.length}, (_,i) => i);
      chartECG.data.datasets[0].data = d.wave_ecg;
      chartECG.update('none');
    }
    if (d.wave_apw1 && d.wave_apw1.length > 0) {
      chartAPW1.data.labels = Array.from({length: d.wave_apw1.length}, (_,i) => i);
      chartAPW1.data.datasets[0].data = d.wave_apw1;
      chartAPW1.update('none');
    }
    if (d.wave_apw2 && d.wave_apw2.length > 0) {
      chartAPW2.data.labels = Array.from({length: d.wave_apw2.length}, (_,i) => i);
      chartAPW2.data.datasets[0].data = d.wave_apw2;
      chartAPW2.update('none');
    }

    if (d.ts) {
      const age = Math.round(Date.now()/1000 - d.ts);
      $('last-update').textContent = `last update: ${age}s ago`;
    }
  } catch(e) {
    console.error("Poll error:", e);
  }
}

poll();
setInterval(poll, 350);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/vitals")
def vitals():
    if not os.path.exists(VITALS_FILE):
        return jsonify({"connected": False, "error": "no data yet"})
    try:
        with open(VITALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        response = make_response(jsonify(data))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 500


if __name__ == "__main__":
    # Get local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "127.0.0.1"

    # ngrok public URL
    try:
        ngrok.set_auth_token("<removed for safety reasons - to be added by the person hoping to run their own server>")
        public_url = ngrok.connect(5000, "http").public_url
        print("\n" + "="*70)
        print("  PUBLIC URL (share with anyone):")
        print(f"  → {public_url}")
        print("="*70)
    except Exception as e:
        print(f"ngrok failed: {e}")
        public_url = None

    print("\nPTT Web Dashboard Started")
    print(f"  Local:     http://localhost:5000")
    print(f"  Network:   http://{lan_ip}:5000")
    if public_url:
        print(f"  Public:    {public_url}")
    print("\nMake sure ptt_beauty_web.py is running and device is connected.\n")

    app.run(host="0.0.0.0", port=5000, debug=False)
