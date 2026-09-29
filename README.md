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

This builds the site into `_site`, runs `htmlproofer` against the generated
HTML (broken links, images and HTML), and prints the `image-coverage` line
listing which posts under `_posts/` still lack an image. Use
`bash tools/test.sh --help` to see the config options.

To run the site locally with live reload (optionally in production mode):

```bash
bash tools/run.sh            # dev server on 127.0.0.1
bash tools/run.sh --production
```
