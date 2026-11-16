from collections import defaultdict, deque
import time
class IntrusionDetector:
    def __init__(self, zone, mode="crossing", approach_distance=35): self.zone=zone; self.mode=mode; self.approach_distance=approach_distance; self.history=defaultdict(lambda:deque(maxlen=6)); self.inside=set(); self.last_alert={}
    def evaluate(self, person, shape, cooldown):
        tid=person["id"]; point=person["point"]; inside=self.zone.inside(point,shape); hist=self.history[tid]; previous=hist[-1][1] if hist else None; hist.append((time.time(),inside))
        event=None; direction=None; mode=self.zone.zone.get("mode",self.mode)
        if mode=="crossing" and previous is not None and previous != inside:
            event="Boundary Crossing" if inside else None; direction="Outside to Inside" if inside else "Inside to Outside"
        elif mode=="intrusion" and inside and tid not in self.inside: event="Restricted Zone Intrusion"; direction="Outside to Inside"
        elif mode=="approach" and not inside and self.zone.distance(point,shape)<=self.approach_distance: event="Boundary Approach"; direction="Approaching"
        if inside:self.inside.add(tid)
        else:self.inside.discard(tid)
        allowed=event and time.time()-self.last_alert.get((tid,event),0)>=cooldown
        if allowed:self.last_alert[(tid,event)]=time.time()
        return {"inside":inside,"event":event if allowed else None,"direction":direction,"zone":"Restricted Area"}
