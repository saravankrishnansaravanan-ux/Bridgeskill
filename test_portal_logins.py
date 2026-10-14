import os
import sys
import unittest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from backend.app.main import app
from backend.app.db import init_db

client = TestClient(app)

class TestPortalLogins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        pid = os.getpid()
        cls.student_email = f"student_portal_{pid}@test.com"
        cls.company_email = f"company_portal_{pid}@test.com"
        cls.admin_email = f"admin_portal_{pid}@test.com"
        cls.password = "TestPass123!"

        # Register Student
        r1 = client.post("/api/auth/register", json={
            "email": cls.student_email,
            "password": cls.password,
            "role": "student",
            "name": "Jane Learner"
        })
        assert r1.status_code == 201, f"Student registration failed: {r1.text}"

        # Register Company
        r2 = client.post("/api/auth/register", json={
            "email": cls.company_email,
            "password": cls.password,
            "role": "company",
            "companyName": "TechCorp Global"
        })
        assert r2.status_code == 201, f"Company registration failed: {r2.text}"

        # Register Admin
        r3 = client.post("/api/auth/register", json={
            "email": cls.admin_email,
            "password": cls.password,
            "role": "admin"
        })
        assert r3.status_code == 201, f"Admin registration failed: {r3.text}"

    def test_student_login_on_student_portal(self):
        # Student logs in through Student Portal (#login-student)
        res = client.post("/api/auth/login", json={
            "email": self.student_email,
            "password": self.password,
            "expected_role": "student"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("token", data)
        self.assertEqual(data["user"]["role"], "student")
        self.assertEqual(data["user"]["profile"]["name"], "Jane Learner")

    def test_company_login_on_company_portal(self):
        # Company logs in through Company Portal (#login-company)
        res = client.post("/api/auth/login", json={
            "email": self.company_email,
            "password": self.password,
            "expected_role": "company"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("token", data)
        self.assertEqual(data["user"]["role"], "company")
        self.assertEqual(data["user"]["profile"]["company_name"], "TechCorp Global")

    def test_student_mismatch_on_company_portal(self):
        # Student accidentally tries logging in on Company Portal
        res = client.post("/api/auth/login", json={
            "email": self.student_email,
            "password": self.password,
            "expected_role": "company"
        })
        self.assertEqual(res.status_code, 400)
        detail = res.json().get("detail", "")
        self.assertIn("Student / Learner", detail)
        self.assertIn("#login-student", detail)

    def test_company_mismatch_on_student_portal(self):
        # Company user accidentally tries logging in on Student Portal
        res = client.post("/api/auth/login", json={
            "email": self.company_email,
            "password": self.password,
            "expected_role": "student"
        })
        self.assertEqual(res.status_code, 400)
        detail = res.json().get("detail", "")
        self.assertIn("Company / Enterprise", detail)
        self.assertIn("#login-company", detail)

    def test_admin_bypass_on_any_portal(self):
        # Admin can access from both portals
        res1 = client.post("/api/auth/login", json={
            "email": self.admin_email,
            "password": self.password,
            "expected_role": "student"
        })
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["user"]["role"], "admin")

        res2 = client.post("/api/auth/login", json={
            "email": self.admin_email,
            "password": self.password,
            "expected_role": "company"
        })
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["user"]["role"], "admin")

    def test_generic_login_without_expected_role(self):
        # Generic login endpoint without expected_role allows either role
        res = client.post("/api/auth/login", json={
            "email": self.student_email,
            "password": self.password
        })
        self.assertEqual(res.status_code, 200)

if __name__ == "__main__":
    unittest.main()
