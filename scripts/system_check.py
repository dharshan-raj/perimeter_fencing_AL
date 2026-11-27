import socket, sqlite3, sys, os, json
sys.path.insert(0, os.getcwd())

print("== CAMERA REACHABILITY ==")
from shared.config import settings
print("source kind:", settings.source_kind, "| ip:", settings.rtsp_ip, "port:", settings.rtsp_port, "| face_v2:", settings.face_v2_enabled)
try:
    s = socket.create_connection((settings.rtsp_ip, settings.rtsp_port), timeout=4); s.close()
    print("TCP port 554: REACHABLE")
except Exception as e:
    print("TCP port 554: NOT reachable ->", e)

print("== DATABASE ==")
c = sqlite3.connect("perimeter_monitor.db").cursor()
for t in ("cameras", "alerts", "detection_logs", "system_logs", "headcount_events"):
    print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
print("headcount by direction:", c.execute("select direction,count(*) from headcount_events group by 1").fetchall())
print("events with employee_name:", c.execute("select count(*) from headcount_events where employee_name is not null").fetchone()[0])
print("latest alert:", c.execute("select event_type,severity,event_timestamp from alerts order by id desc limit 1").fetchall())
print("latest headcount:", c.execute("select direction,employee_name,event_timestamp from headcount_events order by id desc limit 1").fetchall())
print("recent system logs:", c.execute("select log_level,message,timestamp from system_logs order by id desc limit 3").fetchall())

print("== API ENDPOINTS ==")
from fastapi.testclient import TestClient
from main import app
import main as m
# do not start the camera worker for this check
settings.camera_auto_start = False
with TestClient(app) as client:
    paths = ["/api/health", "/api/cameras", "/api/cameras/14/status", "/api/alerts", "/api/zones",
             "/api/analytics/summary", "/api/analytics/daily", "/api/headcount/live?gate_name=Gate%203",
             "/api/headcount/events?gate_name=Gate%203&limit=3",
             "/api/headcount/reports/daily?gate_name=Gate%203",
             "/api/headcount/reports/monthly?gate_name=Gate%203",
             "/api/headcount/attendance/today", "/api/headcount/employee-timings"]
    for p in paths:
        try:
            r = client.get(p)
            body = r.text[:90].replace("\n", " ")
            print(r.status_code, p, "|", body)
        except Exception as e:
            print("ERR", p, e)

print("== GATE LINES ==")
from entry_exit_headcount.headcount_manager import HeadcountManager
h = HeadcountManager()
print("two_lines:", h.two_lines, "IN:", h.line_in_start, h.line_in_end, "OUT:", h.line_out_start, h.line_out_end)

print("== FACE REGISTRY (cache) ==")
from shared.face_recognition.embedding_cache import list_employee_photos
print({k: len(v) for k, v in list_employee_photos("shared/employee_face").items()})
print("cache file exists:", os.path.exists("shared/employee_face/.embeddings_cache.npz"))
