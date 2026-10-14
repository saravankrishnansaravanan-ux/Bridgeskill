import os
import sys
import unittest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from backend.app.main import app
from backend.app.db import init_db

client = TestClient(app)

class TestAllBridgeSkillFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        pid = os.getpid()
        # Admin
        res_adm = client.post("/api/auth/register", json={
            "email": f"admin_feat_{pid}@test.com",
            "password": "Password123!",
            "role": "admin"
        })
        cls.adm_token = res_adm.json().get("token")

        # Company
        res_cmp = client.post("/api/auth/register", json={
            "email": f"company_feat_{pid}@test.com",
            "password": "Password123!",
            "role": "company",
            "companyName": "AI Systems Corp"
        })
        cls.cmp_token = res_cmp.json().get("token")

        # Student
        res_stu = client.post("/api/auth/register", json={
            "email": f"student_feat_{pid}@test.com",
            "password": "Password123!",
            "role": "student",
            "name": "Alex Mercer"
        })
        cls.stu_token = res_stu.json().get("token")
        cls.stu_id = res_stu.json()["user"]["id"]

        # Create a Project
        res_proj = client.post("/api/projects", json={
            "title": "Machine Learning Model Deployment",
            "description": "Deploy a predictive FastAPI service with Docker.",
            "required_skills": ["Python", "Machine Learning", "FastAPI", "Docker"],
            "duration_days": 10
        }, headers={"Authorization": f"Bearer {cls.cmp_token}"})
        cls.proj_id = res_proj.json()["project"]["id"]

    def test_01_ai_roles_and_skill_gap(self):
        # 1. Roles
        r = client.get("/api/ai/roles")
        self.assertEqual(r.status_code, 200)
        self.assertIn("roles", r.json())
        self.assertTrue(len(r.json()["roles"]) > 0)

        # 2. Skill Gap Analysis
        r2 = client.post("/api/ai/skill-gap-analysis", json={
            "target_role": "AI / Machine Learning Engineer",
            "custom_skills": ["Python", "Pandas"]
        }, headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r2.status_code, 200)
        analysis = r2.json()["analysis"]
        self.assertIn("overall_readiness_score", analysis)
        self.assertIn("missing_critical_skills", analysis)
        self.assertIn("roadmap", analysis)

    def test_02_ai_project_recommendations(self):
        r = client.get("/api/ai/project-recommendations", headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r.status_code, 200)
        recs = r.json()["recommendations"]
        self.assertTrue(len(recs) > 0)
        self.assertIn("match_percentage", recs[0])

    def test_03_application_submission_ai_eval_and_grading(self):
        # Student applies
        r_app = client.post(f"/api/projects/{self.proj_id}/apply", json={
            "cover_letter": "Passionate ML engineer ready to deliver."
        }, headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r_app.status_code, 201)

        # Get applications
        r_get = client.get(f"/api/projects/{self.proj_id}/applications", headers={"Authorization": f"Bearer {self.cmp_token}"})
        app_id = r_get.json()["applications"][0]["id"]

        # Company accepts
        r_acc = client.post(f"/api/applications/{app_id}/status", json={"status": "accepted"}, headers={"Authorization": f"Bearer {self.cmp_token}"})
        self.assertEqual(r_acc.status_code, 200)

        # Student submits
        r_sub = client.post(f"/api/applications/{app_id}/submit", json={
            "submission_link": "https://github.com/alex/ml-fastapi-service",
            "submission_notes": "Implemented Dockerized REST endpoints with unit tests and swagger docs."
        }, headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r_sub.status_code, 200)

        # AI Evaluation & Plagiarism Check
        r_ai = client.post(f"/api/ai/evaluate-submission/{app_id}", headers={"Authorization": f"Bearer {self.cmp_token}"})
        self.assertEqual(r_ai.status_code, 200)
        ai_data = r_ai.json()["evaluation"]
        self.assertIn("code_quality_score", ai_data)
        self.assertIn("plagiarism_score", ai_data)
        self.assertIn("plagiarism_risk", ai_data)
        self.assertIn("strengths", ai_data)

        # Company grades and awards certificate
        r_grade = client.post(f"/api/applications/{app_id}/grade", json={
            "grade": 4.8,
            "feedback": "Outstanding implementation with solid clean architecture!"
        }, headers={"Authorization": f"Bearer {self.cmp_token}"})
        self.assertEqual(r_grade.status_code, 200)
        cert_uuid = r_grade.json()["certificate_uuid"]

        # Public certificate verification
        r_cert = client.get(f"/api/certificates/{cert_uuid}")
        self.assertEqual(r_cert.status_code, 200)
        self.assertTrue(r_cert.json()["verified"])

    def test_04_talent_pool_and_portfolio(self):
        # Talent directory
        r_tal = client.get("/api/talents")
        self.assertEqual(r_tal.status_code, 200)
        self.assertTrue(len(r_tal.json()["talents"]) > 0)

        # Talent portfolio
        student_prof_id = r_tal.json()["talents"][0]["id"]
        r_port = client.get(f"/api/talents/{student_prof_id}")
        self.assertEqual(r_port.status_code, 200)
        self.assertIn("completed_projects", r_port.json())

    def test_05_messaging_and_notifications(self):
        # Get company user ID from admin users list
        r_u = client.get("/api/admin/users", headers={"Authorization": f"Bearer {self.adm_token}"})
        self.assertEqual(r_u.status_code, 200)
        cmp_user = next(u for u in r_u.json()["users"] if u["role"] == "company")

        # Student sends message to company
        r_msg = client.post("/api/messages/send", json={
            "receiver_id": cmp_user["id"],
            "content": "Hello! Thank you for the opportunity."
        }, headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r_msg.status_code, 200)

        # Company views conversations
        r_conv = client.get("/api/messages/conversations", headers={"Authorization": f"Bearer {self.cmp_token}"})
        self.assertEqual(r_conv.status_code, 200)
        self.assertTrue(len(r_conv.json()["conversations"]) > 0)

        # Notifications
        r_notif = client.get("/api/notifications", headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r_notif.status_code, 200)
        self.assertTrue(len(r_notif.json()["notifications"]) > 0)

    def test_06_mock_interview(self):
        # Start interview
        r_start = client.post("/api/ai/interview/start", json={
            "target_role": "AI / Machine Learning Engineer"
        }, headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r_start.status_code, 200)
        sess_id = r_start.json()["session_id"]

        # Answer question
        r_ans = client.post(f"/api/ai/interview/{sess_id}/answer", json={
            "question_index": 0,
            "answer": "To prevent overfitting, we use L2 regularization, dropout layers, early stopping on validation loss, and data augmentation."
        }, headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r_ans.status_code, 200)
        self.assertIn("evaluation", r_ans.json())
        self.assertGreater(r_ans.json()["evaluation"]["score"], 5.0)

    def test_07_admin_dashboard(self):
        # Admin stats
        r_stats = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {self.adm_token}"})
        self.assertEqual(r_stats.status_code, 200)
        stats = r_stats.json()["stats"]
        self.assertGreaterEqual(stats["total_students"], 1)
        self.assertGreaterEqual(stats["total_projects"], 1)

        # Admin companies verification
        r_comps = client.get("/api/admin/companies", headers={"Authorization": f"Bearer {self.adm_token}"})
        self.assertEqual(r_comps.status_code, 200)
        comp_id = r_comps.json()["companies"][0]["id"]

        r_ver = client.post(f"/api/admin/companies/{comp_id}/verify", json={"is_verified": True}, headers={"Authorization": f"Bearer {self.adm_token}"})
        self.assertEqual(r_ver.status_code, 200)

    def test_08_team_micro_projects(self):
        r_team = client.post(f"/api/projects/{self.proj_id}/teams", json={
            "name": "Alpha ML Squad"
        }, headers={"Authorization": f"Bearer {self.stu_token}"})
        self.assertEqual(r_team.status_code, 200)

        r_list = client.get(f"/api/projects/{self.proj_id}/teams")
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(len(r_list.json()["teams"]), 1)

if __name__ == "__main__":
    unittest.main()
