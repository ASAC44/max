# Test: Zepto MCP unauthenticated preflight

> Project disposition, 1 August 2026: preserved as valid endpoint/OAuth evidence,
> but superseded for provider selection by the authenticated failures in
> `TEST-VIRGIN.md`. Zepto is no longer an active or fallback hackathon path.

- Date/time and timezone: 1 August 2026, approximately 00:24 IST
- Operator: Codex, read-only commands in the Max workspace
- Goal/question: Is the official Zepto MCP endpoint live, and does it publish a
  standards-based OAuth discovery path suitable for an MCP client?
- Required decision/gate: Select Zepto MCP as the Phase 1 commerce source; this
  does not pass the authenticated commerce/payment gate.
- Environment: local network against Zepto production metadata; no account login
- Hardware/device/browser/network: project workstation, command-line HTTPS
- Service/package/API versions: server versions not disclosed; no local MCP
  package used
- Account/access class: unauthenticated
- Primary documentation checked: official `zeptonow/mcp` repository and Zepto
  engineering article

## Preconditions

- No Zepto access token, phone number, OTP, address, cart, or order was used.
- The test was limited to public endpoint and OAuth metadata reads.

## Exact steps

1. Request headers from `https://mcp.zepto.co.in/mcp` without authorization.
2. Follow the advertised OAuth protected-resource metadata URL.
3. Read authorization-server metadata from
   `https://auth.zepto.co.in/.well-known/oauth-authorization-server`.

## Expected result

- The MCP endpoint rejects anonymous access with `401` and advertises OAuth
  metadata.
- Protected-resource metadata identifies an authorization server and scopes.
- Authorization metadata exposes authorization-code flow with PKCE.

## Observed result

- The MCP endpoint returned `HTTP/2 401` with a `WWW-Authenticate` challenge
  pointing to `https://mcp.zepto.co.in/.well-known/oauth-protected-resource` and
  scope `tools:read`.
- Protected-resource metadata identified `https://auth.zepto.co.in`, scopes
  `tools:read` and `tools:write`, bearer-header authentication, and resource
  `https://mcp.zepto.co.in`.
- Authorization-server metadata exposed `/authorize`, `/token`, `/register`,
  authorization-code and refresh-token grants, `S256` PKCE, and public-client
  token authentication (`none`).

## Evidence

- HTTP status and public metadata were observed directly. No sensitive output
  was produced or stored.

## Deviations and interventions

- Initial guesses using path-suffixed well-known URLs returned ordinary 404
  pages. The exact URL advertised by `WWW-Authenticate` succeeded.
- Dynamic client registration and account OAuth were not attempted because they
  create external state and require user interaction.

## Conclusion

- **Observed**
- What this proves: the official endpoint was reachable and published a normal
  OAuth/PKCE MCP authentication surface from this network.
- What this does not prove: account eligibility, successful OAuth callback,
  live tool list, search/cart/quote behavior, online checkout, Prava credential
  compatibility, payment decline, order status, reliability, or OpenAI runtime
  integration.
- Follow-up: complete. The authenticated follow-up is in `TEST-VIRGIN.md`; no
  further Zepto work is scheduled.
- Documents/decisions updated: `README.md`, `DECISIONS.md`, `PRAVA.md`,
  `ARCHITECTURE.md`, `ROADMAP.md`, and `VALIDATION.md`.
