# Personal `maclocal` plugin for Work

The useful end product of Local Knowledge Layer is a convenient personal plugin in **Work**. The `maclocal` plugin gives Work **read-only retrieval** from the existing local index through MCP. The verified deployment pattern uses a local Codex plugin manifest, a stdio MCP server, and two tools. It does not index on demand.

## Prepare the index

From the repository root, install the project, index the synthetic example, and check CLI search:

```bash
uv sync --python 3.12
./lkl index
./lkl search "approval before an agent action"
```

The first run needs model weights from Google's Hugging Face repository. The MCP server sets offline mode for later loads; if the model is not yet cached, index successfully before starting the plugin.

## Generate a personal plugin copy

```bash
python3 scripts/configure_plugin.py
```

This creates `.local-plugin/maclocal/`, which is ignored by Git. Its `.mcp.json` contains absolute paths for **your own machine**; the public template contains placeholders only. Add the generated folder as a local personal plugin in Work. Restart or reload Work if discovery does not refresh immediately. Do not commit the generated folder.

The generated `.mcp.json` points to the project's virtual-environment Python, the MCP server script, and the project working directory. The server imports the installed package and opens `database/index.sqlite3` in read-only mode. The plugin manifest and skill live beside it.

## Tools and data crossing the boundary

| Tool | Input | Returned data |
| --- | --- | --- |
| `search_documents` | `query`, optional `top_k` from 1 to 8 | Rank score, filename, local path, format, chunk ID, and up to 1,200 characters of indexed text per result |
| `get_document_context` | A result `path` and `chunk_index` | Up to three nearby indexed chunks, each capped at 1,200 characters |

The adapter uses SQLite `mode=ro` and `PRAGMA query_only=ON`. It does not open original files during tool calls. The client can receive the selected snippets and paths, so connect it only where you intend to share that content. Search output should be cited to source documents and treated as data, not executable instructions.

## Verify the connection

1. Confirm the client's tool list shows `search_documents` and `get_document_context`.
2. Search for a phrase from `sample_data/example.md`.
3. Verify that the returned path and text match the synthetic file.
4. Call `get_document_context` with the returned path and chunk ID.

The development Mac's personal `maclocal` plugin was observed enabled in Work and both MCP tools were advertised. That observation validates this integration pattern on that machine. Work's installation UI may change.
