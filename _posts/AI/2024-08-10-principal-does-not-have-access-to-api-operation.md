---
layout: post
title: "Principal does not have access to API/Operation"
description: "Resolve the Azure OpenAI 'principal does not have access to API' error by assigning the correct RBAC role to your user or application identity."
date: 2024-08-10 00:00:00 +0200
categories: ai
tags: ai azure openai security
author: manishtiwari25
image:
  path: /assets/img/headers/ai/azure-openai.webp
  alt: Azure OpenAI header image illustrating the principal does not have access to API operation RBAC error
---

## Why?

This issue can occur when you or application does not have correct permissions to use the AI resource.

{% include feed-ads.html %}

## How to fix?

- Identify which role you want to assign, in our case we will consider Azure Open AI resource and it supports [these](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/role-based-access-control#azure-openai-roles) roles.
- For application, we would recommend Cognitive Services OpenAI User
- Follow [this](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-assignments-portal) to assign a role  

In the Azure portal the fix looks like this: open the Azure OpenAI resource, go to **Access control (IAM)** > **Add role assignment**, pick the `Cognitive Services OpenAI User` role and add your user or app identity as a member:

width=

{% include feed-ads.html %}

## Related posts

- [Key based authentication is disabled for this resource](/posts/key-based-authentication-is-disabled-for-this-resource/)
- [Call to get Azure Search index failed - Server responded with status 403](/posts/call-to-get-azure-search-index-failed-server-responded-with-status-403/)
- [Enterprise AI: Six Governance Controls Before Azure OpenAI Goes to Production in a Regulated Org](/posts/enterprise-ai-governance-azure-openai/)
