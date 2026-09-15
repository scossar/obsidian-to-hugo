# Obsidian to Hugo

Export one explicitly selected Markdown note to Hugo, preserving your vault source.
Requires Python 3.11+, uv, and `hugo` on PATH. uv installs the PyYAML and TOML Kit
dependencies automatically.

```bash
uv run --project ~/projects/obsidian-to-hugo obsidian-to-hugo \
  "My note.md" --directory notes --dry-run

uv run --project ~/projects/obsidian-to-hugo obsidian-to-hugo \
  "My note.md" --directory notes
```

`--project` takes a project directory, not a `.py` file. Alternatively, run the
standalone script without installing a package:

```bash
uv run --with PyYAML --with tomlkit ~/projects/obsidian-to-hugo/obsidian_to_hugo.py "My note.md" --directory notes
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
Then enter additional flags, such as `--directory "notes" --dry-run`, or press
Enter again to continue with the options already supplied. Quoted values are
supported; shell commands and variable substitutions are not executed. Options
entered after selection override earlier values for the same option. Ctrl-C or
end-of-input at the flags prompt cancels the export.
The preview shows the first 160 lines. Escape/Ctrl-C cancels without exporting.
The picker includes Markdown notes in vault subdirectories, excluding hidden
directories and the `assets` and `website_assets` trees. Filenames with spaces,
quotes, and other special characters are passed safely to the exporter.

All exporter options are forwarded, including `--vault`, `--hugo-site`,
`--filename`, and `--dry-run`. Do not supply a positional note filename to the
picker. Supply `--vault` before opening the picker to change the directory searched.
Requires `fzf` and `rg`.
The Bash launcher is installed at `~/bin/obsidian-to-hugo-pick` and runs the
exporter project at `~/projects/obsidian-to-hugo`.

## Export behavior

- Replaces Obsidian YAML/TOML frontmatter with output from the site's actual
  `archetypes/default.md`, rendered by `hugo new content` in a temporary minimal
  site. The archetype supplies the default frontmatter.
  The title comes from the destination filename, as with your usual Hugo command.
- Copies `created_at` into Hugo's `date` as a quoted `"YYYY-MM-DD"` string.
  Accepts quoted/unquoted ISO dates and timestamps; timestamps use their written
  calendar date without timezone conversion.
- Copies frontmatter `tags` into Hugo's string array, supporting YAML block lists,
  inline lists, and a single string (one tag). Tag spelling and order are preserved.
  An explicit `[]` clears the archetype tags. Missing or null properties keep the
  archetype defaults. Invalid dates or non-string tags stop the export before writes.
  Dry runs show these overrides. Other Obsidian properties are not copied.
- Preserves external Markdown links, reference links, bare URLs, and remote images.
- Converts internal wiki links such as `[[Another note]]` to
  `[Another note](/another-note)`, using the same slugification as exported filenames.
  Aliases keep their display text: `[[Another note|alias]]` becomes
  `[alias](/another-note)`. Each conversion still prints a warning with its source
  line number: verify the destination exists in Hugo and set its full path
  (for example, `/notes/another-note` or `/posts/another-note`).
- Leaves note embeds, wiki links with heading/block anchors or empty slugs,
  relative Markdown links, and anchors
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
- Existing posts require confirmation: only `y` or `yes` allows replacement;
  Enter, end-of-input, or any other answer cancels without writing. The prompt
  applies to both the picker and direct exporter. Replacement regenerates the
  entire post, including frontmatter, from the note and archetype. The old post
  remains intact if preparing or writing its replacement fails.
- Refuses missing/ambiguous images and conflicting image filenames.
  Existing byte-identical images are reused. `--dry-run` validates and reports
  without writing, including planned post overwrites, and does not prompt for
  confirmation. Failed writes roll back newly created files.

This is a conservative Markdown converter, not a complete Obsidian renderer.
Raw HTML links/images, callouts, plugin syntax, and non-image attachments are not
converted. Complex nested Markdown constructs may require manual review.
Archetypes that depend on site configuration, data, or partials would need the
temporary-site rendering strategy extended; the current default archetype does not.

## Development

```bash
uv run python -m unittest discover -s tests -v
```

The integration test runs the installed Hugo against a temporary site using
`~/zalgorithm/archetypes/default.md`; it does not write to the real Hugo site.
