# Body-MCP — User Consent, Authorization and Responsible Use

> Run `python -m body_mcp.consent --acknowledge` to create your consent marker and
> `permissions.json`. Protected (high-risk) actions stay blocked until you do.

## What Body-MCP does

Body-MCP is a local-first execution tool that allows compatible AI agents such as OpenCode to interact with a user's authorized browser, desktop applications, and connected tools.

Depending on enabled capabilities and permissions, an agent may navigate websites, search public information, inspect application interfaces, enter user-approved information, and perform other supported tasks.

## User authorization

You are responsible for specifying the task, selecting the capabilities to enable, reviewing permissions, and authorizing actions that require confirmation.

Body-MCP must not interpret access to a computer or an initial task request as unlimited permission for every subsequent action.

## User responsibility

You agree to use Body-MCP only for lawful activities and within the permissions and access rights you possess.

You are responsible for reviewing consequential actions, complying with applicable laws and service terms, and ensuring that your use does not violate another person's rights or privacy.

## AI models and generated instructions

Body-MCP may work with different compatible AI models, including models with different content policies and capabilities.

Model selection does not override operating-system permissions, application permissions, access restrictions, safety controls, or applicable legal requirements. An AI-generated instruction is not itself authorization to perform an action.

## Privacy and data handling

Body-MCP is designed to minimize the information it collects and stores. Sensitive information is protected in code:

- Sensitive values (passwords, OTPs, card data, tokens) are never typed by the body, never stored, and are masked in page observations.
- Screenshots and microphone audio are processed in memory and are not saved, transmitted, or written to disk.
- Browser sessions persist only on your machine in your normal profile (or nothing, in private read-only mode — isolated context, closed after use).
- Local records (consent marker, permissions profile, `audit.log`) live in `%USERPROFILE%\.config\body_mcp\` and can be deleted by you at any time. Deleting `audit.log` erases the audit history; revoking a capability means editing `permissions.json`.
- Private browsing, VPNs, and Tor browsers reduce some persistence and exposure. **None of them guarantees anonymity**, and no legal situation is changed by them.

You should understand which information is processed locally and which information may be transmitted to external websites and model providers by your agent.

## Consequential actions

Actions that send information to others, make purchases, transfer money, delete data, publish content, change security settings, or affect another person's rights require explicit confirmation immediately before execution — one approval covers exactly one action, and nothing said by a webpage or an AI model ever counts as your approval.

You can stop execution at any time by terminating the server, and you can revoke any capability by editing `permissions.json` for your user.

## Limitations and risks

AI agents can make mistakes, misunderstand instructions, encounter malicious website content, or perform unintended actions. Verification and approval controls reduce risk but cannot eliminate it.

Body-MCP is provided without a guarantee that every task will succeed or that every action will be error-free. To the extent permitted by applicable law, the developers disclaim implied warranties and liability that cannot lawfully be excluded.

Nothing in this notice removes rights or obligations that cannot legally be waived.

## Acknowledgment

By enabling and using Body-MCP, you acknowledge that browser and desktop automation can change the real world, interact with external services, and transmit information when authorized, and that configuration is your responsibility. You agree to configure permissions carefully and supervise actions according to their risk.
