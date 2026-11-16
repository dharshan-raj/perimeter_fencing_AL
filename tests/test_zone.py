from backend.detection.zone_manager import ZoneManager
from backend.detection.intrusion_detector import IntrusionDetector

def test_crossing_only_raises_on_entry():
    zone=ZoneManager(); zone.zone={"name":"test","mode":"crossing","points":[[.5,.5],[.9,.5],[.9,.9],[.5,.9]]}
    detector=IntrusionDetector(zone)
    outside=detector.evaluate({"id":1,"point":[20,20]},(100,100),30)
    assert outside["event"] is None
    entered=detector.evaluate({"id":1,"point":[70,70]},(100,100),30)
    assert entered["event"]=="Boundary Crossing"
    assert entered["direction"]=="Outside to Inside"
    assert detector.evaluate({"id":1,"point":[75,75]},(100,100),30)["event"] is None

def test_intrusion_resets_after_exit():
    zone=ZoneManager();zone.zone={"name":"test","mode":"intrusion","points":[[.5,.5],[.9,.5],[.9,.9],[.5,.9]]}
    detector=IntrusionDetector(zone)
    assert detector.evaluate({"id":2,"point":[70,70]},(100,100),30)["event"]=="Restricted Zone Intrusion"
    detector.evaluate({"id":2,"point":[10,10]},(100,100),30)
    assert detector.evaluate({"id":2,"point":[70,70]},(100,100),30)["event"] is None
