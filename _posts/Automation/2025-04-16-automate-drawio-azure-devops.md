---
layout: post
title: "Automate Draw.io Diagram Export with Azure DevOps"
date: 2025-04-16
categories: [devops, Automation, azure, Drawio]
tags: [azure-devops, pipelines, drawio, automation, documentation]
author: manishtiwari25
description: "Learn how to automate exporting Draw.io diagrams into PNG images using Azure DevOps pipelines. A complete step-by-step guide using deathstar-blueprint.drawio."
image:
  path: /assets/img/headers/automation/automate-drawio-azure-devops.webp

---

> _“Turning your Death Star blueprints into beautiful, versioned documentation”_

Keeping visual documentation up-to-date in a fast-moving development workflow can be a real pain—especially when those diagrams live as `.drawio` files in your repository. They’re often forgotten or manually exported just before a release (or never), leading to stale or missing images in your docs.

But what if you could automate that?

In this post, you’ll learn how to **automatically export your `.drawio` diagrams into PNG images using Azure DevOps Pipelines** every time the file changes. Our example will revolve around a diagram file called `deathstar-blueprint.drawio`, because let’s face it—good DevOps is how the Empire *should* have built the Death Star.

{% include article-ads.html %}

---

## 🧩 The Objective

Whenever `deathstar-blueprint.drawio` is updated in your Git repository, this pipeline will:

1. Detect the change  
2. Spin up a headless Linux environment  
3. Install Draw.io and necessary dependencies  
4. Export each diagram page as a PNG image  
5. Commit the images back to the repo  

All hands-off. All automated.

{% include article-ads.html %}

---

## 🧰 Prerequisites

Make sure your repo:

- Contains `.drawio` diagrams inside `docs/drawio/`
- Has a configured Azure DevOps Pipeline
- Has permissions to push changes to branches (PAT or system access)
- Uses Git version control

{% include article-ads.html %}

---

## 🔁 Pipeline Overview

Here’s the full pipeline YAML and a breakdown of how each step works.

{% include article-ads.html %}

---

### 🚨 Trigger on Diagram Changes

```yaml
trigger:
  paths:
    include:
      - docs/drawio/**
```

Only runs when files inside `docs/drawio/` are modified.

{% include article-ads.html %}

---

### 🧪 Setup: Ubuntu Agent

```yaml
pool:
  vmImage: 'ubuntu-latest'
```

Uses Microsoft’s `ubuntu-latest` hosted agent.

---

### 🧱 Install Dependencies & Prepare Draw.io

```yaml
- script: |
    sudo apt-get update && sudo apt-get install -y xvfb libxml2-utils
    wget https://github.com/jgraph/drawio-desktop/releases/download/v26.2.2/drawio-x86_64-26.2.2.AppImage -O drawio || exit 1
    chmod +x drawio
    ./drawio --appimage-extract || exit 1
    sudo chown root:root squashfs-root/chrome-sandbox
    sudo chmod 4755 squashfs-root/chrome-sandbox
    mkdir -p docs/images/
  displayName: 'Prepare Draw.io Environment'
```

- Installs **Xvfb** (virtual display server) and `libxml2-utils`
- Downloads and extracts **Draw.io Desktop**
- Prepares output folder `docs/images/`

{% include article-ads.html %}

---

### 📄 Count Pages in the Diagram

```yaml
- script: |
    page_count=$(xmllint --xpath "count(//diagram)" docs/drawio/deathstar-blueprint.drawio)
    echo $page_count > page_count.txt
  displayName: 'Count Pages in Draw.io File'
```

Parses XML to count `<diagram>` nodes (pages).

{% include article-ads.html %}

---

### 🖼️ Export Each Page to PNG

```yaml
- script: |
    Xvfb :99 -screen 0 1024x768x24 & 
    export DISPLAY=:99
    sleep 3

    if ! pgrep Xvfb > /dev/null; then
      echo "Xvfb failed to start"
      exit 1
    fi

    echo "Available disk space:"
    df -h
    echo "Available memory:"
    free -h

    page_count=$(cat page_count.txt)
    echo "Total pages to export: $page_count"
    for i in $(seq 0 $((page_count - 1))); do
      echo "Exporting page $i..."
      ./squashfs-root/drawio -x -f png --page-index $i -o docs/images/deathstar-blueprint-page-$i.png docs/drawio/deathstar-blueprint.drawio
      if [ $? -ne 0 ]; then
        echo "Exporting page $i failed"
        pkill Xvfb || echo "Failed to stop Xvfb"
        exit 1
      fi
    done

    pkill Xvfb || echo "Failed to stop Xvfb"
  displayName: 'Export Draw.io Pages to PNG'
```

Exports each page from the `.drawio` file as PNG images into `docs/images/`.

{% include article-ads.html %}

---

### 🧹 Cleanup and Push Changes

```yaml
- script: |
    rm -rf squashfs-root drawio page_count.txt || echo "Cleanup failed"
    git config --global user.email "$(email)"
    git config --global user.name "$(username)"
    git fetch --all
    git add -A || echo "No files to add"
    git commit -m "Generated images from Draw.io [skip ci]" || echo "No changes to commit"
    branchName=$(echo "$BUILD_SOURCEBRANCH" | sed 's/refs\/heads\///')
    git push origin "HEAD:$branchName" || echo "Failed to push changes"
  displayName: 'Cleanup and Push Changes'
```

- Cleans up temporary files
- Commits image exports back to the same branch
- Skips triggering another pipeline run (`[skip ci]`)

{% include article-ads.html %}

---

## 🧠 Why Automate This?

✅ Keeps diagrams in sync with code  
✅ Encourages updating diagrams regularly  
✅ Eliminates manual export steps  
✅ Version-controls visuals alongside source

---

## 🔄 Bonus Ideas

- Export SVG or PDF formats using the Draw.io CLI
- Publish images to a static site (e.g., GitHub Pages)
- Auto-generate README previews or Confluence pages

{% include article-ads.html %}

---

## 🧨 Final Thoughts

By integrating Draw.io exports into your CI pipeline, your diagrams become as maintainable and versioned as your code. No more manual exports. No more outdated visuals.

And just like that—your `deathstar-blueprint.drawio` evolves into a living artifact of your software system.

{% include article-ads.html %}

---

**Need help extending this setup?** Reach out, comment, or fork this into your own DevOps Death Star ✨

{% include article-ads.html %}
{% include article-ads.html %}
