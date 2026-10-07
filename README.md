<p align="center">
  <a href="https://github.com/lamplitlabs/blog">
    <img src="assets/img/favicons/android-chrome-512x512.png" width="256px" />
  </a>
</p>
<h1 align="center">Blog</h1>

A space for my stories about AI, dotnet, c#, azure, devops and more

## How to Use

### Install dependencies

```bash
bundle install
```

### Run the development server

```bash
bundle exec jekyll s
```

## Local checks

Run the same checks the build relies on before opening a pull request:

```bash
bash tools/test.sh
```

Before building, the script checks every post under `_posts/` (subfolders
included) and prints one summary line per check:

- Tag case: the build **fails** if two posts spell the same tag with different
  letter case (e.g. `Azurite` vs `azurite`), since Jekyll would drop one tag page.
- `category-case-duplicates`: the build **fails** if two posts use the same
  category with different letter case (e.g. `Drawio` vs `drawio`), since Jekyll
  would drop one category page the same way a tag-case collision drops a tag
  page.
- `tag-synonym-groups`: the build **fails** if more than `TAG_SYNONYM_ALLOWED`
  post tags use a known synonym of a canonical tag (e.g. `.NET`/`net8` instead
  of `dotnet`, or `C#` instead of `csharp`), since a synonym splits a topic
  across two tag pages instead of one. See `TAG_SYNONYM_GROUPS` in
  `tools/test.sh` for the canonical groups.
- `ai-related-coverage`: informational only, never fails the build. Prints
  `ai-related-coverage: <count>/<total> _posts posts without a '## Related'
  heading (...)`, counting any post under `_posts/` missing a `## Related`
  footer linking to other posts.
- `description-coverage`: the build **fails** if any post lacks a front-matter
  `description:` or its description is outside 50-160 characters. When all posts
  pass it prints `description-coverage: all <total> posts have a front-matter
  description of 50-160 characters (...)`.
- `image-coverage`: informational only, never fails the build. Prints
  `image-coverage: <count>/<total> posts without image (...)` followed by the
  offending post paths, indented, if any.
- `alt-coverage`: informational only, never fails the build. Prints
  `alt-coverage: <count>/<with-image> posts with a front-matter image but no
  alt text (...)` followed by the offending post paths, where `<with-image>`
  is the number of posts that have a front-matter `image:` key.
- `body-image-coverage`: informational only, never fails the build. Prints
  `body-image-coverage: <count>/<total> posts without an inline ![...] image in
  the body (...)` followed by the offending post paths; a front-matter `image:`
  alone does not count, only a Markdown image after the closing `---`.
- `folder-categories`: the build **fails** if a post under `_posts/<Folder>/`
  does not list the lowercased folder name (e.g. `performance` for
  `_posts/Performance/`) in its front-matter `categories`, since the post would
  be missing from the category page its folder promises. Posts directly under
  `_posts/` are not checked. When all posts pass it prints `folder-categories:
  every post under _posts/<Folder>/ lists its lowercased folder name in
  'categories'`.
- `date-match-coverage`: the build **fails** if a post's filename date (the
  first 10 characters, `YYYY-MM-DD`) differs from its front-matter `date:`,
  since that mismatch leaves the permalink, feed order and file listing
  disagreeing on the publish day. When all posts pass it prints
  `date-match-coverage: 0 mismatches between filename date and front-matter
  'date:' across <total> posts (...)`.
  A post that passes: `_posts/2024-01-05-example.md` with front matter
  `date: 2024-01-05 10:00:00 +0000` (first ten characters of both are
  `2024-01-05`). Worked example of a post that trips it:

  ```text
  _posts/AI/2024-05-23-azure-openai-prompt-caching.md
  ---
  title: "Prompt caching with Azure OpenAI"
  date: 2024-05-22 10:00:00 +0000      # <-- 2024-05-22 != filename's 2024-05-23
  ---
  ```

  Fix it by renaming the file or changing `date:` so the first ten characters
  agree. To self-check a single post before running the full script:

  ```bash
  f=_posts/AI/2024-05-23-things-to-consider-azure-openai.md  # real example post; illustrates a passing check
  echo "filename: $(basename "$f" | cut -c1-10)"
  echo "date:     $(grep -m1 '^date:' "$f" | sed 's/^date:[[:space:]]*//; s/["'"'"']//g' | cut -c1-10)"
  ```
- `tab-order-coverage`: the build **fails** if two `_tabs/*.md` files share the
  same front-matter `order:`, since Chirpy would silently reorder the sidebar
  nav by file name instead of the intended position. Tabs without an `order:`
  key are not checked. When all tabs pass it prints `tab-order-coverage: all
  _tabs/*.md 'order:' values are unique (...)`.

- `related-link-resolution`: the build **fails** if a post's `## Related`
  section links to `/posts/<slug>/` for a slug that no file in `_posts`
  produces (readers would hit a 404). When all links resolve it prints
  `related-link-resolution: 0/<total> posts with unresolved Related links
  (...)`.

It then builds the site into `_site` and runs `htmlproofer` against the
generated HTML (broken links, images and HTML). Use `bash tools/test.sh --help`
to see the config options.

To run the site locally with live reload (optionally in production mode):

```bash
bash tools/run.sh            # dev server on 127.0.0.1
bash tools/run.sh --production
```
