import os
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from database import get_db, init_db
from auth import hash_password, verify_password, create_access_token, decode_token
from fastapi.staticfiles import StaticFiles
import shutil
from fastapi import UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse


app = FastAPI(title="Video Editor Backend")
@app.get("/")
def serve_home():
    return FileResponse("index.html")
@app.on_event("startup")
def startup():
    init_db()
    os.makedirs("uploads", exist_ok=True)

class UserAuthRequest(BaseModel):
    username: str
    password: str

class SaveProjectRequest(BaseModel):
    project_id: int
    timeline_data: str

def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Header mein 'Bearer <token>' hona chahiye")
    
    token = authorization.split(" ")[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token invalid ya expire ho chuka hai")
    return payload


# --- 1. REGISTER (Strict 5-User Limit) ---
@app.post("/api/auth/register")
def register(user_data: UserAuthRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    # User Count Check
    cursor.execute("SELECT COUNT(*) AS total FROM users")
    total_users = cursor.fetchone()["total"]
    
    if total_users >= 5:
        conn.close()
        raise HTTPException(
            status_code=403, 
            detail="Registration closed: Maximum 5 users limit reached!"
        )
    
    # Username uniqueness check
    cursor.execute("SELECT id FROM users WHERE username = ?", (user_data.username,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Yeh username pehle se exist karta hai")
    
    hashed_pwd = hash_password(user_data.password)
    cursor.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)", 
        (user_data.username, hashed_pwd)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    os.makedirs(f"uploads/user_{user_id}", exist_ok=True)
    return {"message": "User register ho gaya!", "user_id": user_id}


# --- 2. LOGIN ---
@app.post("/api/auth/login")
def login(user_data: UserAuthRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (user_data.username,))
    user = cursor.fetchone()
    conn.close()
    
    if not user or not verify_password(user_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Galat username ya password")
    
    token = create_access_token({"user_id": user["id"], "username": user["username"]})
    return {"access_token": token, "token_type": "bearer", "username": user["username"]}


# --- 3. TIMELINE STATE SAVE ---
@app.post("/api/projects/save")
def save_project(payload: SaveProjectRequest, user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE projects 
        SET timeline_data = ?, updated_at = CURRENT_TIMESTAMP 
        WHERE id = ? AND user_id = ?
    """, (payload.timeline_data, payload.project_id, user["user_id"]))
    
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Timeline save ho gayi!"}
# --- 4. VIDEO UPLOAD ENDPOINT ---
@app.post("/api/projects/upload-video")
def upload_video(
    project_name: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    user_id = user["user_id"]
    user_folder = f"uploads/user_{user_id}"
    os.makedirs(user_folder, exist_ok=True)
    
    file_path = os.path.join(user_folder, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO projects (user_id, project_name, video_filename)
        VALUES (?, ?, ?)
    """, (user_id, project_name, file.filename))
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "project_id": project_id,
        "filename": file.filename,
        "stream_url": f"/api/video/stream/{user_id}/{file.filename}"
    }

# --- 5. VIDEO STREAM ROUTE (HTTP Range Requests ke saath) ---
@app.get("/api/video/stream/{user_id}/{filename}")
def stream_video(user_id: int, filename: str):
    file_path = os.path.join(f"uploads/user_{user_id}", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file nahi mili")
    
    # FileResponse automatically 206 Partial Content (HTTP Range) handle karta hai
    return FileResponse(file_path, media_type="video/mp4")
os.makedirs("frontend", exist_ok=True)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
