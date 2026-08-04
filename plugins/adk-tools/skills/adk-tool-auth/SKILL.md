---
name: adk-tool-auth
description: Use when a Google ADK (google-adk Python) tool needs authentication or user identity — OAuth2/OIDC in a tool, AuthenticatedFunctionTool versus a plain FunctionTool, CredentialService choices, storing tokens in session state, custom credential exchangers/refreshers, or when you need application roles/RBAC, service credentials or token exchange that ADK does not provide.
---

# Authentication and identity in ADK tools

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`), `google/adk-docs` and `google/adk-samples`.

## 1. Two paths, and the official samples all take the simpler one

**Self-managed (`FunctionTool`)** — documented in adk-docs
(`docs/tools-custom/authentication.md`, "Build custom tools requiring
authentication"): a plain `FunctionTool` whose body calls
`tool_context.get_auth_response(AuthConfig(...))` and
`tool_context.request_credential(...)`, caching the result in
`tool_context.state` yourself. Both real OIDC/OAuth2 custom samples use this
(`adk-samples/python/agents/adk-ae-oauth/adk_ae_oauth/auths.py`,
`adk-samples/python/agents/brand-aligner/brand_aligner_agent/auth.py`). The
authentication doc does not mention `AuthenticatedFunctionTool` at all.

**Wrapper (`AuthenticatedFunctionTool`)** — adk-python:
`src/google/adk/tools/authenticated_function_tool.py`. Marked
`@experimental(FeatureName.AUTHENTICATED_FUNCTION_TOOL)`: the API can change
between releases without compatibility guarantees.

Choose deliberately. If you need the raw OIDC ID token (for signature/issuer
verification) rather than the normalized access token the `CredentialManager`
produces, the self-managed path is the honest choice.

## 2. The `credential` parameter gotcha

`AuthenticatedFunctionTool` injects the credential **only if the wrapped
function declares a `credential` parameter**:

```python
# src/google/adk/tools/authenticated_function_tool.py
self._ignore_params.append("credential")          # __init__
...
credential = await self._credentials_manager.get_auth_credential(tool_context)
if not credential:
    await self._credentials_manager.request_credential(tool_context)
...
if "credential" in signature.parameters:          # _run_async_impl
    args_to_call["credential"] = credential
```

If your function does not declare it, the `CredentialManager` still runs the
full load / exchange / refresh cycle and **the result is silently discarded**.
Doing the fetch again by hand inside the function then means two parallel
credential paths that are never in sync, and you skip exactly the
exchange/refresh steps the manager would have applied.

Fix: either accept `credential: AuthCredential` and use it, or drop back to a
plain `FunctionTool` with the manual logic you already wrote.

## 3. Credential services run even when you do not configure one

`get_fast_api_app` instantiates an `InMemoryCredentialService()` by default
(adk-python: `src/google/adk/cli/fast_api.py`). It is process RAM, not
persisted, and it is only consulted from inside `CredentialManager` — i.e.
from the `AuthenticatedFunctionTool` path. If your real token flow is manual,
you have two stores that never talk to each other.

Available implementations
(`adk-python: src/google/adk/auth/credential_service/`):

- `InMemoryCredentialService` — default, volatile.
- `SessionStateCredentialService` — stores credentials in the session state
  under a `credential_key`. Experimental, and must be passed explicitly.

## 4. Do not put raw tokens in persisted session state

adk-docs (`docs/tools-custom/authentication.md`) warns directly: *"Storing
sensitive credentials ... directly in the session state can pose security
risks depending on your session storage backend..."*

With a persistent `SessionService` (SQLite/Postgres/Redis), a `raw_token`
written into state ends up in cleartext on disk. If you must keep something
user-scoped across sessions, split it: non-sensitive profile fields under
`user:`, the token in a non-persisted (`temp:`) key or an external secret
store. Whatever you decide, read the token through **one** accessor so a
future change is a single edit — a token read in four places is four places
to fix.

## 5. Extension points, if you need to integrate a custom flow

- `CredentialExchangerRegistry` + `CredentialManager.register_credential_exchanger(credential_type, exchanger)`
  (adk-python: `src/google/adk/auth/credential_manager.py`,
  `src/google/adk/auth/exchanger/`). Defaults registered are
  `OAuth2CredentialExchanger` (auth code → token) and
  `ServiceAccountCredentialExchanger` (Google service-account JSON → token).
- `CredentialRefresherRegistry` (`src/google/adk/auth/refresher/`).
- `AuthProviderRegistry.register(...)` (`src/google/adk/auth/auth_provider_registry.py`).
- OIDC discovery helper: `src/google/adk/auth/oauth2_discovery.py`.

## 6. What ADK deliberately does not give you

Confirmed absent from the auth modules — build these yourself, and do not
waste time looking for a native hook:

| Need | Status |
|---|---|
| Application **roles / RBAC** ("admin of workspace X") | Absent. ADK models OAuth2 `scope` only. Official samples derive at most a user id from the token. With Keycloak, the usual source is the `realm_access.roles` / `resource_access.<client>.roles` claims — verify on a real token. |
| **RFC 8693 token exchange / downscoping** per request | Absent. Declarative `scopes` on `OpenIdConnectWithConfig`/`OAuth2` are fixed at initial consent. The only hook is a custom `BaseCredentialExchanger` (§5). |
| Distinguishing a **user credential from a service credential** in the same process | Absent. `AuthCredentialTypes.SERVICE_ACCOUNT` is Google Cloud service accounts (adk-docs `docs/tools-custom/authentication.md`), and "Agent Identity" (`docs/integrations/agent-identity.md`) is a managed GCP service — neither applies to a self-hosted Keycloak/OpenStack deployment. An `access_mode="user"|"service"` switch is application logic. |
| A **session-end hook** to clean up per-session clients | No native "session end" hook in common use. If you build a client cache keyed by session, wire its cleanup to something real (app shutdown hook, TTL) or it will never run. |

## Review checklist

- [ ] `AuthenticatedFunctionTool` functions declare and use `credential` — or
      the tool is a plain `FunctionTool`.
- [ ] Only one credential path is live; no silent duplicate fetch.
- [ ] No raw token in persisted state; token read through one accessor.
- [ ] RBAC / token exchange / service-vs-user logic is acknowledged as
      application code, with its own tests.
- [ ] Experimental auth APIs are pinned and re-verified on ADK upgrade.

## Related skills

`adk-function-tools`, `adk-service-backends`, `adk-conformance-review`.
