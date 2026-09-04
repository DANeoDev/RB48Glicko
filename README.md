# RB48Glicko

[![Python Version](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Framework-Flask-black.svg)](https://flask.palletsprojects.com/)
[![Database](https://img.shields.io/badge/Database-SQLite-003B57.svg)](https://www.sqlite.org/)
[![AI Ingestion](https://img.shields.io/badge/AI%20Vision%20%26%20NLP-Google%20Gemini-4285F4.svg)](https://ai.google.dev/)
[![Tests](https://img.shields.io/badge/Tests-96%20Passing-brightgreen.svg)]()
[![i18n](https://img.shields.io/badge/i18n-English%20%7C%20German-orange.svg)]()
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)]()

A full-stack sports analytics platform and Bayesian rating engine tailored for recreational football.

**RB48Glicko** combines a custom multi-player Glicko-2 skill estimation model, multimodal AI match ingestion (Google Gemini Vision & NLP), a combinatorial team matchmaking optimizer, and an advanced probabilistic calibration and validation suite (ECE, Log-Loss, LOWESS smoothing) behind a responsive, bilingual web application.

---

## 🌟 Key Highlights & Engineering Features

```
                      ┌────────────────────────────────────────────────────────┐
                      │                 Match Ingestion Layer                  │
                      │  • Manual Web Form                                     │
                      │  • Multimodal Gemini AI OCR (Handwritten Sheets)       │
                      │  • NLP Text Parsing (Chat Logs)                        │
                      │  • Bulk CSV Importer                                   │
                      └───────────────────────────┬────────────────────────────┘
                                                  │ (Structured Match Payloads)
                                                  ▼
                      ┌────────────────────────────────────────────────────────┐
                      │              SQLite Relational Database                │
                      │  Players • Aliases • Matches • Pitch Types • Snapshots │
                      └───────────────────────────┬────────────────────────────┘
                                                  │
                            ┌─────────────────────┴─────────────────────┐
                            ▼                                           ▼
         ┌─────────────────────────────────────┐     ┌─────────────────────────────────────┐
         │     Glicko-2 Bayesian Engine        │     │    Model Validation & Analytics     │
         │  • Quadratic RD Team Pooling        │     │  • Expected Calibration Error (ECE) │
         │  • Multi-Track (TOTAL / BOX / HF)   │     │  • Log-Loss (Cross-Entropy) & MAE   │
         │  • Virtual Opponent Resolution      │     │  • Scaled Goal-Diff Analysis        │
         │  • Full Replay & Incremental Modes  │     │  • Non-Parametric LOWESS Smoothing  │
         └──────────────────┬──────────────────┘     └──────────────────┬──────────────────┘
                            │                                           │
                            └─────────────────────┬─────────────────────┘
                                                  ▼
                      ┌────────────────────────────────────────────────────────┐
                      │                 Flask Web Application                  │
                      │  • Leaderboards & Historical Curves (Pure SVG)         │
                      │  • Combinatorial Matchmaker (Fairness Optimization)    │
                      │  • Real-Time Attendance Planner                        │
                      │  • Draggable "Noise" Social Annotation System          │
                      │  • RBAC (User/Admin/Webmaster) + Live Role Simulator   │
                      │  • Full Bilingual Internationalization (EN / DE)       │
                      └────────────────────────────────────────────────────────┘
```

---

### 1. 🧠 Custom Multi-Player Bayesian Rating Engine (Glicko-2)
* **Team-Level Uncertainty Aggregation:** Adapts classical 1v1 Glicko-2 to team sports by calculating team ratings as the arithmetic mean of players and team uncertainty (**Rating Deviation / RD**) via **quadratic mean pooling**—ensuring high-uncertainty players proportionally widen the team's confidence interval.
* **Multi-Track Rating Systems:** Tracks separate skill profiles for different pitch dynamics:
  * `TOTAL` (Unified overall rating across all formats)
  * `BOX` (Indoor enclosed pitch, high-scoring small-sided games)
  * `HF` (Half-pitch outdoor games)
* **Inactivity & Volatility Decay:** Dynamically expands rating uncertainty over periods of non-participation per pitch category.
* **Deterministic Replay vs. Incremental Updates:**
  * `glicko2_calculator.py`: Recomputes entire multi-season histories from raw matches with automatic database backups.
  * `glicko2_updater.py`: Real-time incremental processor for newly recorded fixtures with sub-second execution.

### 2. 📊 Probabilistic Model Validation & Calibration Suite
* **Expected Calibration Error (ECE):**
  $$\text{ECE} = \sum_{b=1}^{B} \frac{N_b}{N} |\bar{p}_b - \bar{o}_b|$$
  Evaluates reliability across discrete probability bins weighted by sample count, avoiding the variance distortion of traditional Brier scores on balanced 50:50 recreational matchups.
* **Cross-Entropy Log-Loss & MAE:** Rigorously penalizes overconfident incorrect predictions.
* **Ist vs. Soll Macro-Calibration:** Directly contrasts actual favourite win rates against the average predicted probability ($\frac{1}{N} \sum p_i$) to measure macro-level bias.
* **Normalized Goal-Difference Calibration:** Scales half-pitch scorelines to standard 10-goal benchmarks ($W \to 10, L \to L \times \frac{10}{W}$) for consistent margin-of-victory tracking.
* **LOWESS Non-Parametric Smoothing:** Locally weighted polynomial regression generating smooth empirical calibration curves rendered in native SVG without heavy JavaScript dependencies.

### 3. 🤖 Multimodal AI Ingestion (Google Gemini Vision & NLP)
* **Handwritten Match Sheet OCR:** Utilizes `gemini-2.5-flash` to extract participating player rosters, teams, pitch types, and final scores directly from photos of handwritten whiteboard/paper records.
* **Natural Language Match Parser:** Ingests unformatted group-chat messages (e.g., WhatsApp/Discord match summaries) and converts them into validated match objects.
* **Human-in-the-Loop Review:** Interactive visual verification UI allowing administrators to inspect, edit, and confirm AI extractions before committing to the database.

### 4. ⚡ Combinatorial Matchmaker & Balance Optimizer
* **Exhaustive Roster Partitioning:** Evaluates all $\binom{N}{N/2}$ team combinations for any session lineup.
* **Multi-Objective Optimization:**
  * **Win Probability Delta:** Minimizes $|P_{\text{win}}(\text{Team A}) - 0.50|$.
  * **Positional Balance:** Distributes preferred goalkeepers, defenders, and forwards evenly.
  * **Variance & Rating Spread:** Balances skill dispersion across both squads.

### 5. 🔒 Enterprise-Grade Security, Auth & Webmaster Tools
* **Role-Based Access Control (RBAC):** Tiered roles (`user`, `admin`, `webmaster`) with protected routes and administrative match-entry controls.
* **Secure Authentication:** Password hashing, verification tokens, and approval workflows for new user registrations.
* **Webmaster Role Simulation Bar:** Live testing bar allowing webmasters to simulate the exact UI, permissions, and navigation of any user role without re-authenticating.
* **Psychological Mindset / Onboarding Quiz:** Interactive questionnaire assessing variance literacy and sportsmanship before player stats are unlocked.

### 6. 🌐 Modern UI, Social Layer & Internationalization (i18n)
* **Bilingual Locale Engine:** Native English and German localization across all templates, flash messages, tooltips, and data views (`web/translations/`).
* **Noise Social Engine:** Persistent, draggable, collapsible sticky-note board for leaving comments, banter, and tactical annotations across match records.
* **Real-Time Attendance Planner:** Interactive availability tracker with headcount states (Yes / No / Maybe) for upcoming matchdays.
* **Ultra-Fast Vanilla Frontend:** Pure CSS design system with custom theme tokens and zero heavy frontend framework bloat.

### 7. 🧪 Synthetic Ground-Truth Simulation Engine
* **Monte Carlo Validation:** Generates synthetic leagues with known, hidden latent player abilities.
* **Ground-Truth Benchmarking:** Measures Glicko-2 rating convergence speed, error rates, and parameter sensitivity under controlled synthetic match conditions (`scripts/simulation/`).

---

## 🏗️ Repository Architecture

```
RB48Glicko/
├── data/                       # SQLite databases (rb48.db, accounts.db)
├── scripts/
│   ├── accounts/               # Auth, RBAC, session management & psychology test
│   ├── analysis/               # ECE, Log-Loss, MAE, LOWESS & model calibration
│   ├── database/               # Database connections, schemas & migrations
│   ├── frontend/               # Data serialization & view-model mappers
│   ├── glicko/                 # Glicko-2 engine, calculator & incremental updater
│   ├── matchmaking/            # Combinatorial team balancing optimizer
│   ├── matches/                # CSV importers, validators & Gemini AI extraction
│   └── simulation/             # Synthetic league generator & ground-truth testing
├── web/
│   ├── static/                 # CSS design system, SVG assets & client scripts
│   ├── templates/              # Jinja2 HTML templates
│   ├── translations/           # Bilingual dictionary modules (de.py, en.py)
│   └── app.py                  # Flask application entry point & route controllers
└── tests/                      # Automated test suite (96+ unit & integration tests)
```

---

## 🗄️ Database Schema Overview

```
 ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
 │     players     │       │     aliases     │       │    positions    │
 ├─────────────────┤       ├─────────────────┤       ├─────────────────┤
 │ player_id (PK)  │◄──┐   │ alias_id (PK)   │   ┌──►│ position_id(PK) │
 │ name            │   └───│ player_id (FK)  │   │   │ player_id (FK)  │
 │ is_active       │       │ alias           │   │   │ position_name   │
 └────────┬────────┘       └─────────────────┘   │   │ is_preferred    │
          │                                      │   └─────────────────┘
          │ ┌────────────────────────────────────┘
          ▼ ▼
 ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
 │  match_players  │       │     matches     │       │     ratings     │
 ├─────────────────┤       ├─────────────────┤       ├─────────────────┤
 │ match_id (FK)   │──────►│ match_id (PK)   │   ┌──►│ player_id (FK)  │
 │ player_id (FK)  │       │ match_date      │   │   │ pitch_type (PK) │
 │ team (A / B)    │       │ pitch_type      │   │   │ rating          │
 └─────────────────┘       │ goals_a         │   │   │ rd              │
                           │ goals_b         │   │   │ vol (sigma)     │
                           │ created_at      │   │   │ last_match_date │
                           └────────┬────────┘   │   └─────────────────┘
                                    │            │
                                    ▼            │
                           ┌─────────────────┐   │
                           │  match_ratings  │   │
                           ├─────────────────┤   │
                           │ match_id (FK)   │   │
                           │ player_id (FK)  ├───┘ (Historical pre-match snapshot)
                           │ rating_before   │
                           │ rd_before       │
                           └─────────────────┘
```

---

## 🚀 Quickstart & Setup

### Prerequisites
* Python 3.11, 3.12, or 3.13
* Virtual environment tool (`venv`)

### 1. Clone the Repository
```bash
git clone https://github.com/DANeoDev/RB48Glicko.git
cd RB48Glicko
```

### 2. Set Up Virtual Environment & Dependencies
```bash
# On Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# On Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. (Optional) Configure Gemini AI Integration
If you wish to use multimodal match parsing from image sheets or chat logs:
```bash
# Set your Google Gemini API key
export GEMINI_API_KEY="your-api-key-here"      # Linux / macOS
$env:GEMINI_API_KEY="your-api-key-here"        # Windows PowerShell
```

### 4. Run the Test Suite
Ensure all 96 unit and integration tests pass:
```bash
python -m unittest discover tests
```

### 5. Launch the Web Application
```bash
python web/app.py
```
The application will be accessible at `http://127.0.0.1:5000`.

---

## 🧪 Testing & Reliability

The test suite covers:
* **Mathematical Integrity:** Rating bounds, probability convergence, quadratic RD pooling, and floating-point stability.
* **Calibration & Metrics:** Expected Calibration Error (ECE), Log-Loss, MAE, and goal-difference scaling.
* **Security & Auth:** Password hashing, session isolation, role enforcement, and token expiry.
* **UI & Rendering:** Template order validation, i18n key completeness, and responsive layout structure.

To run specific test modules:
```bash
# Model analytics & calibration tests
python -m unittest tests/test_model_analysis.py

# Glicko-2 engine calculations
python -m unittest tests/test_glicko2.py

# Authentication and RBAC tests
python -m unittest tests/test_auth.py
```

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
