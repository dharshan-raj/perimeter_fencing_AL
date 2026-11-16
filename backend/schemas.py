from pydantic import BaseModel, Field
class ZonePayload(BaseModel):
    name:str="Restricted Area"
    mode:str="crossing"
    points:list[tuple[float,float]]=Field(min_length=3)
