# NEET Master — Student Practice Portal

Flask-based NEET preparation starter with student accounts, an offline sample question bank, practice mode, mini mock tests, full-length mock test mode, bookmarks, progress tracking and optional Gemini question generation.

## Mock test modes
- Mini mock: 45 unique questions, 60 minutes.
- Full NEET mock: 180 unique questions, 180 minutes; question distribution is 45 Physics, 45 Chemistry and 90 Biology (Botany + Zoology combined).
- Both modes support Previous/Next, question palette, answer selection, submission confirmation, automatic timer submission, answer review and NEET scoring (+4 / -1 / 0).
- The backend calculates scores from submitted question IDs and the answer key, rather than trusting a score sent by the browser.
- The full test is intentionally blocked until the bank contains the required number of unique questions. The supplied starter bank has 72 sample questions (24 Physics, 16 Chemistry, 16 Botany, 16 Zoology), so it can run the 45-question mini mock but cannot yet run a true 180-question full mock. No questions are duplicated to fake a full test.

## Other features
- Student registration and mobile-number login (requested last-four-digit password format).
- Student-specific bookmarks, AI-generated questions and test history.
- Topic selection and keyword search for Physics, Chemistry, Botany and Zoology.
- MCQ practice with explanations.
- SQLite data storage and responsive interface.
- Optional Gemini AI MCQ generation (requires a Gemini API key).

## Windows setup (PowerShell)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app.py
```
Open http://127.0.0.1:5000 and register a student account. If Python 3.12 is unavailable, use an installed supported Python version.

## Login format
Register with a name, 10-digit mobile number and the last four digits of that number as password. This is a weak credential and is only suitable for a local demo. Before public deployment, switch to OTP or user-chosen strong passwords, set a strong random SECRET_KEY, enable HTTPS, CSRF protection, rate limiting and database backups.

## Enable AI generation (optional)
Set `GEMINI_API_KEY=your_key` in `.env`, then restart the app. The offline question bank and test engine do not require the AI key.

## Important content limitation
The included 72 questions are a small starter sample, not a complete NCERT-aligned or official NTA question bank. Full-length mock tests require 180 distinct, quality-checked questions. Verify all content against the current official NEET syllabus and NCERT textbooks. This is not an official NTA product.
