import os
import json
import uuid
import shutil
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func, or_
from sqlalchemy.orm import Session, relationship

from backend.app.db import Base, get_db, engine
from backend.app.auth import get_current_user, require_role

# -------------------------------------------------------------------------
# SQLAlchemy Database Models
# -------------------------------------------------------------------------

class ProjectApplication(Base):
    """
    ProjectApplication Database Model.
    Tracks id, project_id, student_id, status ('pending', 'accepted', 'rejected'),
    and applied_at timestamp.
    """
    __tablename__ = "project_applications"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default="pending", nullable=False)  # 'pending', 'accepted', 'rejected'
    cover_letter = Column(Text, nullable=True)
    applied_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    submissions = relationship("ProjectSubmission", back_populates="application", cascade="all, delete-orphan")
    project = relationship("Project", back_populates="applications")
    student = relationship("StudentProfile", back_populates="applications")


class ProjectSubmission(Base):
    """
    ProjectSubmission Database Model.
    Tracks id, application_id, submission_url or file_path, notes,
    submitted_at timestamp, and grade.
    """
    __tablename__ = "project_submissions"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("project_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    submission_url = Column(String(500), nullable=True)
    file_path = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    grade = Column(Float, nullable=True)

    # Relationships
    application = relationship("ProjectApplication", back_populates="submissions")


# Models for joins & relations with existing platform schema
class Project(Base):
    __tablename__ = "projects"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    required_skills = Column(Text, default="[]")
    duration_days = Column(Integer, nullable=False)
    status = Column(String(50), default="open")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    company = relationship("CompanyProfile", back_populates="projects")
    applications = relationship("ProjectApplication", back_populates="project", cascade="all, delete-orphan")


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    skills = Column(Text, default="[]")
    bio = Column(Text, nullable=True)
    employability_score = Column(Float, default=0.0)
    resume_url = Column(String(500), nullable=True)
    portfolio_url = Column(String(500), nullable=True)

    applications = relationship("ProjectApplication", back_populates="student", cascade="all, delete-orphan")


class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    company_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    website = Column(String(500), nullable=True)
    is_verified = Column(Integer, default=0)

    projects = relationship("Project", back_populates="company", cascade="all, delete-orphan")


# Create tables if not existing
Base.metadata.create_all(bind=engine)

# -------------------------------------------------------------------------
# Pydantic Request / Response Schemas
# -------------------------------------------------------------------------

class ProjectApplicationRequest(BaseModel):
    cover_letter: Optional[str] = None

class ProjectSubmissionRequest(BaseModel):
    submission_url: Optional[str] = None
    file_path: Optional[str] = None
    notes: Optional[str] = None

class ProjectApplicationResponse(BaseModel):
    id: int
    project_id: int
    student_id: int
    status: str
    cover_letter: Optional[str] = None
    applied_at: datetime

    class Config:
        from_attributes = True

class ProjectSubmissionResponse(BaseModel):
    id: int
    application_id: int
    submission_url: Optional[str] = None
    file_path: Optional[str] = None
    notes: Optional[str] = None
    submitted_at: datetime
    grade: Optional[float] = None

    class Config:
        from_attributes = True

# Upload storage directory
UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../uploads/submissions"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

# -------------------------------------------------------------------------
# FastAPI Router
# -------------------------------------------------------------------------

router = APIRouter(
    prefix="/student/projects",
    tags=["Student Project Workspace"]
)

# Helper function to parse skills JSON
def _parse_skills(skills_str: Optional[str]) -> list:
    if not skills_str:
        return []
    try:
        return json.loads(skills_str)
    except Exception:
        return [skills_str] if isinstance(skills_str, str) else []


# 1) GET /student/projects/ - Browse active projects
@router.get("/", summary="Browse active projects for students")
@router.get("", summary="Browse active projects for students (alias)")
async def browse_active_projects(
    search: Optional[str] = Query(None, description="Search keyword in title or description"),
    skill: Optional[str] = Query(None, description="Filter by required skill"),
    status_filter: Optional[str] = Query("open", description="Project status filter (default: open)"),
    db: Session = Depends(get_db)
):
    """
    Endpoint 1: Let students browse active projects.
    Returns active projects with details including company name, skills, and duration.
    """
    query = db.query(Project).join(CompanyProfile, Project.company_id == CompanyProfile.id)

    if status_filter:
        query = query.filter(Project.status == status_filter)

    if search:
        search_fmt = f"%{search}%"
        query = query.filter(
            or_(
                Project.title.ilike(search_fmt),
                Project.description.ilike(search_fmt),
                Project.required_skills.ilike(search_fmt)
            )
        )

    if skill:
        skill_fmt = f"%{skill}%"
        query = query.filter(Project.required_skills.ilike(skill_fmt))

    projects = query.order_by(Project.created_at.desc()).all()

    result = []
    for p in projects:
        comp = p.company
        result.append({
            "id": p.id,
            "company_id": p.company_id,
            "company_name": comp.company_name if comp else "Unknown Company",
            "company_verified": bool(comp.is_verified) if comp else False,
            "title": p.title,
            "description": p.description,
            "required_skills": _parse_skills(p.required_skills),
            "duration_days": p.duration_days,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })

    return {
        "count": len(result),
        "projects": result
    }


# 2) POST /student/projects/{project_id}/apply - Submit an application
@router.post("/{project_id}/apply", status_code=status.HTTP_201_CREATED, summary="Submit project application")
async def apply_to_project(
    project_id: int,
    req: Optional[ProjectApplicationRequest] = None,
    current_user: dict = Depends(require_role(["student"])),
    db: Session = Depends(get_db)
):
    """
    Endpoint 2: Submit an application to an active project.
    Tracks id, project_id, student_id, status ('pending'), and applied_at.
    """
    student_profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user["id"]).first()
    if not student_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found. Please complete your profile first."
        )

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found."
        )

    if project.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This project is currently '{project.status}' and not open for new applications."
        )

    # Check for existing application
    existing_app = db.query(ProjectApplication).filter(
        ProjectApplication.project_id == project_id,
        ProjectApplication.student_id == student_profile.id
    ).first()

    if existing_app:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You have already applied for this project (Status: {existing_app.status})."
        )

    cover_letter_text = req.cover_letter if req else None

    # Create new ProjectApplication with status 'pending'
    application = ProjectApplication(
        project_id=project_id,
        student_id=student_profile.id,
        status="pending",
        cover_letter=cover_letter_text,
        applied_at=datetime.now(timezone.utc)
    )

    db.add(application)
    db.commit()
    db.refresh(application)

    return {
        "message": "Application submitted successfully.",
        "application": {
            "id": application.id,
            "project_id": application.project_id,
            "student_id": application.student_id,
            "status": application.status,
            "cover_letter": application.cover_letter,
            "applied_at": application.applied_at.isoformat()
        }
    }


# 3) POST /student/projects/{project_id}/submit - Upload project deliverables
@router.post("/{project_id}/submit", status_code=status.HTTP_201_CREATED, summary="Submit project deliverables")
async def submit_project_deliverables(
    project_id: int,
    req: Optional[ProjectSubmissionRequest] = None,
    current_user: dict = Depends(require_role(["student"])),
    db: Session = Depends(get_db)
):
    """
    Endpoint 3: Upload/submit project deliverables for an accepted application.
    Tracks id, application_id, submission_url or file_path, notes, submitted_at, and grade.
    """
    student_profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user["id"]).first()
    if not student_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found."
        )

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found."
        )

    # Find the student's application for this project
    application = db.query(ProjectApplication).filter(
        ProjectApplication.project_id == project_id,
        ProjectApplication.student_id == student_profile.id
    ).first()

    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No application found for this project. Please apply first."
        )

    if application.status == "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit deliverables. Your application is still 'pending' review by the company."
        )

    if application.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit deliverables. Your application was rejected."
        )

    if application.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot submit deliverables. Application status is '{application.status}', must be 'accepted'."
        )

    submission_url = req.submission_url if req else None
    file_path = req.file_path if req else None
    notes = req.notes if req else None

    if not submission_url and not file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a submission_url or upload a deliverable file."
        )

    # Create submission record
    submission = ProjectSubmission(
        application_id=application.id,
        submission_url=submission_url,
        file_path=file_path,
        notes=notes,
        submitted_at=datetime.now(timezone.utc),
        grade=None
    )

    db.add(submission)
    db.commit()
    db.refresh(submission)

    return {
        "message": "Project deliverables submitted successfully.",
        "submission": {
            "id": submission.id,
            "application_id": submission.application_id,
            "submission_url": submission.submission_url,
            "file_path": submission.file_path,
            "notes": submission.notes,
            "submitted_at": submission.submitted_at.isoformat(),
            "grade": submission.grade
        }
    }


# 3b) POST /student/projects/{project_id}/submit-file - Multipart file upload deliverable
@router.post("/{project_id}/submit-file", status_code=status.HTTP_201_CREATED, summary="Upload deliverable file")
async def submit_deliverable_file(
    project_id: int,
    file: UploadFile = File(...),
    submission_url: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    current_user: dict = Depends(require_role(["student"])),
    db: Session = Depends(get_db)
):
    """
    Multipart file upload endpoint for submitting deliverables.
    Saves file to disk and stores the relative file_path in ProjectSubmission.
    """
    student_profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user["id"]).first()
    if not student_profile:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    application = db.query(ProjectApplication).filter(
        ProjectApplication.project_id == project_id,
        ProjectApplication.student_id == student_profile.id
    ).first()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found for this project.")

    if application.status != "accepted":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit deliverables. Application status is '{application.status}' (must be 'accepted')."
        )

    # Save uploaded file
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ""
    saved_filename = f"deliverable_app_{application.id}_{uuid.uuid4().hex[:8]}{file_ext}"
    saved_path = os.path.join(UPLOAD_DIR, saved_filename)

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    relative_file_path = f"/uploads/submissions/{saved_filename}"

    submission = ProjectSubmission(
        application_id=application.id,
        submission_url=submission_url,
        file_path=relative_file_path,
        notes=notes,
        submitted_at=datetime.now(timezone.utc),
        grade=None
    )

    db.add(submission)
    db.commit()
    db.refresh(submission)

    return {
        "message": "File uploaded and deliverables submitted successfully.",
        "submission": {
            "id": submission.id,
            "application_id": submission.application_id,
            "submission_url": submission.submission_url,
            "file_path": submission.file_path,
            "notes": submission.notes,
            "submitted_at": submission.submitted_at.isoformat(),
            "grade": submission.grade
        }
    }


# 4) GET /student/projects/applications/my - Student's application & submission history
@router.get("/applications/my", summary="Get current student's applications & submissions")
async def get_my_student_applications(
    current_user: dict = Depends(require_role(["student"])),
    db: Session = Depends(get_db)
):
    """
    Retrieve all applications and submissions submitted by the logged-in student.
    """
    student_profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user["id"]).first()
    if not student_profile:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    applications = db.query(ProjectApplication).filter(
        ProjectApplication.student_id == student_profile.id
    ).order_by(ProjectApplication.applied_at.desc()).all()

    result = []
    for app in applications:
        proj = app.project
        comp = proj.company if proj else None
        subs = []
        for s in app.submissions:
            subs.append({
                "id": s.id,
                "submission_url": s.submission_url,
                "file_path": s.file_path,
                "notes": s.notes,
                "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
                "grade": s.grade
            })

        result.append({
            "id": app.id,
            "project_id": app.project_id,
            "project_title": proj.title if proj else "Unknown",
            "project_description": proj.description if proj else "",
            "company_name": comp.company_name if comp else "Unknown",
            "status": app.status,
            "cover_letter": app.cover_letter,
            "applied_at": app.applied_at.isoformat() if app.applied_at else None,
            "submissions": subs
        })

    return {"applications": result}


# 5) GET /student/projects/{project_id} - View single project details
@router.get("/{project_id}", summary="Get active project details")
async def get_student_project_details(
    project_id: int,
    db: Session = Depends(get_db)
):
    """
    Retrieve detailed information for a single project.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    comp = project.company
    return {
        "project": {
            "id": project.id,
            "company_id": project.company_id,
            "company_name": comp.company_name if comp else "Unknown",
            "company_description": comp.description if comp else "",
            "company_website": comp.website if comp else "",
            "company_verified": bool(comp.is_verified) if comp else False,
            "title": project.title,
            "description": project.description,
            "required_skills": _parse_skills(project.required_skills),
            "duration_days": project.duration_days,
            "status": project.status,
            "created_at": project.created_at.isoformat() if project.created_at else None
        }
    }
