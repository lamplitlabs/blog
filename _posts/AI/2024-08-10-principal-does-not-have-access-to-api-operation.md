---
layout: post
title: "Principal does not have access to API/Operation"
description: "Resolve the Azure OpenAI 'principal does not have access to API' error by assigning the correct RBAC role to your user or application identity."
date: 2024-08-10 06:00:00 0500
categories: ai
tags: ai azure openai security
author: manishtiwari25
image:
  path: /assets/img/headers/ai/azure-openai.webp
---

## Why?

This issue can occur when you or application does not have correct permissions to use the AI resource.

{% include feed-ads.html %}
{% include feed-ads.html %}

## How to fix?

- Identify which role you want to assign, in our case we will consider Azure Open AI resource and it supports [these](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/role-based-access-control#azure-openai-roles) roles.
- For application, we would recommend Cognitive Services OpenAI User
- Follow [this](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-assignments-portal) to assign a role  

{% include feed-ads.html %}
{% include feed-ads.html %}
