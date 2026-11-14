# Security policy

## Reporting a vulnerability

Please don't open a public issue for security problems.

Report them privately through GitHub instead: go to the
[Security tab](https://github.com/bencom-tech/famfam-homeassistant/security)
and choose **Report a vulnerability**. Only the maintainers can see the report.

Include what you found, how to reproduce it, and which version of the
integration and of Home Assistant you were running. You'll get a reply within a
few days, and credit in the release notes once a fix is out, if you'd like it.

## Supported versions

Fixes go into the latest release only. Update through HACS to get them.

## Your token

The integration authenticates with a FamFam integration token. If you think
yours has leaked, for example in a screenshot, a log or a pasted config, revoke it in
the FamFam app under **Settings → Your Family → Connected services**, then
create a new one and use **Reconfigure** on the integration to paste it in.

Never include your token in an issue, a discussion or a diagnostics file you've
edited by hand. The integration's own diagnostics download already redacts it.
