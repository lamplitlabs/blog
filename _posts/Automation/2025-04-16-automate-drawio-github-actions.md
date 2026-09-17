---
layout: post
title: "Automate Draw.io Diagram Export with GitHub Actions"
date: 2025-04-16
categories: [DevOps, GitHub, CI/CD, Drawio]
author: manishtiwari25
tags: [github-actions, drawio, automation, diagrams, documentation]
description: "Learn how to automate exporting Draw.io diagrams into PNG images using GitHub Actions. Keep your visual documentation always in sync with your code."
image: 
  path: /assets/img/headers/automation/automate-drawio-github-actions.webp
---

> _“Every great architecture deserves versioned blueprints.”_

Whether you're documenting microservices, infrastructure, or galactic weapons (👀), chances are you’re using `.drawio` files. But how often do you remember to export those diagrams as images before sharing or shipping?

This post walks you through automating the export of `.drawio` diagrams to PNG using **GitHub Actions**, so your visuals are always up-to-date and versioned alongside your code.

{% include article-ads.html %}

---

## 🧩 The Objective

Every time you update a `.drawio` file in your GitHub repo, the workflow will:

1. Detect the change  
2. Spin up a Linux runner  
3. Install Draw.io CLI & dependencies  
4. Export each diagram page as PNG  
5. Commit and push the images back to the repo  

Let’s say your diagram is called `deathstar-blueprint.drawio`. You’ll end up with image files like:

```
docs/images/deathstar-blueprint-page-0.png  
docs/images/deathstar-blueprint-page-1.png  
...
```

{% include article-ads.html %}

---

## 🧰 Prerequisites

- GitHub repo with `.drawio` files under `docs/drawio/`
- GitHub Actions enabled
- A personal access token (PAT) with repo push access (used to commit image changes)

{% include article-ads.html %}

---

## 🧾 The GitHub Actions Workflow

More In depth [Here]({% post_url Automation/2025-04-16-automate-drawio-azure-devops %})

Create a workflow file at: `.github/workflows/drawio-export.yml`

```yaml
name: Export Draw.io Diagrams

on:
  push:
    paths:
      - 'docs/drawio/**.drawio'

jobs:
  export-drawio:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout Repository
      uses: actions/checkout@v3

    - name: Install Dependencies and Draw.io
      run: |
        sudo apt-get update && sudo apt-get install -y xvfb libxml2-utils
        wget https://github.com/jgraph/drawio-desktop/releases/download/v26.2.2/drawio-x86_64-26.2.2.AppImage -O drawio
        chmod +x drawio
        ./drawio --appimage-extract
        mkdir -p docs/images/

    - name: Count Pages in Draw.io File
      id: count
      run: |
        page_count=$(xmllint --xpath "count(//diagram)" docs/drawio/deathstar-blueprint.drawio)
        echo "count=$page_count" >> $GITHUB_OUTPUT

    - name: Export PNG Images from Draw.io
      run: |
        Xvfb :99 -screen 0 1024x768x24 &
        export DISPLAY=:99
        sleep 3
        for i in $(seq 0 $(( ${{ steps.count.outputs.count }} - 1 ))); do
          ./squashfs-root/drawio -x -f png --page-index $i -o docs/images/deathstar-blueprint-page-$i.png docs/drawio/deathstar-blueprint.drawio
        done

    - name: Commit and Push Exported Images
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      run: |
        git config --global user.name "github-actions"
        git config --global user.email "github-actions@github.com"
        git add docs/images/
        git commit -m "Exported Draw.io diagrams [skip ci]" || echo "No changes to commit"
        git push
```

{% include article-ads.html %}
{% include article-ads.html %}

---

## 🧠 Why Automate This?

✅ Keeps diagrams in sync with code  
✅ Encourages updating visuals regularly  
✅ Eliminates manual exports  
✅ Git-tracks your documentation like your code

{% include article-ads.html %}
{% include article-ads.html %}

---

## 💡 Bonus Ideas

- Export diagrams to SVG or PDF
- Publish diagrams to GitHub Pages or a wiki
- Trigger exports nightly or per release branch

{% include article-ads.html %}

---

## 🧨 Final Thoughts

Documentation is better when it’s automated. By integrating Draw.io diagram exports into your GitHub Actions workflow, you make diagrams a living part of your engineering system—always versioned, always fresh.

Turn your `deathstar-blueprint.drawio` into a blueprint the rebellion would envy. ✨

{% include article-ads.html %}

---

Need help extending this workflow? Feel free to fork, adapt, or drop a question!

{% include article-ads.html %}
{% include article-ads.html %}
