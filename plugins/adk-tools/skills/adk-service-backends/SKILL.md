---
name: adk-service-backends
description: >-
  Use when choosing or wiring the pluggable backing services of a Google ADK (google-adk Python) deployment - SessionService, ArtifactService, MemoryService, CredentialService - including self-hosted options (SQLite, Postgres, Redis, S3/MinIO), what the defaults silently are, and how to register a custom service via services.yaml or services.py.
---

# Pluggable service backends

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`), `google/adk-docs` and
`google/adk-python-community`.

## 1. Four service families

The `Runner` takes them all (adk-python: `src/google/adk/runners.py::Runner`):
`session_service` (required), `artifact_service`, `memory_service`,
`credential_service`, plus `app` / `plugins` / `resumability_config`.

**If you do not pass one, you get an in-memory implementation.** That is fine
for `adk web` and tests, and wrong for anything that must survive a restart or
run more than one replica.

## 2. Available implementations

### Session

| Class                    | Module                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------- |
| `InMemorySessionService` | `adk-python: src/google/adk/sessions/in_memory_session_service.py`                                      |
| `SqliteSessionService`   | `adk-python: src/google/adk/sessions/sqlite_session_service.py`                                         |
| `DatabaseSessionService` | `adk-python: src/google/adk/sessions/database_session_service.py` (SQLAlchemy: Postgres, MySQL, SQLite) |
| `VertexAiSessionService` | `adk-python: src/google/adk/sessions/vertex_ai_session_service.py`                                      |
| `RedisSessionService`    | `adk-python-community: src/google/adk_community/sessions/redis_session_service.py`                      |

Only a persistent service makes `app:` and `user:` state meaningful across
sessions. `temp:` is stripped before persistence regardless
(`src/google/adk/sessions/base_session_service.py::_trim_temp_delta_state`).
There is also a migration package (`src/google/adk/sessions/migration/`,
adk-docs `docs/sessions/session/migrate.md`) and session rewind
(`docs/sessions/session/rewind.md`).

### Artifact

| Class                     | Module                                                                                                                                                      |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `InMemoryArtifactService` | `adk-python: src/google/adk/artifacts/in_memory_artifact_service.py`                                                                                        |
| `FileArtifactService`     | `adk-python: src/google/adk/artifacts/file_artifact_service.py`                                                                                             |
| `GcsArtifactService`      | `adk-python: src/google/adk/artifacts/gcs_artifact_service.py`                                                                                              |
| `S3ArtifactService`       | `adk-python-community: src/google/adk_community/artifacts/s3_artifact_service.py` - `bucket_name`, `aws_configs`, `save_max_retries`; works with MinIO/Ceph |

### Memory

`InMemoryMemoryService`, `VertexAiRagMemoryService`, `VertexAiMemoryBankService`
(`adk-python: src/google/adk/memory/`), community `OpenMemoryService`
(`adk-python-community: src/google/adk_community/memory/open_memory_service.py`).
Read `adk-memory-and-retrieval` before picking one - none of the self-hostable
options does semantic search.

### Credential

`InMemoryCredentialService` (the silent default in `get_fast_api_app`) and the
experimental `SessionStateCredentialService`
(`adk-python: src/google/adk/auth/credential_service/`). See `adk-tool-auth`.

## 3. Wiring through the FastAPI app

`adk-python: src/google/adk/cli/fast_api.py::get_fast_api_app` takes URIs, not
objects:

```python
get_fast_api_app(
    agents_dir=...,
    session_service_uri="postgresql://...",   # or "sqlite:///./sessions.db"
    session_db_kwargs={...},
    artifact_service_uri=...,
    memory_service_uri=...,
    eval_storage_uri=...,
    task_store_uri=...,
    extra_plugins=[...],
    web=True,
)
```

Note there is **no `credential_service` parameter** - it is constructed
internally, and unlike session/artifact/memory the `services.py`/
`services.yaml` registry (§4 below) does not cover credentials either. See
`adk-tool-auth` §3c for the two real workarounds (build `DevServer`/
`ApiServer` yourself, or monkeypatch the hardcoded name) and §3a/§3b for two
concrete bugs (cross-session credential reuse, JSON-serialization failure
with `SessionStateCredentialService` on a persisted backend) that follow from
this gap.

## 4. Registering a custom service without forking ADK

Non-obvious and very useful: ADK resolves service URIs through a registry that
you can extend from your agents directory
(adk-python: `src/google/adk/cli/service_registry.py`, loaded by
`fast_api.py` and `cli.py` via `load_services_module`).

**Option A - `services.yaml` (or `.yml`) in the agent directory:**

```yaml
services:
  - scheme: mysession
    type: session
    class: my_package.my_module.MyCustomSessionService
  - scheme: mymemory
    type: memory
    class: my_package.other_module.MyCustomMemoryService
```

Works when the class can be built as `MyService(uri="...", **kwargs)`.
You then pass `session_service_uri="mysession://..."`.

**Option B - `services.py` in the agent directory:**

```python
from google.adk.cli.service_registry import get_service_registry
from my_package.my_module import MyCustomSessionService

def my_session_factory(uri: str, **kwargs):
    return MyCustomSessionService(...)

get_service_registry().register_session_service("mysession", my_session_factory)
```

Registry API: `register_session_service`, `register_artifact_service`,
`register_memory_service` (and the matching `create_*`). If both files are
present, YAML is processed first and `services.py` overrides on scheme
collisions.

This is how you plug in the community Redis/S3 services, or your own, without
building the `Runner` by hand.

## 5. Getting the community package

The community implementations live in a separate distribution
(`google/adk-python-community`, importable as `google.adk_community.*`) with
its own release cadence and a lighter review bar than core. Read the source of
anything you adopt from it - quality varies, and some modules
(`tools/spraay/` blockchain payment tools, for example) are narrow
domain contributions rather than general infrastructure.

## 6. Self-hosted starting point

- Session: `DatabaseSessionService` on Postgres (or `SqliteSessionService` for
  a single-node dev box; community Redis if you already run Redis and accept
  its durability model).
- Artifacts: `S3ArtifactService` against MinIO, or `FileArtifactService` on a
  mounted volume for a single node.
- Memory: nothing hosted will do semantic search - plan for an external vector
  store (`adk-memory-and-retrieval`).
- Credentials: default in-memory, and keep tokens out of persisted state
  (`adk-tool-auth`).

## Review checklist

- [ ] No `InMemory*` service in a production path.
- [ ] The session backend actually supports the state prefixes you use.
- [ ] Artifact storage survives container restarts and is shared across replicas.
- [ ] Custom services registered via `services.yaml` / `services.py` rather
      than a forked entrypoint.
- [ ] Community dependencies pinned and their source reviewed.

## Related skills

`adk-app-and-plugins`, `adk-artifacts-and-files`, `adk-memory-and-retrieval`,
`adk-tool-auth`.
