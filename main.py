# main.py - Simple Chat App with AI Integration
from fastapi import FastAPI, HTTPException, Depends, Request, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
import sqlite3
import hashlib
import jwt
from datetime import datetime, timedelta, timezone
import openai
import os
from contextlib import contextmanager, asynccontextmanager
import google.generativeai as genai

# Configure OpenAI (you can use any AI API)
openai.api_key = os.getenv("OPENAI_API_KEY", "your-api-key-here")

# FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup"""
    init_db()
    yield

app = FastAPI(title="Simple Chat App with AI", lifespan=lifespan)

# Templates setup
templates = Jinja2Templates(directory="templates")

# Database setup
DATABASE = "chat.db"

def init_db():
    """Initialize database with tables"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            user_id INTEGER,
            is_ai BOOLEAN DEFAULT FALSE,
            ai_model TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    # Create indexes for better performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    
    conn.commit()
    conn.close()

@contextmanager
def get_db():
    """Database context manager"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Pydantic Models
class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class MessageCreate(BaseModel):
    content: str

class MessageResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    
    id: int
    content: str
    username: str
    is_ai: bool
    ai_model: Optional[str] = None
    created_at: str

class Token(BaseModel):
    access_token: str
    token_type: str

# Utility Functions
def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_token(user_id: int, username: str) -> str:
    """Create JWT token"""
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24)
    }
    return jwt.encode(payload, "secret-key", algorithm="HS256")

def verify_token(token: str):
    """Verify JWT token and return user info"""
    try:
        payload = jwt.decode(token, "secret-key", algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(authorization: str = None):
    """Get current user from token"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token required")
    
    token = authorization.replace("Bearer ", "")
    return verify_token(token)


# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY", "AIzaSyCImgZ0pi0CqSn6tCX_FF4b_qwtvTDP9NA"))

async def get_ai_response(message: str) -> str:
    """Get AI response from Gemini"""
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(message)
    return f"🤖 {response.text}"


# Web Pages (HTML Routes)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with login/register"""
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Chat page"""
    return templates.TemplateResponse("chat.html", {"request": request})

# API Endpoints



@app.post("/api/register", response_model=Token)
async def register(user: UserCreate):
    """Register new user"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (user.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # Create user
        password_hash = hash_password(user.password)
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (user.username, password_hash)
        )
        user_id = cursor.lastrowid
        conn.commit()
        
        # Return token
        token = create_token(user_id, user.username)
        return Token(access_token=token, token_type="bearer")

@app.post("/api/login", response_model=Token)
async def login(user: UserLogin):
    """Login user"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Check credentials
        password_hash = hash_password(user.password)
        cursor.execute(
            "SELECT id, username FROM users WHERE username = ? AND password_hash = ?",
            (user.username, password_hash)
        )
        
        user_data = cursor.fetchone()
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Return token
        token = create_token(user_data[0], user_data[1])
        return Token(access_token=token, token_type="bearer")

@app.post("/api/messages", response_model=MessageResponse)
async def send_message(
    message: MessageCreate,
    authorization: str = Header(None)
):
    """Send a message"""
    current_user = get_current_user(authorization)
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Save user message
        cursor.execute(
            "INSERT INTO messages (content, user_id, is_ai) VALUES (?, ?, FALSE)",
            (message.content, current_user["user_id"])
        )
        message_id = cursor.lastrowid
        conn.commit()
        
        # Get the saved message
        cursor.execute("""
            SELECT m.id, m.content, u.username, m.is_ai, m.ai_model, m.created_at
            FROM messages m JOIN users u ON m.user_id = u.id
            WHERE m.id = ?
        """, (message_id,))
        
        result = cursor.fetchone()
        
        # Check if message mentions AI (starts with "@ai" or contains "hey ai")
        if message.content.lower().startswith("@ai") or "hey ai" in message.content.lower():
            # Get AI response
            ai_content = await get_ai_response(message.content)
            
            # Save AI response
            cursor.execute(
                "INSERT INTO messages (content, user_id, is_ai, ai_model) VALUES (?, NULL, TRUE, ?)",
                (ai_content, "gemini-1.5-flash")
            )
            conn.commit()
        
        return MessageResponse(
            id=result[0],
            content=result[1],
            username=result[2],
            is_ai=bool(result[3]),
            ai_model=result[4],
            created_at=result[5]
        )

@app.get("/api/messages", response_model=List[MessageResponse])
async def get_messages(
    limit: int = 50,
    authorization: str = Header(None)
):
    """Get recent messages"""
    get_current_user(authorization)  # Verify user is authenticated
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Add index hint and optimize query
        cursor.execute("""
            SELECT m.id, m.content, 
                   COALESCE(u.username, 'AI Assistant') as username,
                   m.is_ai, m.ai_model, m.created_at
            FROM messages m 
            LEFT JOIN users u ON m.user_id = u.id
            ORDER BY m.created_at DESC 
            LIMIT ?
        """, (min(limit, 100),))  # Cap limit to prevent excessive data
        
        results = cursor.fetchall()
        
        return [
            MessageResponse(
                id=row[0],
                content=row[1],
                username=row[2],
                is_ai=bool(row[3]),
                ai_model=row[4],
                created_at=row[5]
            )
            for row in reversed(results)  # Show oldest first
        ]

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)