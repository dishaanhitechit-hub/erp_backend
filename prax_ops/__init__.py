"""
Shared pieces for PRAX ERP operations (Python standard library only, so the
server alert scripts can use them with the system python3 too):

  recipients   — who gets which alert email (one JSON file for every sender)
  email_html   — the PRAX alert email look (header, status banner, rows…)
  mailer       — send an HTML + plain-text email over SMTP
"""

__version__ = "1.1.0"
