"""Email a digest of UK-viable qualifying jobs that have never been sent
before. Sends nothing (and exits quietly) when there is nothing new.

Jobs are marked as digested only AFTER the email sends successfully, so a
failed send leaves them eligible for the next run - same
never-lose-anything semantics as the rest of the pipeline.

Not part of the pytest suite - real SMTP send.
"""

import smtplib
import ssl
from email.message import EmailMessage

from jobagg.config import get_settings
from jobagg.db import connect, mark_digested, qualifying_jobs, undigested_keys

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def build_digest(rows) -> str:
    lines = []
    for r in rows:
        location = r["location"] or "location not stated"
        lines.append(f"[{r['company']}] {r['title']}")
        lines.append(f"  {location}")
        if r["url"]:
            lines.append(f"  {r['url']}")
        lines.append("")
    lines.append("Sent by jobagg - https://github.com/GaganaGowda06/jobagg")
    return "\n".join(lines)


def main() -> None:
    settings = get_settings()
    if settings.gmail_address is None or settings.gmail_app_password is None:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not configured - digest skipped.")
        return

    from jobagg.locations import is_uk_viable

    conn = connect()
    sent_before = undigested_keys(conn)
    fresh = [
        r
        for r in qualifying_jobs(conn)
        if is_uk_viable(r["location"]) and (r["source"], r["id"]) not in sent_before
    ]

    if not fresh:
        print("No new UK-viable qualifying jobs - nothing to send.")
        return

    msg = EmailMessage()
    msg["Subject"] = f"jobagg: {len(fresh)} new UK-viable qualifying job(s)"
    msg["From"] = settings.gmail_address
    msg["To"] = settings.gmail_address
    msg.set_content(build_digest(fresh))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()) as smtp:
        smtp.login(settings.gmail_address, settings.gmail_app_password.get_secret_value())
        smtp.send_message(msg)

    mark_digested(conn, [(r["source"], r["id"]) for r in fresh])
    print(f"Sent digest with {len(fresh)} job(s) to {settings.gmail_address}.")


if __name__ == "__main__":
    main()
