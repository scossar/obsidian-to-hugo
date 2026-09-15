# Obsidian to Hugo

Export one explicitly selected Markdown note to Hugo, preserving your vault source.
Requires Python 3.11+, uv, and `hugo` on PATH. No runtime Python dependencies.

```bash
uv run --project ~/projects/obsidian-to-hugo obsidian-to-hugo \
  "My note.md" --directory notes --dry-run

uv run --project ~/projects/obsidian-to-hugo obsidian-to-hugo \
  "My note.md" --directory notes
```

`--project` takes a project directory, not a `.py` file. Alternatively, run the
standalone script without installing a package:

```bash
uv run ~/projects/obsidian-to-hugo/obsidian_to_hugo.py "My note.md" --directory notes
```

Defaults: vault `~/obsidian_vault`, Hugo site `~/zalgorithm`, destination
`content/notes/my-note.md`. Note paths can be absolute or vault-relative; include
the `.md` extension. Use `--vault`, `--hugo-site`, `--content-dir`, and `--filename`
to override defaults. `--directory` is relative to the selected content directory.

## Fuzzy note picker

The script at `scripts/obsidian-to-hugo-pick` adds a fuzzy note picker as a convenience. Move it to
somewhere on your path (e.g.`~/bin`) and make it executable. E.g.:

```bash
install -m 755 scripts/obsidian-to-hugo-pick ~/bin/obsidian-to-hugo-pick
```

Then run from any directory:

```bash
obsidian-to-hugo-pick --directory notes --dry-run
obsidian-to-hugo-pick --directory notes
```

Type part of a filename to filter, use the arrow keys to select, and press Enter.
The preview shows the first 160 lines. Escape/Ctrl-C cancels without exporting.
The picker includes Markdown notes in vault subdirectories, excluding hidden
directories and the `assets` and `website_assets` trees. Filenames with spaces,
quotes, and other special characters are passed safely to the exporter.

All exporter options are forwarded, including `--vault`, `--hugo-site`,
`--filename`, and `--dry-run`. Do not supply a positional note filename to the
picker. `--vault` also changes the directory searched. Requires `fzf` and `rg`.
The Bash launcher is installed at `~/bin/obsidian-to-hugo-pick` and runs the
exporter project at `~/projects/obsidian-to-hugo`.

## Export behavior

- Replaces Obsidian YAML/TOML frontmatter with output from the site's actual
  `archetypes/default.md`, rendered by `hugo new content` in a temporary minimal
  site. Your current date, ID, draft, title, summary, and tags template is preserved.
  The title comes from the destination filename, as with your usual Hugo command.
- Preserves external Markdown links, reference links, bare URLs, and remote images.
- Leaves internal wiki links, note embeds, relative Markdown links, and anchors
  unchanged; prints warnings with source line numbers to stderr. Review these
  before publishing. Internal reference definitions are also reported, including
  definitions retained after converting a reference image.
- Converts `![[image.png]]`, `![[image.png|Alt text]]`, standard Markdown images,
  and reference images to `![Alt text](/images/image.png)`.
- Copies local images from `assets` or `website_assets` (including subdirectories)
  into `static/images`. Explicit paths resolve first; bare filenames must be unique.
  Spaces and URL-sensitive characters are percent-encoded in image URLs.
- Obsidian image dimensions such as `|300x200` are omitted with a warning.
- Ignores fenced/indented code, inline code, and HTML comments during conversion.
- Refuses existing posts, missing/ambiguous images, and conflicting image filenames.
  Existing byte-identical images are reused. `--dry-run` validates and reports
  without writing. Failed writes roll back newly created files.

This is a conservative Markdown converter, not a complete Obsidian renderer.
Raw HTML links/images, callouts, plugin syntax, and non-image attachments are not
converted. Complex nested Markdown constructs may require manual review.
Archetypes that depend on site configuration, data, or partials would need the
temporary-site rendering strategy extended; the current default archetype does not.

## Development

```bash
python -m unittest discover -s tests -v
```

The integration test runs the installed Hugo against a temporary site using
`~/zalgorithm/archetypes/default.md`; it does not write to the real Hugo site.
