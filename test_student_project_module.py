import os
import sys
import unittest
from fastapi.testclient import TestClient

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from backend.app.main import app
from backend.app.db import init_db, get_db_connection, Base, engine, SessionLocal
from modules.student_project import ProjectApplication, ProjectSubmission, Project, StudentProfile, CompanyProfile

client = TestClient(app)

class TestStudentProjectWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Re-init db schema
        init_db()
        Base.metadata.create_all(bind=engine)
        
        # Create test users and company project
        # 1. Company
        res_comp = client.post("/api/auth/register", json={
            "email": f"company_test_{os.getpid()}@test.com",
            "password": "Password123!",
            "role": "company",
            "companyName": "TechBridge Global"
        })
        cls.comp_token = res_comp.json().get("token")
        
        # 2. Student
        res_student = client.post("/api/auth/register", json={
            "email": f"student_test_{os.getpid()}@test.com",
            "password": "Password123!",
            "role": "student",
            "name": "Jane Student"
        })
        cls.student_token = res_student.json().get("token")
        cls.student_user_id = res_student.json()["user"]["id"]
        
        # 3. Create a project under company
        res_proj = client.post("/api/projects", json={
            "title": "AI Recommendation Engine Micro-Project",
            "description": "Develop a FastAPI microservice for cosine similarity recommendation.",
            "required_skills": ["Python", "FastAPI", "Machine Learning"],
            "duration_days": 14
        }, headers={"Authorization": f"Bearer {cls.comp_token}"})
        cls.project_id = res_proj.json()["project"]["id"]

    def test_01_browse_active_projects(self):
        """Test GET /student/projects/ endpoint"""
        res = client.get("/student/projects/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("projects", data)
        self.assertGreaterEqual(data["count"], 1)
        
        # Check project attributes
        proj = next((p for p in data["projects"] if p["id"] == self.project_id), None)
        self.assertIsNotNone(proj)
        self.assertEqual(proj["title"], "AI Recommendation Engine Micro-Project")
        self.assertEqual(proj["company_name"], "TechBridge Global")
        self.assertIn("Python", proj["required_skills"])
        self.assertEqual(proj["status"], "open")

    def test_02_apply_to_project(self):
        """Test POST /student/projects/{project_id}/apply endpoint"""
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = client.post(
            f"/student/projects/{self.project_id}/apply",
            json={"cover_letter": "I am passionate about AI and experienced with FastAPI."},
            headers=headers
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertIn("application", data)
        app_data = data["application"]
        self.assertEqual(app_data["project_id"], self.project_id)
        self.assertEqual(app_data["status"], "pending")
        self.assertIsNotNone(app_data["applied_at"])
        self.assertEqual(app_data["cover_letter"], "I am passionate about AI and experienced with FastAPI.")
        
        # Verify in DB via SQLAlchemy Session
        db = SessionLocal()
        try:
            db_app = db.query(ProjectApplication).filter(ProjectApplication.id == app_data["id"]).first()
            self.assertIsNotNone(db_app)
            self.assertEqual(db_app.status, "pending")
            self.assertEqual(db_app.project_id, self.project_id)
        finally:
            db.close()

    def test_03_prevent_duplicate_application(self):
        """Verify student cannot apply twice to the same project"""
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = client.post(
            f"/student/projects/{self.project_id}/apply",
            json={"cover_letter": "Duplicate attempt"},
            headers=headers
        )
        self.assertEqual(res.status_code, 400)

    def test_04_submit_deliverables_validation(self):
        """Verify cannot submit while application is pending"""
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = client.post(
            f"/student/projects/{self.project_id}/submit",
            json={"submission_url": "https://github.com/student/ai-recommender", "notes": "Initial draft"},
            headers=headers
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("pending", res.json()["detail"])

    def test_05_accept_application_and_submit_deliverables(self):
        """Accept the application and test POST /student/projects/{project_id}/submit"""
        # Accept application directly or in DB
        db = SessionLocal()
        try:
            app_record = db.query(ProjectApplication).filter(
                ProjectApplication.project_id == self.project_id
            ).first()
            self.assertIsNotNone(app_record)
            app_record.status = "accepted"
            db.commit()
            app_id = app_record.id
        finally:
            db.close()

        # Submit deliverables via JSON
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = client.post(
            f"/student/projects/{self.project_id}/submit",
            json={
                "submission_url": "https://github.com/student/ai-recommender",
                "notes": "Completed all cosine similarity endpoints and documentation."
            },
            headers=headers
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertIn("submission", data)
        sub_data = data["submission"]
        self.assertEqual(sub_data["application_id"], app_id)
        self.assertEqual(sub_data["submission_url"], "https://github.com/student/ai-recommender")
        self.assertEqual(sub_data["notes"], "Completed all cosine similarity endpoints and documentation.")
        self.assertIsNotNone(sub_data["submitted_at"])
        self.assertIsNone(sub_data["grade"])

        # Verify submission in DB via SQLAlchemy Session
        db = SessionLocal()
        try:
            db_sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == sub_data["id"]).first()
            self.assertIsNotNone(db_sub)
            self.assertEqual(db_sub.application_id, app_id)
            self.assertEqual(db_sub.submission_url, "https://github.com/student/ai-recommender")
        finally:
            db.close()

    def test_06_submit_deliverable_file_upload(self):
        """Test POST /student/projects/{project_id}/submit-file multipart upload"""
        headers = {"Authorization": f"Bearer {self.student_token}"}
        fake_file_content = b"Deliverable zip package simulation content"
        files = {
            "file": ("deliverable.zip", fake_file_content, "application/zip")
        }
        data = {
            "submission_url": "https://github.com/student/ai-recommender/releases/tag/v1.0",
            "notes": "Attached zip archive containing source code and models."
        }
        res = client.post(
            f"/student/projects/{self.project_id}/submit-file",
            data=data,
            files=files,
            headers=headers
        )
        self.assertEqual(res.status_code, 201)
        res_json = res.json()
        self.assertIn("submission", res_json)
        self.assertIn("/uploads/submissions/", res_json["submission"]["file_path"])

    def test_07_get_student_applications_history(self):
        """Test GET /student/projects/applications/my endpoint"""
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = client.get("/student/projects/applications/my", headers=headers)
        self.assertEqual(res.status_code, 200)
        res_json = res.json()
        self.assertIn("applications", res_json)
        self.assertGreaterEqual(len(res_json["applications"]), 1)
        my_app = res_json["applications"][0]
        self.assertEqual(my_app["project_id"], self.project_id)
        self.assertGreaterEqual(len(my_app["submissions"]), 2)

if __name__ == "__main__":
    unittest.main()
