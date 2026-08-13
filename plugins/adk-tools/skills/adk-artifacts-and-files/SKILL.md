---
name: adk-artifacts-and-files
description: >-
  Use when a Google ADK (google-adk Python) agent must handle files — a user attaches a PDF or image in chat and a tool cannot find it, wiring SaveFilesAsArtifactsPlugin, choosing an ArtifactService (in-memory, local file, GCS, S3), loading and listing artifacts from a tool, or returning binary/multimodal content from a tool.
---

# Files and artifacts in ADK

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`), `google/adk-docs`, `google/adk-samples` and
`google/adk-python-community`.

## 1. A file attached in chat is NOT an artifact

This is the single most common misunderstanding. When a user attaches a file,
it arrives as a `types.Part` with `inline_data` inside the user content
(`llm_request.contents` / `invocation_context.user_content`). Nothing puts it
into the artifact service, so `tool_context.load_artifact(name)` and
`list_artifacts()` will not see it. A tool that expects an artifact will fail
with "not found" and the file is never even looked for.

## 2. `SaveFilesAsArtifactsPlugin` is the native fix

adk-python: `src/google/adk/plugins/save_files_as_artifacts_plugin.py`.

What it does:

- `on_user_message_callback` — for every `Part` with `inline_data` in the
  current user message, calls
  `invocation_context.artifact_service.save_artifact(...)`, i.e. the same
  store behind `tool_context.save_artifact` / `load_artifact`.
- Filename = `Blob.display_name`; if absent it generates
  `artifact_{invocation_id}_{i}` and logs a warning.
- Replaces the binary `Part` with a text placeholder
  `[Uploaded Artifact: "<name>"]` (optionally plus a `Part(file_data=...)`
  when the canonical URI is reachable by the model).
- Records `{filename: version}` in session state under
  `"<plugin_name>:pending_delta"`, and its `before_agent_callback` merges that
  into `callback_context.actions.artifact_delta` — the same bookkeeping an
  explicit `save_artifact` from a tool produces.

Wiring (a `Plugin` is registered on the `App`/`Runner`, **not** as a
per-agent `before_model_callback`):

```python
from google.adk.apps import App
from google.adk.plugins.save_files_as_artifacts_plugin import SaveFilesAsArtifactsPlugin

app = App(
    name="my_app",
    root_agent=root_agent,
    plugins=[SaveFilesAsArtifactsPlugin()],
)
```

`AgentLoader` prefers a module-level `app` (a `google.adk.apps.App`) over
`root_agent`, so with `adk web` / `get_fast_api_app` you do not have to touch
your server code (adk-python: `src/google/adk/cli/utils/agent_loader.py`).

This is Google's own recommendation: `Runner(save_input_blobs_as_artifacts=True)`
emits a `DeprecationWarning` telling you to *"Use SaveFilesAsArtifactsPlugin
instead for better control and flexibility"* (adk-python:
`src/google/adk/runners.py`). Real usage in
`adk-samples/python/agents/product-catalog-ad-generation/content_gen_agent/agent.py`
(`App(..., plugins=[SaveFilesAsArtifactsPlugin()])` together with
`google.adk.tools.load_artifacts`).

## 3. Two things the plugin does not do for you

**Naming.** If your frontend does not set `Blob.display_name`, artifacts are
named `artifact_<invocation_id>_<i>` — opaque and impossible for the user to
retype. Fix the client to send the original filename.

**Discovery when the user does not name the file.** "Analyse this document"
gives your tool no filename. Two options:

- Attach `google.adk.tools.load_artifacts` to the consuming agent
  (adk-python: `src/google/adk/tools/load_artifacts_tool.py`). It injects the
  list of available artifact names into the LLM request, so the model can
  supply the right name itself.
- Or add a small application `before_agent_callback` that reads
  `callback_context.state.get("<plugin_name>:pending_delta")` and copies the
  most recent filename into your own convention key (e.g.
  `last_uploaded_artifact`). The plugin does not know your state conventions.

`ToolContext.list_artifacts()` (adk-python: `src/google/adk/agents/context.py`)
lets a tool enumerate what exists — use it instead of shadow-tracking
filenames in state.

## 4. Do not let a domain resolver pre-empt `load_artifact`

Frequent bug shape: a tool takes `path_or_id`, and *always* runs a
domain-specific path→ID resolver (a remote filesystem, a CMS, a bucket) before
trying the artifact store. A chat upload can never be resolved that way, so
the tool returns "not found" and never reaches the `load_artifact` line that
would have worked.

Order the lookups cheapest-and-most-local first:

```python
if path_or_id and path_or_id.strip():
    direct = await tool_context.load_artifact(path_or_id.strip())
    if direct is not None:
        artifact = direct
    else:
        ...  # domain-specific resolution
```

## 5. Artifact service implementations

| Class | Module | Notes |
|---|---|---|
| `InMemoryArtifactService` | `adk-python: src/google/adk/artifacts/in_memory_artifact_service.py` | default; lost on restart |
| `FileArtifactService` | `adk-python: src/google/adk/artifacts/file_artifact_service.py` | local filesystem, has `FileArtifactVersion` |
| `GcsArtifactService` | `adk-python: src/google/adk/artifacts/gcs_artifact_service.py` | Google Cloud Storage |
| `S3ArtifactService` | `adk-python-community: src/google/adk_community/artifacts/s3_artifact_service.py` | S3-compatible (MinIO, Ceph...); `bucket_name`, `aws_configs`, `save_max_retries` |

All implement `BaseArtifactService`
(`adk-python: src/google/adk/artifacts/base_artifact_service.py`, with
`ArtifactVersion` in `artifact_util.py`). For a self-hosted deployment,
`S3ArtifactService` from the community package is the natural GCS replacement
— see `adk-service-backends` for how to register it.

## 6. Returning files *from* a tool

A function tool's return value is JSON-ish (see `adk-function-tools`). To
return actual parts, `MultimodalToolResultsPlugin`
(adk-python: `src/google/adk/plugins/multimodal_tool_results_plugin.py`)
adapts function tool responses so they can return a list of `Part`s directly.
Its own docstring notes it is a stopgap pending native
`FunctionResponsePart` support outside computer-use tools — check whether it
is still needed on your version before depending on it.

## Review checklist

- [ ] `SaveFilesAsArtifactsPlugin` registered on the `App` if users can attach files.
- [ ] Client sets `Blob.display_name` to the original filename.
- [ ] Consuming tools try `load_artifact` before any domain resolver.
- [ ] `load_artifacts` tool or a state bridge covers "this document" with no name.
- [ ] Artifact service is persistent in production (not `InMemory`).

## Related skills

`adk-app-and-plugins`, `adk-function-tools`, `adk-structured-output`
(multimodal input to a sub-agent), `adk-service-backends`.
