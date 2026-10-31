# User Configuration & Secrets

This directory holds your private configurations for **Letterboxd Streaming Alerts**.

Files matching `*.txt` or `*.json` (except `*.example.*`) in this folder are **ignored by git** to protect your privacy and ensure your email address and active subscriptions are never pushed to a public repository.

### Setup Instructions
1. **Streaming Services (`services.txt`):**
   Copy `services.example.txt` to `services.txt` and list the streaming services you subscribe to (one per line).

2. **Email Address (`email.txt`):**
   Copy `email.example.txt` to `email.txt` and enter your alert email address. Alternatively, specify `RECIPIENT_EMAIL` in `.env`.

