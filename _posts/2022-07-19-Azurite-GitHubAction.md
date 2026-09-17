---
layout: post
title: "Azurite + GitHub Actions"
date: 2022-07-19 09:00:00 -0500
categories: github
tags: github-actions Azurite Csharp github
author: manishtiwari25
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

Add your Integration test steps after this, and Voila YOU ARE DONE.

You can use the same trick with azure DevOps or any other CI/CD Tool.
Change the azurite version according to your need.

{% include article-ads.html %}

Hope it help you,
Cheers 🍻
