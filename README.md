# Letterboxd Streaming Alert Pipeline 🎬

An automated Python pipeline that monitors your public **Letterboxd Watchlist** and emails you whenever any film becomes available to stream on your active subscription services.

---

## 🔒 Privacy & Public Repo Safety

This repository is designed from the ground up to **never expose your personal email address, active streaming subscriptions, or alert history** to GitHub or any public repository:

- **Email addresses** reside in `config/email.txt` or `.env` (both are gitignored).
- **Streaming services** reside in `config/services.txt` (gitignored).
- **Alert history database** (`alerts.db`) is gitignored.
- Only template files (`.env.example`, `config/email.example.txt`, `config/services.example.txt`) are committed to version control.

---

## 🚀 Features

- **Watchlist Ingestion (`feedparser` & `curl_cffi`):** Parses your Letterboxd watchlist, extracting film titles and release years while handling Cloudflare bot protection and multi-page watchlists.
- **TMDB Watch Provider Lookups (`requests`):** Queries TMDB `/search/movie` and `/movie/{id}/watch/providers` to check real-time US flatrate streaming availability.
- **Fuzzy & Canonical Service Matching:** Automatically maps naming variations across services (e.g., `Disney+` ↔ `Disney Plus`, `Apple TV+` ↔ `Apple TV Plus`, `Prime Video` ↔ `Amazon Prime Video`, `Paramount+ with Showtime` ↔ `Paramount Plus`).
- **State Deduplication & Auto-Sync:** Persists notified films in both local SQLite (`alerts.db`) and a git-friendly, privacy-preserving state file (`state/alerts_state.json`) using HMAC hashes. Alerts are sent only once per film per service.
- **Responsive HTML Email Delivery (`smtplib`):** Sends a clean, dark-themed HTML alert via Gmail SMTP SSL (`smtp.gmail.com:465`) when new arrivals are found. If no new titles are available, stdout displays a status message and email sending is skipped.
- **Zero-Maintenance GitHub Actions Automation:** Runs automatically once a week (every Friday morning) via GitHub Actions. It auto-commits state changes back to GitHub so you never have to manually run or push anything.

---

## 📁 Repository Structure

```text
streaming-notify/
├── .github/
│   └── workflows/
│       └── check_streaming.yml     # Weekly scheduled GitHub Actions workflow
├── config/
│   ├── README.md                   # Explanation of private user config
│   ├── email.example.txt           # Template for alert email (tracked)
│   ├── services.example.txt        # Template for streaming services (tracked)
│   ├── email.txt                   # YOUR private email (gitignored)
│   └── services.txt                # YOUR private active subscriptions (gitignored)
├── state/
│   └── alerts_state.json           # Privacy-preserving alert state hashes (auto-updated by GitHub Actions)
├── src/
│   ├── __init__.py
│   ├── config.py                   # Configuration loader & validator
│   ├── database.py                 # SQLite persistence & deduplication
│   ├── matcher.py                  # Canonical & fuzzy provider matching
│   ├── notifier.py                 # HTML & plain text email generator via Gmail SMTP
│   ├── tmdb.py                     # TMDB API client (search & watch providers)
│   └── watchlist.py                # Letterboxd watchlist ingestion with feedparser
├── main.py                         # CLI entrypoint
├── test_pipeline.py                # Unit and mock test suite
├── requirements.txt                # Python package dependencies
├── .env.example                    # Template environment variables (tracked)
├── .env                            # YOUR private secrets (gitignored)
└── .gitignore                      # Keeps secrets, db, and configs safe
```

---

## ⚙️ Setup & Installation

### 1. Clone & Set Up Virtual Environment

```bash
git clone <your-repo-url>
cd streaming-notify

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Your Private Files

1. **Email (`config/email.txt` or `.env`):**
   ```bash
   cp config/email.example.txt config/email.txt
   # Enter your email address inside config/email.txt
   ```

2. **Streaming Subscriptions (`config/services.txt`):**
   ```bash
   cp config/services.example.txt config/services.txt
   ```
   Add one service name per line, for example:
   ```text
   Criterion Channel
   Netflix
   Max
   Paramount Plus
   Peacock
   Disney Plus
   Hulu
   Apple TV Plus
   Amazon Prime Video
   ```

3. **Secrets (`.env`):**
   ```bash
   cp .env.example .env
   ```
   Fill in your `.env` values:
   ```ini
   TMDB_API_KEY=your_tmdb_api_key_here
   SENDER_EMAIL=your_email@gmail.com
   SENDER_APP_PASSWORD=your_16_char_google_app_password
   RECIPIENT_EMAIL=your_email@gmail.com
   LETTERBOXD_USERNAME=kclyde
   ```

> **Obtaining Credentials:**
> - **TMDB API Key:** Register a free account at [themoviedb.org](https://www.themoviedb.org/) and copy the API key from **Settings → API**.
> - **Google App Password:** If your Gmail account has 2-Step Verification enabled, generate a 16-character App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

---

## 🧪 Testing & Verification

Run the test suite to verify configuration loading, feed parsing, provider matching, SQLite deduplication, and email template generation:

```bash
python3 test_pipeline.py
```

### Dry Run (Simulate without sending emails or updating the DB)

```bash
# With real TMDB API Key:
python3 main.py --dry-run

# Mock mode (tests the pipeline end-to-end without needing API keys or passwords):
python3 main.py --mock --dry-run
```

---

## 💻 Running the Alert Pipeline

To execute the check and send real email notifications for newly available titles:

```bash
python3 main.py
```

**Options:**
- `--dry-run`: Simulate detection without sending email or marking titles as notified.
- `--mock`: Use mock streaming provider data for testing.
- `--limit N`: Limit to checking only the first `N` films in the watchlist.
- `--db path`: Use an alternative SQLite database file.
- `-v` / `--verbose`: Enable detailed debug logging.

---

## 🤖 GitHub Actions Automation

The repository includes a GitHub Actions workflow in [`.github/workflows/check_streaming.yml`](file:///.github/workflows/check_streaming.yml) that automatically runs once a week (every Friday at 13:00 UTC / 9:00 AM EDT).

### Adding Repository Secrets to GitHub

In your GitHub repository, go to **Settings → Secrets and variables → Actions** and add the following repository secrets:

| Secret Name | Description | Example |
| :--- | :--- | :--- |
| `TMDB_API_KEY` | Your TMDB API v3 Key | `a1b2c3d4...` |
| `SENDER_EMAIL` | Gmail account sending the alert | `your_email@gmail.com` |
| `SENDER_APP_PASSWORD` | Google 16-character App Password | `abcd efgh ijkl mnop` |
| `RECIPIENT_EMAIL` | Email address receiving alerts | `your_email@gmail.com` |
| `STREAMING_SERVICES` | Comma-separated list of your subscriptions | `Criterion Channel, Netflix, Max, Paramount Plus, Peacock, Disney Plus, Hulu, Apple TV Plus, Amazon Prime Video` |
| `LETTERBOXD_USERNAME` | (Optional, defaults to `kclyde`) | `kclyde` |

The workflow utilizes `actions/cache` to restore and save `alerts.db` between runs, preserving deduplication history without ever pushing the database or your subscription details into the repository.

