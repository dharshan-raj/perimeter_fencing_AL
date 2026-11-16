import json
from pathlib import Path
import cv2, numpy as np
DEFAULT = {"name":"Restricted Area","mode":"crossing","points":[[.72,.3],[.98,.3],[.98,.98],[.72,.98]]}
class ZoneManager:
    def __init__(self, path="config/zones.json"):
        self.path=Path(path); self.zone=DEFAULT.copy()
        try: self.zone=json.loads(self.path.read_text())
        except (OSError, ValueError): pass
    def update(self, zone):
        pts=zone.get("points", [])
        if len(pts)<3 or any(len(p)!=2 or not all(0<=float(v)<=1 for v in p) for p in pts): raise ValueError("Zone requires 3+ normalized points in [0,1]")
        if zone.get("mode", "crossing") not in ("crossing","intrusion","approach"): raise ValueError("Invalid boundary mode")
        self.zone={"name":zone.get("name","Restricted Area"),"mode":zone.get("mode","crossing"),"points":pts}; self.path.parent.mkdir(exist_ok=True); self.path.write_text(json.dumps(self.zone,indent=2)); return self.zone
    def polygon(self, shape):
        h,w=shape[:2]; return np.array([[int(float(x)*w),int(float(y)*h)] for x,y in self.zone["points"]],dtype=np.int32)
    def inside(self, point, shape): return cv2.pointPolygonTest(self.polygon(shape), tuple(map(float,point)), False)>=0
    def distance(self, point, shape):
        poly=self.polygon(shape); return min(abs(cv2.pointPolygonTest(poly,tuple(map(float,point)),True)), 100000)
    def annotate(self, frame): cv2.polylines(frame,[self.polygon(frame.shape)],True,(0,200,255),2); return frame
