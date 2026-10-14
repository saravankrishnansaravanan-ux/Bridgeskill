import json
import sqlite3
from fastapi import FastAPI, Request, Response, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from typing import Optional
import os
from dotenv import load_dotenv

# Automatically load environment variables
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.env")))
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "../.env")))

from backend.app.db import transaction, get_db_connection
from backend.app.auth import hash_password, verify_password, create_access_token, get_current_user, require_role
from modules.student_project import router as student_project_router
from backend.app.advanced_features import router as advanced_features_router, create_notification

app = FastAPI(title="BridgeSkill API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Module Routers
app.include_router(student_project_router)
app.include_router(advanced_features_router)

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    role: str
    name: Optional[str] = None
    companyName: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    expected_role: Optional[str] = None

@app.post("/api/auth/register", status_code=201)
async def register(req: RegisterRequest, response: Response):
    if req.role not in ["student", "company", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'student', 'company', or 'admin'.")
        
    if req.role == "student" and not req.name:
        raise HTTPException(status_code=400, detail="Name is required for students.")
        
    if req.role == "company" and not req.companyName:
        raise HTTPException(status_code=400, detail="Company name is required for companies.")

    try:
        with transaction() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM users WHERE email = ?", (req.email,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="Email already registered.")
                
            pwd_hash = hash_password(req.password)
            
            cursor.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
                (req.email, pwd_hash, req.role)
            )
            user_id = cursor.lastrowid
            
            if req.role == "student":
                cursor.execute(
                    "INSERT INTO student_profiles (user_id, name) VALUES (?, ?)",
                    (user_id, req.name)
                )
            elif req.role == "company":
                cursor.execute(
                    "INSERT INTO company_profiles (user_id, company_name) VALUES (?, ?)",
                    (user_id, req.companyName)
                )
                
            token_data = {"id": user_id, "email": req.email, "role": req.role}
            token = create_access_token(token_data)
            
            response.set_cookie(
                key="token",
                value=token,
                httponly=True,
                max_age=7 * 24 * 60 * 60,
                samesite="lax",
                secure=False
            )
            
            return {
                "message": "Registration successful",
                "token": token,
                "user": {
                    "id": user_id,
                    "email": req.email,
                    "role": req.role,
                    "name": req.name if req.role == "student" else None,
                    "companyName": req.companyName if req.role == "company" else None
                }
            }
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/api/auth/login")
async def login(req: LoginRequest, response: Response):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE email = ?", (req.email,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=400, detail="Invalid email or password.")
            
        if not verify_password(req.password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="Invalid email or password.")
            
        if req.expected_role and user["role"] != req.expected_role and user["role"] != "admin":
            actual_title = "Student / Learner" if user["role"] == "student" else "Company / Enterprise"
            portal_hash = "#login-student" if user["role"] == "student" else "#login-company"
            raise HTTPException(
                status_code=400,
                detail=f"This account is registered as a {actual_title}. Please sign in via the {actual_title} portal ({portal_hash})."
            )
            
        profile = None
        if user["role"] == "student":
            cursor.execute("SELECT * FROM student_profiles WHERE user_id = ?", (user["id"],))
            p = cursor.fetchone()
            if p:
                profile = dict(p)
                try:
                    profile["skills"] = json.loads(profile["skills"])
                except Exception:
                    profile["skills"] = []
        elif user["role"] == "company":
            cursor.execute("SELECT * FROM company_profiles WHERE user_id = ?", (user["id"],))
            p = cursor.fetchone()
            if p:
                profile = dict(p)
                
        token_data = {"id": user["id"], "email": user["email"], "role": user["role"]}
        token = create_access_token(token_data)
        
        response.set_cookie(
            key="token",
            value=token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,
            samesite="lax",
            secure=False
        )
        
        return {
            "message": "Login successful",
            "token": token,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "role": user["role"],
                "profile": profile
            }
        }
    finally:
        conn.close()

@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, email, role, created_at FROM users WHERE id = ?", (current_user["id"],))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
            
        profile = None
        if user["role"] == "student":
            cursor.execute("SELECT * FROM student_profiles WHERE user_id = ?", (user["id"],))
            p = cursor.fetchone()
            if p:
                profile = dict(p)
                try:
                    profile["skills"] = json.loads(profile["skills"])
                except Exception:
                    profile["skills"] = []
        elif user["role"] == "company":
            cursor.execute("SELECT * FROM company_profiles WHERE user_id = ?", (user["id"],))
            p = cursor.fetchone()
            if p:
                profile = dict(p)
                
        return {
            "user": {
                "id": user["id"],
                "email": user["email"],
                "role": user["role"],
                "created_at": user["created_at"],
                "profile": profile
            }
        }
    finally:
        conn.close()

# Project Schemas
class ProjectCreate(BaseModel):
    title: str
    description: str
    required_skills: list[str]
    duration_days: int

# Application Schemas
class ApplicationCreate(BaseModel):
    cover_letter: str

class ApplicationStatusUpdate(BaseModel):
    status: str  # 'accepted' or 'rejected'

class ApplicationSubmit(BaseModel):
    submission_link: str
    submission_notes: str

class ApplicationGrade(BaseModel):
    grade: float  # 1.0 to 5.0
    feedback: str

# 1. Create a Project
@app.post("/api/projects", status_code=201)
async def create_project(req: ProjectCreate, current_user: dict = Depends(require_role(["company"]))):
    try:
        with transaction() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM company_profiles WHERE user_id = ?", (current_user["id"],))
            company = cursor.fetchone()
            if not company:
                raise HTTPException(status_code=404, detail="Company profile not found.")
            
            required_skills_json = json.dumps(req.required_skills)
            
            cursor.execute(
                """
                INSERT INTO projects (company_id, title, description, required_skills, duration_days, status)
                VALUES (?, ?, ?, ?, ?, 'open')
                """,
                (company["id"], req.title, req.description, required_skills_json, req.duration_days)
            )
            project_id = cursor.lastrowid
            
            return {
                "message": "Project created successfully.",
                "project": {
                    "id": project_id,
                    "title": req.title,
                    "description": req.description,
                    "required_skills": req.required_skills,
                    "duration_days": req.duration_days,
                    "status": "open"
                }
            }
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# 2. Get All Projects (with search & filtering)
@app.get("/api/projects")
async def get_projects(status: Optional[str] = "open", search: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT p.*, c.company_name, c.is_verified 
            FROM projects p
            JOIN company_profiles c ON p.company_id = c.id
            WHERE p.status = ?
        """
        params = [status]
        
        if search:
            query += " AND (p.title LIKE ? OR p.description LIKE ? OR p.required_skills LIKE ?)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
            
        query += " ORDER BY p.created_at DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        projects = []
        for r in rows:
            p_dict = dict(r)
            try:
                p_dict["required_skills"] = json.loads(p_dict["required_skills"])
            except Exception:
                p_dict["required_skills"] = []
            projects.append(p_dict)
            
        return {"projects": projects}
    finally:
        conn.close()

# 3. Get Company's Posted Projects  *** MUST be before /api/projects/{project_id} ***
@app.get("/api/projects/my")
async def get_my_projects(current_user: dict = Depends(require_role(["company"]))):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM company_profiles WHERE user_id = ?", (current_user["id"],))
        company = cursor.fetchone()
        if not company:
            raise HTTPException(status_code=404, detail="Company profile not found.")
            
        cursor.execute("SELECT * FROM projects WHERE company_id = ? ORDER BY created_at DESC", (company["id"],))
        rows = cursor.fetchall()
        
        projects = []
        for r in rows:
            p_dict = dict(r)
            try:
                p_dict["required_skills"] = json.loads(p_dict["required_skills"])
            except Exception:
                p_dict["required_skills"] = []
            projects.append(p_dict)
            
        return {"projects": projects}
    finally:
        conn.close()

# 4. Get Project Details  *** MUST be after /api/projects/my ***
@app.get("/api/projects/{project_id}")
async def get_project_details(project_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT p.*, c.company_name, c.description as company_desc, c.website, c.is_verified 
            FROM projects p
            JOIN company_profiles c ON p.company_id = c.id
            WHERE p.id = ?
            """,
            (project_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found.")
            
        p_dict = dict(row)
        try:
            p_dict["required_skills"] = json.loads(p_dict["required_skills"])
        except Exception:
            p_dict["required_skills"] = []
            
        return {"project": p_dict}
    finally:
        conn.close()

# 5. Apply for a Project
@app.post("/api/projects/{project_id}/apply", status_code=201)
async def apply_project(project_id: int, req: ApplicationCreate, current_user: dict = Depends(require_role(["student"]))):
    try:
        with transaction() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM student_profiles WHERE user_id = ?", (current_user["id"],))
            student = cursor.fetchone()
            if not student:
                raise HTTPException(status_code=404, detail="Student profile not found.")
                
            cursor.execute("SELECT status FROM projects WHERE id = ?", (project_id,))
            project = cursor.fetchone()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found.")
            if project["status"] != "open":
                raise HTTPException(status_code=400, detail="This project is no longer open for applications.")
                
            cursor.execute(
                "SELECT id FROM applications WHERE project_id = ? AND student_id = ?",
                (project_id, student["id"])
            )
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="You have already applied for this project.")
                
            cursor.execute(
                """
                INSERT INTO applications (project_id, student_id, status, cover_letter)
                VALUES (?, ?, 'applied', ?)
                """,
                (project_id, student["id"], req.cover_letter)
            )
            
            return {"message": "Application submitted successfully."}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# 6. Get Applications for a Project (Company)
@app.get("/api/projects/{project_id}/applications")
async def get_project_applications(project_id: int, current_user: dict = Depends(require_role(["company"]))):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM company_profiles WHERE user_id = ?", (current_user["id"],))
        company = cursor.fetchone()
        if not company:
            raise HTTPException(status_code=404, detail="Company profile not found.")
            
        cursor.execute("SELECT company_id FROM projects WHERE id = ?", (project_id,))
        project = cursor.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found.")
        if project["company_id"] != company["id"]:
            raise HTTPException(status_code=403, detail="Forbidden. You do not own this project.")
            
        cursor.execute(
            """
            SELECT a.*, s.name as student_name, s.employability_score, s.resume_url, s.portfolio_url, s.skills as student_skills
            FROM applications a
            JOIN student_profiles s ON a.student_id = s.id
            WHERE a.project_id = ?
            ORDER BY a.applied_at DESC
            """,
            (project_id,)
        )
        rows = cursor.fetchall()
        
        apps = []
        for r in rows:
            a_dict = dict(r)
            try:
                a_dict["student_skills"] = json.loads(a_dict["student_skills"])
            except Exception:
                a_dict["student_skills"] = []
            apps.append(a_dict)
            
        return {"applications": apps}
    finally:
        conn.close()

# 7. Update Application Status (Accept/Reject by Company)
@app.post("/api/applications/{application_id}/status")
async def update_application_status(application_id: int, req: ApplicationStatusUpdate, current_user: dict = Depends(require_role(["company"]))):
    if req.status not in ["accepted", "rejected"]:
        raise HTTPException(status_code=400, detail="Invalid status. Must be 'accepted' or 'rejected'.")
        
    try:
        with transaction() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM company_profiles WHERE user_id = ?", (current_user["id"],))
            company = cursor.fetchone()
            if not company:
                raise HTTPException(status_code=404, detail="Company profile not found.")
                
            cursor.execute(
                """
                SELECT a.project_id, a.student_id, p.company_id, p.title as project_title, p.status as project_status, s.user_id as student_user_id 
                FROM applications a
                JOIN projects p ON a.project_id = p.id
                JOIN student_profiles s ON a.student_id = s.id
                WHERE a.id = ?
                """,
                (application_id,)
            )
            app_data = cursor.fetchone()
            if not app_data:
                raise HTTPException(status_code=404, detail="Application not found.")
            if app_data["company_id"] != company["id"]:
                raise HTTPException(status_code=403, detail="Forbidden. You do not own this project.")
                
            cursor.execute(
                "UPDATE applications SET status = ? WHERE id = ?",
                (req.status, application_id)
            )
            
            if req.status == "accepted":
                cursor.execute(
                    "UPDATE projects SET status = 'in_progress' WHERE id = ?",
                    (app_data["project_id"],)
                )

            create_notification(
                cursor,
                user_id=app_data["student_user_id"],
                title=f"Application {req.status.capitalize()}",
                message=f"Your application for project '{app_data['project_title']}' has been {req.status}.",
                link="#passport"
            )
                
            return {"message": f"Application {req.status} successfully."}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# 8. Submit Project Deliverables (Student)
@app.post("/api/applications/{application_id}/submit")
async def submit_project(application_id: int, req: ApplicationSubmit, current_user: dict = Depends(require_role(["student"]))):
    try:
        with transaction() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM student_profiles WHERE user_id = ?", (current_user["id"],))
            student = cursor.fetchone()
            if not student:
                raise HTTPException(status_code=404, detail="Student profile not found.")
                
            cursor.execute("""
                SELECT a.*, p.title as project_title, c.user_id as company_user_id
                FROM applications a
                JOIN projects p ON a.project_id = p.id
                JOIN company_profiles c ON p.company_id = c.id
                WHERE a.id = ?
            """, (application_id,))
            app_data = cursor.fetchone()
            if not app_data:
                raise HTTPException(status_code=404, detail="Application not found.")
            if app_data["student_id"] != student["id"]:
                raise HTTPException(status_code=403, detail="Forbidden. This is not your application.")
            if app_data["status"] != "accepted":
                raise HTTPException(status_code=400, detail="Cannot submit deliverables. Application status is " + app_data["status"])
                
            cursor.execute(
                """
                UPDATE applications 
                SET status = 'submitted', submission_link = ?, submission_notes = ?, submitted_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (req.submission_link, req.submission_notes, application_id)
            )

            create_notification(
                cursor,
                user_id=app_data["company_user_id"],
                title="Deliverables Submitted",
                message=f"Deliverables have been submitted for project '{app_data['project_title']}'.",
                link="#manage-projects"
            )
            
            return {"message": "Deliverables submitted successfully."}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# 9. Grade and Review Deliverables (Company)
@app.post("/api/applications/{application_id}/grade")
async def grade_project(application_id: int, req: ApplicationGrade, current_user: dict = Depends(require_role(["company"]))):
    if req.grade < 1.0 or req.grade > 5.0:
        raise HTTPException(status_code=400, detail="Grade must be between 1.0 and 5.0.")
        
    try:
        import uuid
        with transaction() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM company_profiles WHERE user_id = ?", (current_user["id"],))
            company = cursor.fetchone()
            if not company:
                raise HTTPException(status_code=404, detail="Company profile not found.")
                
            cursor.execute(
                """
                SELECT a.*, p.company_id, p.id as project_id, p.title as project_title, s.user_id as student_user_id 
                FROM applications a
                JOIN projects p ON a.project_id = p.id
                JOIN student_profiles s ON a.student_id = s.id
                WHERE a.id = ?
                """,
                (application_id,)
            )
            app_data = cursor.fetchone()
            if not app_data:
                raise HTTPException(status_code=404, detail="Application not found.")
            if app_data["company_id"] != company["id"]:
                raise HTTPException(status_code=403, detail="Forbidden. You do not own this project.")
            if app_data["status"] != "submitted":
                raise HTTPException(status_code=400, detail="Cannot grade. Deliverables have not been submitted.")
                
            certificate_uuid = str(uuid.uuid4())
            
            cursor.execute(
                """
                UPDATE applications 
                SET status = 'graded', grade = ?, feedback = ?, certificate_uuid = ?
                WHERE id = ?
                """,
                (req.grade, req.feedback, certificate_uuid, application_id)
            )
            
            cursor.execute(
                "UPDATE projects SET status = 'completed' WHERE id = ?",
                (app_data["project_id"],)
            )
            
            cursor.execute("SELECT grade FROM applications WHERE student_id = ? AND status = 'graded'", (app_data["student_id"],))
            grades = [row["grade"] for row in cursor.fetchall()]
            if grades:
                avg_grade = sum(grades) / len(grades)
                new_score = min(100.0, (avg_grade * 18.0) + (len(grades) * 4.0))
            else:
                new_score = 0.0
                
            cursor.execute(
                "UPDATE student_profiles SET employability_score = ? WHERE id = ?",
                (new_score, app_data["student_id"])
            )

            create_notification(
                cursor,
                user_id=app_data["student_user_id"],
                title="Project Graded & Certified",
                message=f"Your project '{app_data['project_title']}' was graded {req.grade}/5.0! Certificate issued.",
                link="#passport"
            )
            
            return {
                "message": "Project graded and completed successfully.",
                "certificate_uuid": certificate_uuid,
                "employability_score": new_score
            }

    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# 10. Get Student's Application History  *** MUST be before parameterized application routes ***
@app.get("/api/applications/my")
async def get_my_applications(current_user: dict = Depends(require_role(["student"]))):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM student_profiles WHERE user_id = ?", (current_user["id"],))
        student = cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student profile not found.")
            
        cursor.execute(
            """
            SELECT a.*, p.title as project_title, p.description as project_description, c.company_name
            FROM applications a
            JOIN projects p ON a.project_id = p.id
            JOIN company_profiles c ON p.company_id = c.id
            WHERE a.student_id = ?
            ORDER BY a.applied_at DESC
            """,
            (student["id"],)
        )
        rows = cursor.fetchall()
        
        return {"applications": [dict(r) for r in rows]}
    finally:
        conn.close()

@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie("token")
    return {"message": "Logged out successfully"}

if os.environ.get("VERCEL"):
    uploads_dir = "/tmp/uploads"
else:
    uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../uploads"))
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
