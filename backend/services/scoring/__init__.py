"""
Explainable job scoring (V2.1).

profile.py   candidate profile from the resume (AI once per resume version, keyword fallback)
facts.py     job facts (keyword pre-pass for every job, AI for the top jobs, verified against the text)
filters.py   hard filters (experience, location, job type, blocked companies/keywords)
engine.py    the weighted 0-10 score and its breakdown, computed in code
weights.py   editable part weights (sum to 100)
writer.py    cover letters (AI, task "write")
"""
