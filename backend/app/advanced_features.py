import json
import sqlite3
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from backend.app.db import get_db_connection, transaction
from backend.app.auth import get_current_user, get_optional_current_user, require_role
import os

from backend.app.ai_service import (
    ROLE_TAXONOMY,
    analyze_skill_gap,
    match_projects_for_student,
    evaluate_submission_ai,
    get_mock_interview_question,
    evaluate_interview_answer,
    get_active_llm_config,
    consult_ai_advisor,
    evaluate_code_sandbox,
    analyze_github_profile,
    generate_interview_hint,
    conduct_live_interview_turn
)

router = APIRouter(tags=["Advanced BridgeSkill Features"])

class ConsultantChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = []
    mode: Optional[str] = "career"

@router.post("/api/ai/consultant/chat")
async def chat_with_ai_consultant(
    req: ConsultantChatRequest,
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """AI Consultant Chatbot endpoint for career advice and technical project mentoring (supports guests and authenticated users)."""
    user_name = "Learner"
    user_role = "student"
    skills = []
    score = 0.0
    active_projects = []
    available_projects = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if current_user:
                user_id = int(current_user.get("id") or current_user.get("sub", 0))
                user_role = current_user.get("role", "student")
                cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
                u = cursor.fetchone()
                if u and u["email"]:
                    user_name = u["email"].split("@")[0]

                if user_role == "student":
                    cursor.execute("SELECT id, name, skills, employability_score FROM student_profiles WHERE user_id = ?", (user_id,))
                    p = cursor.fetchone()
                    if p:
                        user_name = p["name"] or user_name
                        score = p["employability_score"] or 0.0
                        try:
                            skills = json.loads(p["skills"]) if p["skills"] else []
                        except Exception:
                            skills = []

                        # Fetch student's assigned or applied projects
                        cursor.execute("""
                            SELECT p.title FROM applications a
                            JOIN projects p ON a.project_id = p.id
                            WHERE a.student_id = ? AND a.status IN ('accepted', 'pending')
                            LIMIT 3
                        """, (p["id"],))
                        active_projects = [r["title"] for r in cursor.fetchall()]

                elif user_role == "company":
                    cursor.execute("SELECT company_name FROM company_profiles WHERE user_id = ?", (user_id,))
                    c = cursor.fetchone()
                    if c and c["company_name"]:
                        user_name = c["company_name"]

            # Fetch top open marketplace projects for context
            cursor.execute("SELECT title, required_skills FROM projects WHERE status = 'open' LIMIT 4")
            available_projects = [f"{r['title']} ({r['required_skills']})" for r in cursor.fetchall()]
        finally:
            conn.close()
    except Exception as db_err:
        print(f"[AI Consultant] DB context warning: {db_err}")

    try:
        result = consult_ai_advisor(
            user_name=user_name,
            user_role=user_role,
            skills=skills,
            employability_score=score,
            user_message=req.message,
            history=req.history or [],
            mode=req.mode or "career",
            active_projects=active_projects,
            available_projects=available_projects
        )
        return result
    except Exception as ai_err:
        print(f"[AI Consultant] Advisor execution error: {ai_err}")
        return {
            "reply": f"Hello {user_name}! I am your AI Mentor. I recommend exploring high-impact micro-projects on BridgeSkill in Python, Web Development, and Cloud Architectures. How can I guide you today?",
            "mode": req.mode or "career",
            "suggested_prompts": [
                "Which micro-project bridges my biggest skill gap?",
                "How can I boost my Employability Score to 95+?",
                "How do I write a compelling project bullet point for my resume?"
            ]
        }

@router.get("/api/ai/consultant/quick-prompts")
async def get_consultant_quick_prompts():
    """Provides prompt suggestions for the AI Consultant."""
    return {
        "prompts": [
            "How can I quickly increase my Employability Score to 90+?",
            "What projects should I build to become a Backend Python Engineer?",
            "How should I structure my submission README and Docker setup?",
            "How can I solve N+1 query performance issues in my project?",
            "Can you review my skills and recommend high-impact micro-projects?"
        ]
    }


class LLMConfigRequest(BaseModel):
    provider: str  # 'groq' | 'gemini' | 'openai' | 'ollama'
    api_key: Optional[str] = ""
    model: Optional[str] = None
    url: Optional[str] = None

@router.get("/api/ai/llm-status")
async def get_llm_status():
    """Returns current active LLM connection status and rate limit metrics."""
    cfg = get_active_llm_config()
    return {
        "connected": cfg["connected"],
        "provider": cfg["provider"],
        "model": cfg["model"],
        "has_key": bool(cfg.get("api_key")),
        "rate_limits": cfg.get("rate_limits", {})
    }


@router.post("/api/ai/llm-config")
async def update_llm_config(req: LLMConfigRequest, current_user: dict = Depends(require_role(["admin"]))):
    """Central AI engine is locked to backend Groq setup."""
    raise HTTPException(
        status_code=403,
        detail="AI engine is centrally configured in BridgeSkill backend and cannot be modified by clients."
    )

# -------------------------------------------------------------------------
# NOVELTY FEATURE 1: AI Code Sandbox & Automated PR Reviewer
# -------------------------------------------------------------------------
class SandboxReviewRequest(BaseModel):
    code: str
    language: Optional[str] = "python"
    project_context: Optional[str] = ""

@router.post("/api/ai/sandbox/review")
async def review_sandbox_code(req: SandboxReviewRequest, current_user: Optional[dict] = Depends(get_optional_current_user)):
    """Reviews student code submission in the sandbox across architecture, complexity, and security."""
    if not req.code or not req.code.strip():
        raise HTTPException(status_code=400, detail="Code snippet cannot be empty.")
    result = evaluate_code_sandbox(
        code=req.code,
        language=req.language or "python",
        project_context=req.project_context or "Industry Engineering Micro-Project"
    )
    return {"review": result}

# -------------------------------------------------------------------------
# NOVELTY FEATURE 2: GitHub Profile & Tech Stack Auto-Analyzer
# -------------------------------------------------------------------------
class GithubAnalyzeRequest(BaseModel):
    target: str
    context_text: Optional[str] = ""

@router.post("/api/ai/analyze-github")
async def analyze_github_repo_or_profile(req: GithubAnalyzeRequest, current_user: Optional[dict] = Depends(get_optional_current_user)):
    """Analyzes a candidate's GitHub repos or stack to generate skill insights and micro-project recommendations."""
    if not req.target or not req.target.strip():
        raise HTTPException(status_code=400, detail="Target username or repo cannot be empty.")
    result = analyze_github_profile(
        target=req.target.strip(),
        context_text=req.context_text or ""
    )
    return {"analysis": result}

# -------------------------------------------------------------------------
# NOVELTY FEATURE 3: Gamified Engineering Leaderboard
# -------------------------------------------------------------------------
@router.get("/api/leaderboard")
async def get_engineering_leaderboard(track: Optional[str] = None, limit: int = 25):
    """Returns top ranked engineering talent with track filter, badges, and verified project metrics."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT sp.id, sp.user_id, sp.name, sp.bio, sp.skills, sp.employability_score,
                   sp.portfolio_url, sp.resume_url, u.email,
                   (SELECT COUNT(*) FROM applications WHERE student_id = sp.id AND status IN ('accepted', 'graded')) as completed_projects,
                   (SELECT COUNT(*) FROM applications WHERE student_id = sp.id AND certificate_uuid IS NOT NULL) as verified_certificates
            FROM student_profiles sp
            JOIN users u ON sp.user_id = u.id
            ORDER BY sp.employability_score DESC, completed_projects DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()

        leaderboard = []
        rank = 1
        for row in rows:
            r = dict(row)
            try:
                skills_list = json.loads(r["skills"]) if r["skills"] else []
            except Exception:
                skills_list = []
            r["skills"] = skills_list

            # Determine dominant tech track
            tracks = []
            skills_lower = [s.lower() for s in skills_list]
            if any(s in skills_lower for s in ["machine learning", "pytorch", "nlp", "llms", "vector db"]):
                tracks.append("ai-ml")
            if any(s in skills_lower for s in ["fastapi", "python", "node.js", "react", "next.js", "web development"]):
                tracks.append("fullstack")
            if any(s in skills_lower for s in ["docker", "kubernetes", "ci/cd", "aws", "terraform"]):
                tracks.append("cloud-devops")
            if any(s in skills_lower for s in ["data analysis", "pandas", "statistics", "sql"]):
                tracks.append("data-eng")
            if any(s in skills_lower for s in ["solidity", "smart contract", "ethereum"]):
                tracks.append("blockchain")
            if not tracks:
                tracks.append("fullstack")
            r["tracks"] = tracks

            if track and track != "all" and track not in tracks:
                continue

            # Assign badges
            badges = []
            score = r["employability_score"] or 0
            if score >= 95:
                badges.append({"title": "Top 1% Elite", "icon": "fa-trophy", "color": "#d97706"})
            elif score >= 90:
                badges.append({"title": "Master Engineer", "icon": "fa-medal", "color": "#2563eb"})
            if r["completed_projects"] >= 1:
                badges.append({"title": "Verified Shipper", "icon": "fa-bolt", "color": "#10b981"})
            if r["verified_certificates"] >= 1:
                badges.append({"title": "Cryptographically Verified", "icon": "fa-shield-halved", "color": "#7c3aed"})
            r["badges"] = badges
            r["rank"] = rank
            rank += 1
            leaderboard.append(r)
            if len(leaderboard) >= limit:
                break

        return {"leaderboard": leaderboard, "total_candidates": len(leaderboard)}
    finally:
        conn.close()

# -------------------------------------------------------------------------
# Notification Helper
# -------------------------------------------------------------------------
def create_notification(cursor, user_id: int, title: str, message: str, link: Optional[str] = None):
    """Helper to insert an in-app notification."""
    cursor.execute(
        """
        INSERT INTO notifications (user_id, title, message, link)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, title, message, link)
    )

# -------------------------------------------------------------------------
# Pydantic Request Models
# -------------------------------------------------------------------------
class SkillGapRequest(BaseModel):
    target_role: str
    custom_skills: Optional[List[str]] = None

class MessageSendRequest(BaseModel):
    receiver_id: int
    content: str

class AIReplySuggestRequest(BaseModel):
    other_user_id: int
    incoming_message: Optional[str] = None

class SimulateReplyRequest(BaseModel):
    other_user_id: int
    trigger_content: Optional[str] = None

class VerifyCompanyRequest(BaseModel):
    is_verified: bool

class TeamCreateRequest(BaseModel):
    name: str

class InterviewStartRequest(BaseModel):
    target_role: str

class InterviewAnswerRequest(BaseModel):
    answer: str
    question_index: int

class InterviewHintRequest(BaseModel):
    question_index: int
    current_draft: Optional[str] = ""

class InterviewConverseRequest(BaseModel):
    utterance: str
    turn_index: int = 1
    dialogue_history: Optional[List[Dict[str, Any]]] = []

# =========================================================================
# MODULE 2: AI SKILL ASSESSMENT & PROJECT RECOMMENDATION
# =========================================================================

@router.get("/api/ai/roles")
async def get_target_roles():
    """Returns list of supported career tracks and skills."""
    roles = []
    for role, data in ROLE_TAXONOMY.items():
        roles.append({
            "title": role,
            "description": data["description"],
            "required": data["required"],
            "recommended": data["recommended"]
        })
    return {"roles": roles}

@router.post("/api/ai/skill-gap-analysis")
async def perform_skill_gap_analysis(req: SkillGapRequest, current_user: Optional[dict] = Depends(get_optional_current_user)):
    """Module 2: AI Skill Gap Analysis endpoint for students and visitors."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Determine student skills
        skills = req.custom_skills or []
        if not skills and current_user and current_user.get("role") == "student":
            cursor.execute("SELECT skills FROM student_profiles WHERE user_id = ?", (current_user["id"],))
            p = cursor.fetchone()
            if p and p["skills"]:
                try:
                    skills = json.loads(p["skills"])
                except Exception:
                    skills = []

        # Fetch open projects from the database
        cursor.execute("""
            SELECT p.id, p.title, p.required_skills, p.duration_days, c.company_name
            FROM projects p
            JOIN company_profiles c ON p.company_id = c.id
            WHERE p.status = 'open'
        """)
        open_projects = [dict(row) for row in cursor.fetchall()]

        analysis = analyze_skill_gap(skills, req.target_role, open_projects)
        return {"analysis": analysis}
    finally:
        conn.close()

@router.get("/api/ai/project-recommendations")
async def get_project_recommendations(current_user: dict = Depends(require_role(["student"]))):
    """Module 2: AI Project Matching Engine returning scored and ranked projects."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, skills, employability_score FROM student_profiles WHERE user_id = ?", (current_user["id"],))
        student = cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student profile not found.")

        student_skills = []
        try:
            student_skills = json.loads(student["skills"]) if student["skills"] else []
        except Exception:
            student_skills = []

        student_score = student["employability_score"] or 0.0

        cursor.execute("""
            SELECT p.*, c.company_name, c.is_verified
            FROM projects p
            JOIN company_profiles c ON p.company_id = c.id
            WHERE p.status = 'open'
            ORDER BY p.created_at DESC
        """)
        rows = cursor.fetchall()

        projects = []
        for r in rows:
            p_dict = dict(r)
            try:
                p_dict["required_skills"] = json.loads(p_dict["required_skills"])
            except Exception:
                p_dict["required_skills"] = []
            projects.append(p_dict)

        recommended = match_projects_for_student(student_skills, student_score, projects)
        return {"recommendations": recommended}
    finally:
        conn.close()

# =========================================================================
# MODULE 5: AI EVALUATION & PLAGIARISM DETECTION
# =========================================================================

@router.post("/api/ai/evaluate-submission/{application_id}")
async def evaluate_submission(application_id: int, current_user: dict = Depends(require_role(["company", "admin"]))):
    """
    Module 5: Evaluates student deliverable submission for code quality,
    originality, strengths, and plagiarism risk.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT a.*, p.title as project_title, p.description as project_desc, p.required_skills, p.company_id
            FROM applications a
            JOIN projects p ON a.project_id = p.id
            WHERE a.id = ?
        """, (application_id,))
        app_row = cursor.fetchone()
        if not app_row:
            raise HTTPException(status_code=404, detail="Application not found.")

        if current_user["role"] == "company":
            cursor.execute("SELECT id FROM company_profiles WHERE user_id = ?", (current_user["id"],))
            comp = cursor.fetchone()
            if not comp or comp["id"] != app_row["company_id"]:
                raise HTTPException(status_code=403, detail="Forbidden. You do not own this project.")

        if app_row["status"] not in ["submitted", "graded"]:
            raise HTTPException(status_code=400, detail="Cannot run AI evaluation: No deliverables submitted yet.")

        required_skills = []
        try:
            required_skills = json.loads(app_row["required_skills"]) if app_row["required_skills"] else []
        except Exception:
            pass

        eval_result = evaluate_submission_ai(
            submission_link=app_row["submission_link"] or "",
            submission_notes=app_row["submission_notes"] or "",
            project_title=app_row["project_title"],
            project_desc=app_row["project_desc"],
            required_skills=required_skills
        )

        # Store in ai_evaluations table
        with transaction() as trans_conn:
            t_cursor = trans_conn.cursor()
            t_cursor.execute("DELETE FROM ai_evaluations WHERE application_id = ?", (application_id,))
            t_cursor.execute("""
                INSERT INTO ai_evaluations (
                    application_id, code_quality_score, plagiarism_score,
                    plagiarism_risk, strengths, improvements, ai_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                application_id,
                eval_result["code_quality_score"],
                eval_result["plagiarism_score"],
                eval_result["plagiarism_risk"],
                json.dumps(eval_result["strengths"]),
                json.dumps(eval_result["improvements"]),
                eval_result["ai_summary"]
            ))

        return {"evaluation": eval_result}
    finally:
        conn.close()

@router.get("/api/ai/evaluation/{application_id}")
async def get_saved_ai_evaluation(application_id: int):
    """Retrieve saved AI evaluation for an application."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM ai_evaluations WHERE application_id = ?", (application_id,))
        row = cursor.fetchone()
        if not row:
            return {"evaluation": None}
        r_dict = dict(row)
        try:
            r_dict["strengths"] = json.loads(r_dict["strengths"])
            r_dict["improvements"] = json.loads(r_dict["improvements"])
        except Exception:
            pass
        return {"evaluation": r_dict}
    finally:
        conn.close()

# =========================================================================
# AI INTERVIEW PREPARATION MODULE
# =========================================================================

@router.post("/api/ai/interview/start")
async def start_mock_interview(req: InterviewStartRequest, current_user: Optional[dict] = Depends(get_optional_current_user)):
    """Starts an AI mock technical interview session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        student_id = 1
        if current_user and current_user.get("role") == "student":
            cursor.execute("SELECT id FROM student_profiles WHERE user_id = ?", (current_user["id"],))
            student = cursor.fetchone()
            if student:
                student_id = student["id"]
        elif current_user:
            cursor.execute("SELECT id FROM student_profiles LIMIT 1")
            s = cursor.fetchone()
            if s:
                student_id = s["id"]

        q_info = get_mock_interview_question(req.target_role, 0)
        initial_dialogue = [{
            "index": 0,
            "question": q_info["question"],
            "topic": q_info.get("topic", "General"),
            "keypoints": q_info.get("keypoints", [])
        }]

        with transaction() as trans_conn:
            t_cursor = trans_conn.cursor()
            t_cursor.execute("""
                INSERT INTO mock_interviews (student_id, target_role, dialogue, status)
                VALUES (?, ?, ?, 'in_progress')
            """, (student_id, req.target_role, json.dumps(initial_dialogue)))
            session_id = t_cursor.lastrowid

        return {
            "session_id": session_id,
            "target_role": req.target_role,
            "question_index": 0,
            "total_questions": 3,
            "question": q_info["question"],
            "topic": q_info.get("topic", "General")
        }
    finally:
        conn.close()

@router.post("/api/ai/interview/{session_id}/hint")
async def get_interview_hint_endpoint(
    session_id: int,
    req: InterviewHintRequest,
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """Provides an AI hint or architectural direction for an interview question."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM mock_interviews WHERE id = ?", (session_id,))
        session = cursor.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Interview session not found.")

        dialogue = json.loads(session["dialogue"])
        if req.question_index < 0 or req.question_index >= len(dialogue):
            raise HTTPException(status_code=400, detail="Invalid question index.")

        curr_q = dialogue[req.question_index]
        hint_result = generate_interview_hint(
            target_role=session["target_role"],
            question=curr_q["question"],
            current_draft=req.current_draft or ""
        )
        return hint_result
    finally:
        conn.close()

@router.post("/api/ai/interview/{session_id}/converse")
async def live_interview_converse(
    session_id: int,
    req: InterviewConverseRequest,
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """
    Live interactive conversational turn with Sarah Vance (AI Principal Interviewer).
    Evaluates candidate's spoken utterance and returns Sarah's spoken response + targeted follow-up.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM mock_interviews WHERE id = ?", (session_id,))
        session = cursor.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Interview session not found.")

        target_role = session["target_role"]
        dialogue = json.loads(session["dialogue"]) if session["dialogue"] else []

        turn_result = conduct_live_interview_turn(
            target_role=target_role,
            candidate_utterance=req.utterance,
            dialogue_history=req.dialogue_history or dialogue,
            turn_index=req.turn_index
        )

        dialogue.append({"role": "candidate", "content": req.utterance, "turn": req.turn_index})
        dialogue.append({
            "role": "interviewer",
            "content": turn_result.get("spoken_response", ""),
            "turn": req.turn_index,
            "score": turn_result.get("current_turn_score", 7.5),
            "sentiment": turn_result.get("sentiment", "encouraging")
        })

        with transaction() as trans_conn:
            t_cursor = trans_conn.cursor()
            t_cursor.execute(
                "UPDATE mock_interviews SET dialogue = ? WHERE id = ?",
                (json.dumps(dialogue), session_id)
            )

        return {
            "spoken_response": turn_result.get("spoken_response"),
            "current_turn_score": turn_result.get("current_turn_score", 7.5),
            "sentiment": turn_result.get("sentiment", "encouraging"),
            "suggested_topic": turn_result.get("suggested_topic", "System Architecture"),
            "turn_index": req.turn_index + 1
        }
    finally:
        conn.close()

@router.post("/api/ai/interview/{session_id}/answer")
async def answer_interview_question(session_id: int, req: InterviewAnswerRequest, current_user: Optional[dict] = Depends(get_optional_current_user)):
    """Submits answer to current question, evaluates it, and generates next question or final score."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM mock_interviews WHERE id = ?", (session_id,))
        session = cursor.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Interview session not found.")

        dialogue = json.loads(session["dialogue"])
        curr_q = dialogue[req.question_index]
        
        evaluation = evaluate_interview_answer(session["target_role"], curr_q["question"], req.answer)
        curr_q["student_answer"] = req.answer
        curr_q["evaluation"] = evaluation

        next_index = req.question_index + 1
        is_completed = next_index >= 3

        with transaction() as trans_conn:
            t_cursor = trans_conn.cursor()
            if is_completed:
                scores = [d.get("evaluation", {}).get("score", 7.0) for d in dialogue]
                avg_score = round(sum(scores) / len(scores), 1)
                t_cursor.execute("""
                    UPDATE mock_interviews 
                    SET dialogue = ?, overall_score = ?, status = 'completed'
                    WHERE id = ?
                """, (json.dumps(dialogue), avg_score, session_id))

                # Slight employability score bump for practicing if student profile exists
                try:
                    t_cursor.execute("""
                        UPDATE student_profiles
                        SET employability_score = MIN(100.0, employability_score + 1.5)
                        WHERE id = ?
                    """, (session["student_id"],))
                except Exception:
                    pass

                return {
                    "completed": True,
                    "evaluation": evaluation,
                    "overall_score": avg_score,
                    "dialogue": dialogue
                }
            else:
                next_q_info = get_mock_interview_question(session["target_role"], next_index)
                dialogue.append({
                    "index": next_index,
                    "question": next_q_info["question"],
                    "topic": next_q_info.get("topic", "General"),
                    "keypoints": next_q_info.get("keypoints", [])
                })
                t_cursor.execute("UPDATE mock_interviews SET dialogue = ? WHERE id = ?", (json.dumps(dialogue), session_id))

                return {
                    "completed": False,
                    "evaluation": evaluation,
                    "next_question_index": next_index,
                    "next_question": next_q_info["question"],
                    "next_topic": next_q_info["topic"]
                }
    finally:
        conn.close()

# =========================================================================
# MODULE 6: TALENT POOL ("RECRUIT FROM PORTFOLIO") & PUBLIC CERTIFICATES
# =========================================================================

@router.get("/api/talents")
async def list_talent_pool(
    search: Optional[str] = None,
    skill: Optional[str] = None,
    min_score: Optional[float] = None
):
    """
    Module 6 / Contribution: 'Recruit from Portfolio'.
    Allows companies to discover candidates based on verified project performance.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT s.*, u.email,
                   (SELECT COUNT(*) FROM applications a WHERE a.student_id = s.id AND a.status = 'graded') as completed_projects_count
            FROM student_profiles s
            JOIN users u ON s.user_id = u.id
            WHERE 1=1
        """
        params = []
        if min_score is not None:
            query += " AND s.employability_score >= ?"
            params.append(min_score)
        if search:
            query += " AND (s.name LIKE ? OR s.bio LIKE ?)"
            s_param = f"%{search}%"
            params.extend([s_param, s_param])
        if skill:
            query += " AND s.skills LIKE ?"
            params.append(f"%{skill}%")

        query += " ORDER BY s.employability_score DESC, completed_projects_count DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()

        talents = []
        for r in rows:
            t = dict(r)
            try:
                t["skills"] = json.loads(t["skills"]) if t["skills"] else []
            except Exception:
                t["skills"] = []
            talents.append(t)
        return {"talents": talents}
    finally:
        conn.close()

@router.get("/api/talents/{student_id}")
async def get_talent_portfolio(student_id: int):
    """Module 6: Digital Portfolio Generation endpoint for a student."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT s.*, u.email, u.created_at as joined_date
            FROM student_profiles s
            JOIN users u ON s.user_id = u.id
            WHERE s.id = ?
        """, (student_id,))
        student = cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found.")

        s_dict = dict(student)
        try:
            s_dict["skills"] = json.loads(s_dict["skills"]) if s_dict["skills"] else []
        except Exception:
            s_dict["skills"] = []

        # Completed projects & verified feedback
        cursor.execute("""
            SELECT a.id as application_id, a.grade, a.feedback, a.certificate_uuid, a.submitted_at,
                   p.title as project_title, p.description as project_desc, p.duration_days,
                   c.company_name, c.is_verified
            FROM applications a
            JOIN projects p ON a.project_id = p.id
            JOIN company_profiles c ON p.company_id = c.id
            WHERE a.student_id = ? AND a.status = 'graded'
            ORDER BY a.submitted_at DESC
        """, (student_id,))
        completed = [dict(r) for r in cursor.fetchall()]

        return {
            "student": s_dict,
            "completed_projects": completed,
            "total_certificates": len(completed)
        }
    finally:
        conn.close()

@router.get("/api/certificates/{certificate_uuid}")
async def verify_certificate(certificate_uuid: str):
    """Module 6: Public certificate verification endpoint."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT a.certificate_uuid, a.grade, a.feedback, a.submitted_at,
                   s.name as student_name,
                   p.title as project_title, p.duration_days,
                   c.company_name, c.is_verified
            FROM applications a
            JOIN student_profiles s ON a.student_id = s.id
            JOIN projects p ON a.project_id = p.id
            JOIN company_profiles c ON p.company_id = c.id
            WHERE a.certificate_uuid = ?
        """, (certificate_uuid,))
        cert = cursor.fetchone()
        if not cert:
            raise HTTPException(status_code=404, detail="Certificate not found or invalid.")

        return {
            "verified": True,
            "certificate": dict(cert)
        }
    finally:
        conn.close()

# =========================================================================
# MODULE 7: COMMUNICATION & NOTIFICATION MODULE
# =========================================================================

@router.get("/api/messages/contacts")
async def get_message_contacts(q: Optional[str] = None, role: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Returns available platform contacts (students, companies) to message, including live active status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    uid = current_user["id"]
    try:
        query = "SELECT id, email, role FROM users WHERE id != ?"
        params = [uid]
        if role and role != "all":
            query += " AND role = ?"
            params.append(role)
        query += " ORDER BY id DESC LIMIT 60"
        cursor.execute(query, tuple(params))
        users = cursor.fetchall()

        contacts = []
        for u in users:
            u_id = u["id"]
            u_role = u["role"]
            name = u["email"].split("@")[0].capitalize()
            subtitle = ""
            if u_role == "student":
                cursor.execute("SELECT name, skills, bio FROM student_profiles WHERE user_id = ?", (u_id,))
                sp = cursor.fetchone()
                if sp and sp["name"]:
                    name = sp["name"]
                skills_val = []
                if sp and sp["skills"]:
                    try:
                        import json
                        skills_val = json.loads(sp["skills"])
                    except:
                        pass
                subtitle = ", ".join(skills_val[:3]) if skills_val else (sp["bio"][:45] if sp and sp["bio"] else "Student Candidate")
            elif u_role == "company":
                cursor.execute("SELECT company_name, description FROM company_profiles WHERE user_id = ?", (u_id,))
                cp = cursor.fetchone()
                if cp and cp["company_name"]:
                    name = cp["company_name"]
                subtitle = cp["description"][:50] if cp and cp["description"] else "Verified Partner Organization"
            elif u_role == "admin":
                name = "BridgeSkill Admin"
                subtitle = "Platform Support & Moderation"

            # Search filter
            if q:
                ql = q.lower().strip()
                if ql not in name.lower() and ql not in u["email"].lower() and ql not in subtitle.lower():
                    continue

            # Deterministic/rich active status
            # 80% active online, others active recently
            is_online = (u_id % 4 != 0)
            active_status = "online" if is_online else "away"
            status_text = "Active Now" if is_online else "Active 15m ago"

            contacts.append({
                "user_id": u_id,
                "name": name,
                "email": u["email"],
                "role": u_role,
                "subtitle": subtitle,
                "active_status": active_status,
                "status_text": status_text
            })

        return {"contacts": contacts}
    finally:
        conn.close()

@router.get("/api/messages/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user)):
    """Returns list of active chat conversations with last message, active status and unread count."""
    conn = get_db_connection()
    cursor = conn.cursor()
    uid = current_user["id"]
    try:
        # Get all distinct user IDs current user has chatted with
        cursor.execute("""
            SELECT DISTINCT
                CASE WHEN sender_id = ? THEN receiver_id ELSE sender_id END as other_user_id
            FROM messages
            WHERE sender_id = ? OR receiver_id = ?
        """, (uid, uid, uid))
        contact_rows = cursor.fetchall()

        conversations = []
        for crow in contact_rows:
            other_id = crow["other_user_id"]
            # Fetch user info
            cursor.execute("SELECT id, email, role FROM users WHERE id = ?", (other_id,))
            other_u = cursor.fetchone()
            if not other_u:
                continue

            name = other_u["email"]
            if other_u["role"] == "student":
                cursor.execute("SELECT name FROM student_profiles WHERE user_id = ?", (other_id,))
                p = cursor.fetchone()
                if p and p["name"]: name = p["name"]
            elif other_u["role"] == "company":
                cursor.execute("SELECT company_name FROM company_profiles WHERE user_id = ?", (other_id,))
                c = cursor.fetchone()
                if c and c["company_name"]: name = c["company_name"]
            elif other_u["role"] == "admin":
                name = "BridgeSkill Admin"

            # Fetch last message
            cursor.execute("""
                SELECT content, sent_at, sender_id
                FROM messages
                WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
                ORDER BY sent_at DESC LIMIT 1
            """, (uid, other_id, other_id, uid))
            last_msg = cursor.fetchone()

            # Count unread messages
            cursor.execute("""
                SELECT COUNT(*) as unread_count
                FROM messages
                WHERE sender_id = ? AND receiver_id = ? AND is_read = 0
            """, (other_id, uid))
            unread = cursor.fetchone()["unread_count"]

            is_online = (other_id % 4 != 0)
            conversations.append({
                "other_user_id": other_id,
                "name": name,
                "role": other_u["role"],
                "last_message": last_msg["content"] if last_msg else "",
                "last_sent_at": last_msg["sent_at"] if last_msg else "",
                "unread_count": unread,
                "active_status": "online" if is_online else "away",
                "status_text": "Active Now" if is_online else "Active 10m ago"
            })

        conversations.sort(key=lambda x: x["last_sent_at"] or "", reverse=True)
        return {"conversations": conversations}
    finally:
        conn.close()

@router.get("/api/messages/{other_user_id}")
async def get_chat_history(other_user_id: int, current_user: dict = Depends(get_current_user)):
    """Returns message history between current user and specified user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    uid = current_user["id"]
    try:
        # Mark incoming as read
        with transaction() as trans_conn:
            t_cursor = trans_conn.cursor()
            t_cursor.execute("""
                UPDATE messages SET is_read = 1
                WHERE sender_id = ? AND receiver_id = ?
            """, (other_user_id, uid))

        cursor.execute("""
            SELECT * FROM messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY sent_at ASC
        """, (uid, other_user_id, other_user_id, uid))
        msgs = [dict(r) for r in cursor.fetchall()]
        return {"messages": msgs}
    finally:
        conn.close()

@router.post("/api/messages/send")
async def send_message(req: MessageSendRequest, current_user: dict = Depends(get_current_user)):
    """Sends a message and creates a notification for the recipient with smart recipient resolution."""
    uid = current_user["id"]
    try:
        with transaction() as conn:
            cursor = conn.cursor()
            
            # Resolve receiver_id to a valid users(id)
            target_user_id = req.receiver_id
            cursor.execute("SELECT id FROM users WHERE id = ?", (target_user_id,))
            if not cursor.fetchone():
                # Check if receiver_id was a student_profiles.id
                cursor.execute("SELECT user_id FROM student_profiles WHERE id = ?", (target_user_id,))
                sp = cursor.fetchone()
                if sp and sp["user_id"]:
                    target_user_id = sp["user_id"]
                else:
                    # Check if receiver_id was a company_profiles.id
                    cursor.execute("SELECT user_id FROM company_profiles WHERE id = ?", (target_user_id,))
                    cp = cursor.fetchone()
                    if cp and cp["user_id"]:
                        target_user_id = cp["user_id"]

            # Double-check sender exists in users
            cursor.execute("SELECT id FROM users WHERE id = ?", (uid,))
            if not cursor.fetchone():
                cursor.execute("SELECT id FROM users WHERE email = ?", (current_user.get("email"),))
                u = cursor.fetchone()
                if u:
                    uid = u["id"]

            cursor.execute("""
                INSERT INTO messages (sender_id, receiver_id, content)
                VALUES (?, ?, ?)
            """, (uid, target_user_id, req.content))
            msg_id = cursor.lastrowid

            # Create notification for recipient
            sender_name = current_user.get("email", "A user")
            try:
                create_notification(
                    cursor,
                    user_id=target_user_id,
                    title="New Message",
                    message=f"You received a new message: '{req.content[:40]}...'",
                    link="#messages"
                )
            except Exception:
                pass

            return {"message_id": msg_id, "status": "sent"}
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail="Unable to send message: Recipient account does not exist or was removed.")
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/messages/ai-reply-suggest")
async def ai_reply_suggest(req: AIReplySuggestRequest, current_user: dict = Depends(get_current_user)):
    """Generates context-aware smart quick replies and a full draft reply using AI."""
    from backend.app.ai_service import call_llm
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch other user details
        cursor.execute("SELECT id, email, role FROM users WHERE id = ?", (req.other_user_id,))
        other_u = cursor.fetchone()
        other_name = other_u["email"].split("@")[0] if other_u else "Contact"
        other_role = other_u["role"] if other_u else "member"

        incoming = req.incoming_message or ""
        if not incoming:
            cursor.execute("""
                SELECT content FROM messages 
                WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
                ORDER BY sent_at DESC LIMIT 1
            """, (req.other_user_id, current_user["id"], current_user["id"], req.other_user_id))
            last = cursor.fetchone()
            if last:
                incoming = last["content"]

        my_role = current_user.get("role", "user")

        # Fallback quick replies depending on role
        if my_role == "company":
            default_chips = [
                "👋 Hi! Thanks for connecting. We'd love to chat about opportunities.",
                "📅 Are you available for a brief 15-minute sync this week?",
                "🚀 Great work on the project milestones! We reviewed your code."
            ]
            default_draft = f"Hi {other_name}, thanks for reaching out. We reviewed your recent micro-project work on BridgeSkill and were very impressed. Would you be free for a brief 15-minute call sometime this week to discuss potential opportunities?"
        else:
            default_chips = [
                "👋 Hello! Thank you for the message, looking forward to discussing.",
                "📄 I have submitted my micro-project solution and test suite.",
                "✅ Sounds great! I'm available anytime tomorrow afternoon."
            ]
            default_draft = f"Hello {other_name}, thank you for reaching out! I'm excited about this project opportunity and would be glad to discuss my background and project code whenever you're ready."

        # Attempt LLM generation
        try:
            prompt = f"""You are a professional assistant on BridgeSkill platform helping a {my_role} reply to {other_name} ({other_role}).
Incoming message: "{incoming}"
Return strict JSON with two fields:
"quick_replies": a list of exactly 3 short sentence options (max 10 words each)
"draft_reply": a polite, professional complete message (2-3 sentences)."""
            import json
            raw = call_llm(prompt, system_prompt="You are an expert career messaging assistant. Output valid JSON only.", json_mode=True)
            if raw:
                parsed = json.loads(raw)
                return {
                    "quick_replies": parsed.get("quick_replies", default_chips),
                    "draft_reply": parsed.get("draft_reply", default_draft)
                }
        except Exception:
            pass

        return {
            "quick_replies": default_chips,
            "draft_reply": default_draft
        }
    finally:
        conn.close()

@router.post("/api/messages/simulate-reply")
async def simulate_reply(req: SimulateReplyRequest, current_user: dict = Depends(get_current_user)):
    """Simulates an instant realistic reply from the other contact (demo / test interaction)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    uid = current_user["id"]
    try:
        cursor.execute("SELECT id, email, role FROM users WHERE id = ?", (req.other_user_id,))
        other_u = cursor.fetchone()
        if not other_u:
            raise HTTPException(status_code=404, detail="User not found")

        other_role = other_u["role"]
        other_name = other_u["email"].split("@")[0].capitalize()
        if other_role == "student":
            cursor.execute("SELECT name FROM student_profiles WHERE user_id = ?", (req.other_user_id,))
            sp = cursor.fetchone()
            if sp and sp["name"]: other_name = sp["name"]
        elif other_role == "company":
            cursor.execute("SELECT company_name FROM company_profiles WHERE user_id = ?", (req.other_user_id,))
            cp = cursor.fetchone()
            if cp and cp["company_name"]: other_name = cp["company_name"]

        trigger = req.trigger_content or "Hello"

        # Realistic reply logic
        if other_role == "student":
            replies = [
                f"Hi! Thank you for reaching out. I'm actively working on micro-projects and would love to collaborate. I have pushed my latest changes to GitHub for your review!",
                f"Hello! Thanks for your response regarding '{trigger[:30]}...'. I'm available anytime for a quick technical discussion or code walkthrough.",
                f"Thank you! I really enjoyed completing the practical challenge. Looking forward to discussing the next steps!"
            ]
        elif other_role == "company":
            replies = [
                f"Hello! Thanks for following up on '{trigger[:30]}...'. We checked your verified micro-project credential and were very impressed with your score. Let's set up a quick 15-minute call!",
                f"Hi! Thank you for the update. Our engineering team reviewed your submission and we'd like to invite you for an interview.",
                f"Thanks for reaching out! We are currently screening candidates for our upcoming cohort and your skill profile stands out."
            ]
        else:
            replies = [f"BridgeSkill Support here! We received your message and our team is standing by to assist with any questions."]

        import random
        reply_content = random.choice(replies)

        with transaction() as t_conn:
            t_cursor = t_conn.cursor()
            t_cursor.execute("""
                INSERT INTO messages (sender_id, receiver_id, content)
                VALUES (?, ?, ?)
            """, (req.other_user_id, uid, reply_content))
            msg_id = t_cursor.lastrowid

            create_notification(
                t_cursor,
                user_id=uid,
                title=f"New Message from {other_name}",
                message=f"{reply_content[:45]}...",
                link="#messages"
            )

        return {"message_id": msg_id, "content": reply_content, "sender_name": other_name, "status": "sent"}
    finally:
        conn.close()

@router.get("/api/notifications")
async def get_notifications(current_user: dict = Depends(get_current_user)):
    """Fetches user notifications."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT * FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 30
        """, (current_user["id"],))
        rows = [dict(r) for r in cursor.fetchall()]
        unread = sum(1 for r in rows if r["is_read"] == 0)
        return {"notifications": rows, "unread_count": unread}
    finally:
        conn.close()

@router.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int, current_user: dict = Depends(get_current_user)):
    """Marks a notification as read."""
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notification_id, current_user["id"]))
    return {"status": "ok"}

@router.post("/api/notifications/read-all")
async def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    """Marks all notifications as read."""
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (current_user["id"],))
    return {"status": "ok"}

# =========================================================================
# MODULE 8: ADMIN DASHBOARD
# =========================================================================

@router.get("/api/admin/stats")
async def get_admin_stats(current_user: dict = Depends(require_role(["admin"]))):
    """Module 8: System-wide KPI metrics and analytics."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student'")
        total_students = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'company'")
        total_companies = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM company_profiles WHERE is_verified = 1")
        verified_companies = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM projects")
        total_projects = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM projects WHERE status = 'open'")
        active_projects = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM projects WHERE status = 'completed'")
        completed_projects = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM applications")
        total_applications = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM applications WHERE status = 'graded'")
        total_certificates = cursor.fetchone()["cnt"]

        cursor.execute("SELECT AVG(employability_score) as avg_score FROM student_profiles")
        avg_score_row = cursor.fetchone()["avg_score"]
        avg_employability = round(avg_score_row, 1) if avg_score_row else 0.0

        return {
            "stats": {
                "total_students": total_students,
                "total_companies": total_companies,
                "verified_companies": verified_companies,
                "total_projects": total_projects,
                "active_projects": active_projects,
                "completed_projects": completed_projects,
                "total_applications": total_applications,
                "total_certificates": total_certificates,
                "average_employability": avg_employability
            }
        }
    finally:
        conn.close()

@router.get("/api/admin/companies")
async def admin_list_companies(current_user: dict = Depends(require_role(["admin"]))):
    """Module 8: Review company verification queue to mitigate platform fraud."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT c.*, u.email, u.created_at,
                   (SELECT COUNT(*) FROM projects p WHERE p.company_id = c.id) as project_count
            FROM company_profiles c
            JOIN users u ON c.user_id = u.id
            ORDER BY c.is_verified ASC, u.created_at DESC
        """)
        companies = [dict(r) for r in cursor.fetchall()]
        return {"companies": companies}
    finally:
        conn.close()

@router.post("/api/admin/companies/{company_id}/verify")
async def admin_toggle_company_verification(
    company_id: int,
    req: VerifyCompanyRequest,
    current_user: dict = Depends(require_role(["admin"]))
):
    """Module 8: Admin verifies or revokes company legitimacy."""
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, company_name FROM company_profiles WHERE id = ?", (company_id,))
        comp = cursor.fetchone()
        if not comp:
            raise HTTPException(status_code=404, detail="Company profile not found.")

        cursor.execute("UPDATE company_profiles SET is_verified = ? WHERE id = ?", (1 if req.is_verified else 0, company_id))

        status_text = "Verified" if req.is_verified else "Revoked"
        create_notification(
            cursor,
            user_id=comp["user_id"],
            title="Verification Update",
            message=f"Your company profile '{comp['company_name']}' is now {status_text} by platform administrators.",
            link="#dashboard"
        )

        return {"message": f"Company status updated to {status_text}."}

@router.get("/api/admin/projects")
async def admin_list_projects(current_user: dict = Depends(require_role(["admin"]))):
    """Module 8: Moderates posted projects."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT p.*, c.company_name, c.is_verified,
                   (SELECT COUNT(*) FROM applications a WHERE a.project_id = p.id) as application_count
            FROM projects p
            JOIN company_profiles c ON p.company_id = c.id
            ORDER BY p.created_at DESC
        """)
        projects = [dict(r) for r in cursor.fetchall()]
        return {"projects": projects}
    finally:
        conn.close()

@router.delete("/api/admin/projects/{project_id}")
async def admin_delete_project(project_id: int, current_user: dict = Depends(require_role(["admin"]))):
    """Module 8: Deletes inappropriate or spam project."""
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return {"message": "Project removed by administrator."}

@router.get("/api/admin/users")
async def admin_list_users(current_user: dict = Depends(require_role(["admin"]))):
    """Module 8: Lists users for platform moderation."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT u.id, u.email, u.role, u.created_at,
                   COALESCE(s.name, c.company_name, 'Admin') as display_name
            FROM users u
            LEFT JOIN student_profiles s ON u.id = s.user_id
            LEFT JOIN company_profiles c ON u.id = c.user_id
            ORDER BY u.created_at DESC
        """)
        users = [dict(r) for r in cursor.fetchall()]
        return {"users": users}
    finally:
        conn.close()

@router.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, current_user: dict = Depends(require_role(["admin"]))):
    """Module 8: Removes fraudulent user profile."""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account.")
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"message": "User deleted successfully."}

# =========================================================================
# TEAM-BASED MICRO PROJECTS
# =========================================================================

@router.post("/api/projects/{project_id}/teams")
async def create_project_team(
    project_id: int,
    req: TeamCreateRequest,
    current_user: dict = Depends(require_role(["student"]))
):
    """Allows students to create collaborative teams for complex micro-projects."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM student_profiles WHERE user_id = ?", (current_user["id"],))
        student = cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student profile not found.")

        with transaction() as trans_conn:
            t_cursor = trans_conn.cursor()
            t_cursor.execute("""
                INSERT INTO teams (project_id, name, leader_student_id)
                VALUES (?, ?, ?)
            """, (project_id, req.name, student["id"]))
            team_id = t_cursor.lastrowid

            t_cursor.execute("""
                INSERT INTO team_members (team_id, student_id, status)
                VALUES (?, ?, 'accepted')
            """, (team_id, student["id"]))

        return {"team_id": team_id, "name": req.name, "message": "Team created successfully."}
    finally:
        conn.close()

@router.get("/api/projects/{project_id}/teams")
async def list_project_teams(project_id: int):
    """Returns active student teams formed for a project."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT t.*, s.name as leader_name,
                   (SELECT COUNT(*) FROM team_members m WHERE m.team_id = t.id) as member_count
            FROM teams t
            JOIN student_profiles s ON t.leader_student_id = s.id
            WHERE t.project_id = ?
        """, (project_id,))
        teams = [dict(r) for r in cursor.fetchall()]
        return {"teams": teams}
    finally:
        conn.close()

@router.post("/api/teams/{team_id}/join")
async def join_team(team_id: int, current_user: dict = Depends(require_role(["student"]))):
    """Student joins an existing project team."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM student_profiles WHERE user_id = ?", (current_user["id"],))
        student = cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student profile not found.")

        cursor.execute("SELECT * FROM team_members WHERE team_id = ? AND student_id = ?", (team_id, student["id"]))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="You are already a member of this team.")

        with transaction() as trans_conn:
            t_cursor = trans_conn.cursor()
            t_cursor.execute("INSERT INTO team_members (team_id, student_id, status) VALUES (?, ?, 'accepted')", (team_id, student["id"]))

        return {"message": "Joined team successfully."}
    finally:
        conn.close()
