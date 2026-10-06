---
layout: post
title: "Azurite + GitHub Actions"
description: "Run Azurite, the Azure Storage emulator, inside GitHub Actions or any CI/CD pipeline to execute integration tests against local storage."
date: 2022-07-19 09:00:00 -0500
categories: github
tags: github-actions Azurite csharp github
author: manishtiwari25
image:
  path: /assets/img/headers/azurite-github-actions.webp
  alt: GitHub Actions workflow run of the Build And Test job with the Azurite step and integration tests passing
redirect_from:
  - /media/e52ece39cd93224dd7fc1d9efa62f08a
  - /azurite-github-actions-2a29953af13f?source=author_recirc-----a9c256fee353----4----------------------------
  - /azurite-github-actions-2a29953af13f
  - /azurite-github-actions-2a29953af13f?source=user_profile---------2----------------------------
  - /azurite-github-actions-2a29953af13f?source=author_recirc-----a9c256fee353----3----------------------------
---

Do you have any project where you want to run Integration Test cases on your build pipelines?

If your answer is YES, then you are in a correct place, in this story I will talk about <strong>HOW TO RUN AZURITE WITHIN GITHUB ACTIONS (OR ANY OTHER CI/CD TOOL)</strong>.

First thing first, add some Integration Tests in your projects and on the configuration file set <strong>UseDevelopmentStorage=true</strong>, this will tell your code to use the local instance of storage account.

{% include article-ads.html %}

Next step is to add the following steps in you build.yml file.

```yml
name: Build And Test

on:
  pull_request:
    branches:
      - qa
    paths-ignore:
      - "README.md"

jobs:
  build-and-test:
    name: Build And Test
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install Azurite
        run: npm install --location=global azurite@3.17.1
        shell: bash

      - name: Run Azurite
        run: azurite --silent -l /tmp &
        shell: bash
```

{% include feed-ads.html %}

When the workflow runs, the **Run Azurite** step finishes in about a second and the job log shows the emulator starting its Blob, Queue and Table endpoints on `127.0.0.1:10000-10002`; because the process is backgrounded with `&`, the job moves straight on to the next step while Azurite keeps listening.

![GitHub Actions job log of the Build And Test workflow with the Run Azurite step expanded, showing Azurite Blob, Queue and Table services successfully listening on 127.0.0.1 ports 10000, 10001 and 10002, followed by the integration test step passing](/assets/img/posts/github/azurite-github-actions-run-azurite-step-log.webp)
*The expanded **Run Azurite** step in the GitHub Actions job log. If you see these three "successfully listening" lines, your integration tests can connect with `UseDevelopmentStorage=true`.*

Add your Integration test steps after this, and Voila YOU ARE DONE.

You can use the same trick with azure DevOps or any other CI/CD Tool.
Change the azurite version according to your need.

{% include article-ads.html %}

Hope it help you,
Cheers 🍻

## Related posts

- [Automate Draw.io Diagram Export with GitHub Actions](/posts/automate-drawio-github-actions/)
- [Updating Azure Function App From V3 to V4](/posts/Updating-Azure-Function-v3-v4/)
- [Automating RSS Feed Posts to Social Media Using GitHub: Say Hello To Ferret](/posts/auto-post-RSS-feed-to-social-media-using-github/)
