import json
from pathlib import Path
import cv2, numpy as np
DEFAULT = {"name":"Restricted Area","mode":"crossing","allowed_employees":["dharshan"],"points":[[.72,.3],[.98,.3],[.98,.98],[.72,.98]]}
class ZoneManager:
    def __init__(self, path="config/zones.json"):
        self.path=Path(path); self.zone=DEFAULT.copy()
        try: self.zone=json.loads(self.path.read_text())
        except (OSError, ValueError): pass
    def is_authorised(self, employee_name):
        if not employee_name or employee_name == "Unknown":
            return False
        allowed = [e.lower() for e in self.zone.get("allowed_employees", ["dharshan"])]
        return employee_name.strip().lower() in allowed
    def update(self, zone):
        pts=zone.get("points", [])
        if len(pts)<3 or any(len(p)!=2 or not all(0<=float(v)<=1 for v in p) for p in pts): raise ValueError("Zone requires 3+ normalized points in [0,1]")
        if zone.get("mode", "crossing") not in ("crossing","intrusion","approach"): raise ValueError("Invalid boundary mode")
        allowed = zone.get("allowed_employees", self.zone.get("allowed_employees", ["dharshan"]))
        self.zone={"name":zone.get("name","Restricted Area"),"mode":zone.get("mode","crossing"),"allowed_employees":allowed,"points":pts}
        self.path.parent.mkdir(exist_ok=True); self.path.write_text(json.dumps(self.zone,indent=2)); return self.zone
    def polygon(self, shape):
        h,w=shape[:2]; return np.array([[int(float(x)*w),int(float(y)*h)] for x,y in self.zone["points"]],dtype=np.int32)
    def inside(self, point, shape): return cv2.pointPolygonTest(self.polygon(shape), tuple(map(float,point)), False)>=0
    def distance(self, point, shape):
        poly=self.polygon(shape); return min(abs(cv2.pointPolygonTest(poly,tuple(map(float,point)),True)), 100000)
    def annotate(self, frame, is_intrusion=False):
        poly = self.polygon(frame.shape)
        overlay = frame.copy()
        fill_color = (0, 0, 180) if is_intrusion else (0, 140, 255)
        border_color = (0, 0, 255) if is_intrusion else (0, 200, 255)
        cv2.fillPoly(overlay, [poly], fill_color)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
        cv2.polylines(frame, [poly], True, border_color, 2, cv2.LINE_AA)
        top_idx = int(np.argmin(poly[:, 1]))
        tx, ty = int(poly[top_idx][0]), max(22, int(poly[top_idx][1]) - 8)
        name = self.zone.get("name", "Restricted Area")
        text = f"PERIMETER: {name}" + (" [INTRUSION!]" if is_intrusion else "")
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (tx - 4, ty - th - 5), (tx + tw + 4, ty + 3), (15, 23, 42), -1)
        cv2.rectangle(frame, (tx - 4, ty - th - 5), (tx + tw + 4, ty + 3), border_color, 1)
        cv2.putText(frame, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, border_color, 1, cv2.LINE_AA)
        return frame
