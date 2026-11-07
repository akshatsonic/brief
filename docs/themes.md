# PDF magazine theme

Brief renders a 6 × 9 inch PDF designed for comfortable Kindle reading. The built-in magazine uses
large type, high contrast, one story per page, an optional full-width image, a short summary,
important points, watchouts, and the original source link.

## Custom templates

Set a directory relative to `brief.yaml`:

```yaml
output:
  format: pdf
  theme: magazine
  template_directory: ./themes/my-magazine
```

The directory may override:

| File | Purpose |
| --- | --- |
| `magazine.html` | Complete Jinja publication template; receives `edition`, `article_images`, and `css` |
| `style.css` | Replaces the built-in paged-media stylesheet |

Start from the built-in files:

```bash
mkdir -p themes/my-magazine
cp src/brief/templates/magazine.html themes/my-magazine/
cp src/brief/templates/magazine-pdf.css themes/my-magazine/style.css
```

Keep `@page { size: 6in 9in; }` and use print-safe CSS. Article images are packaged as data URLs;
templates should never fetch remote assets. Keep image rendering conditional because some stories
have no usable image. Test custom themes on the actual target Kindle as well as a desktop PDF
reader.
