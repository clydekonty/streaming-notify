"""Email notification service using Gmail SMTP SSL."""

import html
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


@dataclass
class AlertItem:
    """Represents a film availability match to be notified."""
    tmdb_id: int
    title: str
    year: Optional[int]
    service: str
    letterboxd_link: Optional[str] = None
    tmdb_watch_link: Optional[str] = None
    logo_url: Optional[str] = None


def generate_email_content(alerts: List[AlertItem], username: str) -> tuple[str, str]:
    """Generate both plain text and rich HTML email content for alerts."""
    # Plain text version
    lines = [
        f"Letterboxd Watchlist Alert for @{username}",
        "=" * 40,
        f"Great news! {len(alerts)} film(s) on your watchlist are newly streaming on your active subscriptions:\n",
    ]

    for item in alerts:
        year_str = f" ({item.year})" if item.year else ""
        lines.append(f"• {item.title}{year_str}")
        lines.append(f"  Streaming on: {item.service}")
        if item.tmdb_watch_link:
            lines.append(f"  Watch Provider Link: {item.tmdb_watch_link}")
        if item.letterboxd_link:
            lines.append(f"  Letterboxd: {item.letterboxd_link}")
        lines.append("")

    lines.append("-" * 40)
    lines.append(f"Watchlist: https://letterboxd.com/{username}/watchlist/")
    text_content = "\n".join(lines)

    # HTML version
    card_htmls = []
    for item in alerts:
        year_badge = f"<span class='year'>({html.escape(str(item.year))})</span>" if item.year else ""
        safe_title = html.escape(item.title)
        safe_service = html.escape(item.service)

        buttons = []
        if item.tmdb_watch_link:
            buttons.append(
                f"<a href='{html.escape(item.tmdb_watch_link)}' class='btn btn-primary' target='_blank'>Where to Watch</a>"
            )
        if item.letterboxd_link:
            buttons.append(
                f"<a href='{html.escape(item.letterboxd_link)}' class='btn btn-secondary' target='_blank'>Letterboxd</a>"
            )

        btn_container = f"<div class='btn-group'>{' '.join(buttons)}</div>" if buttons else ""

        card_htmls.append(
            f"""
            <div class="card">
                <div class="card-content">
                    <div class="film-header">
                        <span class="film-title">{safe_title}</span> {year_badge}
                    </div>
                    <div class="platform-badge">
                        <span class="pulse-dot"></span> Now Streaming on <strong>{safe_service}</strong>
                    </div>
                    {btn_container}
                </div>
            </div>
            """
        )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Letterboxd Watchlist Alert</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background-color: #14181c;
    color: #9ab;
    margin: 0;
    padding: 24px 12px;
  }}
  .container {{
    max-width: 580px;
    margin: 0 auto;
    background-color: #1f252d;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    border: 1px solid #2c3440;
  }}
  .header {{
    background: linear-gradient(135deg, #00e054 0%, #00b040 100%);
    padding: 24px 28px;
    text-align: left;
  }}
  .header h1 {{
    color: #14181c;
    margin: 0 0 4px 0;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.5px;
  }}
  .header p {{
    color: #1a3824;
    margin: 0;
    font-size: 14px;
    font-weight: 500;
  }}
  .content {{
    padding: 24px 24px 12px 24px;
  }}
  .subtitle {{
    color: #c7d1db;
    font-size: 15px;
    margin-bottom: 20px;
    line-height: 1.4;
  }}
  .card {{
    background-color: #14181c;
    border: 1px solid #2c3440;
    border-radius: 8px;
    margin-bottom: 16px;
    padding: 16px 18px;
  }}
  .film-header {{
    margin-bottom: 8px;
  }}
  .film-title {{
    color: #ffffff;
    font-size: 18px;
    font-weight: 700;
  }}
  .year {{
    color: #89a;
    font-size: 16px;
    font-weight: 400;
  }}
  .platform-badge {{
    display: inline-block;
    background-color: rgba(0, 224, 84, 0.12);
    color: #00e054;
    padding: 5px 10px;
    border-radius: 4px;
    font-size: 13px;
    margin-bottom: 12px;
  }}
  .pulse-dot {{
    display: inline-block;
    width: 7px;
    height: 7px;
    background-color: #00e054;
    border-radius: 50%;
    margin-right: 5px;
    vertical-align: middle;
  }}
  .btn-group {{
    margin-top: 8px;
  }}
  .btn {{
    display: inline-block;
    padding: 7px 14px;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 600;
    text-decoration: none;
    margin-right: 8px;
    margin-bottom: 4px;
  }}
  .btn-primary {{
    background-color: #40bcf4;
    color: #14181c !important;
  }}
  .btn-secondary {{
    background-color: #2c3440;
    color: #bcd !important;
  }}
  .footer {{
    background-color: #181d23;
    padding: 18px 24px;
    border-top: 1px solid #2c3440;
    font-size: 12px;
    color: #678;
    text-align: center;
  }}
  .footer a {{
    color: #00e054;
    text-decoration: none;
  }}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🎬 Watchlist Streaming Alert</h1>
      <p>Letterboxd watchlist updates for @{html.escape(username)}</p>
    </div>
    <div class="content">
      <div class="subtitle">
        <strong>{len(alerts)}</strong> new film(s) from your Letterboxd watchlist are now streaming on your active subscriptions:
      </div>
      {''.join(card_htmls)}
    </div>
    <div class="footer">
      Automated alert generated by <a href="https://github.com">Letterboxd Streaming Alert</a>.<br>
      View your full watchlist at <a href="https://letterboxd.com/{html.escape(username)}/watchlist/">letterboxd.com/{html.escape(username)}/watchlist</a>.
    </div>
  </div>
</body>
</html>
"""
    return text_content, html_content


class EmailNotifier:
    """Delivers alerts using Gmail SMTP with SSL."""

    def __init__(
        self,
        sender_email: Optional[str],
        sender_app_password: Optional[str],
        recipient_email: Optional[str],
    ):
        self.sender_email = sender_email
        self.sender_app_password = sender_app_password
        self.recipient_email = recipient_email

    def send_alert(self, alerts: List[AlertItem], username: str = "kclyde", dry_run: bool = False) -> bool:
        """
        Send an HTML email alert with the matched films.

        Returns True if successful, False otherwise.
        """
        if not alerts:
            logger.info("No alerts to send.")
            return True

        if dry_run:
            logger.info("[DRY RUN] Would send alert email for %d film(s) to %s", len(alerts), self.recipient_email)
            for a in alerts:
                logger.info("  -> %s (%s) on %s", a.title, a.year or "N/A", a.service)
            return True

        if not self.sender_email or not self.sender_app_password or not self.recipient_email:
            logger.error("Missing email configuration: SENDER_EMAIL, SENDER_APP_PASSWORD, and RECIPIENT_EMAIL must all be set.")
            return False

        subject = f"🎬 Letterboxd Alert: {len(alerts)} Film{'s' if len(alerts) != 1 else ''} Now Streaming!"
        text_body, html_body = generate_email_content(alerts, username=username)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Letterboxd Alerts <{self.sender_email}>"
        msg["To"] = self.recipient_email

        # Attach text then HTML
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        logger.info("Connecting to %s:%d via SSL...", SMTP_HOST, SMTP_PORT)
        context = ssl.create_default_context()

        try:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
                server.login(self.sender_email, self.sender_app_password)
                server.sendmail(self.sender_email, [self.recipient_email], msg.as_string())
            logger.info("Successfully delivered alert email to %s for %d film(s).", self.recipient_email, len(alerts))
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error("Gmail SMTP Authentication failed: %s. Please verify SENDER_EMAIL and SENDER_APP_PASSWORD (16-character App Password).", e)
            return False
        except Exception as e:
            logger.error("Failed to send alert email via SMTP: %s", e)
            return False

