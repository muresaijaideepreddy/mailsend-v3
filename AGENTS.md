# MailSend project instructions

V3 is the primary product requirement. Use V1 only for details V3 leaves unspecified, subject to the user's explicit product decisions.

## Keep documentation current

When changing user-visible behavior, permissions, workflows, setup, configuration, limits, or error handling:

- Update `docs/MAILSEND_GUIDE.md` in the same change.
- Update `templates/mail/worker_help.html` when workers are affected.
- Update relevant setup/run/deployment documents and README links when applicable.
- Record the date and a concise entry in the guide's change history.
- Describe actual implemented behavior. Separate local availability from production deployment, and test evidence from limitations. Never put credentials, API keys, OAuth tokens, or private uploaded content in documentation.

Keep historical test reports as evidence; add a dated follow-up or status note rather than rewriting old results as new results. Documentation updates do not authorize deployment or sending emails.

Current deployment constraint: work locally unless the user explicitly authorizes another deployment. Use synthetic documents for external AI tests; private source documents and contact lists must not be sent to AI without appropriate user authorization.
