---
name: command-output-safety
description: Prevent oversized shell or tool results from exhausting the Codex IDE extension host. Use before broad searches, recursive log inspection, verbose tests, large diffs, or data/fixture scans when result size or individual record size is unknown.
---

# Command Output Safety

Keep the requested operation complete. Bound only the data transported back to
Codex and the IDE.

## Safety invariant

- Do not return an unbounded result set or an unknown-size record through a tool
  call.
- Treat `max_output_tokens`, `head`, `Select-Object -First`, and similar display
  caps as secondary safeguards. They limit records or the final display, but a
  single minified JSON/CSV/log record can still be several megabytes.
- Do not skip required files or weaken verification merely to reduce output.
  Change the inspection shape instead.

## Choose the smallest safe result shape

Before a potentially large command, decide what evidence is actually needed:

1. To locate relevant files, return paths with `rg -l` or `rg --files` instead
   of matching line contents.
2. To measure prevalence, aggregate with `rg -c`, `Measure-Object`, or the
   domain tool's summary mode.
3. To inspect content, restrict roots and file types at the source with `-g`,
   exclude known bulk directories, and request only the relevant context.
4. When every record must be processed, aggregate or validate the full stream
   inside the command and return only totals, failures, paths, and small
   excerpts. Inspect exceptional files separately in bounded chunks.

For short or numeric patterns, start with file discovery. Do not print matching
lines across fixtures, generated outputs, minified assets, or datasets until
the matching files and their sizes are known.

## Potentially large outputs

Assume these can contain very large files or records:

- `tests/fixtures`, `debug`, generated registries, coverage and build outputs;
- `node_modules`, `dist`, `.angular`, caches, and source maps;
- JSON, JSONL, GeoJSON, CSV, SQL dumps, logs, images, and model artifacts.

Include one of these areas only when it is relevant to the request. When it is
relevant, prefer names/counts or a purpose-built parser over raw matching lines.

## Safe search patterns

For source and documentation searches, constrain file types explicitly:

```powershell
rg -n -F '1,404' docs -g '*.md'
rg -n 'isolated processes|module.*pytest' scripts docs -g '*.py' -g '*.md'
```

If the location is unknown, discover files first and then inspect selected
matches:

```powershell
rg -l -F '1404' scripts tests docs
Get-Item -LiteralPath <selected-path> | Select-Object FullName,Length
rg -n -m 20 -F '1404' <selected-path>
```

`rg -m` limits matches per file, not total bytes. Check file size before
printing content from minified or single-line formats.

## Unexpected large output

If a tool reports truncation, millions of tokens, or megabytes omitted:

- do not repeat the same command;
- identify whether the volume came from many results or one oversized record;
- switch to paths, counts, aggregation, or a format-aware parser;
- continue the original task from that bounded evidence.
