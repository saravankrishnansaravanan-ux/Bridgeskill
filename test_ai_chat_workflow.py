import os
import sys
import unittest
from fastapi.testclient import TestClient

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from backend.app.main import app
from backend.app.db import init_db

client = TestClient(app)

class TestAIChatWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        pid = os.getpid()
        
        # Register a test student
        res_stu = client.post("/api/auth/register", json={
            "email": f"student_chat_{pid}@test.com",
            "password": "Password123!",
            "role": "student",
            "name": "Jordan Lee"
        })
        cls.stu_token = res_stu.json().get("token")
        
        # Register a test company
        res_cmp = client.post("/api/auth/register", json={
            "email": f"company_chat_{pid}@test.com",
            "password": "Password123!",
            "role": "company",
            "companyName": "TechCorp Global"
        })
        cls.cmp_token = res_cmp.json().get("token")

    def test_01_llm_status(self):
        res = client.get("/api/ai/llm-status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("connected"))
        self.assertEqual(data.get("provider"), "groq")
        print("✓ LLM Status:", data.get("provider"), data.get("model"))

    def test_02_quick_prompts(self):
        res = client.get("/api/ai/consultant/quick-prompts")
        self.assertEqual(res.status_code, 200)
        prompts = res.json().get("prompts", [])
        self.assertGreater(len(prompts), 0)
        print("✓ Quick Prompts Count:", len(prompts))

    def test_03_unauthenticated_guest_chat(self):
        # Visitor chats with AI without logging in
        res = client.post("/api/ai/consultant/chat", json={
            "message": "What micro-projects are best for learning backend engineering?",
            "history": [],
            "mode": "career"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("reply", data)
        self.assertTrue(len(data["reply"]) > 10)
        self.assertIn("suggested_prompts", data)
        print("✓ Guest Chat Response length:", len(data["reply"]))
        print("  Sample snippet:", data["reply"][:80].replace('\n', ' '))

    def test_04_authenticated_student_chat(self):
        # Student chats with personalized profile
        res = client.post(
            "/api/ai/consultant/chat",
            json={
                "message": "How do I optimize database query performance for large datasets?",
                "history": [],
                "mode": "architecture"
            },
            headers={"Authorization": f"Bearer {self.stu_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("reply", data)
        self.assertEqual(data.get("mode"), "architecture")
        print("✓ Student Chat Response length:", len(data["reply"]))

    def test_05_authenticated_company_chat(self):
        # Company asks for technical advice
        res = client.post(
            "/api/ai/consultant/chat",
            json={
                "message": "What skills should we require for a junior python backend project?",
                "history": [],
                "mode": "career"
            },
            headers={"Authorization": f"Bearer {self.cmp_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("reply", data)
        print("✓ Company Chat Response length:", len(data["reply"]))

    def test_06_unauthenticated_skill_gap_analysis(self):
        # Guest tests skill gap analysis
        res = client.post("/api/ai/skill-gap-analysis", json={
            "target_role": "Backend Python Engineer",
            "custom_skills": ["Python", "SQL"]
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("analysis", data)
        print("✓ Guest Skill Gap Readiness:", data["analysis"]["overall_readiness_score"])

if __name__ == "__main__":
    unittest.main()
