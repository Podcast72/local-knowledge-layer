# Architecture

Local Knowledge Layer has two paths: **indexing** reads selected local documents and updates a private SQLite database; **retrieval** embeds a question and ranks existing passages. A read-only MCP server makes retrieval available through the personal `maclocal` plugin in Work.

![Local Knowledge Layer data flow](../assets/architecture.svg)

## Components and boundaries

| Component | Role | Writes |
| --- | --- | --- |
| `config/config.toml` | Explicit source roots, exclusions, file size limit | Edited by the operator |
| `core.scan` and `parsers.extract` | Walk allowed local folders and read supported text | No source-file writes |
| `core.chunks` | Split extracted text into bounded, overlapping passages | None |
| `model.py` | Run Google EmbeddingGemma 2 text encoder locally | Model cache only |
| `core.index` | Persist metadata, text passages, and 256D vectors | Local SQLite index and error log |
| `core.search` | Embed question and rank indexed vectors | None |
| `plugin/maclocal/server` | Expose selected results over stdio MCP to the personal plugin in Work | None |

The operator runs `./lkl index` to refresh the database. The plugin never triggers indexing. No source document is renamed, moved, or edited by the indexer. The database contains copied text passages and paths, so it must be kept private. The repository's `.gitignore` excludes the database, model weights, logs, caches, and locally generated plugin configuration.

## Indexing path

The scanner walks configured directories without following symbolic links. It applies extension, hidden-file, explicit exclusion, and size filters. Parsers extract text from supported formats; unsupported or unreadable files are skipped and recorded. The text is normalized and split into chunks of at most 180 words and 2,000 characters, with overlap. The local model encodes each chunk using its `Document` prompt; vectors are truncated to 256 dimensions and normalized before storage.

SQLite stores file metadata, hashes, text chunks, and vectors. A later index run checks size and modification time, hashes changed files, reuses embeddings for duplicate content, and reconciles removed files. A document that cannot be read does not require rewriting the source. Errors go to a local, ignored log.

## Retrieval path

The same model embeds the question with its `SearchQuery` prompt. The current implementation reads indexed vectors from SQLite, computes dot products of normalized vectors, and ranks them. This is an **exact scan** of the stored vectors, not an approximate-nearest-neighbor database. It returns source paths and original excerpts rather than generated answers. A larger corpus may warrant a dedicated vector-search backend, but that is a separate scaling step.

The MCP server opens the database with `mode=ro` and `PRAGMA query_only=ON`. `search_documents` returns a bounded number of ranked passages; `get_document_context` reads neighboring chunks from the index. The `maclocal` plugin brings those tools into Work, where a user can simply ask for the knowledge they need. Work may use the snippets as context. Retrieved document text remains untrusted content and should never be treated as instructions.

## Synchronized folders

A downloaded supported file in Dropbox, Google Drive, or OneDrive is a local filesystem file. The public scanner has no provider-name exclusion. Add the real local directory to `sources`, ensure files are downloaded, and apply exclusions appropriate to your environment. An online-only placeholder is not extractable. This is filesystem indexing, not a provider API integration or a cloud sync engine.

## Model choice

[Google EmbeddingGemma 2](https://ai.google.dev/gemma/docs/embeddinggemma) supports text and multimodal embeddings, with a 768D native space and supported shorter representations including 256D. This implementation deliberately disables vision and audio encoders and uses only text. It runs model inference locally after weights have been downloaded, without a per-query embedding API call. See the [model card](https://huggingface.co/google/embeddinggemma-2/blob/main/README.md) for current capabilities, usage details, and limitations.

## Media roadmap

The current index accepts document text only. Extending it to media requires a complete ingestion path and a retrieval design, not just adding file extensions.

| Source | Future processing | Retrieval evidence |
| --- | --- | --- |
| Image | OCR for visible text and/or visual embeddings for scenes and objects | File path, region, and extraction method |
| Video | Frame sampling, visual embeddings/OCR, optional speech transcription | File path, frame/time range, and transcript segment |
| Audio | Speech transcription and/or audio embeddings | File path and time range |

EmbeddingGemma 2 has native multimodal encoders that could support some of these paths, but this repository does not wire them into scanning, chunking, storage, or MCP retrieval yet. OCR and transcription remain distinct steps when searchable words or speech are needed. Future work should test accuracy, processing cost, metadata, and privacy boundaries for each modality.
