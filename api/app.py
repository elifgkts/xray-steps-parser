from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd, io

app = FastAPI()
app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.post("/parse")
async def parse_csv(file: UploadFile = File(...)):
    content = await file.read()
    df = pd.read_csv(io.BytesIO(content))
    return JSONResponse({"rows": int(len(df)), "cols": int(len(df.columns))})
