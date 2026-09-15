import argparse
from pathlib import Path
import tempfile
import unittest
import tomllib

from obsidian_to_hugo import Export, run


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.vault, self.site = root / 'vault', root / 'site'
        for path in [self.vault / 'assets', self.vault / 'website_assets', self.site / 'archetypes']:
            path.mkdir(parents=True)
        self.note = self.vault / 'A note.md'
        (self.vault / 'assets/a picture.png').write_bytes(b'image')
        self.export = Export(self.vault, self.site, self.note)

    def test_links_images_and_code(self):
        source = r'''---
tags: [obsidian]
---
[External](https://example.com/a_(b) "Title")
<https://example.com>
[[Another note|alias]] [Local](other.md#heading)
![[a picture.png|Picture title]]
![Other title](<assets/a picture.png> "Caption")
![Remote](https://example.com/x.png)
`![[missing.png]]` and \[[escaped]]
```markdown
![[missing.png]]
```
'''
        output = self.export.convert(source)
        self.assertNotIn('tags:', output)
        self.assertIn('[External](https://example.com/a_(b) "Title")', output)
        self.assertIn('![Picture title](/images/a%20picture.png)', output)
        self.assertIn('![Other title](/images/a%20picture.png "Caption")', output)
        self.assertIn('![Remote](https://example.com/x.png)', output)
        self.assertIn('`![[missing.png]]`', output)
        self.assertEqual(len(self.export.warnings), 2)
        self.assertIn(':6:', self.export.warnings[0])
        self.assertEqual(len(self.export.copies), 1)

    def test_references_and_dimensions(self):
        result = self.export.convert('![Title][pic]\n[Go][ext]\n![[a picture.png|300x200]]\n[pic]: <assets/a picture.png> "caption"\n[ext]: https://example.com\n')
        self.assertIn('![Title](/images/a%20picture.png "caption")', result)
        self.assertIn('[Go][ext]', result)
        self.assertTrue(any('dimensions' in w for w in self.export.warnings))

    def test_linked_image(self):
        result = self.export.convert('[![Photo](<assets/a picture.png>)](https://example.com)')
        self.assertEqual(result, '[![Photo](/images/a%20picture.png)](https://example.com)')

    def test_missing_ambiguous_and_conflicting_images(self):
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.export.convert('![[missing.png]]')
        (self.vault / 'website_assets/a picture.png').write_bytes(b'other')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.export.convert('![[a picture.png]]')
        self.export.convert('![[assets/a picture.png]]')
        with self.assertRaisesRegex(ValueError, 'share the filename'):
            self.export.convert('![[website_assets/a picture.png]]')
        dest = self.site / 'static/images/a picture.png'
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b'existing')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            Export(self.vault, self.site, self.note).convert('![[assets/a picture.png]]')

    def test_actual_hugo_export_and_dry_run(self):
        archetype = Path.home() / 'zalgorithm/archetypes/default.md'
        (self.site / 'archetypes/default.md').write_text(archetype.read_text())
        self.note.write_text('---\ntags: [old]\n---\n# Hello\n![[a picture.png]]\n')
        args = argparse.Namespace(vault=self.vault, hugo_site=self.site, note=self.note,
                                  filename=None, directory='notes', content_dir='content', dry_run=True)
        run(args)
        self.assertFalse((self.site / 'content').exists())
        self.assertFalse((self.site / 'static').exists())
        args.dry_run = False
        run(args)
        dest = self.site / 'content/notes/a-note.md'
        text = dest.read_text()
        metadata = tomllib.loads(text.split('+++')[1])
        self.assertTrue(metadata['draft'])
        self.assertEqual(metadata['title'], 'A Note')
        self.assertEqual(len(metadata['id']), 32)
        self.assertIn('![a picture](/images/a%20picture.png)', text)
        self.assertEqual((self.site / 'static/images/a picture.png').read_bytes(), b'image')
        with self.assertRaisesRegex(ValueError, 'existing post'):
            run(args)

    def test_path_escape(self):
        (self.site / 'archetypes/default.md').write_text('+++\ndraft = true\n+++')
        self.note.write_text('hello')
        args = argparse.Namespace(vault=self.vault, hugo_site=self.site, note=self.note,
                                  filename=None, directory='../outside', content_dir='content', dry_run=True)
        with self.assertRaisesRegex(ValueError, 'relative path'):
            run(args)


if __name__ == '__main__':
    unittest.main()
