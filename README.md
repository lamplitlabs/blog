<p align="center">
  <a href="https://github.com/lamplitlabs/blog">
    <img src="assets/img/favicons/android-chrome-512x512.png" width="256px" />
  </a>
</p>
<h1 align="center">Blog</h1>

A space for stories about AI, our products, the AI SDLC, enterprise AI, performance, Rust, Go, and more

## How to Use

### Install dependencies

The site expects Ruby **3.3.5**, pinned in `.ruby-version` and `.tool-versions`. With [mise](https://mise.jdx.dev/):

```bash
mise install   # installs Ruby 3.3.5
bundle install
```

With rbenv/asdf install Ruby 3.3.5 first, then run `bundle install`. Check with
`ruby -v`, which should print `ruby 3.3.5`.

### Run the development server

```bash
bundle exec jekyll s
```

The site opens at <http://127.0.0.1:4000> (the terminal prints
`Server address: http://127.0.0.1:4000/`). Stop it with `Ctrl+C`.

### Troubleshooting

- **`jekyll: command not found`**: Jekyll is installed into the bundle, not on
  your `PATH`. Always prefix the command with `bundle exec`
  (`bundle exec jekyll s`), never run bare `jekyll s`.
- **`bundle: command not found`** or a Ruby version error from `bundle
  install`: the site expects Ruby **3.3.5** - run the setup in
  [Install dependencies](#install-dependencies) above, then re-run
  `bundle install`.
- **`Could not find gem ...` / `Bundler::GemNotFound`**: run `bundle install`
  again in the repository root; it reads `Gemfile.lock` and installs the exact
  versions the build uses.

## Local checks

Run the same checks the build relies on before opening a pull request:

```bash
bash tools/test.sh
```

Before building, the script checks every post under `_posts/` (subfolders
included) and prints one summary line per check:

- `tag-case-duplicates`: the build **fails** if two posts spell the same tag
  with different letter case (e.g. `Azurite` vs `azurite`), since Jekyll would
  drop one tag page.
- `category-case-duplicates`: the build **fails** if two posts use the same
  category with different letter case (e.g. `Drawio` vs `drawio`), since Jekyll
  would drop one category page the same way a tag-case collision drops a tag
  page.
- `tag-synonym-groups`: the build **fails** if more than `TAG_SYNONYM_ALLOWED`
  post tags use a known synonym of a canonical tag (e.g. `.NET`/`net8` instead
  of `dotnet`, or `C#` instead of `csharp`), since a synonym splits a topic
  across two tag pages instead of one. See `TAG_SYNONYM_GROUPS` in
  `tools/test.sh` for the canonical groups.
- `description-coverage`: the build **fails** if any post lacks a front-matter
  `description:` or its description is outside 50-160 characters. When all posts
  pass it prints `description-coverage: all <total> posts have a front-matter
  description of 50-160 characters (...)`.
- `image-coverage`: reports posts without an image (front-matter `image:`,
  Markdown `![` or `<img`). Prints
  `image-coverage: <count>/<total> posts without image (...)` followed by the
  offending post paths, indented, if any. `IMAGE_GATE_CUTOFF` is
  resolved to today's date on every run (`date +%F`, in `tools/test.sh`); posts
  dated on or before today are grandfathered, so the build **fails** only for a
  post dated after today (a scheduled post) that has no image.
- `alt-coverage`: fails the build when the count is above 0. Prints
  `alt-coverage: <count>/<with-image> posts with a front-matter image but no
  alt text (...)` followed by the offending post paths, where `<with-image>`
  is the number of posts that have a front-matter `image:` key.
- `body-image-coverage`: fails the build for posts dated after 2026-05-11
  (`BODY_IMAGE_GATE_CUTOFF`); older posts are grandfathered. Prints
  `body-image-coverage: <count>/<total> posts without an inline ![...] image in
  the body (...)` followed by the offending post paths; a front-matter `image:`
  alone does not count, only a Markdown image after the closing `---`.
- `image-link-coverage`: the build **fails** if any post's Markdown image
  (`![...](path)`) or front-matter `image:`/`path:` value that starts with
  `/` or `assets/` points at a file that does not exist under the repo root,
  since the image would render broken for readers. Prints
  `image-link-coverage: <count>/<total> broken (...)` and, on failure, the
  offending post and path.
- `alt-duplicate-coverage`: informational only, never fails the build. Prints
  `alt-duplicate-coverage: <count> alt text values repeated verbatim across
  more than one post (...)` followed by each repeated (trimmed, case-folded)
  alt text value and the posts that share it, since identical alt text on
  different images loses its accessibility value for screen reader users.
- `body-image-alt-length`: the build **fails** if an inline body image in a post
  dated after 2026-05-11 has alt text shorter than `ALT_MIN_LENGTH` characters;
  older posts are grandfathered. Prints `body-image-alt-length: <count> inline
  body image(s) with alt text under <N> characters (...)`.
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
- `future-backlog`: the build **fails** if any post in `_posts/`
  is dated after today, or if any future-dated post is scheduled more than
  14 days out. `_config.yml` sets `future: false`, so a future-dated post is
  invisible on the live site until its day arrives; a large or far-out
  backlog means finished work sits unread. It uses the filename date
  (`YYYY-MM-DD` prefix), which `date-match-coverage` keeps equal to
  `date:`, and never rewrites dates. When the backlog is within both caps it
  prints `future-backlog: <count>/<total> posts dated after today <date>,
  none more than 14 days out (...)`.

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

- `forward-link-coverage`: the build **fails** if a post links to
  `/posts/<slug>/` for a post dated after both the referencing post and
  today, since `future: false` means Jekyll has not built that page yet and
  the link would 404 in `htmlproofer`. When no such links exist it prints
  `forward-link-coverage: 0/<total> posts linking to a not-yet-published
  later-dated /posts/<slug>/ (...)`.

- `tag-conflict-coverage`: the build **fails** if the Jekyll build log
  contains a `Conflict: The following destination is shared by multiple
  files.` warning, since Jekyll exits 0 but silently lets one tag or category
  page overwrite another with the same output path (the archive then lists
  only part of the posts). When the build log is clean it prints
  `tag-conflict-coverage: 0 'Conflict: The following destination is shared by
  multiple files' warnings in the jekyll build log (...)`.

- `today-not-future-coverage`: the build **fails** if a post dated today is
  skipped as `has a future date` by a production read (no `--future`), e.g. a
  `date:` time later today or a `+offset` that is still ahead of now; such a
  post would land invisibly on the live site. Set a time that has already
  passed, or date it tomorrow to schedule it deliberately. When clean it prints
  `today-not-future-coverage: 0 posts dated <today> skipped as 'has a future
  date' by a production (no --future) read (...)`.

- `future-external-links`: runs after the main `htmlproofer` pass, which
  skips external URLs (`--disable-external`) so CI stays fast and immune to
  the back catalogue's link rot. Only the rendered pages of scheduled
  (future-dated) posts are re-checked with external links enabled, since
  those posts are still editable and a dead outbound link there should be
  caught before publish day instead of by a reader afterwards. The build
  **fails** if `htmlproofer` finds a broken external link in one of those
  pages; it **warns** (`WARNING: scheduled post ... has no rendered page`)
  when a scheduled post has no `_site/posts/<slug>/` directory, in which
  case that post's links go unchecked. The site's own URLs (a scheduled
  post's canonical link is a 404 until it goes live), 403/429/999 responses
  and the bare font preconnect hosts are ignored. Prints
  `future-external-links: <count> scheduled post page(s) checked with
  external links enabled (...)`.

It then builds the site into `_site` and runs `htmlproofer` against the
generated HTML (broken links, images and HTML), followed by the
`future-external-links` pass above. Use `bash tools/test.sh --help`
to see the config options.

### External link watcher

`tools/test.sh` runs htmlproofer with `--disable-external`, so a dead outbound
link in a post (DNS failure, timeout, 4xx/5xx) is **not** caught by the test
suite. To find those, run the read-only watcher:

```bash
bash tools/check_external_links.sh
```

It checks Markdown inline links of the form `](http...)` / `](https...)` in
every `.md` file under `_posts/` (subfolders included), prints only the broken
ones (`UNREACHABLE <url>` or `HTTP <code> <url>`) and always exits 0 - it is a
watcher, not a gate, so silence means nothing looked broken. It does **not**
check bare URLs pasted as plain text, HTML `<a href="...">` links, or
reference-style link definitions (`[label]: http...`), so those stay unchecked
by both the watcher and the test suite.

Two kinds of false positives are filtered out: a `404` from a single-page-app
host (e.g. `tools.lamplitlabs.com`, which GitHub Pages serves from `404.html`
for every client-side route) is accepted when the host's `/sitemap.xml` lists
the URL, and a `403` from a host whose root also answers `403` (medium.com,
stackoverflow.com block non-browser clients) is not reported because it says
nothing about the specific page.

To run the site locally with live reload (optionally in production mode or
bound to a non-default host, e.g. to reach the dev server from another device
or a container):

```bash
bash tools/run.sh                    # dev server on 127.0.0.1
bash tools/run.sh --production       # JEKYLL_ENV=production
bash tools/run.sh -H 0.0.0.0         # bind to all interfaces (also --host <host>)
bash tools/run.sh --help             # list all options
```
