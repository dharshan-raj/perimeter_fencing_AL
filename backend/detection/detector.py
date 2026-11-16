from pathlib import Path
import logging
from ultralytics import YOLO
from ..config import settings
log=logging.getLogger(__name__)
class PersonDetector:
    def __init__(self):
        path=Path(settings.model_path)
        if path.exists(): self.model=YOLO(str(path))
        else:
            log.warning("Configured model %s is missing; using pretrained yolov8n.pt",path)
            self.model=YOLO("yolov8n.pt")
    def detect_track(self, frame):
        result=self.model.track(frame, persist=True, classes=[0], conf=settings.person_confidence, iou=settings.iou_threshold, tracker="bytetrack.yaml", verbose=False)[0]
        out=[]
        if result.boxes is None: return out
        for box in result.boxes:
            if box.id is None: continue
            x1,y1,x2,y2=map(int,box.xyxy[0].tolist())
            out.append({"id":int(box.id.item()),"confidence":float(box.conf.item()),"box":[x1,y1,x2,y2],"point":[(x1+x2)//2,y2]})
        return out
