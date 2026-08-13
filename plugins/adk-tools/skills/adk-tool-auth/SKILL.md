---
name: adk-tool-auth
description: "Use when a Google ADK (google-adk Python) tool needs authentication or user identity - OAuth2/OIDC in a tool, AuthenticatedFunctionTool versus a plain FunctionTool, CredentialService choices, storing tokens in session state, custom credential exchangers/refreshers, or when you need application roles/RBAC, service credentials or token exchange that ADK does not provide."
---

# Authentication and identity in ADK tools

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`), `google/adk-docs` and `google/adk-samples`.

## 1. Two paths, and the official samples all take the simpler one

**Self-managed (`FunctionTool`)** - documented in adk-docs
(`docs/tools-custom/authentication.md`, "Build custom tools requiring
authentication"): a plain `FunctionTool` whose body calls
`tool_context.get_auth_response(AuthConfig(...))` and
`tool_context.request_credential(...)`, caching the result in
`tool_context.state` yourself. Both real OIDC/OAuth2 custom samples use this
(`adk-samples/python/agents/adk-ae-oauth/adk_ae_oauth/auths.py`,
`adk-samples/python/agents/brand-aligner/brand_aligner_agent/auth.py`). The
authentication doc does not mention `AuthenticatedFunctionTool` at all.

**Wrapper (`AuthenticatedFunctionTool`)** - adk-python:
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
persisted, and it is only consulted from inside `CredentialManager` - i.e.
from the `AuthenticatedFunctionTool` path. If your real token flow is manual,
you have two stores that never talk to each other.

Available implementations
(`adk-python: src/google/adk/auth/credential_service/`):

- `InMemoryCredentialService` - default, volatile.
- `SessionStateCredentialService` - stores credentials in the session state
  under a `credential_key`. Experimental, and must be passed explicitly.

### 3a. `InMemoryCredentialService` is keyed by `(app_name, user_id)`, not session

`InMemoryCredentialService._get_bucket_for_current_context` (adk-python:
`src/google/adk/auth/credential_service/in_memory_credential_service.py`)
buckets purely on `app_name`/`user_id`. Combine that with `CredentialManager
.get_auth_credential`'s resolution order (adk-python:
`src/google/adk/auth/credential_manager.py`) - step 3
(`_load_from_credential_service`, the shared bucket) runs **before** step 4
(`_load_from_auth_response`, the current turn's own OIDC exchange) - and the
consequence is concrete: once _any_ session under a given `(app_name,
user_id)` completes interactive login, _every other_ session sharing that
same pair (e.g. a dev-ui client that never changes its `userId` field)
silently reuses that stale credential. `AuthenticatedFunctionTool.run_async`
finds a truthy credential from step 3, so it never calls
`request_credential()` - the fresh session gets no popup at all, and unless
your function actually uses the injected `credential` (§2), it falls through
to whatever "no auth yet" string you return, which reads like a bug in your
tool rather than what it is: a caching layer working exactly as coded, on an
identity key that was too coarse for your use case.

This is not a `SessionStateCredentialService` problem - it is inherent to
having _any_ cross-session shared bucket under an identity key your
application does not otherwise guarantee is per-conversation. Fix at the
identity layer (§7), not by trying to force fresher lookups here.

### 3b. `SessionStateCredentialService` breaks persisted session stores

`SessionStateCredentialService.save_credential` (same module) does
`callback_context.state[auth_config.credential_key] =
auth_config.exchanged_auth_credential` - the **raw `AuthCredential` pydantic
object**, not a dict. `InMemorySessionService` tolerates that fine. Any
persisted backend from `adk-service-backends` (`DatabaseSessionService` in
particular) serializes state to JSON on save and throws `TypeError: Object of
type AuthCredential is not JSON serializable` on the very first exchanged
login. Reproduced directly against SQLite via `DatabaseSessionService`.

Fix: subclass it and dump/reparse around the same storage -

```python
class JsonSafeSessionStateCredentialService(SessionStateCredentialService):
    async def load_credential(self, auth_config, callback_context):
        raw = callback_context.state.get(auth_config.credential_key)
        if raw is None or isinstance(raw, AuthCredential):
            return raw
        return AuthCredential.model_validate(raw)

    async def save_credential(self, auth_config, callback_context):
        callback_context.state[auth_config.credential_key] = (
            auth_config.exchanged_auth_credential.model_dump(mode="json")
        )
```

### 3c. No public parameter to inject any of this

`get_fast_api_app` hardcodes `credential_service = InMemoryCredentialService()`
with no `credential_service`/`credential_service_uri` argument - confirmed:
it is the only one of the four service families (session/artifact/memory all
take a `*_uri`) without an override (see also `adk-service-backends` §3). The
`services.py`/`services.yaml` registry (`adk-service-backends` §4) does not
cover it either - `ServiceRegistry` only has `session`/`artifact`/`memory`/
`task_store` factory dicts (adk-python:
`src/google/adk/cli/service_registry.py`), no `credential`.

Two real options, not one: (a) do not call `get_fast_api_app` and build
`DevServer`/`ApiServer` yourself, passing `credential_service` to its real
constructor parameter (adk-python: `src/google/adk/cli/api_server.py`) - the
"correct" API but means reimplementing the ~500-line body of
`get_fast_api_app` (agent-loader detection, eval managers, CORS, builder
endpoints, A2A, reload observer) by hand, which is more surface to keep in
sync across ADK upgrades than option (b); or (b) monkeypatch the name
`google.adk.cli.fast_api.InMemoryCredentialService` to your class _before_
calling `get_fast_api_app` - one hardcoded name, isolated and commented,
versus ~500 lines forked. In practice (b) is the pragmatic choice; treat it
as tech debt to revisit each ADK upgrade, and worth an upstream feature
request (`credential_service_uri` + a `credential` scheme in
`ServiceRegistry` would close this cleanly).

## 4. Do not put raw tokens in persisted session state

adk-docs (`docs/tools-custom/authentication.md`) warns directly: _"Storing
sensitive credentials ... directly in the session state can pose security
risks depending on your session storage backend..."_

With a persistent `SessionService` (SQLite/Postgres/Redis), a `raw_token`
written into state ends up in cleartext on disk. If you must keep something
user-scoped across sessions, split it: non-sensitive profile fields under
`user:`, the token in a non-persisted (`temp:`) key or an external secret
store. Whatever you decide, read the token through **one** accessor so a
future change is a single edit - a token read in four places is four places
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

Confirmed absent from the auth modules - build these yourself, and do not
waste time looking for a native hook:

| Need                                                                               | Status                                                                                                                                                                                                                                                                                                          |
| ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Application **roles / RBAC** ("admin of workspace X")                              | Absent. ADK models OAuth2 `scope` only. Official samples derive at most a user id from the token. With Keycloak, the usual source is the `realm_access.roles` / `resource_access.<client>.roles` claims - verify on a real token.                                                                               |
| **RFC 8693 token exchange / downscoping** per request                              | Absent. Declarative `scopes` on `OpenIdConnectWithConfig`/`OAuth2` are fixed at initial consent. The only hook is a custom `BaseCredentialExchanger` (§5).                                                                                                                                                      |
| Distinguishing a **user credential from a service credential** in the same process | Absent. `AuthCredentialTypes.SERVICE_ACCOUNT` is Google Cloud service accounts (adk-docs `docs/tools-custom/authentication.md`), and "Agent Identity" (`docs/integrations/agent-identity.md`) is a managed GCP service - neither applies to a self-hosted Keycloak/OpenStack deployment. An `access_mode="user" | "service"` switch is application logic. |
| A **session-end hook** to clean up per-session clients                             | No native "session end" hook in common use. If you build a client cache keyed by session, wire its cleanup to something real (app shutdown hook, TTL) or it will never run.                                                                                                                                     |
| **Verifying `user_id` belongs to the caller**                                      | Absent, deliberately out of scope - see §7.                                                                                                                                                                                                                                                                     |

## 7. `user_id` (session identity) and tool-delegated credentials are two separate, unauthenticated-by-default layers - do not conflate them

Everything above (§1-6) is about a **tool** obtaining delegated access to a
downstream API "on behalf of an already-known user" - that phrase is
adk-docs' own framing (`docs/tools-custom/authentication.md`). It presupposes
the caller's identity is already established. It is not the mechanism that
establishes it.

`user_id` - the value that partitions everything (`SessionService`,
`ArtifactService`, `MemoryService` storage, and the credential buckets in
§3a) - is a second, separate layer, and ADK treats it as an opaque string the
caller supplies with **zero verification**:

- adk-docs Sessions page: the entire specification of `user_id` is _"Links
  the conversation to a particular user."_ No security model, no ownership
  check.
- Google's own reference HTTP client for the ADK web server (adk-python:
  `src/google/adk/cli/conformance/adk_web_server_client.py`) sends **no
  `Authorization` header on any request** - confirms there is no implicit
  wire-level convention being missed.
- `user_id` arrives via a URL path segment on every `/apps/{app_name}/users/
{user_id}/...` route, or inside the JSON body on `/run` and `/run_sse`
  (`req.user_id`, adk-python: `src/google/adk/cli/api_server.py`), and again
  inside the JSON body as a derived value on the opt-in
  `/apps/{app_name}/trigger/pubsub` and `/trigger/eventarc` routes
  (adk-python: `src/google/adk/cli/trigger_routes.py`, only registered if you
  pass `trigger_sources=[...]`). None of these routes check who is asking.
- `cli_deploy.py` (`adk deploy cloud_run` / `to_gke` / `to_agent_engine`)
  confirms this is deliberate, not an oversight: none of ADK's own deploy
  targets wire up caller auth. Cloud Run gets whatever `gcloud run deploy`
  itself defaults to (ADK never passes `--allow-unauthenticated` either way);
  the generated GKE manifest has no NetworkPolicy/Ingress/IAP; only Agent
  Engine gets caller auth for free, and that is Vertex AI's own IAM, external
  to ADK. The `--url_prefix` option's own help text - _"when the application
  is mounted behind a reverse proxy or API gateway"_ - confirms ADK expects
  something else to sit in front and handle this.

**Practical consequence**: if more than one real, distinct human will ever
call your deployment (i.e. almost always, outside of solo `adk web` use), you
must build a thin identity gateway yourself. There is no flag, no built-in
class, and no sample that does this for you. A workable, self-contained
pattern - a `starlette.middleware.base.BaseHTTPMiddleware` added via
`app.add_middleware(...)` on the object `get_fast_api_app()` returns (it is a
plain `FastAPI` instance, nothing prevents adding your own middleware after
the fact):

1. Extract and verify a bearer token (your own IdP - OIDC/JWT signature +
   issuer, same mechanism §1 already uses for the tool-delegated token; it
   can be the _same_ token if your IdP is also the API's authority).
2. Derive the verified identity from a trusted claim (e.g.
   `preferred_username`).
3. Extract the _claimed_ `user_id` - regex the path for
   `/apps/[^/]+/users/([^/]+)`, or read `request.body()` (Starlette caches
   it, so downstream Pydantic parsing still works) and pull `user_id` out of
   the JSON for `/run`/`/run_sse`.
4. Reject (401/403) on missing token or mismatch. Do not silently rewrite -
   a mismatch is a bug or tampering, not something to paper over.

This is deployment-level plumbing, not a tool concern, but it belongs in this
skill because getting §1-6 right is meaningless if step 0 - knowing who is
actually asking - was never verified.

## Review checklist

- [ ] `AuthenticatedFunctionTool` functions declare and use `credential` - or
      the tool is a plain `FunctionTool`.
- [ ] Only one credential path is live; no silent duplicate fetch.
- [ ] No raw token in persisted state; token read through one accessor.
- [ ] RBAC / token exchange / service-vs-user logic is acknowledged as
      application code, with its own tests.
- [ ] Experimental auth APIs are pinned and re-verified on ADK upgrade.
- [ ] If a persisted `SessionService` is in use with
      `SessionStateCredentialService`, credentials are dumped/reparsed as
      JSON, not stored as raw pydantic objects (§3b).
- [ ] `user_id` is verified against an authenticated caller identity before
      it reaches ADK, for every deployment with more than one real user (§7)
      - not assumed safe because "only the dev-ui talks to this today".

## Related skills

`adk-function-tools`, `adk-service-backends`, `adk-conformance-review`.
