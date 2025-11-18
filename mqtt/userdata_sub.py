from fastapi import FastAPI
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()

# PostgreSQL connection config
DB_CONFIG = {
    "host": "localhost",
    "dbname": "jlmill",
    "user": "kaai",
    "password": "yourpassword"
}

class UserData(BaseModel):
    user_id: str
    name: str
    role: str
    device_unique_id: str
    company_name: str
    branch: str
    sub_branch: str
    password: str
    mail: str | None = None

@app.post("/sync_user")
def sync_user(data: UserData):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_data (user_id, name, role, device_unique_id, company_name, branch, sub_branch, password, mail)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (user_id)
        DO UPDATE SET
            name = EXCLUDED.name,
            role = EXCLUDED.role,
            device_unique_id = EXCLUDED.device_unique_id,
            company_name = EXCLUDED.company_name,
            branch = EXCLUDED.branch,
            sub_branch = EXCLUDED.sub_branch,
            password = EXCLUDED.password,
            mail = EXCLUDED.mail;
    """, (
        data.user_id, data.name, data.role, data.device_unique_id,
        data.company_name, data.branch, data.sub_branch,
        data.password, data.mail
    ))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "user_id": data.user_id}

@app.get("/user")
def get_users():
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_data")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return {"users": users}
