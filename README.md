Tech stack:
FastAPI app with HTML routes and JSON APIs
Jinja2 templates: home.html, chat.html
SQLite database (chat.db)
Auth with JWT (PyJWT)
AI via Google Gemini (google-generativeai)
Uvicorn server
Main modules (in main.py):
App setup with lifespan: initializes DB on startup
Templates: Jinja2Templates(directory="templates")
DB helpers: init_db() creates tables and indexes; get_db() context manager
Models: Pydantic schemas for user, message, token, response
Auth:
hash_password() for SHA256
create_token() (JWT exp in UTC)
verify_token() and get_current_user() from Authorization header
AI:
genai.configure(api_key=GEMINI_API_KEY)
get_ai_response(message) uses gemini-1.5-flash
Routes:
GET / → home.html
GET /chat → chat.html
POST /api/register → create user + return token
POST /api/login → validate user + return token
GET /api/messages → recent messages (auth required)
POST /api/messages → create message; if starts with “@ai” (or contains “hey ai”), call Gemini and store AI reply with ai_model="gemini-1.5-flash"
Database schema:
users(id, username UNIQUE, password_hash, created_at)
messages(id, content, user_id NULL for AI, is_ai, ai_model, created_at)
Indexes on messages(created_at), messages(user_id), users(username)
Frontend (in chat.html):
Reads token and username from localStorage
Displays messages with styling for user/others/AI
Fetches messages (Authorization: Bearer token)
Sends messages (POST JSON); triggers AI when content starts with “@ai”
Auto-refresh messages periodically; loading indicator and error logs
Behavior:
New users register/login to get JWT
All API calls require Authorization: Bearer <token>
Messages saved to DB; AI replies appended when triggered
AI responses labeled as gemini-1.5-flash
How to run:
Install deps (FastAPI, Uvicorn, PyJWT, google-generativeai, etc.)
Set GEMINI_API_KEY env var
Start: python main.py
Visit: http://localhost:8000 (home), http://localhost:8000/chat (chat), http://localhost:8000/docs (API docs)
Notable safeguards:
JWT expiry (24h)
401s for missing/invalid tokens
Basic error logging on frontend
Query limit capped server-side
