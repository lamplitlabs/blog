---
layout: post
title: "Key based authentication is disabled for this resource"
description: "What the 'key based authentication is disabled for this resource' error means in Azure AI Services and how to switch to Entra ID authentication."
date: 2024-08-10 06:00:00 0500
categories: ai
tags: ai azure openai security
author: manishtiwari25
image:
  path: /assets/img/headers/ai/azure-openai.webp
  alt: Azure OpenAI header image
---

## Why?

If you have disabled local auth([Disable local authentication in Azure AI Services](https://learn.microsoft.com/en-us/azure/ai-services/disable-local-auth)), that means you can not use keys for AI service authentication.

{% include feed-ads.html %}
{% include feed-ads.html %}

## How to fix?

Make sure when accessing the AI service API do not use api keys instead try to use Managed service identities.

- Go to Azure AI service (In this case, I am using Azure Open AI Service), and go to Resource Management and select Identity

  ![Compliance](/assets/img/posts/ai/key-based-authentication-is-disabled-for-this-resource.webp){: height="300px" }
- Make sure you are in **System Assigned** Tab
- If the status is **Off**, please change it to **On** and save the generated ID for future use.

Once the identity is enabled, the fix on your screen looks like this: the **System assigned** status is **On** and an Object (principal) ID is shown. Keys stay disabled (`disableLocalAuth: true`), so your application must now call the API with an Entra ID token (for example `DefaultAzureCredential` in the Azure SDK) instead of the `api-key` header:

![Azure portal: Azure OpenAI resource Identity blade with System assigned status On and the Object (principal) ID shown, the fix for 'Key based authentication is disabled for this resource'](/assets/img/posts/ai/key-based-authentication-is-disabled-for-this-resource-fix.webp){: width="700px" }

{% include feed-ads.html %}
{% include feed-ads.html %}
