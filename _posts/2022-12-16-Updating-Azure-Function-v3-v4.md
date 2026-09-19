---
layout: post
title: "Updating Azure Function App From V3 to V4"
date: 2022-12-16 09:00:00 -0500
categories: cloud azure
tags: azure azurefunction
author: manishtiwari25
image:
  path: /assets/img/headers/updating-azure-function-v3-v4.webp
  alt: Azure portal application settings showing FUNCTIONS_EXTENSION_VERSION changed from ~3 to ~4
redirect_from:
  - /1
  - /-1
  - /updating-azure-function-app-from-v3-to-v4-cb0b8ef3fc7c?source=author_recirc-----a9c256fee353----1----------------------------
  - /updating-azure-function-app-from-v3-to-v4-cb0b8ef3fc7c
  - /share?text=Updating Azure Function App From V3 to V4 - Lamplit Labs https://blogs.lamplitlabs.com/posts/Updating-Azure-Function-v3-v4/
---

Updating an Azure Functions app from version 3 to version 4 involves a few steps. Here is a general outline of the process:

{% include feed-ads.html %}

1. Make a backup of your function app: Before you begin the update process, it is a good idea to make a backup of your function app in case something goes wrong. You can do this by exporting the function app to a ZIP file using the Azure Functions Core Tools.

2. Update the runtime version: In the Azure portal, navigate to your function app and select the “Configuration” tab. Scroll down to the “Application settings” section and update the “FUNCTIONS_EXTENSION_VERSION” setting to “v4”.

{% include article-ads.html %}

3. Update the function app’s hosting plan: Azure Functions version 4 requires an updated hosting plan, so you will need to update the hosting plan for your function app. To do this, navigate to the “Scale up (App Service plan)” blade in the Azure portal and select an updated hosting plan.

4. Update the function app’s dependencies: If your function app uses any third-party libraries or packages, you may need to update them to versions that are compatible with Azure Functions version 4. You can do this by updating the package references in your function app’s project files and then redeploying the app.

{% include article-ads.html %}

5. Test your function app: After you have completed the update process, it is a good idea to test your function app to make sure it is working correctly. You can do this by triggering the functions in your app and verifying that they are running as expected.

{% include article-ads.html %}

Updating an Azure Functions app from version 3 to version 4 can be a complex process, and it is important to carefully follow the steps outlined above to ensure a smooth transition. If you encounter any issues during the update process, you may want to consult the Azure Functions documentation or seek help from Microsoft support.
