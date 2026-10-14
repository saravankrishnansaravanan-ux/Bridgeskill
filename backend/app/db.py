import sqlite3
import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

if os.environ.get("VERCEL"):
    import shutil
    TMP_DB = "/tmp/database.db"
    SRC_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../database.db"))
    if not os.path.exists(TMP_DB) and os.path.exists(SRC_DB):
        try:
            shutil.copyfile(SRC_DB, TMP_DB)
        except Exception as e:
            print(f"[Vercel DB copy]: {e}")
    DB_PATH = TMP_DB
else:
    DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../database.db"))

DATABASE_URL = f"sqlite:///{DB_PATH}"

# SQLAlchemy Setup
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """FastAPI Dependency for SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def transaction():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    with transaction() as conn:
        cursor = conn.cursor()
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT CHECK(role IN ('student', 'company', 'admin')) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Student profiles table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                skills TEXT DEFAULT '[]',
                bio TEXT,
                employability_score REAL DEFAULT 0.0,
                resume_url TEXT,
                portfolio_url TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Company profiles table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                company_name TEXT NOT NULL,
                description TEXT,
                website TEXT,
                is_verified INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Projects table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                required_skills TEXT DEFAULT '[]',
                duration_days INTEGER NOT NULL,
                status TEXT CHECK(status IN ('open', 'in_progress', 'completed')) DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES company_profiles(id) ON DELETE CASCADE
            )
        """)
        
        # Applications table (legacy/general)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                status TEXT CHECK(status IN ('applied', 'accepted', 'rejected', 'submitted', 'graded')) DEFAULT 'applied',
                cover_letter TEXT,
                submission_link TEXT,
                submission_notes TEXT,
                grade REAL,
                feedback TEXT,
                certificate_uuid TEXT,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                submitted_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student_profiles(id) ON DELETE CASCADE
            )
        """)

        # Project Applications table (Module 3 - Student Project Workspace)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                status TEXT CHECK(status IN ('pending', 'accepted', 'rejected')) DEFAULT 'pending',
                cover_letter TEXT,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student_profiles(id) ON DELETE CASCADE
            )
        """)

        # Project Submissions table (Module 3 - Student Project Workspace)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                submission_url TEXT,
                file_path TEXT,
                notes TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                grade REAL,
                FOREIGN KEY (application_id) REFERENCES project_applications(id) ON DELETE CASCADE
            )
        """)
        
        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Notifications table (Module 7)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                link TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Teams table (Team-Based Micro Projects)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                leader_student_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (leader_student_id) REFERENCES student_profiles(id) ON DELETE CASCADE
            )
        """)

        # Team Members table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS team_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                status TEXT DEFAULT 'accepted',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student_profiles(id) ON DELETE CASCADE
            )
        """)

        # AI Evaluations table (Module 5)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                code_quality_score REAL,
                plagiarism_score REAL,
                plagiarism_risk TEXT,
                strengths TEXT,
                improvements TEXT,
                ai_summary TEXT,
                evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
            )
        """)

        # Mock Interviews table (AI Interview Preparation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mock_interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                target_role TEXT NOT NULL,
                dialogue TEXT DEFAULT '[]',
                overall_score REAL DEFAULT 0.0,
                feedback TEXT,
                status TEXT DEFAULT 'in_progress',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES student_profiles(id) ON DELETE CASCADE
            )
        """)

        # Safe Column Migrations
        try:
            cursor.execute("ALTER TABLE projects ADD COLUMN max_team_size INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

    # Populate diverse verified industry micro-projects curriculum
    try:
        from backend.app.seed_projects import seed_verified_curriculum
        from backend.app.seed_talents import seed_verified_talents
        with transaction() as conn:
            seed_verified_curriculum(conn, clean_duplicates=False)
            seed_verified_talents(conn)
    except Exception as e:
        print(f"[BridgeSkill DB] Notice on curriculum/talent seed check: {e}")

# Initialize database tables
init_db()

