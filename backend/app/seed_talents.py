import json
import sqlite3
import uuid
from backend.app.auth import hash_password

TALENTS_SEED = [
    {
        "email": "alex.chen@bridgeskill.dev",
        "name": "Alex Chen",
        "skills": ["Python", "FastAPI", "React", "Docker", "SQL", "JavaScript", "Microservices"],
        "bio": "Full-Stack Software Engineer building high-throughput microservices, clean API gateways, and real-time React web applications.",
        "employability_score": 94.5,
        "resume_url": "https://bridgeskill.io/resumes/alex-chen.pdf",
        "portfolio_url": "https://github.com/alexchen-dev",
        "project_title": "High-Throughput Distributed Rate Limiter & API Gateway",
        "grade": 4.9,
        "feedback": "Outstanding implementation of token-bucket algorithm with low latency Redis caching and unit test coverage."
    },
    {
        "email": "priya.sharma@bridgeskill.dev",
        "name": "Priya Sharma",
        "skills": ["Python", "Machine Learning", "PyTorch", "NLP", "LLMs", "FastAPI", "Vector DB"],
        "bio": "AI/ML Engineer specializing in Retrieval-Augmented Generation (RAG), vector embeddings, and deploying real-time inference microservices.",
        "employability_score": 96.0,
        "resume_url": "https://bridgeskill.io/resumes/priya-sharma.pdf",
        "portfolio_url": "https://github.com/priyasharma-ai",
        "project_title": "RAG-Powered Technical Documentation Assistant with Vector Search",
        "grade": 5.0,
        "feedback": "Exceptional vector retrieval latency and hallucination mitigation techniques. Production-ready architecture."
    },
    {
        "email": "marcus.vance@bridgeskill.dev",
        "name": "Marcus Vance",
        "skills": ["Docker", "Kubernetes", "Linux", "CI/CD", "AWS", "Terraform", "GitHub Actions"],
        "bio": "Cloud & DevOps Specialist focused on automated GitOps pipelines, Helm charts, and multi-region Kubernetes clusters.",
        "employability_score": 92.0,
        "resume_url": "https://bridgeskill.io/resumes/marcus-vance.pdf",
        "portfolio_url": "https://github.com/marcusvance-ops",
        "project_title": "Automated Kubernetes Microservices Deployment with GitOps & CI/CD",
        "grade": 4.8,
        "feedback": "Robust multi-stage Docker builds with automated linting and zero-downtime rolling updates."
    },
    {
        "email": "sophia.martinez@bridgeskill.dev",
        "name": "Sophia Martinez",
        "skills": ["Python", "SQL", "Data Analysis", "Pandas", "Statistics", "Data Visualization", "Machine Learning"],
        "bio": "Data Scientist turning clickstream telemetry and financial datasets into actionable predictive customer churn analytics.",
        "employability_score": 91.5,
        "resume_url": "https://bridgeskill.io/resumes/sophia-martinez.pdf",
        "portfolio_url": "https://github.com/sophiamartinez-data",
        "project_title": "Customer Churn Prediction & Multi-Channel Marketing Attribution",
        "grade": 4.7,
        "feedback": "Rigorous exploratory data analysis with clean feature engineering and uplift metric validation."
    },
    {
        "email": "kavita.patel@bridgeskill.dev",
        "name": "Kavita Patel",
        "skills": ["JavaScript", "React", "Next.js", "Node.js", "WebSocket", "TailwindCSS", "SQL"],
        "bio": "Frontend & Full-Stack developer crafting real-time collaborative workspaces, state persistence, and fluid UI design systems.",
        "employability_score": 93.0,
        "resume_url": "https://bridgeskill.io/resumes/kavita-patel.pdf",
        "portfolio_url": "https://github.com/kavitapatel-web",
        "project_title": "Next.js Real-Time Collaborative Canvas & Whiteboard",
        "grade": 4.9,
        "feedback": "Flawless WebSocket synchronization and intuitive multi-cursor presence indicators."
    },
    {
        "email": "david.kim@bridgeskill.dev",
        "name": "David Kim",
        "skills": ["Security", "Python", "FastAPI", "SQL", "REST API", "Networking", "OAuth2"],
        "bio": "Cybersecurity & Backend Engineer experienced in zero-trust architecture, OAuth2/OIDC with PKCE, and automated vulnerability scanning.",
        "employability_score": 95.0,
        "resume_url": "https://bridgeskill.io/resumes/david-kim.pdf",
        "portfolio_url": "https://github.com/davidkim-sec",
        "project_title": "Zero-Trust OAuth2/OIDC Enterprise Identity Provider & Security Audit",
        "grade": 5.0,
        "feedback": "Strict PKCE verification, robust token rotation, and zero high/medium OWASP vulnerabilities detected."
    }
]

def seed_verified_talents(conn: sqlite3.Connection):
    cursor = conn.cursor()

    for item in TALENTS_SEED:
        cursor.execute("SELECT id FROM users WHERE email = ?", (item["email"],))
        user_row = cursor.fetchone()
        if not user_row:
            pwd_hash = hash_password("TalentPass2026!")
            cursor.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'student')",
                (item["email"], pwd_hash)
            )
            user_id = cursor.lastrowid
        else:
            user_id = user_row[0]

        cursor.execute("SELECT id FROM student_profiles WHERE user_id = ?", (user_id,))
        prof_row = cursor.fetchone()
        if not prof_row:
            cursor.execute(
                """
                INSERT INTO student_profiles (user_id, name, skills, bio, employability_score, resume_url, portfolio_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    item["name"],
                    json.dumps(item["skills"]),
                    item["bio"],
                    item["employability_score"],
                    item["resume_url"],
                    item["portfolio_url"]
                )
            )
            student_id = cursor.lastrowid
        else:
            student_id = prof_row[0]
            cursor.execute(
                """
                UPDATE student_profiles
                SET name = ?, skills = ?, bio = ?, employability_score = ?, resume_url = ?, portfolio_url = ?
                WHERE id = ?
                """,
                (
                    item["name"],
                    json.dumps(item["skills"]),
                    item["bio"],
                    item["employability_score"],
                    item["resume_url"],
                    item["portfolio_url"],
                    student_id
                )
            )

        # Ensure verified completed project application exists
        cursor.execute("SELECT id FROM projects WHERE title = ?", (item["project_title"],))
        proj_row = cursor.fetchone()
        if proj_row:
            proj_id = proj_row[0]
            cursor.execute(
                "SELECT id FROM applications WHERE student_id = ? AND project_id = ?",
                (student_id, proj_id)
            )
            app_row = cursor.fetchone()
            cert_id = f"CERT-VERIFIED-{uuid.uuid4().hex[:8].upper()}"
            if not app_row:
                cursor.execute(
                    """
                    INSERT INTO applications (project_id, student_id, status, cover_letter, submission_link, submission_notes, grade, feedback, certificate_uuid, submitted_at)
                    VALUES (?, ?, 'graded', 'Excited to deliver this production-grade project.', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        proj_id,
                        student_id,
                        item["portfolio_url"],
                        "Delivered comprehensive solution with full unit test coverage and containerization.",
                        item["grade"],
                        item["feedback"],
                        cert_id
                    )
                )
            else:
                cursor.execute(
                    """
                    UPDATE applications
                    SET status = 'graded', grade = ?, feedback = ?, certificate_uuid = COALESCE(certificate_uuid, ?)
                    WHERE id = ?
                    """,
                    (item["grade"], item["feedback"], cert_id, app_row[0])
                )

    conn.commit()
