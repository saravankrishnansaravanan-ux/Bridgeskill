import json
from backend.app.ai_service import (
    analyze_skill_gap,
    match_projects_for_student,
    evaluate_submission_ai,
    evaluate_interview_answer,
    get_mock_interview_question
)

print("=== 1. AI SKILL GAP ANALYSIS ===")
gap = analyze_skill_gap(['Python', 'SQL', 'FastAPI'], 'AI / Machine Learning Engineer', [
    {'id': 1, 'title': 'Train PyTorch Classifier', 'required_skills': ['Python', 'Machine Learning', 'PyTorch'], 'duration_days': 14}
])
print(f"Readiness Score: {gap['overall_readiness_score']}%")
print(f"Missing Critical Skills: {gap['missing_critical_skills']}")
print(f"Recommended Bridge Projects: {[p['title'] for p in gap['recommended_projects']]}")
print(f"Roadmap Steps Count: {len(gap['roadmap'])}")

print("\n=== 2. AI PROJECT MATCHING ENGINE ===")
matches = match_projects_for_student(['Python', 'FastAPI'], 75.0, [
    {'id': 10, 'title': 'Build FastAPI Microservice', 'required_skills': ['Python', 'FastAPI', 'Docker']},
    {'id': 11, 'title': 'Mobile Flutter App', 'required_skills': ['Flutter', 'Dart']}
])
for m in matches:
    print(f"-> {m['title']}: {m['match_percentage']}% Match | Reason: {m['ai_recommendation_reason']}")

print("\n=== 3. AI SUBMISSION EVALUATION & PLAGIARISM DETECTION ===")
eval_res = evaluate_submission_ai(
    'https://github.com/student/ecommerce-api',
    'Implemented clean architecture with FastAPI, unit tests, and Docker containerization.',
    'Build REST API',
    'Create endpoints',
    ['Python', 'FastAPI', 'Docker']
)
print(f"Code Quality Score: {eval_res['code_quality_score']} / 5.0")
print(f"Originality Score: {eval_res['plagiarism_score']}%")
print(f"Plagiarism Risk: {eval_res['plagiarism_risk'].upper()}")
print(f"Suggested Rating: {eval_res['suggested_grade']} / 5.0")
print(f"AI Summary: {eval_res['ai_summary']}")

print("\n=== 4. AI MOCK INTERVIEW SIMULATOR ===")
q = get_mock_interview_question('Backend Python Engineer', 0)
print(f"Generated Question: {q['question']}")
ans_eval = evaluate_interview_answer(
    'Backend Python Engineer',
    q['question'],
    'FastAPI uses ASGI which runs an asynchronous event loop via Uvicorn, handling concurrent non-blocking I/O, whereas WSGI in Django handles synchronous thread-per-request execution.'
)
print(f"Answer Score: {ans_eval['score']} / 10.0")
print(f"Feedback: {ans_eval['feedback']}")
print(f"Key Strengths Identified: {ans_eval['strengths']}")
