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

It then builds the site into `_site` and runs `htmlproofer` against the
generated HTML (broken links, images and HTML). Use `bash tools/test.sh --help`
to see the config options.

To run the site locally with live reload (optionally in production mode):

```bash
bash tools/run.sh            # dev server on 127.0.0.1
bash tools/run.sh --production
```
