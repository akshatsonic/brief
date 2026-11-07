# Publication themes

Brief ships with two EPUB themes:

- `magazine` is the default. Each article chapter opens with its available image, category,
  headline, summary, metadata, and body.
- `classic` is a quieter newspaper treatment using the same accessible chapter structure.

EPUB is reflowable: Kindle may substitute fonts, change margins, or ignore unsupported CSS. Keep
templates deliberately simple—one reading column, strong type hierarchy, high contrast, raster
images, and no JavaScript, animation, fixed positioning, complex grids, or text over images.

## Custom templates

Set `output.template_directory` to a directory relative to `brief.yaml`:

```yaml
output:
  theme: magazine
  template_directory: ./themes/my-magazine
```

Any of these files in that directory overrides the built-in file of the same name:

| File | Template variables |
| --- | --- |
| `cover.xhtml` | `edition` (`edition.display_title` includes the date and weekday) |
| `section.xhtml` | `category`, `articles`, `article_hrefs` |
| `article.xhtml` | `article`, `image_href` |
| `style.css` | none; replaces the selected theme stylesheet |

You can start from the built-in files in `src/brief/templates/`. For example:

```bash
mkdir -p themes/my-magazine
cp src/brief/templates/article.xhtml themes/my-magazine/
cp src/brief/templates/cover.xhtml themes/my-magazine/
cp src/brief/templates/section.xhtml themes/my-magazine/
cp src/brief/templates/magazine.css themes/my-magazine/style.css
```

Keep `image_href` conditional. Some articles have no usable image, and the layout should close that
space instead of showing a placeholder. Do not load remote assets from a template: article images
are validated and packaged by Brief so the edition works offline.

Run `brief build`, then validate the result with EPUBCheck. Test on a physical Kindle or the Kindle
Previewer too, because EPUBCheck verifies structure rather than the exact rendering of a device.
