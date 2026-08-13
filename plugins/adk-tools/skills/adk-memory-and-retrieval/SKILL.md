---
name: adk-memory-and-retrieval
description: >-
  Use when adding memory or RAG to a Google ADK (google-adk Python) project - deciding between BaseMemoryService, BaseRetrievalTool and an external vector store, evaluating hosted or community memory services, wondering whether ADK gives you semantic search or multi-tenant document visibility, or deciding whether ingestion should be a conversational tool.
---

# Memory vs retrieval vs your own vector store

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`), `google/adk-docs`, `google/adk-samples` and
`google/adk-python-community`.

## 1. ADK has two abstractions, and neither is "a RAG over your documents"

**`BaseMemoryService`** - adk-python:
`src/google/adk/memory/base_memory_service.py`. Conceptually **conversational
memory**: `add_session_to_memory(session)` ingests the events of a finished
ADK session, `search_memory(app_name, user_id, query)` retrieves past turns.
It answers "what did this user and I discuss before", not "what does this
corpus of PDFs say".

**`BaseRetrievalTool`** - adk-python:
`src/google/adk/tools/retrieval/base_retrieval_tool.py`. A `BaseTool` whose
declaration is a single `query: string`, returning relevant text. This is the
closer analogue to a document RAG, but the shipped implementations are thin:

- `files_retrieval.py` / `llama_index_retrieval.py` - load a whole directory
  into an in-memory LlamaIndex **at boot**. No incremental update, no
  persistence, no tenancy. Demo-grade.
- `vertex_ai_rag_retrieval.py` - Vertex AI RAG Engine, a Google-managed
  corpus. Not self-hostable.

If you need a multi-source, incrementally updated, multi-tenant document
corpus, **there is no adequate ADK abstraction and building your own on a
vector database is the correct choice**, not an act of NIH.

## 2. Hosted and community memory services do keyword matching, not semantics

| Implementation | Where | Semantic search? |
|---|---|---|
| `InMemoryMemoryService` | `adk-python: src/google/adk/memory/in_memory_memory_service.py` | no (keyword) |
| `VertexAiRagMemoryService` | `adk-python: src/google/adk/memory/vertex_ai_rag_memory_service.py` | yes, Vertex-only |
| `VertexAiMemoryBankService` | `adk-python: src/google/adk/memory/vertex_ai_memory_bank_service.py` | yes, Vertex-only |
| `OpenMemoryService` | `adk-python-community: src/google/adk_community/memory/open_memory_service.py` | delegates to the external OpenMemory service (`base_url`, `api_key`, `OpenMemoryServiceConfig` with `search_top_k`, `timeout`) - still conversational memory |
| `adk-database-memory` (separate community package) | adk-docs: `docs/integrations/database-memory.md` | **no** |

The `adk-database-memory` documentation says it outright: *"Retrieval uses the
same keyword-extraction and matching approach as the in-memory and Firestore
memory services... For embedding-based recall, pair this package with Vertex
AI Memory Bank or a vector store."*

Conclusion, from ADK's own docs: **no hosted or community option does
self-hosted semantic search without an external vector store.** Pairing with
Qdrant / pgvector / Weaviate / Milvus is the direction ADK itself points at.

## 3. Ownership, tenancy and visibility are entirely yours

None of the examined abstractions has any notion of *who may see what*.
`BaseMemoryService` is single-tenant by design (one `app_name` / `user_id` at
a time); `BaseRetrievalTool` has no filter argument at all. A model of
public / personal / group-scoped documents, with the corresponding query-time
filter, is application code with no ADK equivalent. Do not look for a hook -
design it, and test it (see `adk-eval-harness` §custom metrics).

## 4. Should the LLM be able to write to the corpus?

The official RAG sample (`adk-samples/python/agents/RAG`) exposes exactly
**one** tool to the agent - `retrieve_rag_documentation` (query → text).
Corpus creation and ingestion live in
`shared_libraries/prepare_corpus_and_data.py`, an offline/admin pipeline that
is never a tool of the conversational agent.

Exposing `store`, `forget`, `list` as conversational tools is legitimate for a
personal knowledge base ("remember this for me"), but it is a decision, not a
default. For any **shared or public** tier, the sample's separation is the
safer pattern: reads through the agent, writes through an administrative path
with real authorization. If you keep writes conversational, gate them (see
`adk-tool-auth` §6 on the absence of RBAC, and `adk-function-tools` §5 on
`request_confirmation`).

## 5. Cheap alignment: conform the interface, keep your backend

You can subclass `BaseRetrievalTool` for the **search** tool only, keeping the
vector store underneath. Its declared `query: string` is a subset of what a
richer tool offers; extra optional parameters (filters, `max_results`,
`min_score`) are allowed. This buys interface conformance with the ADK
abstraction at near-zero cost. Write/manage tools have no ADK analogue and
correctly stay plain `FunctionTool`s.

## 6. Built-in memory tools

If you do use a `BaseMemoryService`, do not reimplement access to it:

- `src/google/adk/tools/load_memory_tool.py` - `load_memory(query)` returning
  `LoadMemoryResponse(memories=[MemoryEntry, ...])`.
- `src/google/adk/tools/preload_memory_tool.py` - `PreloadMemoryTool` runs
  automatically on every LLM request and is never called by the model.
- From a tool: `tool_context.add_memory(...)` / `tool_context.search_memory(query)`
  (`src/google/adk/agents/context.py`).

A codebase that calls its vector client directly in some agents and goes
through `ToolContext` memory in others has two ingestion paths that will drift.
Pick one.

## Review checklist

- [ ] The choice memory-service vs retrieval-tool vs own vector store is
      explicit and matches what the data actually is.
- [ ] No expectation of semantic search from a keyword-based hosted service.
- [ ] Tenancy / visibility filtering is implemented and tested as app code.
- [ ] Write and delete on shared corpora are not casually exposed to the LLM.
- [ ] One ingestion path, not two.

## Related skills

`adk-function-tools`, `adk-service-backends`, `adk-tool-auth`,
`adk-eval-harness`.
