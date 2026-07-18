"""
bonaid/notifier.py
Free, open-source notification channels - no paid services required.
Ported from the standalone trading_system project's notifier.py (which
worked well there) and properly integrated into bonaid this time, wired
directly into Paper Trading events rather than living in a disconnected
codebase.

EMAIL: Python's built-in smtplib + any free SMTP (Gmail app password works).
TELEGRAM: Telegram's free Bot API (plain HTTP POST, no extra library).

Both channels are optional and independent - configure one, both, or
neither via .env. Missing config for a channel means that channel is
silently skipped (printed, not raised) so alerting never blocks or crashes
the actual trading logic that triggered it.
"""
import smtplib
import urllib.request
import urllib.parse
from email.mime.text import MIMEText

from bonaid.config import settings


def send_email(subject: str, body: str) -> bool:
    if not settings.alerts_enabled:
        return False
    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_pass, settings.alert_email_to]):
        return False  # not configured - silently skip, this is expected/fine

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = settings.alert_email_to

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.smtp_user, [settings.alert_email_to], msg.as_string())
        return True
    except Exception as e:
        print(f"[notifier] Email failed: {e}")
        return False


def send_telegram(message: str) -> bool:
    if not settings.alerts_enabled:
        return False
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False  # not configured - silently skip

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": settings.telegram_chat_id,
        "text": message[:4000],  # Telegram message length limit
    }).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
        return True
    except Exception as e:
        print(f"[notifier] Telegram failed: {e}")
        return False


def notify(subject: str, body: str) -> dict:
    """Sends to every configured channel. Returns which channels actually
    succeeded, so callers can log/display that if useful - but never raises,
    so a notification failure never breaks the trading logic that triggered it."""
    email_ok = send_email(subject, body)
    telegram_ok = send_telegram(f"*{subject}*\n\n{body}")
    return {"email": email_ok, "telegram": telegram_ok}


# --- Event-specific formatters - keep the actual alert wording in one place
# rather than scattered inline at each call site in paper_trading.py/cli.py ---

def notify_position_opened(ticker: str, shares: int, entry_price: float, stop_loss: float, take_profit: float, confidence: float):
    subject = f"Bonaid: Opened {ticker}"
    body = (
        f"Opened paper position: {shares} shares of {ticker} @ ${entry_price}\n"
        f"Confidence: {confidence}%\n"
        f"Stop-loss: ${stop_loss}\n"
        f"Take-profit: ${take_profit}"
    )
    return notify(subject, body)


def notify_position_closed(ticker: str, shares: int, exit_price: float, reason: str, pnl: float):
    result = "PROFIT" if pnl > 0 else "LOSS"
    subject = f"Bonaid: Closed {ticker} ({result})"
    body = (
        f"Closed {shares} shares of {ticker} @ ${exit_price}\n"
        f"Reason: {reason}\n"
        f"Realized P&L: ${pnl:,.2f}"
    )
    return notify(subject, body)


def notify_exposure_refused(ticker: str, projected_pct: float, cap_pct: float):
    subject = f"Bonaid: {ticker} BUY refused (exposure cap)"
    body = (
        f"A BUY signal on {ticker} was NOT executed - it would have pushed total portfolio "
        f"exposure to {projected_pct}%, over the {cap_pct}% cap.\n\n"
        f"Run `bonaid portfolio` to review current positions."
    )
    return notify(subject, body)


def notify_portfolio_drawdown(drawdown_pct: float, total_unrealized_pnl: float, auto_closed: bool):
    subject = f"Bonaid: PORTFOLIO DRAWDOWN ALERT ({drawdown_pct}%)"
    action_line = (
        "All open positions were AUTO-CLOSED (kill switch enabled)."
        if auto_closed else
        "Positions were NOT auto-closed - review and act manually (`bonaid positions`, `bonaid close`)."
    )
    body = (
        f"Total unrealized P&L across open positions has breached the portfolio-level "
        f"drawdown guideline.\n\n"
        f"Drawdown: {drawdown_pct}%\n"
        f"Unrealized P&L: ${total_unrealized_pnl:,.2f}\n\n"
        f"{action_line}"
    )
    return notify(subject, body)
