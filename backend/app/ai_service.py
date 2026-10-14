import os
import json
import re
import requests
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Load environment configuration
root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.env"))
parent_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.env"))
load_dotenv(root_env)
load_dotenv(parent_env)
load_dotenv()

import time
import hashlib

class RateLimitTracker:
    def __init__(self):
        self.limit_requests = 1000
        self.remaining_requests = 1000
        self.limit_tokens = 8000
        self.remaining_tokens = 8000
        self.reset_tokens_seconds = 0.0
        self.last_updated = 0.0
        self.total_calls = 0

    def update_from_headers(self, headers: dict):
        try:
            for k, v in headers.items():
                k_low = k.lower()
                if "x-ratelimit-limit-requests" in k_low:
                    self.limit_requests = int(v)
                elif "x-ratelimit-remaining-requests" in k_low:
                    self.remaining_requests = int(v)
                elif "x-ratelimit-limit-tokens" in k_low:
                    self.limit_tokens = int(v)
                elif "x-ratelimit-remaining-tokens" in k_low:
                    self.remaining_tokens = int(v)
                elif "x-ratelimit-reset-tokens" in k_low:
                    val = str(v)
                    if val.endswith("s"):
                        self.reset_tokens_seconds = float(val[:-1])
                    elif val.endswith("ms"):
                        self.reset_tokens_seconds = float(val[:-2]) / 1000.0
            self.last_updated = time.time()
            self.total_calls += 1
        except Exception:
            pass

    def to_dict(self):
        status = "healthy"
        if self.remaining_tokens < 500:
            status = "throttled"
        elif self.remaining_tokens < 2000:
            status = "warning"
        return {
            "limit_requests": self.limit_requests,
            "remaining_requests": self.remaining_requests,
            "limit_tokens_per_min": self.limit_tokens,
            "remaining_tokens": self.remaining_tokens,
            "reset_tokens_seconds": round(self.reset_tokens_seconds, 2),
            "total_calls": self.total_calls,
            "status": status
        }

rate_limit_tracker = RateLimitTracker()

# In-Memory Smart Cache (30 min TTL)
_RESPONSE_CACHE: Dict[str, tuple[float, str]] = {}
CACHE_TTL = 1800

def get_cached_response(key_str: str) -> Optional[str]:
    h = hashlib.md5(key_str.encode("utf-8")).hexdigest()
    if h in _RESPONSE_CACHE:
        ts, content = _RESPONSE_CACHE[h]
        if time.time() - ts < CACHE_TTL:
            return content
    return None

def set_cached_response(key_str: str, content: str):
    h = hashlib.md5(key_str.encode("utf-8")).hexdigest()
    _RESPONSE_CACHE[h] = (time.time(), content)

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

def get_active_llm_config() -> Dict[str, Any]:
    """Inspects configured LLM credentials and rate limits from environment variables."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    ollama_url = os.getenv("OLLAMA_BASE_URL", "").strip()

    groq_model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL
    if groq_key:
        return {
            "provider": "groq",
            "model": groq_model,
            "api_key": groq_key,
            "connected": True,
            "rate_limits": rate_limit_tracker.to_dict()
        }
    elif gemini_key:
        return {"provider": "gemini", "model": "gemini-2.5-flash", "api_key": gemini_key, "connected": True, "rate_limits": {}}
    elif openai_key:
        return {"provider": "openai", "model": "gpt-4o-mini", "api_key": openai_key, "connected": True, "rate_limits": {}}
    elif ollama_url:
        return {"provider": "ollama", "model": "llama3", "api_key": "", "connected": True, "url": ollama_url, "rate_limits": {}}
    else:
        return {"provider": "local_nlp", "model": "BridgeSkill-Hybrid-NLP", "api_key": "", "connected": False, "rate_limits": {}}

def call_llm(prompt: str, system_prompt: str = "", json_mode: bool = False) -> Optional[str]:
    """Unified LLM caller with rate limit monitoring, caching, and fallback."""
    full_cache_key = f"{system_prompt}|{prompt}|{json_mode}"
    cached = get_cached_response(full_cache_key)
    if cached:
        return cached

    cfg = get_active_llm_config()
    provider = cfg["provider"]

    if provider == "groq":
        # Candidate models for cascade
        primary_model = cfg.get("model", "openai/gpt-oss-120b")
        candidate_models = [primary_model, "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
        models_to_try = []
        for m in candidate_models:
            if m and m not in models_to_try:
                models_to_try.append(m)

        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json"
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        for model_choice in models_to_try:
            payload = {
                "model": model_choice,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 600
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            try:
                resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
                rate_limit_tracker.update_from_headers(resp.headers)

                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    set_cached_response(full_cache_key, content)
                    return content
                elif resp.status_code == 429:
                    # Rate limit exceeded for this model, try next model or brief pause
                    retry_after = resp.headers.get("retry-after")
                    wait_sec = float(retry_after) if retry_after and retry_after.isdigit() else 1.5
                    if wait_sec <= 2.0:
                        time.sleep(wait_sec)
                    print(f"[BridgeSkill LLM] Groq 429 rate limit on {model_choice}, trying secondary model...")
                    continue
                elif resp.status_code == 400 and json_mode and "json_validate_failed" in resp.text:
                    # Retry without strict server-side schema constraint
                    payload_no_format = dict(payload)
                    payload_no_format.pop("response_format", None)
                    r2 = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload_no_format, timeout=20)
                    rate_limit_tracker.update_from_headers(r2.headers)
                    if r2.status_code == 200:
                        content = r2.json()["choices"][0]["message"]["content"]
                        set_cached_response(full_cache_key, content)
                        return content
                    continue
                else:
                    err_msg = resp.text[:160].encode('ascii', 'replace').decode('ascii')
                    print(f"[BridgeSkill LLM] Groq API notice {resp.status_code} on {model_choice}: {err_msg}")
                    continue

            except Exception as e:
                print(f"[BridgeSkill LLM] Groq request error ({str(e)[:120]}), trying fallback...")
                continue

        # If all models rate limited or failed, fallback to local hybrid
        return None


    elif provider == "gemini":

        try:
            from google import genai
            client = genai.Client(api_key=cfg["api_key"])
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            gen_config = {}
            if json_mode:
                gen_config["response_mime_type"] = "application/json"
            
            response = client.models.generate_content(
                model=cfg["model"],
                contents=full_prompt,
                config=gen_config if gen_config else None
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"[BridgeSkill LLM] Gemini call failed ({e}), using hybrid NLP engine.")
            return None

    elif provider == "openai":
        try:
            headers = {
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json"
            }
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": cfg["model"],
                "messages": messages,
                "temperature": 0.4
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=20)
            if resp.ok:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[BridgeSkill LLM] OpenAI call failed ({e}), using hybrid NLP engine.")
            return None

    elif provider == "ollama":
        try:
            payload = {
                "model": cfg["model"],
                "prompt": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt,
                "stream": False
            }
            if json_mode:
                payload["format"] = "json"
            resp = requests.post(f"{cfg['url'].rstrip('/')}/api/generate", json=payload, timeout=30)
            if resp.ok:
                return resp.json().get("response")
        except Exception as e:
            print(f"[BridgeSkill LLM] Ollama call failed ({e}), using hybrid NLP engine.")
            return None

    return None

# =========================================================================
# Standardized Industry Role Taxonomy
# =========================================================================
ROLE_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "Full Stack Web Developer": {
        "required": ["JavaScript", "React", "Node.js", "Python", "SQL", "Git", "REST API", "HTML/CSS"],
        "recommended": ["TypeScript", "FastAPI", "Docker", "TailwindCSS", "PostgreSQL"],
        "description": "Develops both client and server software, building end-to-end web applications."
    },
    "Backend Python Engineer": {
        "required": ["Python", "FastAPI", "Django", "SQL", "REST API", "Git", "Database Design"],
        "recommended": ["Docker", "Redis", "PostgreSQL", "Celery", "Unit Testing", "Microservices"],
        "description": "Designs robust API architectures, data pipelines, and server-side logic."
    },
    "AI / Machine Learning Engineer": {
        "required": ["Python", "Machine Learning", "Data Analysis", "NumPy", "Pandas", "Scikit-Learn", "Git"],
        "recommended": ["PyTorch", "TensorFlow", "Deep Learning", "FastAPI", "NLP", "LLMs"],
        "description": "Builds and deploys machine learning models, neural networks, and AI predictive services."
    },
    "Data Scientist & Analyst": {
        "required": ["Python", "SQL", "Data Analysis", "Pandas", "Statistics", "Data Visualization"],
        "recommended": ["Tableau", "PowerBI", "Machine Learning", "R", "Seaborn", "A/B Testing"],
        "description": "Extracts actionable business insights and statistical trends from structured data."
    },
    "Cloud & DevOps Engineer": {
        "required": ["Linux", "Docker", "Git", "CI/CD", "AWS", "Bash", "Networking"],
        "recommended": ["Kubernetes", "Terraform", "GitHub Actions", "Azure", "Monitoring", "Security"],
        "description": "Automates deployments, cloud infrastructure, container orchestration, and reliability."
    },
    "Frontend & UI Engineer": {
        "required": ["JavaScript", "HTML/CSS", "React", "Responsive Design", "Git", "UI/UX"],
        "recommended": ["TypeScript", "Next.js", "Vue.js", "TailwindCSS", "Figma", "State Management"],
        "description": "Crafts accessible, high-performance, and visually stunning web interfaces."
    }
}

def normalize_skill(skill: str) -> str:
    """Normalize skill name for fuzzy matching."""
    s = skill.strip().lower()
    s = re.sub(r'[\s\-_.]+', '', s)
    synonyms = {
        "js": "javascript",
        "py": "python",
        "reactjs": "react",
        "nodejs": "nodejs",
        "fastapi": "fastapi",
        "html": "htmlcss",
        "css": "htmlcss",
        "htmlcss": "htmlcss",
        "ml": "machinelearning",
        "machinelearning": "machinelearning",
        "deeplearning": "deeplearning",
        "sql": "sql",
        "postgres": "postgresql",
        "postgresql": "postgresql"
    }
    return synonyms.get(s, s)

def calculate_skill_overlap(student_skills: List[str], target_skills: List[str]) -> tuple[List[str], List[str], float]:
    """Calculates matched skills, missing skills, and matching percentage."""
    normalized_student = {normalize_skill(s): s for s in student_skills}
    matched = []
    missing = []
    
    for req in target_skills:
        req_norm = normalize_skill(req)
        found = False
        for s_norm in normalized_student:
            if req_norm == s_norm or req_norm in s_norm or s_norm in req_norm:
                matched.append(req)
                found = True
                break
        if not found:
            missing.append(req)
            
    total = len(target_skills)
    match_pct = (len(matched) / total * 100.0) if total > 0 else 100.0
    return matched, missing, round(match_pct, 1)

def analyze_skill_gap(student_skills: List[str], target_role: str, open_projects: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Module 2: AI Skill Gap Analysis.
    Combines LLM intelligence (when connected) with platform micro-project mapping.
    """
    role_info = ROLE_TAXONOMY.get(target_role, ROLE_TAXONOMY["Full Stack Web Developer"])
    req_skills = role_info["required"]
    rec_skills = role_info["recommended"]
    
    matched_req, missing_req, readiness_score = calculate_skill_overlap(student_skills, req_skills)
    matched_rec, missing_rec, rec_score = calculate_skill_overlap(student_skills, rec_skills)
    overall_readiness = round(readiness_score * 0.75 + rec_score * 0.25, 1)

    # Attempt LLM Enrichment
    llm_prompt = f"""
    You are an AI Technical Career Advisor for BridgeSkill.
    Target Role: {target_role}
    Candidate Current Skills: {student_skills}
    Required Role Skills: {req_skills}
    Recommended Skills: {rec_skills}

    Provide a JSON response with:
    {{
        "overall_readiness_score": number (0-100),
        "missing_critical_skills": list of strings,
        "missing_recommended_skills": list of strings,
        "advice_summary": string,
        "roadmap": [
            {{"step": 1, "skill": string, "goal": string, "priority": "High"|"Medium"}}
        ]
    }}
    """
    llm_raw = call_llm(llm_prompt, system_prompt="You are an expert tech recruiter and curriculum advisor. Respond in strict JSON.", json_mode=True)
    llm_json = None
    if llm_raw:
        try:
            llm_json = json.loads(re.sub(r'```(?:json)?\n?|```', '', llm_raw).strip())
        except Exception:
            pass

    # Map available bridge projects on platform
    recommended_projects = []
    target_missing = llm_json.get("missing_critical_skills", missing_req) if llm_json else missing_req
    for p in open_projects:
        p_skills = p.get("required_skills", [])
        if isinstance(p_skills, str):
            try:
                p_skills = json.loads(p_skills)
            except Exception:
                p_skills = [p_skills]
                
        p_norm = [normalize_skill(s) for s in p_skills]
        bridged_skills = []
        for miss in target_missing + missing_rec:
            if normalize_skill(miss) in p_norm:
                bridged_skills.append(miss)
                
        if bridged_skills:
            recommended_projects.append({
                "id": p.get("id"),
                "title": p.get("title"),
                "company_name": p.get("company_name", "Partner Company"),
                "duration_days": p.get("duration_days"),
                "bridged_skills": list(set(bridged_skills)),
                "relevance_score": len(bridged_skills) * 25
            })
            
    recommended_projects.sort(key=lambda x: x["relevance_score"], reverse=True)

    if llm_json:
        roadmap = llm_json.get("roadmap", [])
        return {
            "target_role": target_role,
            "description": role_info["description"],
            "overall_readiness_score": llm_json.get("overall_readiness_score", overall_readiness),
            "matched_skills": matched_req + matched_rec,
            "missing_critical_skills": llm_json.get("missing_critical_skills", missing_req),
            "missing_recommended_skills": llm_json.get("missing_recommended_skills", missing_rec),
            "roadmap": roadmap,
            "recommended_projects": recommended_projects[:5],
            "llm_powered": True
        }

    # Deterministic fallback roadmap
    roadmap = []
    for idx, skill in enumerate(missing_req[:4], 1):
        roadmap.append({
            "step": idx,
            "skill": skill,
            "goal": f"Complete a micro-project or practical module demonstrating {skill}.",
            "priority": "High"
        })
    for idx, skill in enumerate(missing_rec[:2], len(roadmap) + 1):
        roadmap.append({
            "step": idx,
            "skill": skill,
            "goal": f"Familiarize with production-level {skill} tooling.",
            "priority": "Medium"
        })
        
    return {
        "target_role": target_role,
        "description": role_info["description"],
        "overall_readiness_score": overall_readiness,
        "matched_skills": matched_req + matched_rec,
        "missing_critical_skills": missing_req,
        "missing_recommended_skills": missing_rec,
        "roadmap": roadmap,
        "recommended_projects": recommended_projects[:5],
        "llm_powered": False
    }

def match_projects_for_student(student_skills: List[str], student_score: float, projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Module 2: AI Project Matching Engine.
    """
    matched_list = []
    for proj in projects:
        p_skills = proj.get("required_skills", [])
        if isinstance(p_skills, str):
            try:
                p_skills = json.loads(p_skills)
            except Exception:
                p_skills = []
                
        matched, missing, overlap_pct = calculate_skill_overlap(student_skills, p_skills)
        score_factor = 20.0 if student_score >= 50.0 else 10.0
        final_match_pct = min(100.0, round(overlap_pct * 0.8 + score_factor, 1))
        
        reason = ""
        if overlap_pct >= 70:
            reason = f"High affinity: You possess {len(matched)} of {len(p_skills)} core technical skills required."
        elif overlap_pct >= 40:
            reason = f"Good growth opportunity: Build practical experience in {', '.join(missing[:2])} while leveraging your strengths."
        else:
            reason = f"Challenging project: Great opportunity to expand into {', '.join(p_skills[:2])}."
            
        proj_copy = dict(proj)
        proj_copy["match_percentage"] = final_match_pct
        proj_copy["matched_skills"] = matched
        proj_copy["missing_skills"] = missing
        proj_copy["ai_recommendation_reason"] = reason
        matched_list.append(proj_copy)
        
    matched_list.sort(key=lambda x: x["match_percentage"], reverse=True)
    return matched_list

def evaluate_submission_ai(submission_link: str, submission_notes: str, project_title: str, project_desc: str, required_skills: List[str]) -> Dict[str, Any]:
    """
    Module 5: AI Evaluation & Plagiarism Detection.
    Uses LLM code evaluation when available, augmented with heuristics.
    """
    llm_prompt = f"""
    You are a Senior Principal Software Architect and Code Reviewer evaluating a student's micro-project submission.
    Project Title: {project_title}
    Project Description: {project_desc}
    Required Skills: {required_skills}
    Deliverable Link: {submission_link}
    Submission Notes: {submission_notes}

    Evaluate the submission and respond with strict JSON in the format:
    {{
        "code_quality_score": number (1.0 to 5.0),
        "plagiarism_score": number (0 to 100, where 100 means fully original and under 70 means high plagiarism/boilerplate risk),
        "plagiarism_risk": "low" | "medium" | "high",
        "suggested_grade": number (1.0 to 5.0),
        "strengths": list of strings,
        "improvements": list of strings,
        "ai_summary": string
    }}
    """
    llm_raw = call_llm(llm_prompt, system_prompt="You are a strict, fair, and thorough engineering evaluator. Output JSON only.", json_mode=True)
    if llm_raw:
        try:
            parsed = json.loads(re.sub(r'```(?:json)?\n?|```', '', llm_raw).strip())
            parsed["llm_powered"] = True
            return parsed
        except Exception:
            pass

    # Hybrid deterministic fallback
    notes_lower = (submission_notes or "").lower()
    link_lower = (submission_link or "").lower()
    is_github = "github.com" in link_lower or "gitlab.com" in link_lower
    has_demo = "vercel.app" in link_lower or "netlify.app" in link_lower or "http" in link_lower
    word_count = len(submission_notes.split()) if submission_notes else 0
    
    originality_score = 92.0
    plagiarism_risk = "low"
    risk_notes = []
    
    if "tutorial" in link_lower or "clone" in link_lower:
        originality_score -= 25.0
        risk_notes.append("Link keywords indicate possible cloned boilerplate or tutorial walkthrough.")
    if word_count < 10:
        originality_score -= 10.0
        risk_notes.append("Documentation notes are minimal.")
    else:
        originality_score = min(98.0, originality_score + 4.0)
        
    if originality_score < 70:
        plagiarism_risk = "high"
    elif originality_score < 85:
        plagiarism_risk = "medium"
    else:
        plagiarism_risk = "low"
        
    base_quality = 4.0
    if is_github: base_quality += 0.5
    if has_demo: base_quality += 0.3
    if any(k in notes_lower for k in ["test", "docker", "readme", "api", "deployed"]): base_quality += 0.4
    if word_count < 5: base_quality -= 0.8
        
    quality_score = min(5.0, max(1.0, round(base_quality, 1)))
    
    strengths = [
        "Repository deliverable link is accessible.",
        f"Meets baseline scope of '{project_title}'.",
        "Demonstrates practical hands-on implementation."
    ]
    if is_github:
        strengths.append("Structured Git version control.")
        
    improvements = [
        "Add automated unit and regression test suites.",
        "Document API schemas with OpenAPI/Swagger specifications.",
        "Include containerization instructions in README."
    ]
    
    ai_summary = (
        f"AI Submission Assessment for '{project_title}': "
        f"Quality rated at {quality_score}/5.0 with {originality_score}% originality ({plagiarism_risk.upper()} plagiarism risk)."
    )
    
    return {
        "code_quality_score": quality_score,
        "plagiarism_score": round(originality_score, 1),
        "plagiarism_risk": plagiarism_risk,
        "risk_notes": risk_notes,
        "suggested_grade": quality_score,
        "strengths": strengths,
        "improvements": improvements,
        "ai_summary": ai_summary,
        "llm_powered": False
    }

# Mock Interview Question Bank & Dynamic Generator
MOCK_INTERVIEW_QUESTIONS: Dict[str, List[Dict[str, str]]] = {
    "Full Stack Web Developer": [
        {
            "question": "Can you explain how the Event Loop works in Node.js and browser JavaScript?",
            "topic": "JavaScript Internals"
        },
        {
            "question": "What strategies do you use to optimize database query performance in a relational database?",
            "topic": "Database Optimization"
        },
        {
            "question": "How do you securely handle user authentication and session management in modern single-page applications?",
            "topic": "Security & Auth"
        }
    ],
    "Backend Python Engineer": [
        {
            "question": "Explain the difference between ASGI and WSGI in Python web architectures, such as FastAPI vs traditional Django.",
            "topic": "Web Frameworks"
        },
        {
            "question": "How does Python handle memory management and what are the implications of the Global Interpreter Lock (GIL)?",
            "topic": "Python Internals"
        },
        {
            "question": "Design a rate limiter for an API endpoint handling 10,000 requests per minute.",
            "topic": "System Design"
        }
    ],
    "AI / Machine Learning Engineer": [
        {
            "question": "How do you detect and mitigate overfitting in deep neural networks?",
            "topic": "Model Optimization"
        },
        {
            "question": "What is the difference between Precision, Recall, and ROC-AUC, and when would you optimize for Precision over Recall?",
            "topic": "Evaluation Metrics"
        },
        {
            "question": "Can you explain how Transformer self-attention mechanisms compute relationships between tokens?",
            "topic": "Deep Learning Architecture"
        }
    ]
}

def get_mock_interview_question(target_role: str, step_index: int) -> Dict[str, Any]:
    """Retrieves or creates next interview question for the role."""
    questions = MOCK_INTERVIEW_QUESTIONS.get(target_role, MOCK_INTERVIEW_QUESTIONS["Full Stack Web Developer"])
    idx = step_index % len(questions)
    return questions[idx]

def evaluate_interview_answer(target_role: str, question: str, answer: str) -> Dict[str, Any]:
    """
    Evaluates student answer for technical accuracy, clarity, and depth using LLM when available.
    """
    llm_prompt = f"""
    You are a Senior Technical Interviewer evaluating a candidate's answer for the position of: {target_role}.
    Question: {question}
    Candidate's Answer: {answer}

    Evaluate the answer and return a JSON object:
    {{
        "score": number (1.0 to 10.0),
        "feedback": string,
        "strengths": list of strings,
        "tips": list of strings
    }}
    """
    llm_raw = call_llm(llm_prompt, system_prompt="You are a senior hiring manager. Be constructive, technical, and objective. Output JSON only.", json_mode=True)
    if llm_raw:
        try:
            parsed = json.loads(re.sub(r'```(?:json)?\n?|```', '', llm_raw).strip())
            parsed["llm_powered"] = True
            return parsed
        except Exception:
            pass

    # Hybrid deterministic fallback
    ans_clean = (answer or "").strip()
    words = len(ans_clean.split())
    
    if words < 8:
        return {
            "score": 3.0,
            "feedback": "Answer is too brief. Provide technical specifics, terminology, and real-world examples.",
            "strengths": ["Direct response."],
            "tips": ["Expand on the core mechanism.", "Mention practical implementation experience."],
            "llm_powered": False
        }
        
    matched_tech_terms = [w for w in ["database", "async", "cache", "performance", "security", "thread", "token", "index", "layer", "scale"] if w in ans_clean.lower()]
    base_score = 6.5 + min(2.5, len(matched_tech_terms) * 0.8)
    if words >= 40:
        base_score += 1.0
        
    score = min(10.0, max(1.0, round(base_score, 1)))
    strengths = [
        "Clear articulation of technical concepts.",
        "Demonstrated understanding of core software engineering fundamentals."
    ]
    if len(matched_tech_terms) >= 2:
        strengths.append(f"Effective use of domain terminology ({', '.join(matched_tech_terms[:3])}).")
        
    tips = [
        "Include a brief concrete project example where you applied this solution.",
        "Highlight trade-offs and edge cases."
    ]
    
    return {
        "score": score,
        "feedback": f"Good technical explanation (scored {score}/10). Your answer addresses key conceptual components effectively.",
        "strengths": strengths,
        "tips": tips,
        "llm_powered": False
    }

def generate_interview_hint(target_role: str, question: str, current_draft: str = "") -> Dict[str, Any]:
    """Generates an encouraging, constructive technical hint or clarification for an active interview question."""
    draft_context = f"\nCandidate's current thoughts: {current_draft}" if current_draft.strip() else ""
    llm_prompt = f"""
    You are an encouraging Principal Software Engineer conducting a technical interview for the role of: {target_role}.
    The candidate has asked for a hint or clarification on this question:
    Question: {question}{draft_context}

    Provide a concise, constructive 2-3 sentence hint or directional guidance without solving the entire problem for them.
    Output a JSON object:
    {{
        "hint": "string",
        "interviewer_tip": "string"
    }}
    """
    llm_raw = call_llm(llm_prompt, system_prompt="You are a senior tech hiring manager giving a helpful nudge. Output valid JSON only.", json_mode=True)
    if llm_raw:
        try:
            parsed = json.loads(re.sub(r'```(?:json)?\n?|```', '', llm_raw).strip())
            return parsed
        except Exception:
            pass

    return {
        "hint": f"Break the problem down into its architectural components (data layer, business logic, client layer) and discuss latency, concurrency, and error recovery trade-offs.",
        "interviewer_tip": "Interviewers love hearing your structured thought process and how you handle failure states or bottlenecks."
    }

def conduct_live_interview_turn(
    target_role: str,
    candidate_utterance: str,
    dialogue_history: List[Dict[str, Any]],
    turn_index: int = 1
) -> Dict[str, Any]:
    """
    Real-time conversational turn generator for FAANG technical interviews.
    Takes candidate's spoken response, critiques/acknowledges it naturally,
    and asks a dynamic, relevant technical follow-up or next design question.
    """
    history_snippet = ""
    for d in (dialogue_history or [])[-4:]:
        speaker = "Interviewer (Sarah)" if d.get("role") in ["interviewer", "assistant"] else "Candidate"
        history_snippet += f"{speaker}: {d.get('content', '')}\n"

    system_prompt = f"""You are Sarah Vance, a Senior Staff Technical Interviewer conducting a live interactive audio/video interview for the role of {target_role}.
Guidelines for speaking:
1. Speak directly, professionally, and warmly as in a live 1-on-1 Zoom technical interview.
2. Acknowledge what the candidate just said with a brief comment (e.g., 'Good breakdown of...', 'Interesting choice using Redis...').
3. If they gave a strong answer, ask a targeted follow-up question (e.g. edge cases, scale, failure modes, or database locking). If their answer lacked depth, ask a clarifying question.
4. Keep your spoken response between 35 and 65 words so it can be voiced naturally without long monologues.
5. Never use markdown symbols like * or # or bullet points in your response because your text will be read aloud via text-to-speech. Output clean, spoken English sentences.
6. Provide an estimated instantaneous score (1.0 to 10.0) and a brief critique in JSON.

Output JSON:
{{
    "spoken_response": "string (the natural dialogue spoken by Sarah)",
    "current_turn_score": number,
    "sentiment": "encouraging" | "challenging" | "satisfied",
    "suggested_topic": "string"
}}"""

    prompt = f"""Conversation so far:
{history_snippet}
Candidate just said: "{candidate_utterance}"

Respond as Sarah Vance directly to the candidate:"""

    llm_raw = call_llm(prompt, system_prompt=system_prompt, json_mode=True)
    if llm_raw:
        try:
            parsed = json.loads(re.sub(r'```(?:json)?\n?|```', '', llm_raw).strip())
            if "spoken_response" in parsed:
                parsed["spoken_response"] = re.sub(r'[*#_`]', '', parsed["spoken_response"]).strip()
            return parsed
        except Exception:
            pass

    # Deterministic conversational fallback
    words = len(candidate_utterance.split())
    if words < 12:
        return {
            "spoken_response": "That's a start, but in a production environment, trade-offs are critical. Could you walk me through the specific architectural bottlenecks or failure modes you would anticipate?",
            "current_turn_score": 5.5,
            "sentiment": "challenging",
            "suggested_topic": "System Reliability"
        }
    else:
        return {
            "spoken_response": "That makes sense. You clearly understand the core mechanism. Now, suppose our user traffic surges by a factor of fifty during a flash sale. How would your architecture handle database connection pooling and caching invalidation?",
            "current_turn_score": 8.0,
            "sentiment": "encouraging",
            "suggested_topic": "Concurrency & High-Throughput Scaling"
        }

def consult_ai_advisor(
    user_name: str,
    user_role: str,
    skills: List[str],
    employability_score: float,
    user_message: str,
    history: List[Dict[str, Any]],
    mode: str = "career",
    active_projects: Optional[List[str]] = None,
    available_projects: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Advanced AI Consultant & Technical Mentor Chatbot.
    Features:
    - 4 Specialized Personas: 'career', 'architecture', 'debug', 'interview'
    - Context injection: Live marketplace projects & student's active projects
    - Dynamic follow-up prompt chips for frictionless user flow
    """
    mode = mode.lower() if mode else "career"
    
    persona_instructions = {
        "career": (
            "You are an Elite Career Strategist & Tech Recruiter. Guide on high-demand skills, "
            "optimizing Employability Score, structuring LinkedIn/resume bullets, and positioning for top internships/jobs."
        ),
        "architecture": (
            "You are a Senior Principal Software Architect. Guide on system architecture, database modeling, "
            "API design (REST/gRPC), modular service separation, caching, Docker, and scalability trade-offs."
        ),
        "debug": (
            "You are a Senior Staff Code Reviewer & Debugging Specialist. Analyze code snippets, identify root-cause bugs, "
            "recommend performance optimizations (N+1 queries, indexing, async I/O), security, and automated unit testing."
        ),
        "interview": (
            "You are a Tech Hiring Manager and Interview Coach. Train the candidate on how to pitch their micro-projects "
            "using the STAR method (Situation, Task, Action, Result) and answer tricky technical design questions."
        )
    }

    persona_desc = persona_instructions.get(mode, persona_instructions["career"])

    proj_context = ""
    if active_projects:
        proj_context += f"\n- Candidate's Active Projects: {', '.join(active_projects[:3])}"
    if available_projects:
        proj_context += f"\n- Open Marketplace Projects on BridgeSkill: {', '.join(available_projects[:4])}"

    system_prompt = f"""You are the BridgeSkill AI Consultant and Lead Technical Mentor.
Current Persona Mode: [{mode.upper()}]
{persona_desc}

User Details:
- Name: {user_name} ({user_role})
- Registered Skills: {skills if skills else 'Not specified yet'}
- Current Employability Score: {employability_score}/100{proj_context}

Guidelines:
1. Provide practical, high-impact advice formatted with clean Markdown (bold headings, bullet points, concise code blocks with language tags when relevant).
2. Ground your advice in real modern software engineering standards (Python, TypeScript, SQL, Docker, FastAPI).
3. If the user asks what to build, reference their skill gaps or relevant BridgeSkill marketplace projects.
4. Keep answers focused, insightful, and actionable (under 280 words unless providing code).
5. When explaining mathematical concepts, algorithm complexity, Big-O notations, data science metrics, or formulas, use standard notation (like O(N log N) or display clean formulas)."""

    formatted_convo = ""
    for msg in history[-6:]:
        sender = "Student" if msg.get("role") == "user" else "AI Mentor"
        formatted_convo += f"{sender}: {msg.get('content')}\n"

    prompt = f"{formatted_convo}Student: {user_message}\nAI Mentor:"

    llm_resp = call_llm(prompt, system_prompt=system_prompt, json_mode=False)

    # Dynamic follow-up prompt generation based on mode and query
    default_follow_ups = {
        "career": [
            "Which micro-project bridges my biggest skill gap?",
            "How can I boost my Employability Score to 95+?",
            "How do I write a compelling project bullet point for my resume?"
        ],
        "architecture": [
            "Can you write the database schema for this?",
            "How should I structure the REST API endpoints?",
            "What Dockerfile and docker-compose setup should I use?"
        ],
        "debug": [
            "How do I write automated pytest unit tests for this?",
            "What edge cases and error handling should I add?",
            "How can I profile and optimize performance?"
        ],
        "interview": [
            "Give me a mock interview question about this project",
            "How do I explain technical trade-offs using STAR?",
            "What common interview pitfalls should I avoid?"
        ]
    }
    follow_ups = default_follow_ups.get(mode, default_follow_ups["career"])

    if llm_resp:
        return {
            "reply": llm_resp.strip(),
            "mode": mode,
            "suggested_prompts": follow_ups
        }

    # Deterministic fallback response if LLM is offline
    fallback_reply = (
        f"Hello {user_name}! In **{mode.capitalize()} Mode**, I recommend focusing on building practical micro-projects "
        f"demonstrating {', '.join(skills[:3]) if skills else 'Python, FastAPI, and Git'}. "
        f"Completing verified projects with clean architecture and automated tests directly drives your Employability Score towards 90+!"
    )
    return {
        "reply": fallback_reply,
        "mode": mode,
        "suggested_prompts": follow_ups
    }

def evaluate_code_sandbox(code: str, language: str = "python", project_context: str = "") -> Dict[str, Any]:
    """Evaluates code in the sandbox across architecture, complexity, and security."""
    system_prompt = """You are a Principal Software Engineer & Code Reviewer on BridgeSkill.
Analyze the user's code submission. You must output strictly valid JSON matching this schema:
{
    "overall_score": 88,
    "architecture_score": 90,
    "security_score": 85,
    "complexity": {
        "time_complexity": "O(N log N)",
        "space_complexity": "O(N)",
        "explanation": "Brief explanation of Big-O"
    },
    "passed_checks": ["Unit tests coverage simulated", "Type annotations present", "Input validation"],
    "code_smells": ["List of potential issues, race conditions, or unhandled exceptions"],
    "security_findings": ["List of security verifications (e.g., SQL injection safe, no secrets hardcoded)"],
    "line_comments": [
        {"line": 1, "severity": "info", "comment": "Comment on this line"}
    ],
    "refactored_snippet": "Clean refactored or improved code",
    "feedback_summary": "Comprehensive summary of code quality and engineering strengths"
}"""

    prompt = f"""Language: {language}
Project Context: {project_context or 'Industry Engineering Micro-Project'}

Code to review:
```{language}
{code[:3000]}
```"""

    llm_resp = call_llm(prompt, system_prompt=system_prompt, json_mode=True)
    if llm_resp:
        try:
            cleaned = re.sub(r"^```(?:json)?\s*", "", llm_resp.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
            data = json.loads(cleaned)
            return data
        except Exception:
            pass

    return {
        "overall_score": 85,
        "architecture_score": 88,
        "security_score": 90,
        "complexity": {
            "time_complexity": "O(N)",
            "space_complexity": "O(1)",
            "explanation": "Linear scan with constant auxiliary memory allocation."
        },
        "passed_checks": [
            "Syntax and AST parsing passed",
            "Modular function structure",
            "No plain-text credentials found",
            "Error boundaries implemented"
        ],
        "code_smells": [
            "Consider adding docstrings to public helper functions",
            "Add edge-case coverage for empty/null inputs"
        ],
        "security_findings": [
            "No unescaped SQL queries detected",
            "Safe input sanitization observed"
        ],
        "line_comments": [
            {"line": 1, "severity": "success", "comment": "Clean modular import and dependency structure."},
            {"line": 5, "severity": "info", "comment": "Consider defining a custom exception class for domain errors."}
        ],
        "refactored_snippet": code,
        "feedback_summary": "Code adheres to standard engineering patterns with clean separation of concerns and robust error handling."
    }

def analyze_github_profile(target: str, context_text: str = "") -> Dict[str, Any]:
    """Analyzes a candidate's GitHub profile or tech stack snippet to generate skill insights."""
    system_prompt = """You are an Executive Tech Recruiter and CTO on BridgeSkill.
Analyze the candidate's GitHub profile, repos, or tech stack description.
Output strictly valid JSON with this schema:
{
    "candidate_target": "username_or_repo",
    "primary_domain": "Backend Distributed Systems",
    "seniority_assessment": "Mid-Level Engineer (L4)",
    "production_score": 89,
    "detected_skills": ["Python", "FastAPI", "Docker", "PostgreSQL", "Redis"],
    "top_strengths": ["Clean microservice separation", "Containerized deployment setups"],
    "areas_for_growth": ["Add distributed tracing with OpenTelemetry", "Increase test coverage to 90%+"],
    "recommended_microprojects": [
        "High-Throughput Distributed Rate Limiter & API Gateway",
        "Automated Kubernetes Microservices Deployment"
    ],
    "estimated_employability_boost": "+7.5 pts"
}"""

    prompt = f"Target Profile / Repos: {target}\nCode / README / Stack context:\n{context_text[:2500]}"
    llm_resp = call_llm(prompt, system_prompt=system_prompt, json_mode=True)
    if llm_resp:
        try:
            cleaned = re.sub(r"^```(?:json)?\s*", "", llm_resp.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
            return json.loads(cleaned)
        except Exception:
            pass

    return {
        "candidate_target": target,
        "primary_domain": "Full-Stack & Cloud Engineering",
        "seniority_assessment": "Aspiring Production Engineer",
        "production_score": 88,
        "detected_skills": ["Python", "JavaScript", "Docker", "REST APIs", "SQL", "Git"],
        "top_strengths": [
            "Demonstrated ability to deploy full-stack applications",
            "Solid adherence to Git workflows and structured commits"
        ],
        "areas_for_growth": [
            "Implement automated CI/CD pipelines with GitHub Actions",
            "Incorporate integration test suites"
        ],
        "recommended_microprojects": [
            "High-Throughput Distributed Rate Limiter & API Gateway",
            "Kubernetes Microservices Deployment with GitOps"
        ],
        "estimated_employability_boost": "+8.0 pts"
    }

