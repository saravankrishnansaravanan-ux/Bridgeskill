import json
import sqlite3
import os
from backend.app.auth import hash_password

COMPANIES_SEED = [
    {
        "email": "partner.meta@bridgeskill.io",
        "company_name": "Meta Open Source",
        "description": "Building community and bringing the world closer together through open source tools, frameworks, and developer platforms.",
        "website": "https://opensource.fb.com",
        "is_verified": 1
    },
    {
        "email": "partner.stripe@bridgeskill.io",
        "company_name": "Stripe Developer",
        "description": "Financial infrastructure for the internet. Millions of businesses use Stripe APIs to accept payments and manage operations.",
        "website": "https://stripe.com/docs",
        "is_verified": 1
    },
    {
        "email": "partner.google@bridgeskill.io",
        "company_name": "Google Cloud",
        "description": "Accelerating digital transformation with best-in-class cloud computing, machine learning, and enterprise data solutions.",
        "website": "https://cloud.google.com",
        "is_verified": 1
    },
    {
        "email": "partner.microsoft@bridgeskill.io",
        "company_name": "Microsoft Azure",
        "description": "Invent with purpose on Microsoft Azure. Enterprise cloud platform empowering organizations with intelligent edge and AI.",
        "website": "https://azure.microsoft.com",
        "is_verified": 1
    },
    {
        "email": "partner.aws@bridgeskill.io",
        "company_name": "AWS CloudLabs",
        "description": "Amazon Web Services provides on-demand cloud computing platforms and APIs with reliable, scalable, and inexpensive cloud infrastructure.",
        "website": "https://aws.amazon.com",
        "is_verified": 1
    },
    {
        "email": "partner.databricks@bridgeskill.io",
        "company_name": "Databricks Labs",
        "description": "Data and AI company helping organizations unify their analytics, data engineering, and generative AI initiatives.",
        "website": "https://databricks.com",
        "is_verified": 1
    },
    {
        "email": "partner.netflix@bridgeskill.io",
        "company_name": "Netflix Engineering",
        "description": "Pioneering distributed microservice architectures, high-performance edge routing, and resilient cloud streaming services.",
        "website": "https://netflixtechblog.com",
        "is_verified": 1
    },
    {
        "email": "partner.uber@bridgeskill.io",
        "company_name": "Uber Engineering",
        "description": "Transforming mobility and logistics through massive scale real-time geospatial processing and distributed systems.",
        "website": "https://eng.uber.com",
        "is_verified": 1
    }
]

PROJECTS_SEED = [
    # Full-Stack Web Development
    {
        "company": "Meta Open Source",
        "title": "Next.js Real-Time Collaborative Canvas & Whiteboard",
        "description": "Build a low-latency collaborative digital workspace supporting real-time multi-cursor syncing, canvas drawing, presence indicators, and state persistence using WebSockets and Next.js.",
        "required_skills": ["JavaScript", "React", "Next.js", "WebSocket", "TailwindCSS", "Node.js"],
        "duration_days": 14,
        "max_team_size": 3
    },
    {
        "company": "Stripe Developer",
        "title": "Full-Stack E-Commerce Platform with Stripe Checkout & Webhooks",
        "description": "Architect an end-to-end multi-vendor marketplace featuring shopping cart management, Stripe Payment Element integration, asynchronous webhook reconciliation, and automated invoicing.",
        "required_skills": ["JavaScript", "React", "Node.js", "SQL", "REST API", "HTML/CSS"],
        "duration_days": 18,
        "max_team_size": 2
    },
    # Backend Engineering & Distributed Systems
    {
        "company": "Netflix Engineering",
        "title": "High-Throughput Distributed Rate Limiter & API Gateway",
        "description": "Implement a token-bucket and sliding-window rate limiter capable of handling 50,000 requests/sec with Redis cluster state sharing, JWT authentication verification, and reverse proxy routing.",
        "required_skills": ["Python", "FastAPI", "Redis", "Docker", "REST API", "Microservices"],
        "duration_days": 12,
        "max_team_size": 2
    },
    {
        "company": "Stripe Developer",
        "title": "Event-Driven Financial Ledger & Transaction Processing Service",
        "description": "Engineer an ACID-compliant double-entry ledger handling concurrent wallet transfers, audit logging, idempotent transactions, and automated reconciliation reports.",
        "required_skills": ["Python", "SQL", "PostgreSQL", "Database Design", "Docker", "Unit Testing"],
        "duration_days": 16,
        "max_team_size": 3
    },
    # AI, Machine Learning & Deep Learning
    {
        "company": "Databricks Labs",
        "title": "RAG-Powered Technical Documentation Assistant with Vector Search",
        "description": "Construct a Retrieval-Augmented Generation (RAG) pipeline parsing engineering documentation, generating dense vector embeddings, and serving contextually grounded conversational answers with sub-second latency.",
        "required_skills": ["Python", "Machine Learning", "NLP", "LLMs", "FastAPI"],
        "duration_days": 14,
        "max_team_size": 2
    },
    {
        "company": "Google Cloud",
        "title": "Autonomous Computer Vision Defect Detection Pipeline",
        "description": "Train, evaluate, and optimize a deep neural network (ResNet/YOLO) for manufacturing surface defect identification with automated data augmentation and ROC-AUC evaluation metrics.",
        "required_skills": ["Python", "Machine Learning", "PyTorch", "Data Analysis", "NumPy", "Git"],
        "duration_days": 21,
        "max_team_size": 3
    },
    {
        "company": "Microsoft Azure",
        "title": "Real-Time Fraud Detection ML Inference Microservice",
        "description": "Deploy an ensemble machine learning classification service detecting anomalous credit transactions in real time, featuring drift detection, latency monitoring, and model explainability.",
        "required_skills": ["Python", "Machine Learning", "Scikit-Learn", "FastAPI", "Pandas", "Docker"],
        "duration_days": 15,
        "max_team_size": 2
    },
    # Data Science & Streaming Analytics
    {
        "company": "Google Cloud",
        "title": "Streaming Clickstream Telemetry & Real-Time Dashboard",
        "description": "Build an analytics pipeline capturing web user events, aggregating session metrics, and visualizing conversion funnels and user retention cohorts in an interactive dashboard.",
        "required_skills": ["Python", "SQL", "Data Analysis", "Pandas", "Statistics", "Data Visualization"],
        "duration_days": 14,
        "max_team_size": 2
    },
    {
        "company": "Databricks Labs",
        "title": "Customer Churn Prediction & Multi-Channel Marketing Attribution",
        "description": "Conduct statistical exploratory data analysis, engineer predictive churn features, build uplift scoring models, and deliver actionable customer retention segment recommendations.",
        "required_skills": ["Python", "Data Analysis", "Pandas", "Statistics", "Machine Learning", "SQL"],
        "duration_days": 10,
        "max_team_size": 2
    },
    # Cloud Architecture, DevOps & SRE
    {
        "company": "AWS CloudLabs",
        "title": "Automated Kubernetes Microservices Deployment with GitOps & CI/CD",
        "description": "Configure multi-stage Docker containerization, Helm charts, automated GitHub Actions pipelines with linting and unit testing, and zero-downtime rolling updates on a managed Kubernetes cluster.",
        "required_skills": ["Docker", "Kubernetes", "Linux", "CI/CD", "AWS", "GitHub Actions"],
        "duration_days": 16,
        "max_team_size": 3
    },
    {
        "company": "AWS CloudLabs",
        "title": "Infrastructure-as-Code Multi-Region Cloud Deployment with Terraform",
        "description": "Provision secure, highly available cloud VPC infrastructure using modular Terraform, including load balancers, auto-scaling groups, SSL termination, and least-privilege IAM policies.",
        "required_skills": ["Terraform", "AWS", "Linux", "Networking", "Security", "Bash"],
        "duration_days": 12,
        "max_team_size": 2
    },
    # Mobile App Development
    {
        "company": "Meta Open Source",
        "title": "Cross-Platform Mobile Personal Finance & Budget Tracker",
        "description": "Develop an intuitive offline-first mobile app featuring biometric authentication, expense categorization, interactive spending analytics, and encrypted local database sync.",
        "required_skills": ["JavaScript", "React", "Mobile Development", "REST API", "Git", "UI/UX"],
        "duration_days": 14,
        "max_team_size": 2
    },
    {
        "company": "Uber Engineering",
        "title": "On-Demand Logistics & Real-Time GPS Geolocation Mobile App",
        "description": "Engineer a driver-passenger dispatch mobile experience with live geospatial tracking, route estimation, background location updates, and push notifications.",
        "required_skills": ["JavaScript", "React", "REST API", "WebSocket", "UI/UX", "Git"],
        "duration_days": 20,
        "max_team_size": 3
    },
    # Cybersecurity & Zero-Trust
    {
        "company": "Microsoft Azure",
        "title": "Zero-Trust OAuth2/OIDC Enterprise Identity Provider & Security Audit",
        "description": "Build an enterprise-grade OAuth2/OpenID Connect authentication server implementing PKCE for single-page applications, multi-factor authentication (MFA), and automated OWASP vulnerability scanning.",
        "required_skills": ["Security", "Python", "FastAPI", "SQL", "REST API", "Networking"],
        "duration_days": 14,
        "max_team_size": 2
    },
    {
        "company": "Stripe Developer",
        "title": "Decentralized Supply Chain Verification & Audit Log Engine",
        "description": "Develop an immutable product provenance tracking system with cryptographically signed batch receipts, cryptographic hash verification, and automated audit test suites.",
        "required_skills": ["Security", "JavaScript", "Python", "REST API", "Unit Testing", "Git"],
        "duration_days": 16,
        "max_team_size": 2
    },
    # Frontend & UI/UX Engineering
    {
        "company": "Meta Open Source",
        "title": "Accessible Design System & Component Library with Storybook",
        "description": "Build a production-ready, WCAG 2.1 AA accessible component library featuring dark/light themes, keyboard navigation, fluid responsive layouts, and interactive Storybook documentation.",
        "required_skills": ["JavaScript", "HTML/CSS", "React", "Responsive Design", "UI/UX"],
        "duration_days": 10,
        "max_team_size": 2
    }
]

def seed_verified_curriculum(conn: sqlite3.Connection, clean_duplicates: bool = True):
    cursor = conn.cursor()
    company_id_map = {}

    # Seed enterprise companies
    for comp in COMPANIES_SEED:
        cursor.execute("SELECT id FROM users WHERE email = ?", (comp["email"],))
        user_row = cursor.fetchone()
        if not user_row:
            pwd_hash = hash_password("PartnerPassword2026!")
            cursor.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'company')",
                (comp["email"], pwd_hash)
            )
            user_id = cursor.lastrowid
        else:
            user_id = user_row[0]

        cursor.execute("SELECT id FROM company_profiles WHERE user_id = ?", (user_id,))
        prof_row = cursor.fetchone()
        if not prof_row:
            cursor.execute(
                """
                INSERT INTO company_profiles (user_id, company_name, description, website, is_verified)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, comp["company_name"], comp["description"], comp["website"], comp["is_verified"])
            )
            comp_id = cursor.lastrowid
        else:
            comp_id = prof_row[0]
            cursor.execute(
                "UPDATE company_profiles SET is_verified = 1, company_name = ?, description = ? WHERE id = ?",
                (comp["company_name"], comp["description"], comp_id)
            )

        company_id_map[comp["company_name"]] = comp_id

    # If clean_duplicates is requested:
    if clean_duplicates:
        # Check existing duplicate titles
        cursor.execute("""
            SELECT id FROM projects 
            WHERE title IN ('AI Recommendation Engine Micro-Project', 'Machine Learning Model Deployment')
            AND id NOT IN (SELECT DISTINCT project_id FROM applications)
            AND id NOT IN (SELECT DISTINCT project_id FROM project_applications)
            AND id NOT IN (SELECT DISTINCT project_id FROM teams)
        """)
        unused_dupes = [r[0] for r in cursor.fetchall()]
        if unused_dupes:
            placeholders = ','.join('?' for _ in unused_dupes)
            cursor.execute(f"DELETE FROM projects WHERE id IN ({placeholders})", unused_dupes)

    # Insert diverse projects if not already present by title
    inserted_count = 0
    for proj in PROJECTS_SEED:
        comp_id = company_id_map.get(proj["company"])
        if not comp_id:
            # Fallback to first company
            comp_id = list(company_id_map.values())[0]

        cursor.execute("SELECT id FROM projects WHERE title = ?", (proj["title"],))
        existing = cursor.fetchone()
        if not existing:
            cursor.execute(
                """
                INSERT INTO projects (company_id, title, description, required_skills, duration_days, status, max_team_size)
                VALUES (?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    comp_id,
                    proj["title"],
                    proj["description"],
                    json.dumps(proj["required_skills"]),
                    proj["duration_days"],
                    proj.get("max_team_size", 2)
                )
            )
            inserted_count += 1

    conn.commit()
    return inserted_count
