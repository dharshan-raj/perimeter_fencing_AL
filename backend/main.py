import asyncio, logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date, select
from .config import settings
from .database import Base,engine,get_db,SessionLocal
from . import models
from .camera.camera_manager import camera_manager
from .detection.zone_manager import ZoneManager
from .services.websocket_manager import manager
from .services.notification_service import send_ntfy
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s")
loop=None
async def publish(payload,notify=False):
    await manager.broadcast(payload)
    if notify and payload.get("severity")=="CRITICAL": await send_ntfy(payload)
def publish_from_thread(payload,notify=False):
    if loop and loop.is_running(): asyncio.run_coroutine_threadsafe(publish(payload,notify),loop)
@asynccontextmanager
async def lifespan(app):
    global loop
    loop=asyncio.get_running_loop(); Base.metadata.create_all(bind=engine)
    db=SessionLocal()
    if not db.query(models.Camera).filter_by(camera_name=settings.camera_name).first(): db.add(models.Camera(camera_name=settings.camera_name,nvr_name=settings.nvr_name,location=settings.camera_location)); db.commit()
    db.close()
    if settings.camera_auto_start and settings.source:
        logging.getLogger(__name__).info("Starting camera worker automatically for configured source")
        camera_manager.start()
    yield; camera_manager.stop()
app=FastAPI(title="IT Furnace Perimeter Monitoring",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_methods=["*"],allow_headers=["*"])
def admin(x_admin_token:str|None=Header(default=None)):
    if x_admin_token != settings.admin_token: raise HTTPException(401,"Valid X-Admin-Token required")
@app.get("/api/health")
def health():return {"status":"ok","camera_status":camera_manager.status}
@app.get("/api/cameras")
def cameras(db:Session=Depends(get_db)):
    return [{"id":c.id,"camera_name":c.camera_name,"nvr_name":c.nvr_name,"location":c.location,"stream_status":camera_manager.status,"last_frame":camera_manager.last_frame is not None} for c in db.query(models.Camera).all()]
@app.get("/api/cameras/14/status")
def camera_status():
    return {"camera_name":settings.camera_name,"location":settings.camera_location,
            "source_type":settings.source_kind,"active_source":camera_manager.active_source,
            "stream_status":camera_manager.status,"video_status":camera_manager.video_status,
            "last_frame_timestamp":camera_manager.last_frame_timestamp,
            "processing":bool(camera_manager.thread and camera_manager.thread.is_alive()),
            "auto_start":settings.camera_auto_start,
            "auto_reconnect":settings.camera_auto_reconnect,
            "reconnect_attempt":camera_manager.stream.retry_attempt if camera_manager.stream else camera_manager.reconnect_attempt,
            "retry_in_seconds":camera_manager.stream.retry_wait_seconds if camera_manager.stream else 0,
            "source_configured":bool(settings.source)}
@app.post("/api/cameras/14/test-connection",dependencies=[Depends(admin)])
def test_camera_connection():
    result=camera_manager.test_connection()
    result.update({"camera_name":settings.camera_name,"location":settings.camera_location,
                   "configured_source_type":settings.source_kind})
    return result
@app.get("/api/stream.mjpg")
def stream():
    def frames():
        import cv2,time
        while True:
            frame=camera_manager.last_frame
            if frame is not None:
                image=frame.copy(); camera_manager.zone.annotate(image)
                for person in camera_manager.people:
                    x1,y1,x2,y2=person["box"]; cv2.rectangle(image,(x1,y1),(x2,y2),(54,210,185),2)
                    cv2.putText(image,f"ID {person['id']}  {person['confidence']:.2f}",(x1,max(18,y1-7)),cv2.FONT_HERSHEY_SIMPLEX,.55,(54,210,185),2)
                ok,data=cv2.imencode(".jpg",image)
                if ok: yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"+data.tobytes()+b"\r\n"
            time.sleep(.08)
    return StreamingResponse(frames(),media_type="multipart/x-mixed-replace; boundary=frame")
@app.get("/api/alerts")
def alerts(limit:int=Query(100,ge=1,le=500),severity:str|None=None,event_type:str|None=None,status:str|None=None,db:Session=Depends(get_db)):
    q=db.query(models.Alert).order_by(models.Alert.event_timestamp.desc())
    if severity:q=q.filter(models.Alert.severity==severity.upper())
    if event_type:q=q.filter(models.Alert.event_type==event_type)
    if status:q=q.filter(models.Alert.alert_status==status)
    return [{"id":a.id,"camera_name":a.camera.camera_name,"nvr_name":a.camera.nvr_name,"location":a.camera.location,"person_tracking_id":a.person_tracking_id,"event_type":a.event_type,"severity":a.severity,"confidence":a.confidence,"zone_name":a.zone_name,"crossing_direction":a.crossing_direction,"evidence_path":None,"alert_status":a.alert_status,"event_timestamp":a.event_timestamp.isoformat()} for a in q.limit(limit).all()]
@app.get("/api/alerts/{alert_id}")
def alert_detail(alert_id:int,db:Session=Depends(get_db)):
    a=db.get(models.Alert,alert_id)
    if not a:raise HTTPException(404,"Alert not found")
    return {"id":a.id,"person_tracking_id":a.person_tracking_id,"event_type":a.event_type,"severity":a.severity,"confidence":a.confidence,"crossing_direction":a.crossing_direction,"evidence_path":a.evidence_path,"alert_status":a.alert_status,"event_timestamp":a.event_timestamp.isoformat()}
@app.post("/api/alerts/{alert_id}/acknowledge",dependencies=[Depends(admin)])
def acknowledge(alert_id:int,db:Session=Depends(get_db)):
    a=db.get(models.Alert,alert_id)
    if not a:raise HTTPException(404,"Alert not found")
    a.alert_status="Acknowledged"; db.commit(); return {"id":a.id,"alert_status":a.alert_status}
@app.get("/api/analytics/summary")
def summary(db:Session=Depends(get_db)):
    total=db.query(models.Alert).count(); critical=db.query(models.Alert).filter_by(severity="CRITICAL").count(); active=db.query(models.Alert).filter_by(alert_status="Open").count()
    return {"total_people_detected":camera_manager.total_people,"total_crossings":camera_manager.crossings,"total_intrusion_alerts":critical,"active_incidents":active,"camera_status":camera_manager.status,"total_alerts":total}
@app.get("/api/analytics/daily")
def daily(db:Session=Depends(get_db)):
    rows=db.query(func.date(models.Alert.event_timestamp),func.count(models.Alert.id)).group_by(func.date(models.Alert.event_timestamp)).order_by(func.date(models.Alert.event_timestamp)).all()
    hours=db.query(func.strftime('%H',models.Alert.event_timestamp),func.count(models.Alert.id)).group_by(func.strftime('%H',models.Alert.event_timestamp)).all()
    kinds=db.query(models.Alert.event_type,func.count(models.Alert.id)).group_by(models.Alert.event_type).all()
    return {"daily":[{"date":str(d),"count":c} for d,c in rows],"hourly":[{"hour":h,"count":c} for h,c in hours],"event_types":[{"name":n,"count":c} for n,c in kinds]}
@app.get("/api/zones")
def get_zone():return camera_manager.zone.zone
@app.post("/api/zones",dependencies=[Depends(admin)])
def set_zone(payload:dict):
    try:return camera_manager.zone.update(payload)
    except ValueError as e:raise HTTPException(422,str(e))
@app.post("/api/cameras/14/start",dependencies=[Depends(admin)])
def start():camera_manager.start();return {"status":"starting"}
@app.post("/api/cameras/14/stop",dependencies=[Depends(admin)])
def stop():camera_manager.stop();return {"status":"stopping"}
@app.get("/api/evidence/{filename:path}")
def evidence(filename:str,token:str=Query(...)):
    if token!=settings.admin_token:raise HTTPException(401,"Authentication required")
    root=Path(settings.evidence_dir).resolve(); target=(root/filename).resolve()
    if root not in target.parents or not target.is_file():raise HTTPException(404,"Evidence not found")
    return FileResponse(target,media_type="image/jpeg")
@app.websocket("/ws/alerts")
async def ws_alerts(ws:WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:manager.disconnect(ws)
