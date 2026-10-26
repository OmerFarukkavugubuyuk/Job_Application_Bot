# Handshake Job Bot

🇬🇧 English | [🇹🇷 Türkçe](README.tr.md)

An automation bot **built specifically for [Handshake](https://joinhandshake.com)** (the student job and internship platform). It scans Handshake job search results, picks software/IT-related postings, generates a **tailored CV and cover letter** for each one with Google Gemini, and submits the application through Handshake's Quick Apply form.

> **Disclaimer:** This is a personal learning project. Automating applications may violate Handshake's Terms of Service or employers' expectations, and the generated documents are not a substitute for a thoughtful, personal application. Use it at your own risk and responsibility.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Requirements](#requirements)
3. [Setup](#setup)
4. [Creating your `master_cv.json`](#creating-your-master_cvjson)
5. [Running the bot](#running-the-bot)
6. [Output files](#output-files)
7. [Customization](#customization)
8. [Limitations](#limitations)
9. [Project files](#project-files)
10. [Security](#security)

---

## How it works

1. **Manual login.** The bot opens a Chromium window (Playwright). You log in to Handshake yourself and press ENTER in the terminal. No password or session is stored by the code.
2. **Page scan.** It walks through the pages of your Handshake job search (25 jobs per page) and collects the job IDs. If a page fails to load 3 times, it moves on to the next page. It stops when a page has no jobs.
3. **Skip checks.** For each job it opens the posting and skips it if you already applied, if there is no *Quick apply / Apply* button, or if the button is disabled.
4. **Relevance filter.** A keyword filter (`TITLE_INCLUDE`, `DESC_INCLUDE` and an acronym matcher) checks the title and description for software / IT / hardware / data / AI / security related terms. Jobs that do not match are skipped.
5. **Tailored documents with Gemini.** The job description and your `master_cv.json` are sent to Google Gemini. If a model fails or times out, the next model in the list is tried.
   - The AI behaves like a résumé **editor, not a writer**: it may only *select and reorder* content that already exists in your master CV.
   - A **validation layer** checks every result. It rejects output that contains technologies, tools, numbers or words that are not in the master CV, exaggerated phrases (for example "passionate", "cutting-edge", "robust"), missing experience entries, wrong bullet text, or a cover letter with the wrong length or format.
   - If validation fails, the problems are sent back to the AI as feedback and it tries again (up to `MAX_TRIES = 3`).
6. **PDF rendering.** The Markdown output is converted to HTML and printed to PDF with Playwright. The CV is scaled down automatically to fit **one page**.
7. **Submission and verification.** The bot opens the Quick Apply form, replaces the attached documents with the generated `cv.pdf` and `cover_letter.pdf`, submits, and then **verifies** the application by waiting for the *Withdraw application* button. The result of each job is counted as `applied`, `skipped` or `failed`.
8. **Logging.** Every step is written to `job_bot.log`, and a screenshot is saved to `debug/`. A summary with the counts is printed at the end.

---

## Requirements

- Python 3.10 or newer (the author ran it on Python 3.12)
- A Handshake account
- A [Google Gemini API key](https://aistudio.google.com/)
- Playwright's Chromium browser

---

## Setup

```bash
git clone <your-repo-url>
cd handshake-job-bot

python -m venv venv
# Windows:      venv\Scripts\activate
# macOS/Linux:  source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 1. Environment variables

Copy `.env.example` to `.env` and fill in both values:

```
GEMINI_API_KEY=your_gemini_api_key_here
HANDSHAKE_SEARCH_ID=your_search_id_here
```

- `GEMINI_API_KEY`: create one in [Google AI Studio](https://aistudio.google.com/).
- `HANDSHAKE_SEARCH_ID`: on Handshake, open the job search you want the bot to scan (apply your filters first). In the address bar the URL looks like `https://app.joinhandshake.com/job-search/<NUMBER>?...`. Copy that number.

### 2. Your master CV

Copy `master_cv.example.json` to `master_cv.json` and replace the placeholder text with your own information. See the next section for the exact rules.

---

## Creating your `master_cv.json`

`master_cv.json` is your **single source of truth**. The bot never invents content; it only chooses and reorders what you write here. The file is listed in `.gitignore` so your personal data is never committed.

| Key | Type | Notes |
|---|---|---|
| `name` | string | Used in the CV header and the cover letter signature |
| `contact` | object | `location`, `email`, `linkedin`, `github` (all used in the CV header) |
| `summary` | string | Your base summary |
| `skills.programming_languages` | list | **Every item must appear in the generated CV** |
| `skills.frameworks_and_platforms` | list | **Every item must appear in the generated CV** |
| `skills.other_skills` | list | Optional ordering by relevance |
| `skills.spoken_languages` | list | Added to the skills section automatically |
| `experience` | list | Each entry has `role`, `company`, `dates`, `bullets`. All entries and bullets are kept word for word |
| `projects` | list | Projects with `name`, optional `link`, and `bullets`. These are kept word for word |
| `projects` (group) | object | One project object with `name` and `items` (a list). The CV must include **4 to 6** of these items, so provide at least 4 |
| `education` | list | Each entry has `school`, `location`, `dates`, `degree` |
| `certifications` | list | Optional |

Important details:

- The group of smaller projects must be named **`Additional Independent Projects (C#)`**, because that heading is hard-coded in `CV_STRUCTURE`. If you want a different name, change it in `CV_STRUCTURE` in `handshake_bot.py` and in your JSON.
- A bullet in the generated CV is only accepted if it matches a bullet in your master CV (the comparison ignores dash types, extra spaces and a trailing period).
- Write your bullets carefully and truthfully. They are used exactly as written in every application.

---

## Running the bot

```bash
python handshake_bot.py
```

1. A Chromium window opens on the Handshake login page.
2. Log in manually (including any verification step), then press **ENTER** in the terminal.
3. The bot starts scanning pages and applying. You can watch it work in the browser and in the terminal. Stop it any time with `Ctrl + C`.

---

## Output files

| File / folder | Description |
|---|---|
| `cv.pdf`, `cv.md` | The tailored CV for the job being processed (overwritten for each job) |
| `cover_letter.pdf`, `cover_letter.md` | The tailored cover letter for the job being processed |
| `job_bot.log` | Detailed log of everything the bot did |
| `debug/` | Screenshot of each step |

All of these are in `.gitignore`.

---

## Customization

All settings are at the top of `handshake_bot.py`:

- **Job filter:** edit `TITLE_INCLUDE`, `DESC_INCLUDE` and `ACRONYMS` to change which jobs are considered relevant.
- **AI retries and models:** `MAX_TRIES` controls validation retries; the model list is in `ask_ai()`.
- **Forbidden content:** `TECH_TERMS` (technologies that must exist in your master CV before they may appear) and `BANNED_PHRASES` (exaggerated wording).
- **Prompts:** the CV and cover letter prompts are in `generate_cv_pdf()` and `generate_cover_letter_pdf()`. Some wording was written for the author's own profile (for example, a line about mentioning a specific university in the cover letter), so review the prompts and adapt them to your profile.
- **Log language:** log messages and code comments are in Turkish.

---

## Limitations

- The bot depends on Handshake's page structure (CSS selectors and `data-hook` attributes). If Handshake changes its interface, selectors may need to be updated.
- The bot is built for the Quick apply / Apply flow inside Handshake. Postings that use a different or external application process may be skipped or fail.
- A keyword filter is not perfect, so some irrelevant jobs may still pass and some relevant ones may be skipped.
- The quality of the generated cover letters is limited by the facts in your master CV and by the AI.

---

## Project files

| File | Purpose |
|---|---|
| `handshake_bot.py` | The bot: filter, AI generation, validation, PDF rendering and the Handshake apply flow |
| `master_cv.example.json` | Template for your own `master_cv.json` |
| `.env.example` | Template for your `.env` (API key and search ID) |
| `requirements.txt` | Python dependencies |
| `.gitignore` | Keeps secrets, personal data and generated files out of Git |
| `README.md`, `README.tr.md` | Documentation (English and Turkish) |

**Tech stack:** Python, Playwright, Google Gemini API (`google-generativeai`), Markdown, python-dotenv.

---

## Security

- Never commit your `.env` file, your API key, or your `master_cv.json`.
- If an API key is ever exposed, revoke it immediately and create a new one.
- The bot never stores your Handshake password; you log in manually in the browser window.
