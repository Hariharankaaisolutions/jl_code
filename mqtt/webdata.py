# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras

app = FastAPI(title="JLMill Backend API")

# Allow React app to access FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev; restrict later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection settings
DB_CONFIG = {
    "dbname": "jlmill",
    "user": "kaai",
    "password": "yourpassword",
    "host": "localhost",
    "port": "5432"
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

@app.get("/users")
def get_all_users():
    """
    Returns all user data from PostgreSQL (except password for security).
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT 
                user_id, 
                name, 
                role, 
                device_unique_id,
                company_name,
                branch,
                sub_branch,
                mail
            FROM user_data
            ORDER BY name;
        """)
        users = cur.fetchall()
        cur.close()
        return {"users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if conn:
            conn.close()
