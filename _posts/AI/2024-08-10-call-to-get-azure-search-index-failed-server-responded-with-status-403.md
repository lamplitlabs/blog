---
layout: post
title: "Call to get Azure Search index failed - Server responded with status 403"
description: "Fix the Azure OpenAI 'call to get Azure Search index failed' 403 error by granting the service the right role on your Azure AI Search resource."
date: 2024-08-10 06:00:00 0500
categories: ai
tags: ai azure openai security
author: manishtiwari25
image:
  path: /assets/img/headers/ai/azure-openai.webp
---

## Why?

Azure Open AI Service does not have access to Azure Search service.

{% include feed-ads.html %}
{% include feed-ads.html %}

## How to fix?

### Assign Role

- Go to Azure AI Search Service (Formally known as Azure Search Service and Cognitive Search Service).
- You have to provide one of the following roles to open ai service

| Role  | Assignee  | Resource  | Description  |
|---|---|---|---|
|Search Index Data Reader| Azure OpenAI| Azure AI Search| Inference service queries the data from the index.|
|Search Service Contributor| Azure OpenAI| Azure AI Search| Inference service queries the index schema for auto fields mapping.<br>Data ingestion service creates index, data sources, skill set, indexer, and queries the indexer status.|

For more information, please visit [Using your data with Azure OpenAI securely](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/use-your-data-securely#role-assignments)

- Assign the role to open ai service, Follow this to know more about role assignment please go through [MS Docs](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-assignments-portal)

{% include feed-ads.html %}
{% include feed-ads.html %}

### Enable RBAC

- Go to Azure AI Search Service (Formally known as Azure Search Service and Cognitive Search Service).
- Under **Settings** section, click on **Keys**
- Under **API Access control** either select **Both** or **Role-based access control**, I would recommend using RBAC(Role-based access control)

  ![Compliance](/assets/img/posts/ai/call-to-get-azure-search-index-failed-server-responded-with-status-403.webp){: height="300px" }
- Press **Yes** when it asks for confirmation

{% include feed-ads.html %}
{% include feed-ads.html %}
